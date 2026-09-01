import json
import secrets
from datetime import datetime, date, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


def utcnow():
    # Naive UTC, deliberately - SQLite (local dev) round-trips
    # DateTime(timezone=True) values as naive datetimes regardless of how
    # they were written, so comparing against an aware "now" raises
    # TypeError. Storing naive UTC everywhere keeps every comparison
    # consistent across SQLite and MySQL/MariaDB (production).
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Reference / lookup tables
# ---------------------------------------------------------------------------

class Role(db.Model):
    __tablename__ = "roles"

    ADMINISTRATOR = "Administrator"
    IT_ADMINISTRATOR = "IT Administrator"
    CURRICULUM_ADMINISTRATOR = "Curriculum Administrator"
    SCHOOL_ADMINISTRATOR = "School Administrator"
    VIEWER = "Viewer"

    ALL = [ADMINISTRATOR, IT_ADMINISTRATOR, CURRICULUM_ADMINISTRATOR, SCHOOL_ADMINISTRATOR, VIEWER]

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.String(255))

    users = db.relationship("User", back_populates="role")

    def __repr__(self):
        return f"<Role {self.name}>"


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

    licenses = db.relationship("License", back_populates="category")

    DEFAULTS = [
        "Curriculum", "Assessment", "Student Information", "Learning Management",
        "Intervention", "Special Education", "Data & Analytics", "Communication",
        "Productivity", "Security", "Library", "Professional Development", "Other",
    ]

    def __repr__(self):
        return f"<Category {self.name}>"


class Setting(db.Model):
    """Admin-configurable key/value settings (status thresholds, etc.)."""
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.String(255), nullable=False)

    @staticmethod
    def get_int(key, default):
        row = Setting.query.filter_by(key=key).first()
        if row is None:
            return default
        try:
            return int(row.value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def set_value(key, value):
        row = Setting.query.filter_by(key=key).first()
        if row is None:
            row = Setting(key=key, value=str(value))
            db.session.add(row)
        else:
            row.value = str(value)
        return row


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)

    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    role = db.relationship("Role", back_populates="users")

    # Only meaningful for School Administrator role - scopes visibility.
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=True)
    school = db.relationship("School", back_populates="users")

    is_active_account = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime)

    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime)

    reset_token = db.Column(db.String(255), unique=True, nullable=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)

    # Bearer token for the JSON API (app/routes/api.py). Session cookies are
    # sufficient for GET requests made by the app's own pages, but
    # state-changing API calls (and any future SIS/Clever/Canvas
    # integration) require this token instead, so a browser session alone
    # can never be tricked into an authenticated cross-site write.
    api_key = db.Column(db.String(64), unique=True, nullable=True)

    def generate_api_key(self):
        self.api_key = secrets.token_hex(32)
        return self.api_key

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    # Flask-Login integration
    @property
    def is_active(self):
        return self.is_active_account

    def is_locked(self):
        return bool(self.locked_until and self.locked_until > utcnow())

    def has_role(self, *role_names):
        return self.role and self.role.name in role_names

    def can_view_school(self, school_id):
        if self.has_role(Role.ADMINISTRATOR, Role.IT_ADMINISTRATOR, Role.CURRICULUM_ADMINISTRATOR, Role.VIEWER):
            return True
        if self.has_role(Role.SCHOOL_ADMINISTRATOR):
            return self.school_id == school_id
        return False

    def __repr__(self):
        return f"<User {self.email}>"


# ---------------------------------------------------------------------------
# Schools / Vendors
# ---------------------------------------------------------------------------

