from datetime import timedelta

from app.extensions import db
from app.models import Notification, utcnow


def notify(type_, title, message, severity="info", user_id=None, related_object_type=None, related_object_id=None):
    """Create a notification, avoiding duplicate same-day alerts for the
    same object/type so re-running the checker doesn't spam the feed."""
    since = utcnow() - timedelta(hours=20)
    existing = Notification.query.filter_by(
        type=type_,
        related_object_type=related_object_type,
        related_object_id=related_object_id,
        user_id=user_id,
    ).filter(Notification.created_at >= since).first()
    if existing:
        return existing

    note = Notification(
        type=type_,
        title=title,
        message=message,
        severity=severity,
        user_id=user_id,
        related_object_type=related_object_type,
        related_object_id=related_object_id,
    )
    db.session.add(note)
    return note


def unread_count(user):
    query = Notification.query.filter_by(is_read=False)
    query = query.filter((Notification.user_id == user.id) | (Notification.user_id.is_(None)))
    return query.count()


def visible_to(user, query=None):
    query = query or Notification.query
    return query.filter((Notification.user_id == user.id) | (Notification.user_id.is_(None)))
