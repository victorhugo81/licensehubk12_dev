"""Authentication for app/routes/api.py.

The JSON API relies solely on the normal Flask-Login session cookie - the
same as every other page in the app - and is therefore subject to the
site's ordinary CSRF protection for anything that could mutate state
(the API blueprint is no longer CSRF-exempt). There's no separate bearer
token: an external caller without a logged-in browser session can only
use the read (GET) endpoints, and even a logged-in session can't drive a
state-changing request without a valid CSRF token.
"""
from functools import wraps

from flask import jsonify
from flask_login import current_user


def api_user():
    """The authenticated user for the current API request."""
    return current_user if current_user.is_authenticated else None


def api_login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify(error="Authentication required."), 401
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
