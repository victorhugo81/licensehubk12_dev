from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import AllocationForm, CategoryForm, LicenseForm
from app.models import Category, Contract, License, LicenseAllocation, Role, School, Vendor
from app.services import allocation as allocation_service
from app.services.audit import diff_changes, log_action
from app.services.status import compute_expiration_status, get_thresholds
from app.utils.decorators import permission_required, scope_to_school

licenses_bp = Blueprint("licenses", __name__)

PER_PAGE = 20


def _license_form_data(lic):
    return {
        "name": lic.name, "category_id": lic.category_id or 0,
        "license_count": lic.license_count, "status": lic.status,
    }


@licenses_bp.route("/licenses")
@login_required
def list_licenses():
    query = License.query

    if current_user.has_role(Role.SCHOOL_ADMINISTRATOR):
        query = query.join(LicenseAllocation).filter(
            LicenseAllocation.school_id == current_user.school_id
        ).distinct()

    q = request.args.get("q", "").strip()
    if q:
        query = query.filter(License.name.ilike(f"%{q}%"))

    vendor_id = request.args.get("vendor_id", type=int)
    if vendor_id:
        query = query.filter(License.vendor_id == vendor_id)

    category_id = request.args.get("category_id", type=int)
    if category_id:
        query = query.filter(License.category_id == category_id)

    status = request.args.get("status", "").strip()
    if status:
        query = query.filter(License.status == status)

    thresholds = get_thresholds()

    page = request.args.get("page", 1, type=int)
    pagination = query.order_by(License.name).paginate(page=page, per_page=PER_PAGE, error_out=False)

    return render_template(
        "licenses/list.html",
        pagination=pagination,
        license_list=pagination.items,
        vendors=Vendor.query.order_by(Vendor.name).all(),
        categories=Category.query.order_by(Category.name).all(),
        contracts=Contract.query.order_by(Contract.po_number).all(),
        statuses=License.STATUSES,
        thresholds=thresholds,
        compute_expiration_status=compute_expiration_status,
    )


@licenses_bp.route("/licenses/new")
@login_required
@permission_required("manage_licenses")
def new_license_redirect():
    contract_id = request.args.get("contract_id", type=int)
    if not contract_id:
        flash("Choose a contract to add a license to.", "danger")
        return redirect(url_for("licenses.list_licenses"))
    Contract.query.get_or_404(contract_id)
    return redirect(url_for("licenses.add_license", contract_id=contract_id))


@licenses_bp.route("/contracts/<int:contract_id>/licenses/add", methods=["GET", "POST"])
@login_required
@permission_required("manage_licenses")
def add_license(contract_id):
    contract = Contract.query.get_or_404(contract_id)
    form = LicenseForm()
    if form.validate_on_submit():
        lic = License(contract=contract, vendor_id=contract.vendor_id, created_by_id=current_user.id)
        form.populate_obj(lic)
        lic.category_id = form.category_id.data or None
        db.session.add(lic)
        db.session.commit()
        log_action("create", "license", lic.id, {"name": lic.name})
        db.session.commit()
        flash(f"{lic.name} added.", "success")
        return redirect(url_for("licenses.view_license", id=lic.id))
    return render_template("licenses/form.html", form=form, lic=None, contract=contract)


@licenses_bp.route("/licenses/<int:id>")
@login_required
def view_license(id):
    lic = License.query.get_or_404(id)
    if current_user.has_role(Role.SCHOOL_ADMINISTRATOR):
        if not any(a.school_id == current_user.school_id for a in lic.allocations):
            abort(403)
    thresholds = get_thresholds()
    return render_template(
        "licenses/detail.html",
        lic=lic,
        thresholds=thresholds,
        computed_status=compute_expiration_status(lic.expiration_date, thresholds),
        allocation_form=AllocationForm(),
    )


@licenses_bp.route("/licenses/<int:id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_licenses")
def edit_license(id):
    lic = License.query.get_or_404(id)
    before = _license_form_data(lic)
    form = LicenseForm(obj=lic)
    if request.method == "GET":
        form.category_id.data = lic.category_id or 0

    if form.validate_on_submit():
        form.populate_obj(lic)
        lic.category_id = form.category_id.data or None
        db.session.commit()
        changes = diff_changes(before, _license_form_data(lic))
        log_action("update", "license", lic.id, changes)
        db.session.commit()
        flash(f"{lic.name} updated.", "success")
        return redirect(url_for("licenses.view_license", id=lic.id))
    return render_template("licenses/form.html", form=form, lic=lic)


@licenses_bp.route("/licenses/<int:id>/delete", methods=["POST"])
@login_required
@permission_required("manage_licenses")
def delete_license(id):
    lic = License.query.get_or_404(id)
    name = lic.name
    db.session.delete(lic)
    log_action("delete", "license", id, {"name": name})
    db.session.commit()
    flash(f"{name} deleted.", "success")
    return redirect(url_for("licenses.list_licenses"))


@licenses_bp.route("/licenses/<int:id>/utilization")
@login_required
def utilization(id):
    lic = License.query.get_or_404(id)
    if current_user.has_role(Role.SCHOOL_ADMINISTRATOR):
        if not any(a.school_id == current_user.school_id for a in lic.allocations):
            abort(403)
    allocations = sorted(lic.allocations, key=lambda a: a.allocated_count, reverse=True)
    return render_template("licenses/utilization.html", lic=lic, allocations=allocations)


@licenses_bp.route("/licenses/<int:id>/allocations", methods=["POST"])
@login_required
@permission_required("manage_licenses")
def add_allocation(id):
    lic = License.query.get_or_404(id)
    form = AllocationForm()
    if form.validate_on_submit():
        school = School.query.get_or_404(form.school_id.data)
        try:
            allocation_service.set_allocation(lic, school, form.allocated_count.data, form.notes.data)
            db.session.commit()
            log_action("update", "license_allocation", lic.id, {
                "school": school.name, "allocated_count": form.allocated_count.data,
            })
            db.session.commit()
            flash(f"Allocation for {school.name} saved.", "success")
        except allocation_service.AllocationError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    else:
        flash("Please correct the errors in the allocation form.", "danger")
    return redirect(url_for("licenses.view_license", id=id))


@licenses_bp.route("/licenses/<int:id>/allocations/<int:allocation_id>/delete", methods=["POST"])
@login_required
@permission_required("manage_licenses")
def delete_allocation(id, allocation_id):
    allocation = LicenseAllocation.query.get_or_404(allocation_id)
    if allocation.license_id != id:
        abort(404)
    school_name = allocation.school.name
    db.session.delete(allocation)
    log_action("delete", "license_allocation", id, {"school": school_name})
    db.session.commit()
    flash(f"Allocation for {school_name} removed.", "success")
    return redirect(url_for("licenses.view_license", id=id))


@licenses_bp.route("/licenses/categories", methods=["GET", "POST"])
@login_required
@permission_required("manage_licenses")
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


@licenses_bp.route("/licenses/categories/<int:id>/delete", methods=["POST"])
@login_required
@permission_required("manage_licenses")
def delete_category(id):
    cat = Category.query.get_or_404(id)
    if cat.licenses:
        flash(f"Cannot delete '{cat.name}' while licenses are assigned to it.", "danger")
    else:
        name = cat.name
        db.session.delete(cat)
        log_action("delete", "category", id, {"name": name})
        db.session.commit()
        flash(f"Category '{name}' deleted.", "success")
    return redirect(url_for("licenses.categories"))
