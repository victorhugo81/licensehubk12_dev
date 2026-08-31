from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import AllocationForm, CategoryForm, SoftwareForm
from app.models import Category, LicenseAllocation, Role, School, Software, Vendor
from app.services import allocation as allocation_service
from app.services.audit import diff_changes, log_action
from app.services.status import compute_expiration_status, get_thresholds
from app.utils.decorators import permission_required, scope_to_school

licenses_bp = Blueprint("licenses", __name__)

PER_PAGE = 20


def _software_form_data(sw):
    return {
        "name": sw.name, "vendor_id": sw.vendor_id, "category_id": sw.category_id or 0,
        "license_count": sw.license_count, "expiration_date": sw.expiration_date, "status": sw.status,
    }


@licenses_bp.route("/software")
@login_required
def list_software():
    query = Software.query

    if current_user.has_role(Role.SCHOOL_ADMINISTRATOR):
        query = query.join(LicenseAllocation).filter(
            LicenseAllocation.school_id == current_user.school_id
        ).distinct()

    q = request.args.get("q", "").strip()
    if q:
        query = query.filter(Software.name.ilike(f"%{q}%"))

    vendor_id = request.args.get("vendor_id", type=int)
    if vendor_id:
        query = query.filter(Software.vendor_id == vendor_id)

    category_id = request.args.get("category_id", type=int)
    if category_id:
        query = query.filter(Software.category_id == category_id)

    status = request.args.get("status", "").strip()
    if status:
        query = query.filter(Software.status == status)

    view = request.args.get("view", "")
    thresholds = get_thresholds()
    if view == "expiring":
        query = query.filter(Software.expiration_date.isnot(None), Software.expiration_date >= date.today())
    elif view == "expired":
        query = query.filter(Software.expiration_date.isnot(None), Software.expiration_date < date.today())
    elif view == "active":
        query = query.filter(Software.status == "Active")

    page = request.args.get("page", 1, type=int)
    pagination = query.order_by(Software.name).paginate(page=page, per_page=PER_PAGE, error_out=False)

    return render_template(
        "licenses/list.html",
        pagination=pagination,
        software_list=pagination.items,
        vendors=Vendor.query.order_by(Vendor.name).all(),
        categories=Category.query.order_by(Category.name).all(),
        statuses=Software.STATUSES,
        thresholds=thresholds,
        view=view,
        compute_expiration_status=compute_expiration_status,
    )


@licenses_bp.route("/software/add", methods=["GET", "POST"])
@login_required
@permission_required("manage_software")
def add_software():
    form = SoftwareForm()
    if form.validate_on_submit():
        sw = Software(created_by_id=current_user.id)
        form.populate_obj(sw)
        sw.category_id = form.category_id.data or None
        db.session.add(sw)
        db.session.commit()
        log_action("create", "software", sw.id, {"name": sw.name})
        db.session.commit()
        flash(f"{sw.name} added.", "success")
        return redirect(url_for("licenses.view_software", id=sw.id))
    return render_template("licenses/form.html", form=form, sw=None)


@licenses_bp.route("/software/<int:id>")
@login_required
def view_software(id):
    sw = Software.query.get_or_404(id)
    if current_user.has_role(Role.SCHOOL_ADMINISTRATOR):
        if not any(a.school_id == current_user.school_id for a in sw.allocations):
            abort(403)
    thresholds = get_thresholds()
    return render_template(
        "licenses/detail.html",
        sw=sw,
        thresholds=thresholds,
        computed_status=compute_expiration_status(sw.expiration_date, thresholds),
        allocation_form=AllocationForm(),
    )


@licenses_bp.route("/software/<int:id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_software")
def edit_software(id):
    sw = Software.query.get_or_404(id)
    before = _software_form_data(sw)
    form = SoftwareForm(obj=sw)
    if request.method == "GET":
        form.category_id.data = sw.category_id or 0

    if form.validate_on_submit():
        form.populate_obj(sw)
        sw.category_id = form.category_id.data or None
        db.session.commit()
        changes = diff_changes(before, _software_form_data(sw))
        log_action("update", "software", sw.id, changes)
        db.session.commit()
        flash(f"{sw.name} updated.", "success")
        return redirect(url_for("licenses.view_software", id=sw.id))
    return render_template("licenses/form.html", form=form, sw=sw)


@licenses_bp.route("/software/<int:id>/delete", methods=["POST"])
@login_required
@permission_required("manage_software")
def delete_software(id):
    sw = Software.query.get_or_404(id)
    name = sw.name
    db.session.delete(sw)
    log_action("delete", "software", id, {"name": name})
    db.session.commit()
    flash(f"{name} deleted.", "success")
    return redirect(url_for("licenses.list_software"))


@licenses_bp.route("/software/<int:id>/utilization")
@login_required
def utilization(id):
    sw = Software.query.get_or_404(id)
    if current_user.has_role(Role.SCHOOL_ADMINISTRATOR):
        if not any(a.school_id == current_user.school_id for a in sw.allocations):
            abort(403)
    allocations = sorted(sw.allocations, key=lambda a: a.allocated_count, reverse=True)
    return render_template("licenses/utilization.html", sw=sw, allocations=allocations)


@licenses_bp.route("/software/<int:id>/allocations", methods=["POST"])
@login_required
@permission_required("manage_licenses")
def add_allocation(id):
    sw = Software.query.get_or_404(id)
    form = AllocationForm()
    if form.validate_on_submit():
        school = School.query.get_or_404(form.school_id.data)
        try:
            allocation_service.set_allocation(sw, school, form.allocated_count.data, form.notes.data)
            db.session.commit()
            log_action("update", "license_allocation", sw.id, {
                "school": school.name, "allocated_count": form.allocated_count.data,
            })
            db.session.commit()
            flash(f"Allocation for {school.name} saved.", "success")
        except allocation_service.AllocationError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    else:
        flash("Please correct the errors in the allocation form.", "danger")
    return redirect(url_for("licenses.view_software", id=id))


@licenses_bp.route("/software/<int:id>/allocations/<int:allocation_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_licenses")
def delete_allocation(id, allocation_id):
    allocation = LicenseAllocation.query.get_or_404(allocation_id)
    if allocation.software_id != id:
        abort(404)
    school_name = allocation.school.name
    db.session.delete(allocation)
    log_action("delete", "license_allocation", id, {"school": school_name})
    db.session.commit()
    flash(f"Allocation for {school_name} removed.", "success")
    return redirect(url_for("licenses.view_software", id=id))


@licenses_bp.route("/software/categories", methods=["GET", "POST"])
@login_required
@permission_required("manage_software")
def categories():
    form = CategoryForm()
    if form.validate_on_submit():
        cat = Category(name=form.name.data.strip())
        db.session.add(cat)
        db.session.commit()
        log_action("create", "category", cat.id, {"name": cat.name})
        db.session.commit()
        flash(f"Category '{cat.name}' added.", "success")
        return redirect(url_for("licenses.categories"))
    all_categories = Category.query.order_by(Category.name).all()
    return render_template("licenses/categories.html", form=form, categories=all_categories)


@licenses_bp.route("/software/categories/<int:id>/delete", methods=["POST"])
@login_required
@permission_required("manage_software")
def delete_category(id):
    cat = Category.query.get_or_404(id)
    if cat.software:
        flash(f"Cannot delete '{cat.name}' while software is assigned to it.", "danger")
    else:
        name = cat.name
        db.session.delete(cat)
        log_action("delete", "category", id, {"name": name})
        db.session.commit()
        flash(f"Category '{name}' deleted.", "success")
    return redirect(url_for("licenses.categories"))
