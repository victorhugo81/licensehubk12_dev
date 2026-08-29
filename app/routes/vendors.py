from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.forms import VendorForm
from app.models import Contract, Vendor
from app.services.audit import diff_changes, log_action
from app.services.status import compute_expiration_status, get_thresholds
from app.utils.decorators import permission_required

vendors_bp = Blueprint("vendors", __name__, url_prefix="/vendors")

PER_PAGE = 20


def _form_data(v):
    return {
        "name": v.name, "website": v.website, "support_email": v.support_email,
        "support_phone": v.support_phone, "account_manager": v.account_manager,
        "account_number": v.account_number, "notes": v.notes,
    }


@vendors_bp.route("/")
@login_required
def list_vendors():
    q = request.args.get("q", "").strip()
    query = Vendor.query
    if q:
        query = query.filter(Vendor.name.ilike(f"%{q}%"))
    page = request.args.get("page", 1, type=int)
    pagination = query.order_by(Vendor.name).paginate(page=page, per_page=PER_PAGE, error_out=False)
    return render_template("vendors/list.html", pagination=pagination, vendors=pagination.items)


@vendors_bp.route("/add", methods=["GET", "POST"])
@login_required
@permission_required("manage_vendors")
def add_vendor():
    form = VendorForm()
    if form.validate_on_submit():
        vendor = Vendor()
        form.populate_obj(vendor)
        db.session.add(vendor)
        db.session.commit()
        log_action("create", "vendor", vendor.id, {"name": vendor.name})
        db.session.commit()
        flash(f"{vendor.name} added.", "success")
        return redirect(url_for("vendors.view_vendor", id=vendor.id))
    return render_template("vendors/form.html", form=form, vendor=None)


@vendors_bp.route("/<int:id>")
@login_required
def view_vendor(id):
    vendor = Vendor.query.get_or_404(id)
    thresholds = get_thresholds()
    upcoming_contracts = [c for c in vendor.contracts if c.end_date >= date.today()]
    expiring_software = [
        s for s in vendor.software
        if s.expiration_date and compute_expiration_status(s.expiration_date, thresholds) != "active"
    ]
    return render_template(
        "vendors/detail.html",
        vendor=vendor,
        upcoming_contracts=upcoming_contracts,
        expiring_software=expiring_software,
        thresholds=thresholds,
        compute_expiration_status=compute_expiration_status,
    )


@vendors_bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_vendors")
def edit_vendor(id):
    vendor = Vendor.query.get_or_404(id)
    before = _form_data(vendor)
    form = VendorForm(obj=vendor)
    if form.validate_on_submit():
        form.populate_obj(vendor)
        db.session.commit()
        changes = diff_changes(before, _form_data(vendor))
        log_action("update", "vendor", vendor.id, changes)
        db.session.commit()
        flash(f"{vendor.name} updated.", "success")
        return redirect(url_for("vendors.view_vendor", id=vendor.id))
    return render_template("vendors/form.html", form=form, vendor=vendor)


@vendors_bp.route("/<int:id>/delete", methods=["POST"])
@login_required
@permission_required("manage_vendors")
def delete_vendor(id):
    vendor = Vendor.query.get_or_404(id)
    if vendor.software:
        flash(f"Cannot delete {vendor.name} while software is linked to it.", "danger")
        return redirect(url_for("vendors.view_vendor", id=id))
    name = vendor.name
    db.session.delete(vendor)
    log_action("delete", "vendor", id, {"name": name})
    db.session.commit()
    flash(f"{name} deleted.", "success")
    return redirect(url_for("vendors.list_vendors"))
