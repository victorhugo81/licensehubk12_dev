from datetime import date, timedelta

from flask import Blueprint, render_template, request
from flask_login import current_user, login_required

from app.models import Contract, LicenseAllocation, Role, School, Software, Vendor
from app.services.status import compute_expiration_status, get_thresholds
from app.utils.decorators import permission_required
from app.utils.exports import export

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")


def _visible_software():
    query = Software.query
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
    software_list = _visible_software()
    fmt = request.args.get("format")
    headers = ["Software", "Vendor", "Category", "License Type", "Total", "Assigned", "Available", "Status", "Expiration Date", "Annual Cost"]
    rows = [
        [s.name, s.vendor.name, s.category.name if s.category else "", s.license_type,
         s.license_count, s.assigned_licenses, s.available_licenses, s.status,
         s.expiration_date.isoformat() if s.expiration_date else "", float(s.annual_cost or 0)]
        for s in software_list
    ]
    if fmt:
        return export(fmt, "license_inventory", "License Inventory", headers, rows)
    return render_template("reports/inventory.html", software_list=software_list)


@reports_bp.route("/expiring")
@login_required
@permission_required("view_reports")
def expiring():
    days = request.args.get("days", 90, type=int)
    if days not in (30, 60, 90):
        days = 90
    cutoff = date.today() + timedelta(days=days)
    software_list = [
        s for s in _visible_software()
        if s.expiration_date and date.today() <= s.expiration_date <= cutoff
    ]
    software_list.sort(key=lambda s: s.expiration_date)

    fmt = request.args.get("format")
    headers = ["Software", "Vendor", "Expiration Date", "Days Remaining", "Total Licenses"]
    rows = [
        [s.name, s.vendor.name, s.expiration_date.isoformat(), s.days_until_expiration, s.license_count]
        for s in software_list
    ]
    if fmt:
        return export(fmt, f"expiring_licenses_{days}d", f"Expiring Licenses (next {days} days)", headers, rows)
    return render_template("reports/expiring.html", software_list=software_list, days=days)


@reports_bp.route("/utilization")
@login_required
@permission_required("view_reports")
def utilization():
    software_list = [s for s in _visible_software() if s.license_count]
    software_list.sort(key=lambda s: s.utilization_pct, reverse=True)

    fmt = request.args.get("format")
    headers = ["Software", "Total Licenses", "Assigned", "Available", "Utilization %"]
    rows = [[s.name, s.license_count, s.assigned_licenses, s.available_licenses, s.utilization_pct] for s in software_list]
    if fmt:
        return export(fmt, "license_utilization", "License Utilization", headers, rows)
    return render_template("reports/utilization.html", software_list=software_list)


@reports_bp.route("/spending")
@login_required
@permission_required("view_reports")
def spending():
    software_list = _visible_software()
    fmt = request.args.get("format")
    headers = ["Vendor", "Software", "Annual Cost", "Total Licenses", "Cost Per License"]
    rows = [[s.vendor.name, s.name, float(s.annual_cost or 0), s.license_count, s.cost_per_license] for s in software_list]
    if fmt:
        return export(fmt, "software_spending", "Software Spending", headers, rows)
    return render_template("reports/spending.html", software_list=software_list)


@reports_bp.route("/school-allocation")
@login_required
@permission_required("view_reports")
def school_allocation():
    query = School.query
    if current_user.has_role(Role.SCHOOL_ADMINISTRATOR):
        query = query.filter(School.id == current_user.school_id)
    schools = query.order_by(School.name).all()

    fmt = request.args.get("format")
    headers = ["School", "Software", "Allocated Licenses"]
    rows = [[a.school.name, a.software.name, a.allocated_count] for s in schools for a in s.allocations]
    if fmt:
        return export(fmt, "school_allocation", "School Allocation", headers, rows)
    return render_template("reports/school_allocation.html", schools=schools)


@reports_bp.route("/vendor-spending")
@login_required
@permission_required("view_reports")
def vendor_spending():
    vendors = Vendor.query.order_by(Vendor.name).all()
    fmt = request.args.get("format")
    headers = ["Vendor", "Software Count", "Total Annual Spend"]
    rows = [[v.name, len(v.software), float(v.total_annual_spend)] for v in vendors]
    if fmt:
        return export(fmt, "vendor_spending", "Vendor Spending", headers, rows)
    return render_template("reports/vendor_spending.html", vendors=vendors)
