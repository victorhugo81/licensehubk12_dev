from datetime import date, timedelta

from flask import Blueprint, render_template, request
from flask_login import current_user, login_required

from app.models import Contract, License, LicenseAllocation, Role, School, Vendor
from app.services.status import compute_expiration_status, get_thresholds
from app.utils.decorators import permission_required
from app.utils.exports import export

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")


def _visible_licenses():
    query = License.query
    if current_user.has_role(Role.SCHOOL_ADMINISTRATOR):
        query = query.join(LicenseAllocation).filter(LicenseAllocation.school_id == current_user.school_id).distinct()
    return query.all()


@reports_bp.route("/")
@login_required
@permission_required("view_reports")
def index():
    return render_template("reports/index.html")


@reports_bp.route("/inventory")
@login_required
@permission_required("view_reports")
def inventory():
    license_list = _visible_licenses()
    fmt = request.args.get("format")
    headers = ["License", "Vendor", "Category", "Total", "Assigned", "Available", "Status", "Expiration Date", "Annual Cost"]
    rows = [
        [lic.name, lic.vendor.name, lic.category.name if lic.category else "",
         lic.license_count, lic.assigned_licenses, lic.available_licenses, lic.status,
         lic.expiration_date.isoformat() if lic.expiration_date else "", float(lic.annual_cost or 0)]
        for lic in license_list
    ]
    if fmt:
        return export(fmt, "license_inventory", "License Inventory", headers, rows)
    return render_template("reports/inventory.html", license_list=license_list)


@reports_bp.route("/expiring")
@login_required
@permission_required("view_reports")
def expiring():
    days = request.args.get("days", 90, type=int)
    if days not in (30, 60, 90):
        days = 90
    cutoff = date.today() + timedelta(days=days)
    license_list = [
        lic for lic in _visible_licenses()
        if lic.expiration_date and date.today() <= lic.expiration_date <= cutoff
    ]
    license_list.sort(key=lambda lic: lic.expiration_date)

    fmt = request.args.get("format")
    headers = ["License", "Vendor", "Expiration Date", "Days Remaining", "Total Licenses"]
    rows = [
        [lic.name, lic.vendor.name, lic.expiration_date.isoformat(), lic.days_until_expiration, lic.license_count]
        for lic in license_list
    ]
    if fmt:
        return export(fmt, f"expiring_licenses_{days}d", f"Expiring Licenses (next {days} days)", headers, rows)
    return render_template("reports/expiring.html", license_list=license_list, days=days)


@reports_bp.route("/utilization")
@login_required
@permission_required("view_reports")
def utilization():
    license_list = [lic for lic in _visible_licenses() if lic.license_count]
    license_list.sort(key=lambda lic: lic.utilization_pct, reverse=True)

    fmt = request.args.get("format")
    headers = ["License", "Total Licenses", "Assigned", "Available", "Utilization %"]
    rows = [[lic.name, lic.license_count, lic.assigned_licenses, lic.available_licenses, lic.utilization_pct] for lic in license_list]
    if fmt:
        return export(fmt, "license_utilization", "License Utilization", headers, rows)
    return render_template("reports/utilization.html", license_list=license_list)


@reports_bp.route("/spending")
@login_required
@permission_required("view_reports")
def spending():
    license_list = _visible_licenses()
    fmt = request.args.get("format")
    headers = ["Vendor", "License", "Annual Cost", "Total Licenses", "Cost Per License"]
    rows = [[lic.vendor.name, lic.name, float(lic.annual_cost or 0), lic.license_count, lic.cost_per_license] for lic in license_list]
    if fmt:
        return export(fmt, "license_spending", "License Spending", headers, rows)
    return render_template("reports/spending.html", license_list=license_list)


@reports_bp.route("/school-allocation")
@login_required
@permission_required("view_reports")
def school_allocation():
    query = School.query
    if current_user.has_role(Role.SCHOOL_ADMINISTRATOR):
        query = query.filter(School.id == current_user.school_id)
    schools = query.order_by(School.name).all()

    fmt = request.args.get("format")
    headers = ["School", "License", "Allocated Licenses"]
    rows = [[a.school.name, a.license.name, a.allocated_count] for s in schools for a in s.allocations]
    if fmt:
        return export(fmt, "school_allocation", "School Allocation", headers, rows)
    return render_template("reports/school_allocation.html", schools=schools)


@reports_bp.route("/vendor-spending")
@login_required
@permission_required("view_reports")
def vendor_spending():
    vendors = Vendor.query.order_by(Vendor.name).all()
    fmt = request.args.get("format")
    headers = ["Vendor", "License Count", "Total Annual Spend"]
    rows = [[v.name, len(v.licenses), float(v.total_annual_spend)] for v in vendors]
    if fmt:
        return export(fmt, "vendor_spending", "Vendor Spending", headers, rows)
    return render_template("reports/vendor_spending.html", vendors=vendors)
