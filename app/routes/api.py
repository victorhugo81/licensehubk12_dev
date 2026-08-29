from datetime import date, timedelta

from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models import LicenseAllocation, Role, School, Software, Vendor
from app.services.audit import log_action
from app.services.status import compute_expiration_status, get_thresholds
from app.utils.api_auth import api_login_required, api_permission_required, api_user

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _software_to_dict(s):
    thresholds = get_thresholds()
    return {
        "id": s.id, "name": s.name, "vendor": s.vendor.name if s.vendor else None,
        "category": s.category.name if s.category else None, "license_type": s.license_type,
        "license_count": s.license_count, "assigned_licenses": s.assigned_licenses,
        "available_licenses": s.available_licenses, "utilization_pct": s.utilization_pct,
        "start_date": s.start_date.isoformat() if s.start_date else None,
        "expiration_date": s.expiration_date.isoformat() if s.expiration_date else None,
        "renewal_date": s.renewal_date.isoformat() if s.renewal_date else None,
        "annual_cost": float(s.annual_cost or 0), "cost_per_license": s.cost_per_license,
        "status": s.status, "computed_status": compute_expiration_status(s.expiration_date, thresholds),
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


def _visible_software_query():
    user = api_user()
    query = Software.query
    if user.has_role(Role.SCHOOL_ADMINISTRATOR):
        query = query.join(LicenseAllocation).filter(LicenseAllocation.school_id == user.school_id).distinct()
    return query


@api_bp.route("/software", methods=["GET"])
@api_login_required
@api_permission_required("view_reports")
def list_software():
    items = _visible_software_query().order_by(Software.name).all()
    return jsonify([_software_to_dict(s) for s in items])


@api_bp.route("/licenses", methods=["GET"])
@api_login_required
@api_permission_required("view_reports")
def list_licenses():
    return list_software()


@api_bp.route("/software/<int:id>", methods=["GET"])
@api_login_required
@api_permission_required("view_reports")
def get_software(id):
    s = _visible_software_query().filter(Software.id == id).first()
    if s is None:
        return jsonify(error="Not found."), 404
    return jsonify(_software_to_dict(s))


@api_bp.route("/software", methods=["POST"])
@api_login_required
@api_permission_required("manage_software")
def create_software():
    data = request.get_json(silent=True) or {}
    if not data.get("name") or not data.get("vendor_id"):
        return jsonify(error="'name' and 'vendor_id' are required."), 400
    if not db.session.get(Vendor, data["vendor_id"]):
        return jsonify(error="Unknown vendor_id."), 400

    s = Software(
        name=data["name"], vendor_id=data["vendor_id"],
        license_type=data.get("license_type", "Subscription"),
        license_count=data.get("license_count", 0),
        annual_cost=data.get("annual_cost", 0),
        status=data.get("status", "Active"),
        created_by_id=api_user().id,
    )
    if data.get("expiration_date"):
        s.expiration_date = date.fromisoformat(data["expiration_date"])
    db.session.add(s)
    db.session.commit()
    log_action("create", "software", s.id, {"name": s.name, "via": "api"})
    db.session.commit()
    return jsonify(_software_to_dict(s)), 201


@api_bp.route("/software/<int:id>", methods=["PUT"])
@api_login_required
@api_permission_required("manage_software")
def update_software(id):
    s = Software.query.get_or_404(id)
    data = request.get_json(silent=True) or {}
    for field in ("name", "license_type", "license_count", "annual_cost", "status", "vendor_id"):
        if field in data:
            setattr(s, field, data[field])
    if "expiration_date" in data:
        s.expiration_date = date.fromisoformat(data["expiration_date"]) if data["expiration_date"] else None
    db.session.commit()
    log_action("update", "software", s.id, {"via": "api"})
    db.session.commit()
    return jsonify(_software_to_dict(s))


@api_bp.route("/software/<int:id>", methods=["DELETE"])
@api_login_required
@api_permission_required("manage_software")
def delete_software(id):
    s = Software.query.get_or_404(id)
    name = s.name
    db.session.delete(s)
    log_action("delete", "software", id, {"name": name, "via": "api"})
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
        s for s in _visible_software_query().all()
        if s.expiration_date and date.today() <= s.expiration_date <= cutoff
    ]
    items.sort(key=lambda s: s.expiration_date)
    return jsonify([_software_to_dict(s) for s in items])
