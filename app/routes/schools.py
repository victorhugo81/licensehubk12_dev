from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import SchoolForm
from app.models import LicenseAllocation, Role, School
from app.services.audit import diff_changes, log_action
from app.utils.decorators import permission_required

schools_bp = Blueprint("schools", __name__, url_prefix="/schools")

PER_PAGE = 20


def _form_data(s):
    return {
        "name": s.name, "code": s.code, "school_type": s.school_type, "address": s.address,
        "principal": s.principal, "grades": s.grades, "student_count": s.student_count,
        "is_active": s.is_active,
    }


@schools_bp.route("/")
@login_required
def list_schools():
    query = School.query
    if current_user.has_role(Role.SCHOOL_ADMINISTRATOR):
        query = query.filter(School.id == current_user.school_id)

    q = request.args.get("q", "").strip()
    if q:
        query = query.filter(School.name.ilike(f"%{q}%"))
    school_type = request.args.get("school_type", "").strip()
    if school_type:
        query = query.filter(School.school_type == school_type)

    page = request.args.get("page", 1, type=int)
    pagination = query.order_by(School.name).paginate(page=page, per_page=PER_PAGE, error_out=False)
    return render_template("schools/list.html", pagination=pagination, schools=pagination.items, types=School.TYPES)


@schools_bp.route("/add", methods=["GET", "POST"])
@login_required
@permission_required("manage_schools")
def add_school():
    form = SchoolForm()
    if form.validate_on_submit():
        school = School()
        form.populate_obj(school)
        db.session.add(school)
        db.session.commit()
        log_action("create", "school", school.id, {"name": school.name})
        db.session.commit()
        flash(f"{school.name} added.", "success")
        return redirect(url_for("schools.view_school", id=school.id))
    return render_template("schools/form.html", form=form, school=None)


@schools_bp.route("/<int:id>")
@login_required
def view_school(id):
    school = School.query.get_or_404(id)
    if current_user.has_role(Role.SCHOOL_ADMINISTRATOR) and current_user.school_id != id:
        abort(403)
    allocations = LicenseAllocation.query.filter_by(school_id=id).all()
    return render_template("schools/detail.html", school=school, allocations=allocations)


@schools_bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_schools")
def edit_school(id):
    school = School.query.get_or_404(id)
    before = _form_data(school)
    form = SchoolForm(obj=school)
    if form.validate_on_submit():
        form.populate_obj(school)
        db.session.commit()
        changes = diff_changes(before, _form_data(school))
        log_action("update", "school", school.id, changes)
        db.session.commit()
        flash(f"{school.name} updated.", "success")
        return redirect(url_for("schools.view_school", id=school.id))
    return render_template("schools/form.html", form=form, school=school)


@schools_bp.route("/<int:id>/delete", methods=["POST"])
@login_required
@permission_required("manage_schools")
def delete_school(id):
    school = School.query.get_or_404(id)
    if school.allocations:
        flash(f"Cannot delete {school.name} while it has license allocations.", "danger")
        return redirect(url_for("schools.view_school", id=id))
    name = school.name
    db.session.delete(school)
    log_action("delete", "school", id, {"name": name})
    db.session.commit()
    flash(f"{name} deleted.", "success")
    return redirect(url_for("schools.list_schools"))
