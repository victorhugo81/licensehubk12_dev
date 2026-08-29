"""CSV bulk import for software/license/school-allocation data (spec section 12).

Two-phase by design: `validate_csv()` never touches the database and is
safe to call repeatedly for a preview; `commit_import()` is the only
function that writes, and it re-validates against live DB state (via
app.services.allocation) before writing each row so a race between preview
and commit can't smuggle in an over-allocation.

Expected columns: software, vendor, school, total_licenses,
assigned_licenses, expiration_date, annual_cost
"""
import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.models import Category, School, Software, Vendor
from app.services import allocation as allocation_service

REQUIRED_COLUMNS = ["software", "vendor", "school", "total_licenses", "assigned_licenses", "expiration_date", "annual_cost"]


@dataclass
class RowResult:
    row_number: int
    data: dict
    status: str = "valid"  # valid | warning | error
    messages: list = field(default_factory=list)

    def add_error(self, msg):
        self.status = "error"
        self.messages.append(msg)

    def add_warning(self, msg):
        if self.status != "error":
            self.status = "warning"
        self.messages.append(msg)


@dataclass
class ImportPreview:
    rows: list
    total: int
    valid: int
    warnings: int
    errors: int
    column_errors: list = field(default_factory=list)


def _parse_int(value):
    try:
        n = int(str(value).strip())
        if n < 0:
            return None
        return n
    except (TypeError, ValueError):
        return None


def _parse_decimal(value):
    try:
        d = Decimal(str(value).strip())
        if d < 0:
            return None
        return d
    except (InvalidOperation, TypeError, ValueError):
        return None


def _parse_date(value):
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def validate_csv(file_stream) -> ImportPreview:
    """Read a CSV file-like object (text) and return a validation preview.
    Performs no database writes."""
    raw = file_stream.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))

    if reader.fieldnames is None:
        return ImportPreview(rows=[], total=0, valid=0, warnings=0, errors=0,
                              column_errors=["The file is empty or not a valid CSV."])

    missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
    if missing:
        return ImportPreview(rows=[], total=0, valid=0, warnings=0, errors=0,
                              column_errors=[f"Missing required column(s): {', '.join(missing)}"])

    existing_schools = {s.name.strip().lower(): s for s in School.query.all()}
    existing_software = {s.name.strip().lower(): s for s in Software.query.all()}

    rows: list[RowResult] = []
    software_totals: dict[str, int] = {}
    software_assigned_sum: dict[str, int] = {}

    for i, raw_row in enumerate(reader, start=2):  # header is row 1
        result = RowResult(row_number=i, data=dict(raw_row))
        software_name = (raw_row.get("software") or "").strip()
        vendor_name = (raw_row.get("vendor") or "").strip()
        school_name = (raw_row.get("school") or "").strip()

        if not software_name:
            result.add_error("Software name is required.")
        if not vendor_name:
            result.add_error("Vendor is required.")
        if not school_name:
            result.add_error("School is required.")

        school = existing_schools.get(school_name.lower()) if school_name else None
        if school_name and school is None:
            result.add_error(f"School '{school_name}' does not exist in LicenseHubK12.")

        total_licenses = _parse_int(raw_row.get("total_licenses"))
        if total_licenses is None:
            result.add_error("total_licenses must be a non-negative integer.")

        assigned_licenses = _parse_int(raw_row.get("assigned_licenses"))
        if assigned_licenses is None:
            result.add_error("assigned_licenses must be a non-negative integer.")

        if total_licenses is not None and assigned_licenses is not None and assigned_licenses > total_licenses:
            result.add_error("assigned_licenses cannot exceed total_licenses.")

        expiration = _parse_date(raw_row.get("expiration_date"))
        if raw_row.get("expiration_date") and expiration is None:
            result.add_error("expiration_date must be YYYY-MM-DD or MM/DD/YYYY.")
        elif expiration and expiration < date.today():
            result.add_warning("expiration_date is in the past.")

        annual_cost = _parse_decimal(raw_row.get("annual_cost"))
        if raw_row.get("annual_cost") and annual_cost is None:
            result.add_error("annual_cost must be a non-negative number.")

        existing_sw = existing_software.get(software_name.lower()) if software_name else None
        if existing_sw and existing_sw.vendor.name.strip().lower() != vendor_name.lower():
            result.add_warning(
                f"'{software_name}' already exists with vendor '{existing_sw.vendor.name}'; "
                f"the vendor will not be changed to '{vendor_name}'."
            )

        if software_name and total_licenses is not None:
            key = software_name.lower()
            software_totals[key] = max(software_totals.get(key, 0), total_licenses)

        rows.append(result)

    # Cross-row check: total assigned per software (this import batch) can't
    # exceed that software's district total_licenses.
    for result in rows:
        if result.status == "error":
            continue
        key = (result.data.get("software") or "").strip().lower()
        assigned = _parse_int(result.data.get("assigned_licenses")) or 0
        software_assigned_sum[key] = software_assigned_sum.get(key, 0) + assigned

    for result in rows:
        if result.status == "error":
            continue
        key = (result.data.get("software") or "").strip().lower()
        total = software_totals.get(key)
        assigned_sum = software_assigned_sum.get(key)
        if total is not None and assigned_sum is not None and assigned_sum > total:
            result.add_error(
                f"Combined assigned_licenses across all rows for '{result.data.get('software')}' "
                f"({assigned_sum}) exceeds its total_licenses ({total})."
            )

    valid = sum(1 for r in rows if r.status == "valid")
    warnings = sum(1 for r in rows if r.status == "warning")
    errors = sum(1 for r in rows if r.status == "error")

    return ImportPreview(rows=rows, total=len(rows), valid=valid, warnings=warnings, errors=errors)


