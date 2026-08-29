from flask import request
from flask_login import current_user

from app.extensions import db
from app.models import AuditLog


def log_action(action: str, object_type: str, object_id=None, changes: dict | None = None):
    """Record an audit entry. Safe to call even when there's no request
    context (e.g. from the background scheduler) or no logged-in user."""
    user_id = None
    ip_address = None
    try:
        if current_user and current_user.is_authenticated:
            user_id = current_user.id
    except Exception:
        pass
    try:
        ip_address = request.remote_addr
    except RuntimeError:
        ip_address = None

    entry = AuditLog(
        user_id=user_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        ip_address=ip_address,
    )
    if changes:
        entry.changes = changes
    db.session.add(entry)
    return entry


def diff_changes(before: dict, after: dict) -> dict:
    """Return {field: {"from": x, "to": y}} for fields that differ."""
    changes = {}
    for key in after:
        old = before.get(key)
        new = after.get(key)
        if str(old) != str(new):
            changes[key] = {"from": old, "to": new}
    return changes
