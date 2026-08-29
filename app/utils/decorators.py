"""Role-based access control.

Every protected route is guarded here, at the decorator level - never by
hiding UI elements alone. This is deliberate: RBAC was designed in from the
start rather than retrofitted, because bolting authorization onto existing
routes later means auditing every single one for gaps.

Usage:
    @bp.route("/software/<int:id>/edit")
    @login_required
    @permission_required("manage_software")
    def edit_software(id): ...
"""
from functools import wraps

from flask import abort, flash, redirect, url_for
from flask_login import current_user

from app.models import Role

# Permission -> roles allowed to perform it. Centralized so the access
# matrix from spec section 13 is defined exactly once.
PERMISSIONS = {
    "manage_users": {Role.ADMINISTRATOR},
    "manage_settings": {Role.ADMINISTRATOR},
    "view_audit_log": {Role.ADMINISTRATOR, Role.IT_ADMINISTRATOR},
    "manage_software": {Role.ADMINISTRATOR, Role.IT_ADMINISTRATOR, Role.CURRICULUM_ADMINISTRATOR},
    "manage_licenses": {Role.ADMINISTRATOR, Role.IT_ADMINISTRATOR, Role.CURRICULUM_ADMINISTRATOR},
    "manage_vendors": {Role.ADMINISTRATOR, Role.IT_ADMINISTRATOR},
    "manage_schools": {Role.ADMINISTRATOR, Role.IT_ADMINISTRATOR},
    "manage_contracts": {Role.ADMINISTRATOR, Role.IT_ADMINISTRATOR},
    "manage_import": {Role.ADMINISTRATOR, Role.IT_ADMINISTRATOR},
    "view_reports": {Role.ADMINISTRATOR, Role.IT_ADMINISTRATOR, Role.CURRICULUM_ADMINISTRATOR,
                      Role.SCHOOL_ADMINISTRATOR, Role.VIEWER},
    "view_district_wide": {Role.ADMINISTRATOR, Role.IT_ADMINISTRATOR, Role.CURRICULUM_ADMINISTRATOR, Role.VIEWER},
}


def roles_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))
            if not current_user.has_role(*roles):
                abort(403)
            return view_func(*args, **kwargs)
        return wrapped
    return decorator


def permission_required(permission):
    roles = PERMISSIONS.get(permission)
    if roles is None:
        raise ValueError(f"Unknown permission: {permission}")
    return roles_required(*roles)


def school_scoped_only(view_func):
    """Marks a route as available to School Administrators, restricted to
    their own school - use alongside a query filter via `scope_to_school`."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        return view_func(*args, **kwargs)
    return wrapped


def scope_to_school(query, school_column):
    """Restrict a SQLAlchemy query to the current user's school when they
    are a School Administrator. No-op for district-wide roles."""
    if current_user.has_role(Role.SCHOOL_ADMINISTRATOR):
        return query.filter(school_column == current_user.school_id)
    return query


def can_write(permission) -> bool:
    roles = PERMISSIONS.get(permission, set())
    return current_user.is_authenticated and current_user.has_role(*roles)
