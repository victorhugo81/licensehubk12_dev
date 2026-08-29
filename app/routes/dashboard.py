from datetime import date, timedelta

from flask import Blueprint, render_template, request
from flask_login import current_user, login_required

from app.models import AuditLog, LicenseAllocation, Role, Software
from app.services.status import (
    STATUS_CRITICAL, STATUS_EXPIRED, STATUS_WARNING, STATUS_UPCOMING,
    compute_expiration_status, get_thresholds,
)

dashboard_bp = Blueprint("dashboard", __name__)


def _visible_software_query():
    query = Software.query
    if current_user.has_role(Role.SCHOOL_ADMINISTRATOR):
        query = query.join(LicenseAllocation).filter(
            LicenseAllocation.school_id == current_user.school_id
        ).distinct()
    return query


def dashboard_bucket(sw, thresholds):
    if sw.status in {"Suspended", "Pending Renewal", "Cancelled"}:
        return sw.status
    exp_status = compute_expiration_status(sw.expiration_date, thresholds)
    if exp_status == STATUS_EXPIRED:
        return "Expired"
    if exp_status in {STATUS_CRITICAL, STATUS_WARNING, STATUS_UPCOMING}:
        return "Expiring Soon"
    return "Active"


@dashboard_bp.route("/")
@login_required
def index():
    thresholds = get_thresholds()
    software_list = _visible_software_query().all()

    total_software = len(software_list)
    buckets = {"Active": 0, "Expiring Soon": 0, "Expired": 0, "Suspended": 0, "Pending Renewal": 0, "Cancelled": 0}
    for sw in software_list:
        buckets[dashboard_bucket(sw, thresholds)] += 1

    active_licenses = buckets["Active"] + buckets["Expiring Soon"]
    expiring_soon = buckets["Expiring Soon"]
    expired = buckets["Expired"]
    unused_licenses = sum(sw.available_licenses for sw in software_list)

    utilization = sorted(
        [sw for sw in software_list if sw.license_count],
        key=lambda s: s.utilization_pct,
        reverse=True,
    )[:6]

    expiring_days = request.args.get("days", default=90, type=int)
    if expiring_days not in (30, 60, 90):
        expiring_days = 90
    cutoff = date.today() + timedelta(days=expiring_days)
    expiring = sorted(
        [sw for sw in software_list if sw.expiration_date and date.today() <= sw.expiration_date <= cutoff],
        key=lambda s: s.expiration_date,
    )[:10]

    alerts = []
    for sw in software_list:
        status = compute_expiration_status(sw.expiration_date, thresholds)
        if status == STATUS_EXPIRED:
            days = -sw.days_until_expiration
            alerts.append(("critical", f"{sw.name} license expired {days} day(s) ago."))
        elif status == STATUS_CRITICAL:
            alerts.append(("warning", f"{sw.name} license expires in {sw.days_until_expiration} days."))
        elif status == STATUS_WARNING:
            alerts.append(("info", f"{sw.name} license expires in {sw.days_until_expiration} days."))
    alerts = alerts[:8]

    recent_activity = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(8).all()

    return render_template(
        "dashboard.html",
        total_software=total_software,
        active_licenses=active_licenses,
        expiring_soon=expiring_soon,
        expired=expired,
        unused_licenses=unused_licenses,
        buckets=buckets,
        utilization=utilization,
        expiring=expiring,
        expiring_days=expiring_days,
        alerts=alerts,
        recent_activity=recent_activity,
    )
