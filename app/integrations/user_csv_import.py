"""CSV bulk import for user accounts (manual upload or FTP-pulled - see
app/integrations/ftp_users.py). Two-phase like app/integrations/csv_import.py:
validate_csv() never touches the database and is safe to call repeatedly for
a preview; commit_import() is the only function that writes, and it
re-checks for existing emails against live DB state so a race between
preview and commit can't create a duplicate account.

Expected columns: first_name, last_name, email, role, school
`school` is required only when role is School Administrator.

Security: a bulk-imported user's password is a random value nobody is ever
shown - a password-reset token is issued immediately instead (the same
mechanism as the "forgot password" flow), so the only way into the new
account is for the person to set their own password via that link. No
temporary password is ever generated, stored, or displayed.
"""
import csv
import io
import re
import secrets
from dataclasses import dataclass, field
from datetime import timedelta

from app.extensions import db
from app.models import Role, School, User, utcnow

REQUIRED_COLUMNS = ["first_name", "last_name", "email", "role"]
RESET_TOKEN_VALID_DAYS = 7
# See app/integrations/csv_import.py's MAX_ROWS for rationale.
MAX_ROWS = 20_000

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class UserRowResult:
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
class UserImportPreview:
    rows: list
    total: int
    valid: int
    warnings: int
    errors: int
    column_errors: list = field(default_factory=list)


def validate_csv(file_stream) -> UserImportPreview:
    """Read a CSV file-like object (text) and return a validation preview.
    Performs no database writes."""
    raw = file_stream.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))

    if reader.fieldnames is None:
        return UserImportPreview(rows=[], total=0, valid=0, warnings=0, errors=0,
                                  column_errors=["The file is empty or not a valid CSV."])

    missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
    if missing:
        return UserImportPreview(rows=[], total=0, valid=0, warnings=0, errors=0,
                                  column_errors=[f"Missing required column(s): {', '.join(missing)}"])

    raw_rows = list(reader)
    if len(raw_rows) > MAX_ROWS:
        return UserImportPreview(rows=[], total=0, valid=0, warnings=0, errors=0,
                                  column_errors=[f"This file has {len(raw_rows)} rows; the limit is {MAX_ROWS:,} per import. Split it into smaller files."])
    reader = raw_rows

    roles_by_name = {r.name.strip().lower(): r for r in Role.query.all()}
    schools_by_name = {s.name.strip().lower(): s for s in School.query.all()}
    existing_emails = {u.email.strip().lower() for u in User.query.all()}

    rows: list[UserRowResult] = []
    seen_emails: set[str] = set()

    for i, raw_row in enumerate(reader, start=2):  # header is row 1
        result = UserRowResult(row_number=i, data=dict(raw_row))

        first_name = (raw_row.get("first_name") or "").strip()
        last_name = (raw_row.get("last_name") or "").strip()
        email = (raw_row.get("email") or "").strip().lower()
        role_name = (raw_row.get("role") or "").strip()
        school_name = (raw_row.get("school") or "").strip()

        if not first_name:
            result.add_error("First name is required.")
        if not last_name:
            result.add_error("Last name is required.")

        if not email:
            result.add_error("Email is required.")
        elif not _EMAIL_RE.match(email):
            result.add_error(f"'{email}' is not a valid email address.")
        elif email in seen_emails:
            result.add_error(f"Duplicate email '{email}' elsewhere in this file.")
        elif email in existing_emails:
            result.add_warning(f"A user with email '{email}' already exists and will be skipped.")

        if email and _EMAIL_RE.match(email):
            seen_emails.add(email)

        role = roles_by_name.get(role_name.lower()) if role_name else None
        if not role_name:
            result.add_error("Role is required.")
        elif role is None:
            result.add_error(
                f"'{role_name}' is not a valid role. Must be one of: "
                + ", ".join(sorted(r.name for r in roles_by_name.values()))
            )

        school = schools_by_name.get(school_name.lower()) if school_name else None
        if role and role.name == "School Administrator":
            if not school_name:
                result.add_error("School is required for role School Administrator.")
            elif school is None:
                result.add_error(f"School '{school_name}' does not exist in LicenseHubK12.")
        elif school_name and school is None:
            result.add_warning(f"School '{school_name}' does not exist and will be ignored.")

        rows.append(result)

    valid = sum(1 for r in rows if r.status == "valid")
    warnings = sum(1 for r in rows if r.status == "warning")
    errors = sum(1 for r in rows if r.status == "error")

    return UserImportPreview(rows=rows, total=len(rows), valid=valid, warnings=warnings, errors=errors)


def commit_import(preview: UserImportPreview):
    """Commit every non-error row from a previously computed preview,
    skipping any row whose email already exists (re-checked here against
    live DB state, not just the preview snapshot). Returns
    (created_count, skipped_count, results) where results is a list of
    dicts describing each created user, including its one-time password
    reset token."""
    roles_by_name = {r.name.strip().lower(): r for r in Role.query.all()}
    schools_by_name = {s.name.strip().lower(): s for s in School.query.all()}

    created = 0
    skipped = 0
    results = []

    for result in preview.rows:
        if result.status == "error":
            continue

        data = result.data
        email = (data.get("email") or "").strip().lower()

        if User.query.filter(db.func.lower(User.email) == email).first():
            skipped += 1
            continue

        role = roles_by_name.get((data.get("role") or "").strip().lower())
        school = schools_by_name.get((data.get("school") or "").strip().lower())

        user = User(
            first_name=(data.get("first_name") or "").strip(),
            last_name=(data.get("last_name") or "").strip(),
            email=email,
            role_id=role.id,
            school_id=school.id if (school and role.name == "School Administrator") else None,
            is_active_account=True,
        )
        user.set_password(secrets.token_urlsafe(32))
        user.reset_token = secrets.token_urlsafe(48)
        user.reset_token_expires = utcnow() + timedelta(days=RESET_TOKEN_VALID_DAYS)
        db.session.add(user)
        db.session.flush()

        created += 1
        results.append({
            "email": user.email, "full_name": user.full_name,
            "role": role.name, "reset_token": user.reset_token,
        })

    return created, skipped, results