class School(db.Model):
    __tablename__ = "schools"

    TYPES = ["Elementary", "Middle School", "High School", "Alternative", "District Office", "Other"]

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, index=True)
    code = db.Column(db.String(30), unique=True, nullable=False)
    school_type = db.Column(db.String(30), nullable=False, default="Elementary")
    address = db.Column(db.String(255))
    principal = db.Column(db.String(150))
    grades = db.Column(db.String(50))
    student_count = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    users = db.relationship("User", back_populates="school")
    allocations = db.relationship("LicenseAllocation", back_populates="school", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<School {self.name}>"


class Vendor(db.Model):
    __tablename__ = "vendors"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False, index=True)
    website = db.Column(db.String(255))
    support_email = db.Column(db.String(255))
    support_phone = db.Column(db.String(50))
    account_manager = db.Column(db.String(150))
    account_number = db.Column(db.String(100))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    licenses = db.relationship("License", back_populates="vendor")
    contracts = db.relationship("Contract", back_populates="vendor")

    @property
    def total_annual_spend(self):
        return sum((lic.annual_cost or 0) for lic in self.licenses)

    def __repr__(self):
        return f"<Vendor {self.name}>"


# ---------------------------------------------------------------------------
# Licenses
# ---------------------------------------------------------------------------

class License(db.Model):
    __tablename__ = "licenses"

    # Administrative lifecycle status (independent of the computed
    # expiration countdown used for dashboard badge colors - see
    # app/services/status.py).
    STATUSES = ["Active", "Suspended", "Pending Renewal", "Cancelled"]

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, index=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)
    description = db.Column(db.Text)

    license_count = db.Column(db.Integer, nullable=False, default=0)

    start_date = db.Column(db.Date)
    expiration_date = db.Column(db.Date, index=True)
    renewal_date = db.Column(db.Date)

    po_number = db.Column(db.String(100))
    support_url = db.Column(db.String(255))
    login_url = db.Column(db.String(255))
    notes = db.Column(db.Text)

    status = db.Column(db.String(30), nullable=False, default="Active", index=True)

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    vendor = db.relationship("Vendor", back_populates="licenses")
    category = db.relationship("Category", back_populates="licenses")
    allocations = db.relationship("LicenseAllocation", back_populates="license", cascade="all, delete-orphan")
    contracts = db.relationship("Contract", back_populates="license")

    @property
    def assigned_licenses(self):
        return sum((a.allocated_count or 0) for a in self.allocations)

    @property
    def available_licenses(self):
        return max((self.license_count or 0) - self.assigned_licenses, 0)

    @property
    def utilization_pct(self):
        if not self.license_count:
            return 0.0
        return round((self.assigned_licenses / self.license_count) * 100, 1)

    @property
    def current_contract(self):
        """The contract annual_cost/vendor_contact are drawn from: the
        currently-active contract (end_date in the future) with the latest
        end_date, or - if none are active - the most recently ended one.
        None if this license has no contracts at all."""
        if not self.contracts:
            return None
        today = date.today()
        active = [c for c in self.contracts if c.end_date >= today]
        return max(active, key=lambda c: c.end_date) if active else max(self.contracts, key=lambda c: c.end_date)

    @property
    def vendor_contact(self):
        contract = self.current_contract
        return contract.vendor_contact if contract else None

    @property
    def annual_cost(self):
        """Total annual cost across all currently-active contracts (0 if
        none are active) - a license with several concurrent contracts
        (e.g. per-building site licenses) sums them."""
        today = date.today()
        return sum((c.annual_cost or 0) for c in self.contracts if c.end_date >= today)

    @property
    def cost_per_license(self):
        if not self.license_count:
            return 0.0
        return round(float(self.annual_cost or 0) / self.license_count, 2)

    @property
    def unused_license_cost(self):
        return round(self.available_licenses * self.cost_per_license, 2)

    @property
    def days_until_expiration(self):
        if not self.expiration_date:
            return None
        return (self.expiration_date - date.today()).days

    def __repr__(self):
        return f"<License {self.name}>"


