from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import UserForm
from app.models import Role, User
from app.services.audit import diff_changes, log_action
from app.utils.decorators import permission_required

users_bp = Blueprint("users", __name__, url_prefix="/administration/users")

PER_PAGE = 20


def _form_data(u):
    return {
        "first_name": u.first_name, "last_name": u.last_name, "email": u.email,
        "role_id": u.role_id, "school_id": u.school_id, "is_active_account": u.is_active_account,
    }


@users_bp.route("/")
@login_required
@permission_required("manage_users")
def list_users():
    q = request.args.get("q", "").strip()
    query = User.query
    if q:
        query = query.filter(User.email.ilike(f"%{q}%") | User.first_name.ilike(f"%{q}%") | User.last_name.ilike(f"%{q}%"))
    page = request.args.get("page", 1, type=int)
    pagination = query.order_by(User.last_name).paginate(page=page, per_page=PER_PAGE, error_out=False)
    return render_template("users/list.html", pagination=pagination, users=pagination.items)


@users_bp.route("/add", methods=["GET", "POST"])
@login_required
@permission_required("manage_users")
def add_user():
    form = UserForm()
    if form.validate_on_submit():
        if not form.password.data:
            form.password.errors.append("Password is required for new users.")
        elif User.query.filter(db.func.lower(User.email) == form.email.data.strip().lower()).first():
            form.email.errors.append("A user with this email already exists.")
        else:
            user = User(
                first_name=form.first_name.data, last_name=form.last_name.data,
                email=form.email.data.strip().lower(), role_id=form.role_id.data,
                school_id=form.school_id.data or None, is_active_account=form.is_active_account.data,
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            log_action("create", "user", user.id, {"email": user.email, "role": user.role.name})
            db.session.commit()
            flash(f"User {user.full_name} created.", "success")
            return redirect(url_for("users.list_users"))
    return render_template("users/form.html", form=form, user=None)


@users_bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_users")
def edit_user(id):
    user = User.query.get_or_404(id)
    before = _form_data(user)
    form = UserForm(obj=user)
    if request.method == "GET":
        form.school_id.data = user.school_id or 0

    if form.validate_on_submit():
        if user.id == current_user.id and form.role_id.data != user.role_id:
            flash("You cannot change your own role.", "danger")
            return render_template("users/form.html", form=form, user=user)

        user.first_name = form.first_name.data
        user.last_name = form.last_name.data
        user.email = form.email.data.strip().lower()
        user.role_id = form.role_id.data
        user.school_id = form.school_id.data or None
        user.is_active_account = form.is_active_account.data
        if form.password.data:
            user.set_password(form.password.data)
        db.session.commit()
        changes = diff_changes(before, _form_data(user))
        log_action("update", "user", user.id, changes)
        db.session.commit()
        flash(f"User {user.full_name} updated.", "success")
        return redirect(url_for("users.list_users"))
    return render_template("users/form.html", form=form, user=user)


@users_bp.route("/<int:id>/toggle-active", methods=["POST"])
@login_required
@permission_required("manage_users")
def toggle_active(id):
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash("You cannot deactivate your own account.", "danger")
        return redirect(url_for("users.list_users"))
    user.is_active_account = not user.is_active_account
    db.session.commit()
    log_action("update", "user", user.id, {"is_active_account": user.is_active_account})
    db.session.commit()
    flash(f"User {user.full_name} {'activated' if user.is_active_account else 'deactivated'}.", "success")
    return redirect(url_for("users.list_users"))


@users_bp.route("/<int:id>/api-key", methods=["POST"])
@login_required
@permission_required("manage_users")
def regenerate_api_key(id):
    user = User.query.get_or_404(id)
    user.generate_api_key()
    db.session.commit()
    log_action("update", "user", user.id, {"api_key": "regenerated"})
    db.session.commit()
    flash(f"API key regenerated for {user.full_name}.", "success")
    return redirect(url_for("users.edit_user", id=id))