def commit_import(preview: ImportPreview, imported_by=None):
    """Commit every non-error row from a previously computed preview.
    Errors are never imported. Returns (created_software, updated_software, allocation_errors)."""
    created, updated = 0, 0
    allocation_errors = []

    for result in preview.rows:
        if result.status == "error":
            continue

        data = result.data
        software_name = data["software"].strip()
        vendor_name = data["vendor"].strip()
        school_name = data["school"].strip()
        total_licenses = _parse_int(data.get("total_licenses"))
        assigned_licenses = _parse_int(data.get("assigned_licenses")) or 0
        expiration = _parse_date(data.get("expiration_date"))
        annual_cost = _parse_decimal(data.get("annual_cost")) or Decimal("0")

        vendor = Vendor.query.filter(db.func.lower(Vendor.name) == vendor_name.lower()).first()
        if vendor is None:
            vendor = Vendor(name=vendor_name)
            db.session.add(vendor)
            db.session.flush()

        school = School.query.filter(db.func.lower(School.name) == school_name.lower()).first()
        if school is None:
            allocation_errors.append(f"Row {result.row_number}: school '{school_name}' not found, skipped.")
            continue

        software = Software.query.filter(db.func.lower(Software.name) == software_name.lower()).first()
        if software is None:
            software = Software(
                name=software_name,
                vendor=vendor,
                license_type="District License",
                license_count=total_licenses or 0,
                expiration_date=expiration,
                annual_cost=annual_cost,
                status="Active",
                created_by_id=imported_by.id if imported_by else None,
            )
            db.session.add(software)
            db.session.flush()
            created += 1
        else:
            if total_licenses is not None:
                software.license_count = max(software.license_count, total_licenses)
            if expiration:
                software.expiration_date = expiration
            if annual_cost:
                software.annual_cost = annual_cost
            updated += 1

        try:
            allocation_service.set_allocation(software, school, assigned_licenses)
        except allocation_service.AllocationError as exc:
            allocation_errors.append(f"Row {result.row_number}: {exc}")

    db.session.commit()
    return created, updated, allocation_errors
