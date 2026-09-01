from datetime import date, timedelta

from flask import Blueprint, render_template, request
from flask_login import current_user, login_required

from app.models import Category, License, LicenseAllocation, Role, School, Vendor
from app.services import dashboard_metrics as metrics
from app.services.status import compute_expiration_status, get_thresholds
from app.utils.decorators import PERMISSIONS

dashboard_bp = Blueprint("dashboard", __name__)


def _visible_license_query():
    query = License.query
    if current_user.has_role(Role.SCHOOL_ADMINISTRATOR):
        query = query.join(LicenseAllocation).filter(
            LicenseAllocation.school_id == current_user.school_id
        ).distinct()
    return query


@dashboard_bp.route("/")
@login_required
def index():
    thresholds = get_thresholds()
    can_view_district_wide = current_user.has_role(*PERMISSIONS["view_district_wide"])

    query = metrics.apply_filters(_visible_license_query(), request.args, allow_school_filter=can_view_district_wide)
    license_list = query.all()

    kpis = metrics.compute_kpis(license_list, thresholds)

    expiring_days = request.args.get("days", default=90, type=int)
    if expiring_days not in (30, 60, 90):
        expiring_days = 90
    cutoff = date.today() + timedelta(days=expiring_days)
    expiring = sorted(
        [lic for lic in license_list if lic.expiration_date and date.today() <= lic.expiration_date <= cutoff],
        key=lambda lic: lic.expiration_date,
    )[:10]

    total_annual_spend = metrics.total_spend(license_list)
    upcoming_renewal_cost = metrics.upcoming_renewal_cost(license_list, expiring_days)

    utilization = sorted(
        [lic for lic in license_list if lic.license_count],
        key=lambda lic: lic.utilization_pct,
        reverse=True,
    )[:6]
    underutilized = metrics.underutilized_licenses(license_list)[:8]

    savings = metrics.potential_savings(license_list, thresholds)
    quality = metrics.data_quality_score(license_list)

    school_spend, vendor_spend, category_spend, school_rows, duplicates = [], [], [], [], []
    if can_view_district_wide:
        school_spend = metrics.spend_by_school(license_list)[:8]
        vendor_spend = metrics.spend_by_vendor(license_list)[:8]
        category_spend = metrics.spend_by_category(license_list)[:8]
        school_rows = metrics.school_comparison(license_list, thresholds)
        duplicates = metrics.potential_duplicates(license_list)
    elif current_user.school:
        total_annual_spend = metrics.spend_for_school(current_user.school, license_list)

    return render_template(
        "dashboard.html",
        can_view_district_wide=can_view_district_wide,
        kpis=kpis,
        total_annual_spend=total_annual_spend,
        upcoming_renewal_cost=upcoming_renewal_cost,
        utilization=utilization,
        underutilized=underutilized,
        expiring=expiring,
        expiring_days=expiring_days,
        savings=savings,
        quality=quality,
        school_spend=school_spend,
        vendor_spend=vendor_spend,
        category_spend=category_spend,
        school_rows=school_rows,
        duplicates=duplicates,
        vendors=Vendor.query.order_by(Vendor.name).all(),
        categories=Category.query.order_by(Category.name).all(),
        schools=School.query.filter_by(is_active=True).order_by(School.name).all() if can_view_district_wide else [],
        statuses=License.STATUSES,
        thresholds=thresholds,
        compute_expiration_status=compute_expiration_status,
    )
