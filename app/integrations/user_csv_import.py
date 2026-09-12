"""CSV bulk import for user accounts (manual upload or FTP-pulled - see
app/integrations/ftp_users.py). Two-phase like app/integrations/csv_import.py:
validate_csv() never touches the database and is safe to call repeatedly for
a preview; commit_import() is the only function that writes, and it
re-checks each email against live DB state (not just the preview snapshot),
so a race between preview and commit can't create a duplicate account.

The standard district roster export has exactly these columns: first_name,
middle_name, last_name, email, site_name, status - no role column at all.
Any other column present in the file is simply ignored (csv.DictReader
already does this - unread keys in a row are never looked at). A `role`
column is still accepted for callers who want it (e.g. deliberately
provisioning an Administrator via CSV): if present it's only used when
CREATING a new user; a new user with no role column defaults to the
least-privileged Viewer role. `site_name` is optional metadata recorded on
User.school_id for ANY role (a "what site is this person at" fact, not a
data-scoping grant - only School Administrator's own school_id is ever used
to restrict a query, see app/utils/decorators.py::scope_to_school), except
when the row is explicitly creating a School Administrator, where a valid
site_name is still required (a School Administrator with no school would
break that account's own scoping everywhere else in the app).

A row whose email matches an existing user UPDATES that account's
first_name/middle_name/last_name/status/site_name instead of creating a
duplicate - but never touches its role. A CSV re-upload is not a place to
grant or revoke admin access; role changes go through the Users page. Any
`role` value on such a row is validated only loosely (a warning if it's
unrecognized or differs from the current role) and otherwise ignored.

Security: a newly created bulk-imported user's password is a random value
nobody is ever shown - a password-reset token is issued immediately instead
(the same mechanism as the "forgot password" flow), so the only way into the
new account is for the person to set their own password via that link. No
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

REQUIRED_COLUMNS = ["first_name", "last_name", "email"]
RESET_TOKEN_VALID_DAYS = 7
DEFAULT_ROLE = Role.VIEWER
# See app/integrations/csv_import.py's MAX_ROWS for rationale.
MAX_ROWS = 20_000

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_VALID_STATUSES = {"active", "inactive"}


def _parse_status(value):
    """Returns (is_active, is_valid). Blank defaults to active."""
    value = (value or "").strip().lower()
    if not value:
        return True, True
    if value not in _VALID_STATUSES:
        return True, False
    return value == "active", True


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
    existing_by_email = {u.email.strip().lower(): u for u in User.query.all()}

    rows: list[UserRowResult] = []
    seen_emails: set[str] = set()

    for i, raw_row in enumerate(reader, start=2):  # header is row 1
        result = UserRowResult(row_number=i, data=dict(raw_row))

        first_name = (raw_row.get("first_name") or "").strip()
        last_name = (raw_row.get("last_name") or "").strip()
        email = (raw_row.get("email") or "").strip().lower()
        role_name = (raw_row.get("role") or "").strip()
        site_name = (raw_row.get("site_name") or "").strip()

        if not first_name:
            result.add_error("First name is required.")
        if not last_name:
            result.add_error("Last name is required.")

        existing_user = None
        if not email:
            result.add_error("Email is required.")
        elif not _EMAIL_RE.match(email):
            result.add_error(f"'{email}' is not a valid email address.")
        elif email in seen_emails:
            result.add_error(f"Duplicate email '{email}' elsewhere in this file.")
        else:
            existing_user = existing_by_email.get(email)
            if existing_user:
                result.add_warning(f"A user with email '{email}' already exists and will be updated (its role is never changed by import).")

        if email and _EMAIL_RE.match(email):
            seen_emails.add(email)

        role = roles_by_name.get(role_name.lower()) if role_name else None
        site_error_added = False

        if existing_user is None:
            if role_name and role is None:
                result.add_error(
                    f"'{role_name}' is not a valid role. Must be one of: "
                    + ", ".join(sorted(r.name for r in roles_by_name.values()))
                )
            else:
                # No role column (or a blank value) defaults a new user to
                # Viewer - the standard district roster export has no role
                # column at all.
                effective_role = role or roles_by_name.get(DEFAULT_ROLE.lower())
                if effective_role and effective_role.name == "School Administrator":
                    if not site_name:
                        result.add_error("site_name is required for role School Administrator.")
                        site_error_added = True
                    elif site_name.lower() not in schools_by_name:
                        result.add_error(f"School '{site_name}' does not exist in LicenseHubK12.")
                        site_error_added = True
        elif role_name and role is None:
            result.add_warning(f"'{role_name}' is not a valid role - the role column is ignored for existing users anyway.")
        elif role_name and role.name != existing_user.role.name:
            result.add_warning(f"'{email}' keeps its current role ({existing_user.role.name}) - the role column is ignored for existing users.")

        if site_name and site_name.lower() not in schools_by_name and not site_error_added:
            result.add_warning(f"School '{site_name}' does not exist and will be ignored.")

        status_raw = (raw_row.get("status") or "").strip()
        if status_raw:
            _, status_ok = _parse_status(status_raw)
            if not status_ok:
                result.add_warning(f"'{status_raw}' is not Active/Inactive - status will not be changed.")

        rows.append(result)

    valid = sum(1 for r in rows if r.status == "valid")
    warnings = sum(1 for r in rows if r.status == "warning")
    errors = sum(1 for r in rows if r.status == "error")

    return UserImportPreview(rows=rows, total=len(rows), valid=valid, warnings=warnings, errors=errors)


def commit_import(preview: UserImportPreview):
    """Commit every non-error row from a previously computed preview.
    A row matching an existing email (re-checked here against live DB
    state, not just the preview snapshot) updates that account's
    name/status/site - never its role. Any other row creates a new
    account, defaulting to the Viewer role when none is given. Returns
    (created_count, updated_count, results) where results is a list of
    dicts describing each *created* user, including its one-time password
    reset token."""
    roles_by_name = {r.name.strip().lower(): r for r in Role.query.all()}
    schools_by_name = {s.name.strip().lower(): s for s in School.query.all()}
    existing_by_email = {u.email.strip().lower(): u for u in User.query.all()}

    created = 0
    updated = 0
    results = []

    for result in preview.rows:
        if result.status == "error":
            continue

        data = result.data
        email = (data.get("email") or "").strip().lower()
        existing_user = existing_by_email.get(email)

        if existing_user:
            first_name = (data.get("first_name") or "").strip()
            middle_name = (data.get("middle_name") or "").strip()
            last_name = (data.get("last_name") or "").strip()
            status_raw = (data.get("status") or "").strip()
            site = schools_by_name.get((data.get("site_name") or "").strip().lower())

            if first_name:
                existing_user.first_name = first_name
            if middle_name:
                existing_user.middle_name = middle_name
            if last_name:
                existing_user.last_name = last_name
            if status_raw:
                is_active, status_ok = _parse_status(status_raw)
                if status_ok:
                    existing_user.is_active_account = is_active
            if site:
                existing_user.school_id = site.id
            # existing_user.role_id is intentionally never touched here.
            updated += 1
            continue

        role = roles_by_name.get((data.get("role") or "").strip().lower()) or roles_by_name.get(DEFAULT_ROLE.lower())
        site = schools_by_name.get((data.get("site_name") or "").strip().lower())
        is_active, _ = _parse_status(data.get("status"))

        user = User(
            first_name=(data.get("first_name") or "").strip(),
            middle_name=(data.get("middle_name") or "").strip() or None,
            last_name=(data.get("last_name") or "").strip(),
            email=email,
            role_id=role.id,
            school_id=site.id if site else None,
            is_active_account=is_active,
        )
        user.set_password(secrets.token_urlsafe(32))
        user.reset_token = secrets.token_urlsafe(48)
        user.reset_token_expires = utcnow() + timedelta(days=RESET_TOKEN_VALID_DAYS)
        db.session.add(user)
        db.session.flush()
        existing_by_email[email] = user

        created += 1
        results.append({
            "email": user.email, "full_name": user.full_name,
            "role": role.name, "reset_token": user.reset_token,
        })

    return created, updated, results
