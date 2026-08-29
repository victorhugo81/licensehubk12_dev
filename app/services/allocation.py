"""License-to-school allocation rules.

Central enforcement point for the invariant that total school allocations
for a piece of software can never exceed its district license count. This
lives at the service layer (not just in WTForms validators) so the API and
CSV import paths get the same guarantee as the web form.
"""
from app.extensions import db
from app.models import LicenseAllocation


class AllocationError(ValueError):
    pass


def total_allocated(software, exclude_allocation_id=None):
    total = 0
    for allocation in software.allocations:
        if exclude_allocation_id and allocation.id == exclude_allocation_id:
            continue
        total += allocation.allocated_count or 0
    return total


def set_allocation(software, school, count, notes=None):
    """Create or update the allocation of `software` to `school`.

    Raises AllocationError if the requested count would push the sum of all
    allocations for this software above its total license_count.
    """
    if count < 0:
        raise AllocationError("Allocated count cannot be negative.")

    existing = LicenseAllocation.query.filter_by(software_id=software.id, school_id=school.id).first()
    exclude_id = existing.id if existing else None

    other_total = total_allocated(software, exclude_allocation_id=exclude_id)
    if other_total + count > software.license_count:
        remaining = max(software.license_count - other_total, 0)
        raise AllocationError(
            f"Allocation of {count} exceeds the district license count for "
            f"{software.name}. Only {remaining} license(s) remain unallocated."
        )

    if existing:
        existing.allocated_count = count
        existing.notes = notes
        allocation = existing
    else:
        allocation = LicenseAllocation(
            software_id=software.id, school_id=school.id, allocated_count=count, notes=notes
        )
        db.session.add(allocation)

    return allocation


def remove_allocation(software, school):
    existing = LicenseAllocation.query.filter_by(software_id=software.id, school_id=school.id).first()
    if existing:
        db.session.delete(existing)
    return existing
