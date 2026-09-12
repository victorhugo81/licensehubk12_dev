"""CSV bulk import for schools ("sites"). Two-phase like
app/integrations/csv_import.py and user_csv_import.py: validate_csv() never
touches the database and is safe to call repeatedly for a preview;
commit_import() is the only function that writes.

Expected columns (matches the district's sites.csv export format):
site_name, site_acronyms, site_cds, site_code, site_address, sitecity,
sitestate, sitezip, prnfirstn, prnlastn, email, phone, site_type
(`grades` and `student_count` are also accepted if present, but aren't part
of the standard export.)

`site_code` is the match key - a row whose code matches an existing school
updates it (every column above gets overwritten from the row); a new code
creates a new school. This mirrors app/integrations/csv_import.py's license
importer (re-uploading a refreshed roster updates existing records rather
than skipping them, unlike the user importer, where silently overwriting an
existing login would be unsafe).
"""
import csv
import io
import re
from dataclasses import dataclass, field

from app.extensions import db
from app.models import School

REQUIRED_COLUMNS = ["site_name", "site_code", "site_type"]
# See app/integrations/csv_import.py's MAX_ROWS for rationale.
MAX_ROWS = 20_000

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_STATE_RE = re.compile(r"^[A-Za-z]{2}$")

# Common shorthand accepted in the site_type column, normalized to the real
# School.TYPES values before validation/storage.
_TYPE_ABBREVIATIONS = {"ES": "Elementary", "MS": "Middle School", "HS": "High School"}


def _normalize_school_type(value):
    value = (value or "").strip()
    return _TYPE_ABBREVIATIONS.get(value.upper(), value)


@dataclass
class SchoolRowResult:
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
class SchoolImportPreview:
    rows: list
    total: int
    valid: int
    warnings: int
    errors: int
    column_errors: list = field(default_factory=list)


def _parse_student_count(value):
    value = (value or "").strip()
    if not value:
        return None, True
    try:
        n = int(value)
        return (n, True) if n >= 0 else (None, False)
    except ValueError:
        return None, False


def _parse_grades(value):
    """Returns (stored_string, unknown_tokens)."""
    value = (value or "").strip()
    if not value:
        return None, []
    tokens = [t.strip() for t in value.replace(";", ",").split(",") if t.strip()]
    known = [t for t in tokens if t in School.GRADES]
    unknown = [t for t in tokens if t not in School.GRADES]
    return (",".join(known) if known else None), unknown


def _principal_name(raw_row):
    first = (raw_row.get("prnfirstn") or "").strip()
    last = (raw_row.get("prnlastn") or "").strip()
    combined = " ".join(p for p in (first, last) if p)
    return combined or None


def validate_csv(file_stream) -> SchoolImportPreview:
    """Read a CSV file-like object (text) and return a validation preview.
    Performs no database writes."""
    raw = file_stream.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))

    if reader.fieldnames is None:
        return SchoolImportPreview(rows=[], total=0, valid=0, warnings=0, errors=0,
                                    column_errors=["The file is empty or not a valid CSV."])

    missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
    if missing:
        return SchoolImportPreview(rows=[], total=0, valid=0, warnings=0, errors=0,
                                    column_errors=[f"Missing required column(s): {', '.join(missing)}"])

    raw_rows = list(reader)
    if len(raw_rows) > MAX_ROWS:
        return SchoolImportPreview(rows=[], total=0, valid=0, warnings=0, errors=0,
                                    column_errors=[f"This file has {len(raw_rows)} rows; the limit is {MAX_ROWS:,} per import. Split it into smaller files."])
    reader = raw_rows

    existing_by_code = {s.code.strip().lower(): s for s in School.query.all()}

    rows: list[SchoolRowResult] = []
    seen_codes: set[str] = set()

    for i, raw_row in enumerate(reader, start=2):  # header is row 1
        result = SchoolRowResult(row_number=i, data=dict(raw_row))

        name = (raw_row.get("site_name") or "").strip()
        code = (raw_row.get("site_code") or "").strip()
        school_type = _normalize_school_type(raw_row.get("site_type"))
        result.data["site_type"] = school_type

        if not name:
            result.add_error("site_name is required.")
        if not code:
            result.add_error("site_code is required.")
        elif code.lower() in seen_codes:
            result.add_error(f"Duplicate site_code '{code}' elsewhere in this file.")
        else:
            seen_codes.add(code.lower())

        if not school_type:
            result.add_error("site_type is required.")
        elif school_type not in School.TYPES:
            result.add_error(f"'{school_type}' is not a valid site_type. Must be one of: {', '.join(School.TYPES)}.")

        student_count, count_ok = _parse_student_count(raw_row.get("student_count"))
        if not count_ok:
            result.add_error("student_count must be a non-negative integer.")

        _, unknown_grades = _parse_grades(raw_row.get("grades"))
        if unknown_grades:
            result.add_warning(f"Unrecognized grade(s) ignored: {', '.join(unknown_grades)}.")

        email = (raw_row.get("email") or "").strip()
        if email and not _EMAIL_RE.match(email):
            result.add_warning(f"'{email}' doesn't look like a valid email and will be saved as-is.")

        state = (raw_row.get("sitestate") or "").strip()
        if state and not _STATE_RE.match(state):
            result.add_warning(f"'{state}' doesn't look like a 2-letter state code and will be saved as-is.")

        if code and code.lower() in existing_by_code:
            result.add_warning(f"A school with site_code '{code}' already exists and will be updated.")

        rows.append(result)

    valid = sum(1 for r in rows if r.status == "valid")
    warnings = sum(1 for r in rows if r.status == "warning")
    errors = sum(1 for r in rows if r.status == "error")

    return SchoolImportPreview(rows=rows, total=len(rows), valid=valid, warnings=warnings, errors=errors)


def commit_import(preview: SchoolImportPreview):
    """Commit every non-error row from a previously computed preview.
    Returns (created_count, updated_count)."""
    existing_by_code = {s.code.strip().lower(): s for s in School.query.all()}

    created = 0
    updated = 0

    for result in preview.rows:
        if result.status == "error":
            continue

        data = result.data
        code = (data.get("site_code") or "").strip()
        name = (data.get("site_name") or "").strip()
        school_type = (data.get("site_type") or "").strip()
        address = (data.get("site_address") or "").strip() or None
        city = (data.get("sitecity") or "").strip() or None
        state = (data.get("sitestate") or "").strip().upper() or None
        zip_code = (data.get("sitezip") or "").strip() or None
        principal = _principal_name(data)
        email = (data.get("email") or "").strip() or None
        phone = (data.get("phone") or "").strip() or None
        acronym = (data.get("site_acronyms") or "").strip() or None
        cds_code = (data.get("site_cds") or "").strip() or None
        student_count, _ = _parse_student_count(data.get("student_count"))
        grades, _ = _parse_grades(data.get("grades"))

        school = existing_by_code.get(code.lower())
        if school is None:
            school = School(code=code)
            db.session.add(school)
            existing_by_code[code.lower()] = school
            created += 1
        else:
            updated += 1

        school.name = name
        school.school_type = school_type
        school.address = address
        school.city = city
        school.state = state
        school.zip_code = zip_code
        school.principal = principal
        school.email = email
        school.phone = phone
        school.acronym = acronym
        school.cds_code = cds_code
        school.grades = grades
        if student_count is not None:
            school.student_count = student_count

    return created, updated
