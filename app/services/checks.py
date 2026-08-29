"""Automated data-processing checks (spec section 24).

`run_all_checks()` is the single entry point. It is scheduler-agnostic: it
takes no scheduler-specific arguments and can be invoked from a cron job, a
Windows Task Scheduler action, a Celery task, an APScheduler job (see
app/services/scheduler.py for the optional in-process wiring), or the
`flask run-checks` CLI command, all calling the exact same code path.
"""
from datetime import date, timedelta

from app.extensions import db
from app.models import Software, Contract
from app.services import notifications
from app.services.status import compute_expiration_status, get_thresholds, get_utilization_thresholds, STATUS_EXPIRED, STATUS_CRITICAL


def check_license_expirations():
    thresholds = get_thresholds()
    horizon = thresholds["upcoming_days"]
    upper = date.today() + timedelta(days=horizon)
    for sw in Software.query.filter(Software.expiration_date.isnot(None), Software.expiration_date <= upper).all():
        status = compute_expiration_status(sw.expiration_date, thresholds)
        if status == STATUS_EXPIRED:
            notifications.notify(
                "license_expired",
                f"{sw.name} license expired",
                f"The license for {sw.name} expired on {sw.expiration_date:%m/%d/%Y}.",
                severity="critical",
                related_object_type="software",
                related_object_id=sw.id,
            )
        else:
            days = sw.days_until_expiration
            severity = "critical" if status == STATUS_CRITICAL else "warning" if status == "warning" else "info"
            notifications.notify(
                "license_expiration",
                f"{sw.name} license expires soon",
                f"The license for {sw.name} expires in {days} day(s) on {sw.expiration_date:%m/%d/%Y}.",
                severity=severity,
                related_object_type="software",
                related_object_id=sw.id,
            )


def check_contract_expirations():
    thresholds = get_thresholds()
    upper = date.today() + timedelta(days=thresholds["upcoming_days"])
    for contract in Contract.query.filter(Contract.end_date <= upper).all():
        days = contract.days_until_end
        severity = "critical" if days < 0 or days <= thresholds["critical_days"] else "warning"
        notifications.notify(
            "contract_expiration",
            f"Contract {contract.contract_number} expiring",
            f"Contract {contract.contract_number} with {contract.vendor.name} ends "
            f"{'in ' + str(days) + ' day(s)' if days >= 0 else str(-days) + ' day(s) ago'} "
            f"({contract.end_date:%m/%d/%Y}).",
            severity=severity,
            related_object_type="contract",
            related_object_id=contract.id,
        )
        if contract.cancellation_deadline and 0 <= (contract.cancellation_deadline - date.today()).days <= thresholds["critical_days"]:
            notifications.notify(
                "renewal_deadline",
                f"Cancellation deadline approaching: {contract.contract_number}",
                f"The cancellation deadline for contract {contract.contract_number} is "
                f"{contract.cancellation_deadline:%m/%d/%Y}.",
                severity="warning",
                related_object_type="contract",
                related_object_id=contract.id,
            )


def check_utilization():
    ut = get_utilization_thresholds()
    for sw in Software.query.all():
        if not sw.license_count:
            continue
        pct = sw.utilization_pct
        # Allocations are hard-capped at license_count (see
        # app/services/allocation.py), so pct can only exceed 100% if
        # license_count was later reduced below what's already assigned -
        # a real over-allocation, distinct from simply being fully
        # subscribed at exactly 100%.
        if pct > ut["over_allocated_pct"]:
            notifications.notify(
                "over_allocated",
                f"{sw.name} is over-allocated",
                f"{sw.name} utilization is {pct}% ({sw.assigned_licenses}/{sw.license_count}).",
                severity="critical",
                related_object_type="software",
                related_object_id=sw.id,
            )
        elif pct > ut["high_utilization_pct"]:
            notifications.notify(
                "high_utilization",
                f"{sw.name} utilization is high",
                f"{sw.name} utilization is {pct}% ({sw.assigned_licenses}/{sw.license_count}).",
                severity="warning",
                related_object_type="software",
                related_object_id=sw.id,
            )


def check_unused_licenses(min_unused=0.25):
    for sw in Software.query.all():
        if not sw.license_count:
            continue
        unused_pct = sw.available_licenses / sw.license_count
        if unused_pct >= min_unused and sw.available_licenses > 0:
            notifications.notify(
                "unused_licenses",
                f"{sw.name} has unused licenses",
                f"{sw.name} has {sw.available_licenses} unused license(s) "
                f"(${sw.unused_license_cost:,.2f}/year).",
                severity="info",
                related_object_type="software",
                related_object_id=sw.id,
            )


def run_all_checks():
    """Run every automated check and commit any notifications created."""
    check_license_expirations()
    check_contract_expirations()
    check_utilization()
    check_unused_licenses()
    db.session.commit()
