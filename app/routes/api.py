from datetime import date, timedelta

from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models import License, LicenseAllocation, Role, School, Vendor
from app.services.audit import log_action
from app.services.status import compute_expiration_status, get_thresholds
from app.utils.api_auth import api_login_required, api_permission_required, api_user

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _license_to_dict(lic):
    thresholds = get_thresholds()
    return {
        "id": lic.id, "name": lic.name, "vendor": lic.vendor.name if lic.vendor else None,
        "category": lic.category.name if lic.category else None,
        "license_count": lic.license_count, "assigned_licenses": lic.assigned_licenses,
        "available_licenses": lic.available_licenses, "utilization_pct": lic.utilization_pct,
        "start_date": lic.start_date.isoformat() if lic.start_date else None,
        "expiration_date": lic.expiration_date.isoformat() if lic.expiration_date else None,
        "renewal_date": lic.renewal_date.isoformat() if lic.renewal_date else None,
        "annual_cost": float(lic.annual_cost or 0), "cost_per_license": lic.cost_per_license,
        "status": lic.status, "computed_status": compute_expiration_status(lic.expiration_date, thresholds),
    }


def _vendor_to_dict(v):
    return {
        "id": v.id, "name": v.name, "website": v.website, "support_email": v.support_email,
        "support_phone": v.support_phone, "account_manager": v.account_manager,
        "total_annual_spend": float(v.total_annual_spend),
    }


def _school_to_dict(sc):
    return {
        "id": sc.id, "name": sc.name, "code": sc.code, "school_type": sc.school_type,
        "is_active": sc.is_active, "student_count": sc.student_count,
    }


def _visible_license_query():
    user = api_user()
    query = License.query
    if user.has_role(Role.SCHOOL_ADMINISTRATOR):
        query = query.join(LicenseAllocation).filter(LicenseAllocation.school_id == user.school_id).distinct()
    return query


@api_bp.route("/licenses", methods=["GET"])
@api_login_required
@api_permission_required("view_reports")
def list_licenses():
    items = _visible_license_query().order_by(License.name).all()
    return jsonify([_license_to_dict(lic) for lic in items])


@api_bp.route("/licenses/<int:id>", methods=["GET"])
@api_login_required
@api_permission_required("view_reports")
def get_license(id):
    lic = _visible_license_query().filter(License.id == id).first()
    if lic is None:
        return jsonify(error="Not found."), 404
    return jsonify(_license_to_dict(lic))


@api_bp.route("/licenses", methods=["POST"])
@api_login_required
@api_permission_required("manage_licenses")
def create_license():
    data = request.get_json(silent=True) or {}
    if not data.get("name") or not data.get("vendor_id"):
        return jsonify(error="'name' and 'vendor_id' are required."), 400
    if not db.session.get(Vendor, data["vendor_id"]):
        return jsonify(error="Unknown vendor_id."), 400

    lic = License(
        name=data["name"], vendor_id=data["vendor_id"],
        license_count=data.get("license_count", 0),
        status=data.get("status", "Active"),
        created_by_id=api_user().id,
    )
    if data.get("expiration_date"):
        lic.expiration_date = date.fromisoformat(data["expiration_date"])
    db.session.add(lic)
    db.session.commit()
    log_action("create", "license", lic.id, {"name": lic.name, "via": "api"})
    db.session.commit()
    return jsonify(_license_to_dict(lic)), 201


@api_bp.route("/licenses/<int:id>", methods=["PUT"])
@api_login_required
@api_permission_required("manage_licenses")
def update_license(id):
    lic = License.query.get_or_404(id)
    data = request.get_json(silent=True) or {}
    for field in ("name", "license_count", "status", "vendor_id"):
        if field in data:
            setattr(lic, field, data[field])
    if "expiration_date" in data:
        lic.expiration_date = date.fromisoformat(data["expiration_date"]) if data["expiration_date"] else None
    db.session.commit()
    log_action("update", "license", lic.id, {"via": "api"})
    db.session.commit()
    return jsonify(_license_to_dict(lic))


@api_bp.route("/licenses/<int:id>", methods=["DELETE"])
@api_login_required
@api_permission_required("manage_licenses")
def delete_license(id):
    lic = License.query.get_or_404(id)
    name = lic.name
    db.session.delete(lic)
    log_action("delete", "license", id, {"name": name, "via": "api"})
    db.session.commit()
    return jsonify(message=f"{name} deleted."), 200


@api_bp.route("/vendors", methods=["GET"])
@api_login_required
@api_permission_required("view_reports")
def list_vendors():
    return jsonify([_vendor_to_dict(v) for v in Vendor.query.order_by(Vendor.name).all()])


@api_bp.route("/schools", methods=["GET"])
@api_login_required
@api_permission_required("view_reports")
def list_schools():
    user = api_user()
    query = School.query
    if user.has_role(Role.SCHOOL_ADMINISTRATOR):
        query = query.filter(School.id == user.school_id)
    return jsonify([_school_to_dict(s) for s in query.order_by(School.name).all()])


@api_bp.route("/expiring", methods=["GET"])
@api_login_required
@api_permission_required("view_reports")
def expiring():
    days = request.args.get("days", 90, type=int)
    cutoff = date.today() + timedelta(days=days)
    items = [
        lic for lic in _visible_license_query().all()
        if lic.expiration_date and date.today() <= lic.expiration_date <= cutoff
    ]
    items.sort(key=lambda lic: lic.expiration_date)
    return jsonify([_license_to_dict(lic) for lic in items])