class LicenseAllocation(db.Model):
    """Allocation of a district's license count to a specific school."""
    __tablename__ = "license_allocations"
    __table_args__ = (
        db.UniqueConstraint("license_id", "school_id", name="uq_allocation_license_school"),
    )

    id = db.Column(db.Integer, primary_key=True)
    license_id = db.Column(db.Integer, db.ForeignKey("licenses.id"), nullable=False, index=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    allocated_count = db.Column(db.Integer, nullable=False, default=0)
    notes = db.Column(db.String(255))
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    license = db.relationship("License", back_populates="allocations")
    school = db.relationship("School", back_populates="allocations")

    def __repr__(self):
        return f"<LicenseAllocation license={self.license_id} school={self.school_id} count={self.allocated_count}>"


class Contract(db.Model):
    __tablename__ = "contracts"

    PAYMENT_FREQUENCIES = ["Monthly", "Quarterly", "Annual", "Multi-Year", "One-Time"]

    id = db.Column(db.Integer, primary_key=True)
    # The one identifying number for a contract - there's no separate
    # contract_number, to avoid carrying two identifying numbers for the
    # same agreement.
    po_number = db.Column(db.String(100), nullable=False, index=True)
    # Derived from license.vendor_id at creation time - contracts are
    # always managed from the license detail page now, so there's no
    # separate vendor picker; this column is kept for direct vendor-spend
    # queries (Vendor.contracts) without a join through License.
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=False, index=True)
    license_id = db.Column(db.Integer, db.ForeignKey("licenses.id"), nullable=False, index=True)

    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False, index=True)
    renewal_date = db.Column(db.Date)

    annual_cost = db.Column(db.Numeric(12, 2), default=0)
    vendor_contact = db.Column(db.String(150))
    payment_frequency = db.Column(db.String(30), nullable=False, default="Annual")
    auto_renewal = db.Column(db.Boolean, default=False, nullable=False)
    cancellation_deadline = db.Column(db.Date)
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    vendor = db.relationship("Vendor", back_populates="contracts")
    license = db.relationship("License", back_populates="contracts")

    @property
    def days_until_end(self):
        return (self.end_date - date.today()).days

    def __repr__(self):
        return f"<Contract {self.po_number}>"


# ---------------------------------------------------------------------------
# Notifications / Audit / Imports
# ---------------------------------------------------------------------------

class Notification(db.Model):
    __tablename__ = "notifications"

    TYPES = [
        "license_expiration", "contract_expiration", "renewal_deadline",
        "high_utilization", "over_allocated", "unused_licenses", "license_expired",
    ]
    SEVERITIES = ["critical", "warning", "info"]

    id = db.Column(db.Integer, primary_key=True)
    # Null user_id = district-wide notification visible to all admin roles.
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    type = db.Column(db.String(50), nullable=False)
    severity = db.Column(db.String(20), nullable=False, default="info")
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text)

    related_object_type = db.Column(db.String(50))
    related_object_id = db.Column(db.Integer)

    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)

    def __repr__(self):
        return f"<Notification {self.type} {self.title}>"


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    action = db.Column(db.String(50), nullable=False)
    object_type = db.Column(db.String(50), nullable=False, index=True)
    object_id = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)
    ip_address = db.Column(db.String(64))
    changes_json = db.Column(db.Text)

    user = db.relationship("User")

    @property
    def changes(self):
        if not self.changes_json:
            return {}
        try:
            return json.loads(self.changes_json)
        except ValueError:
            return {}

    @changes.setter
    def changes(self, value: dict):
        self.changes_json = json.dumps(value, default=str)

    def __repr__(self):
        return f"<AuditLog {self.action} {self.object_type}#{self.object_id}>"


class ImportHistory(db.Model):
    __tablename__ = "import_history"

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    imported_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    imported_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    total_records = db.Column(db.Integer, default=0)
    valid_records = db.Column(db.Integer, default=0)
    warning_records = db.Column(db.Integer, default=0)
    error_records = db.Column(db.Integer, default=0)

    status = db.Column(db.String(30), default="completed")
    details_json = db.Column(db.Text)

    imported_by = db.relationship("User")

    @property
    def details(self):
        if not self.details_json:
            return {}
        try:
            return json.loads(self.details_json)
        except ValueError:
            return {}

    @details.setter
    def details(self, value: dict):
        self.details_json = json.dumps(value, default=str)

    def __repr__(self):
        return f"<ImportHistory {self.filename}>"
