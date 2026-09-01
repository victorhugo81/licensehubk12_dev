from datetime import date, timedelta

from flask import Blueprint, render_template, request
from flask_login import current_user, login_required

from app.models import AuditLog, License, LicenseAllocation, Role
from app.services.status import (
    STATUS_CRITICAL, STATUS_EXPIRED, STATUS_WARNING, STATUS_UPCOMING,
    compute_expiration_status, get_thresholds,
)

dashboard_bp = Blueprint("dashboard", __name__)


def _visible_license_query():
    query = License.query
    if current_user.has_role(Role.SCHOOL_ADMINISTRATOR):
        query = query.join(LicenseAllocation).filter(
            LicenseAllocation.school_id == current_user.school_id
        ).distinct()
    return query


def dashboard_bucket(lic, thresholds):
    if lic.status in {"Suspended", "Pending Renewal", "Cancelled"}:
        return lic.status
    exp_status = compute_expiration_status(lic.expiration_date, thresholds)
    if exp_status == STATUS_EXPIRED:
        return "Expired"
    if exp_status in {STATUS_CRITICAL, STATUS_WARNING, STATUS_UPCOMING}:
        return "Expiring Soon"
    return "Active"


@dashboard_bp.route("/")
@login_required
def index():
    thresholds = get_thresholds()
    license_list = _visible_license_query().all()

    total_licenses = len(license_list)
    buckets = {"Active": 0, "Expiring Soon": 0, "Expired": 0, "Suspended": 0, "Pending Renewal": 0, "Cancelled": 0}
    for lic in license_list:
        buckets[dashboard_bucket(lic, thresholds)] += 1

    active_licenses = buckets["Active"] + buckets["Expiring Soon"]
    expiring_soon = buckets["Expiring Soon"]
    expired = buckets["Expired"]

    utilization = sorted(
        [lic for lic in license_list if lic.license_count],
        key=lambda lic: lic.utilization_pct,
        reverse=True,
    )[:6]

    expiring_days = request.args.get("days", default=90, type=int)
    if expiring_days not in (30, 60, 90):
        expiring_days = 90
    cutoff = date.today() + timedelta(days=expiring_days)
    expiring = sorted(
        [lic for lic in license_list if lic.expiration_date and date.today() <= lic.expiration_date <= cutoff],
        key=lambda lic: lic.expiration_date,
    )[:10]

    alerts = []
    for lic in license_list:
        status = compute_expiration_status(lic.expiration_date, thresholds)
        if status == STATUS_EXPIRED:
            days = -lic.days_until_expiration
            alerts.append(("critical", f"{lic.name} license expired {days} day(s) ago."))
        elif status == STATUS_CRITICAL:
            alerts.append(("warning", f"{lic.name} license expires in {lic.days_until_expiration} days."))
        elif status == STATUS_WARNING:
            alerts.append(("info", f"{lic.name} license expires in {lic.days_until_expiration} days."))
    alerts = alerts[:8]

    recent_activity = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(8).all()

    return render_template(
        "dashboard.html",
        total_licenses=total_licenses,
        active_licenses=active_licenses,
        expiring_soon=expiring_soon,
        expired=expired,
        buckets=buckets,
        utilization=utilization,
        expiring=expiring,
        expiring_days=expiring_days,
        alerts=alerts,
        recent_activity=recent_activity,
    )
