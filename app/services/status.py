"""License expiration status calculation.

Thresholds are admin-configurable (see app/models.py:Setting and
app/routes/settings.py) rather than hardcoded, per the spec:

    Expired    -> expiration_date < today
    Critical   -> 0-<critical_days> days remaining
    Warning    -> critical_days-<warning_days> days remaining
    Upcoming   -> warning_days-<upcoming_days> days remaining
    Active     -> more than upcoming_days days remaining
"""
from datetime import date

from app.models import Setting

STATUS_ACTIVE = "active"
STATUS_UPCOMING = "upcoming"
STATUS_WARNING = "warning"
STATUS_CRITICAL = "critical"
STATUS_EXPIRED = "expired"
STATUS_UNKNOWN = "unknown"

# Maps computed status -> Bootstrap contextual class, per spec section 20.
STATUS_BADGE_CLASS = {
    STATUS_ACTIVE: "success",
    STATUS_UPCOMING: "info",
    STATUS_WARNING: "warning",
    STATUS_CRITICAL: "danger",
    STATUS_EXPIRED: "dark",
    STATUS_UNKNOWN: "secondary",
}

STATUS_LABELS = {
    STATUS_ACTIVE: "Active",
    STATUS_UPCOMING: "Upcoming",
    STATUS_WARNING: "Warning",
    STATUS_CRITICAL: "Expiring",
    STATUS_EXPIRED: "Expired",
    STATUS_UNKNOWN: "Unknown",
}


def get_thresholds():
    return {
        "critical_days": Setting.get_int("critical_days", 30),
        "warning_days": Setting.get_int("warning_days", 60),
        "upcoming_days": Setting.get_int("upcoming_days", 90),
    }


def get_utilization_thresholds():
    return {
        "high_utilization_pct": Setting.get_int("high_utilization_pct", 90),
        "over_allocated_pct": Setting.get_int("over_allocated_pct", 100),
    }


def compute_expiration_status(expiration_date, thresholds=None, today=None):
    """Return one of STATUS_* for a given expiration date."""
    if expiration_date is None:
        return STATUS_UNKNOWN

    thresholds = thresholds or get_thresholds()
    today = today or date.today()
    days_remaining = (expiration_date - today).days

    if days_remaining < 0:
        return STATUS_EXPIRED
    if days_remaining <= thresholds["critical_days"]:
        return STATUS_CRITICAL
    if days_remaining <= thresholds["warning_days"]:
        return STATUS_WARNING
    if days_remaining <= thresholds["upcoming_days"]:
        return STATUS_UPCOMING
    return STATUS_ACTIVE


def badge_class(status: str) -> str:
    return STATUS_BADGE_CLASS.get(status, "secondary")


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, "Unknown")
