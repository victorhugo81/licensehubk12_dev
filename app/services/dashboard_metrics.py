"""Aggregation logic for the executive dashboard (app/routes/dashboard.py).

Every function here operates on an already-filtered, already-RBAC-scoped
list of License objects (fetched once by the route) rather than re-querying,
so the whole dashboard stays consistent under one set of filters. The one
cost-apportionment rule used everywhere money is split across a dimension
(school/vendor/category) is `_license_cost_share()`: a Contract's
annual_cost divided evenly across the licenses it bundles - the same rule
already used for the per-school spend figure. These are dashboard
estimates, not stored facts, since per-license cost isn't tracked once a
contract covers more than one license.
"""
from datetime import date, timedelta

from app.models import License, LicenseAllocation
from app.services.status import (
    STATUS_CRITICAL, STATUS_EXPIRED, STATUS_UPCOMING, STATUS_WARNING,
    compute_expiration_status,
)

UTILIZATION_BANDS = [
    (80, "Highly Utilized"),
    (50, "Normal"),
    (20, "Underutilized"),
    (0, "Extremely Underutilized"),
]


def apply_filters(query, args, allow_school_filter=True):
    """SQL-level filtering shared by every dashboard metric. `args` is a
    request.args-like mapping. `allow_school_filter` is False for a School
    Administrator, whose visibility is already forced to their own school
    upstream - their other filters (vendor/category/status) still apply
    normally."""
    vendor_id = args.get("vendor_id", type=int)
    if vendor_id:
        query = query.filter(License.vendor_id == vendor_id)

    category_id = args.get("category_id", type=int)
    if category_id:
        query = query.filter(License.category_id == category_id)

    status = (args.get("status") or "").strip()
    if status:
        query = query.filter(License.status == status)

    if allow_school_filter:
        school_id = args.get("school_id", type=int)
        if school_id:
            query = query.join(LicenseAllocation).filter(
                LicenseAllocation.school_id == school_id
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


def compute_kpis(license_list, thresholds):
    buckets = {"Active": 0, "Expiring Soon": 0, "Expired": 0, "Suspended": 0, "Pending Renewal": 0, "Cancelled": 0}
    for lic in license_list:
        buckets[dashboard_bucket(lic, thresholds)] += 1

    total = len(license_list)
    active = buckets["Active"] + buckets["Expiring Soon"]
    expiring_soon = buckets["Expiring Soon"]
    expired = buckets["Expired"]

    def pct(n):
        return round((n / total) * 100, 1) if total else 0.0

    return {
        "total": total, "buckets": buckets,
        "active": active, "active_pct": pct(active),
        "expiring_soon": expiring_soon, "expiring_soon_pct": pct(expiring_soon),
        "expired": expired, "expired_pct": pct(expired),
    }


def _distinct_contracts(license_list):
    seen = {}
    for lic in license_list:
        if lic.contract:
            seen[lic.contract.id] = lic.contract
    return list(seen.values())


def total_spend(license_list):
    return round(sum(float(c.annual_cost or 0) for c in _distinct_contracts(license_list)), 2)


def upcoming_renewal_cost(license_list, days):
    today = date.today()
    cutoff = today + timedelta(days=days)
    return round(sum(
        float(c.annual_cost or 0) for c in _distinct_contracts(license_list)
        if today <= c.end_date <= cutoff
    ), 2)


def _license_cost_share(lic):
    contract = lic.contract
    if not contract or not contract.licenses:
        return 0.0
    return float(contract.annual_cost or 0) / len(contract.licenses)


def spend_by_school(license_list):
    totals = {}
    for lic in license_list:
        if not lic.license_count:
            continue
        share = _license_cost_share(lic)
        if not share:
            continue
        for alloc in lic.allocations:
            if not alloc.school.is_active:
                continue
            amount = (alloc.allocated_count / lic.license_count) * share
            totals[alloc.school] = totals.get(alloc.school, 0.0) + amount
    rows = [(school, round(amount, 2)) for school, amount in totals.items() if amount]
    rows.sort(key=lambda pair: pair[1], reverse=True)
    return rows


def spend_for_school(school, license_list):
    """Direct single-school figure (used for a School Administrator's own
    number), restricted to licenses in the already-filtered license_list."""
    allowed_ids = {lic.id for lic in license_list}
    total = 0.0
    for alloc in school.allocations:
        lic = alloc.license
        if lic.id not in allowed_ids or not lic.license_count:
            continue
        share = _license_cost_share(lic)
        if not share:
            continue
        total += (alloc.allocated_count / lic.license_count) * share
    return round(total, 2)


def spend_by_vendor(license_list):
    totals = {}
    for lic in license_list:
        share = _license_cost_share(lic)
        if not share:
            continue
        totals[lic.vendor] = totals.get(lic.vendor, 0.0) + share
    rows = [(vendor, round(amount, 2)) for vendor, amount in totals.items() if amount]
    rows.sort(key=lambda pair: pair[1], reverse=True)
    return rows


def spend_by_category(license_list):
    totals = {}
    uncategorized = 0.0
    for lic in license_list:
        share = _license_cost_share(lic)
        if not share:
            continue
        if lic.category is None:
            uncategorized += share
        else:
            totals[lic.category] = totals.get(lic.category, 0.0) + share
    rows = [(cat, round(amount, 2)) for cat, amount in totals.items() if amount]
    rows.sort(key=lambda pair: pair[1], reverse=True)
    if uncategorized:
        rows.append((None, round(uncategorized, 2)))
    return rows


def utilization_band(pct):
    for floor, label in UTILIZATION_BANDS:
        if pct >= floor:
            return label
    return UTILIZATION_BANDS[-1][1]


def underutilized_licenses(license_list):
    rows = [lic for lic in license_list if lic.license_count and lic.utilization_pct < 50]
    rows.sort(key=lambda lic: lic.utilization_pct)
    return rows


def potential_savings(license_list, thresholds):
    """Estimated, not guaranteed: expired-but-still-Active-status licenses'
    full cost share, plus the wasted-seat share of extremely underutilized
    (<20%) licenses."""
    expired_waste = 0.0
    underutilized_waste = 0.0
    for lic in license_list:
        share = _license_cost_share(lic)
        if not share:
            continue
        status = compute_expiration_status(lic.expiration_date, thresholds)
        if status == STATUS_EXPIRED and lic.status != "Cancelled":
            expired_waste += share
            continue
        if lic.license_count and lic.utilization_pct < 20:
            wasted_fraction = lic.available_licenses / lic.license_count
            underutilized_waste += wasted_fraction * share
    return {
        "total": round(expired_waste + underutilized_waste, 2),
        "expired": round(expired_waste, 2),
        "underutilized": round(underutilized_waste, 2),
    }


def potential_duplicates(license_list):
    """Heuristic only: active licenses sharing a category but coming from
    more than one vendor. Never presented as a confirmed duplicate - always
    labeled 'Potential Duplicate - Review'."""
    by_category = {}
    for lic in license_list:
        if lic.status != "Active" or not lic.category:
            continue
        by_category.setdefault(lic.category, []).append(lic)
    rows = [(cat, lics) for cat, lics in by_category.items() if len({lic.vendor_id for lic in lics}) > 1]
    rows.sort(key=lambda pair: len(pair[1]), reverse=True)
    return rows


def data_quality_score(license_list):
    """% of licenses with the optional-but-expected fields filled in:
    category, PO number, description, and at least one school allocation."""
    checks = [
        ("missing a category", lambda lic: lic.category_id is not None),
        ("missing a PO number", lambda lic: bool(lic.po_number)),
        ("missing a description", lambda lic: bool(lic.description)),
        ("not allocated to any school", lambda lic: len(lic.allocations) > 0),
    ]
    if not license_list:
        return {"pct": 100.0, "missing_fields": 0, "total_fields": 0, "issues": []}

    total = len(license_list) * len(checks)
    missing = 0
    issues = []
    for lic in license_list:
        for label, check in checks:
            if not check(lic):
                missing += 1
                issues.append((lic, label))
    pct = round(((total - missing) / total) * 100, 1)
    return {"pct": pct, "missing_fields": missing, "total_fields": total, "issues": issues}


def school_comparison(license_list, thresholds):
    spend_map = dict(spend_by_school(license_list))
    per_school = {}
    for lic in license_list:
        bucket = dashboard_bucket(lic, thresholds)
        for alloc in lic.allocations:
            school = alloc.school
            if not school.is_active:
                continue
            entry = per_school.setdefault(school, {
                "licenses": set(), "active": 0, "expiring": 0, "expired": 0,
                "utilization_sum": 0.0, "utilization_n": 0,
            })
            if lic.id in entry["licenses"]:
                continue
            entry["licenses"].add(lic.id)
            if bucket == "Active":
                entry["active"] += 1
            elif bucket == "Expiring Soon":
                entry["expiring"] += 1
            elif bucket == "Expired":
                entry["expired"] += 1
            if lic.license_count:
                entry["utilization_sum"] += lic.utilization_pct
                entry["utilization_n"] += 1

    rows = []
    for school, entry in per_school.items():
        avg_util = round(entry["utilization_sum"] / entry["utilization_n"], 1) if entry["utilization_n"] else 0.0
        spend = spend_map.get(school, 0.0)
        cost_per_student = round(spend / school.student_count, 2) if school.student_count else None
        rows.append({
            "school": school, "licenses": len(entry["licenses"]),
            "active": entry["active"], "expiring": entry["expiring"], "expired": entry["expired"],
            "spend": spend, "cost_per_student": cost_per_student, "utilization": avg_util,
        })
    rows.sort(key=lambda r: r["spend"], reverse=True)
    return rows
