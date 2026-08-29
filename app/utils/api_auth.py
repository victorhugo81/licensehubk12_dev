"""Authentication for app/routes/api.py.

Read (GET) requests may rely on the normal Flask-Login session cookie,
since those pages already carry CSRF protection for anything that could
mutate state. Any state-changing API call (POST/PUT/DELETE) must instead
present a per-user Bearer token (User.api_key) in the Authorization header
- tokens aren't sent automatically by a browser, so a malicious site can
never ride a logged-in session into an authenticated write through this
API, without needing per-request CSRF tokens for external/SIS callers.
"""
from functools import wraps

from flask import g, jsonify, request
from flask_login import current_user

from app.models import User


def _authenticate_bearer():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[len("Bearer "):].strip()
    if not token:
        return None
    user = User.query.filter_by(api_key=token).first()
    if user and user.is_active_account:
        return user
    return None


def api_user():
    """The authenticated user for the current API request, whether they
    came in via Bearer token or an existing browser session."""
    return getattr(g, "api_bearer_user", None) or (current_user if current_user.is_authenticated else None)


def api_login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        bearer_user = _authenticate_bearer()
        if bearer_user is not None:
            g.api_bearer_user = bearer_user
        elif not current_user.is_authenticated:
            return jsonify(error="Authentication required."), 401

        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and bearer_user is None:
            return jsonify(error="This operation requires an Authorization: Bearer <api_key> header."), 401

        return view_func(*args, **kwargs)
    return wrapped


def api_permission_required(permission):
    from app.utils.decorators import PERMISSIONS

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            roles = PERMISSIONS.get(permission, set())
            user = api_user()
            if user is None or not user.has_role(*roles):
                return jsonify(error="Forbidden."), 403
            return view_func(*args, **kwargs)
        return wrapped
    return decorator
