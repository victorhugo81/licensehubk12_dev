from datetime import timedelta

from app.extensions import db
from app.models import Notification, Setting, utcnow

# One admin-configurable on/off toggle per notification category (Settings
# page > Notification Settings), rather than per raw `type_` string, since
# several types share one human-meaningful "why am I getting this" concept
# (e.g. a license nearing expiration and one that already expired are both
# "License Expiring or Expired" to an admin turning this on/off). Every
# entry defaults to enabled, so an untouched Setting table reproduces the
# exact notification behavior this app always had.
NOTIFICATION_CATEGORIES = [
    {
        "key": "notify_license_expiring",
        "label": "License Expiring or Expired",
        "description": "A license is approaching its expiration date, or has already expired.",
        "types": ["license_expiration", "license_expired"],
    },
    {
        "key": "notify_license_added",
        "label": "New License Added",
        "description": "A new license was created (manually, via CSV/FTP import, or the API).",
        "types": ["license_added"],
    },
    {
        "key": "notify_contract_expiring",
        "label": "Contract Expiring",
        "description": "A contract is approaching its end date.",
        "types": ["contract_expiration"],
    },
    {
        "key": "notify_renewal_deadline",
        "label": "Cancellation Deadline Approaching",
        "description": "A contract's cancellation deadline is coming up.",
        "types": ["renewal_deadline"],
    },
    {
        "key": "notify_high_utilization",
        "label": "High Utilization",
        "description": "A license's usage has crossed the high-utilization threshold (Settings > License Status Thresholds).",
        "types": ["high_utilization"],
    },
    {
        "key": "notify_over_allocated",
        "label": "Over-Allocated",
        "description": "A license is allocated to schools beyond its total seat count.",
        "types": ["over_allocated"],
    },
    {
        "key": "notify_unused_licenses",
        "label": "Unused Licenses",
        "description": "A license has a significant number of unused seats.",
        "types": ["unused_licenses"],
    },
]

# type_ string (as passed to notify()) -> its category's Setting key.
_SETTING_KEY_BY_TYPE = {t: cat["key"] for cat in NOTIFICATION_CATEGORIES for t in cat["types"]}


def is_category_enabled(setting_key: str) -> bool:
    return Setting.get_bool(setting_key, True)


def notify(type_, title, message, severity="info", user_id=None, related_object_type=None, related_object_id=None):
    """Create a notification, avoiding duplicate same-day alerts for the
    same object/type so re-running the checker doesn't spam the feed.
    Returns None without creating anything if this type's category has
    been turned off (Settings > Notification Settings)."""
    setting_key = _SETTING_KEY_BY_TYPE.get(type_)
    if setting_key and not is_category_enabled(setting_key):
        return None

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
