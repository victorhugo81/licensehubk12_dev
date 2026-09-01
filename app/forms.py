from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileRequired
from wtforms import (
    BooleanField, DateField, DecimalField, FileField, IntegerField, PasswordField,
    SelectField, SelectMultipleField, StringField, SubmitField, TextAreaField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, Optional, Regexp, ValidationError
from wtforms.widgets import CheckboxInput

from app.models import Contract, License, Role, School


class GradesField(SelectMultipleField):
    """Renders as a checkbox per grade; stored on the model as a single
    comma-separated string (School.grades), not a list column."""

    option_widget = CheckboxInput()

    def process_data(self, value):
        self.data = [g.strip() for g in value.split(",")] if value else []

    def populate_obj(self, obj, name):
        setattr(obj, name, ",".join(self.data) if self.data else None)


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired()])
    remember_me = BooleanField("Remember me")
    submit = SubmitField("Sign in")


class RequestResetForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    submit = SubmitField("Send reset link")


class ResetPasswordForm(FlaskForm):
    password = PasswordField("New password", validators=[DataRequired(), Length(min=10)])
    confirm_password = PasswordField(
        "Confirm password", validators=[DataRequired(), EqualTo("password", message="Passwords must match.")]
    )
    submit = SubmitField("Reset password")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current password", validators=[DataRequired()])
    password = PasswordField("New password", validators=[DataRequired(), Length(min=10)])
    confirm_password = PasswordField(
        "Confirm password", validators=[DataRequired(), EqualTo("password", message="Passwords must match.")]
    )
    submit = SubmitField("Update password")


class UserForm(FlaskForm):
    first_name = StringField("First name", validators=[DataRequired(), Length(max=100)])
    last_name = StringField("Last name", validators=[DataRequired(), Length(max=100)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    role_id = SelectField("Role", coerce=int, validators=[DataRequired()])
    school_id = SelectField("School (School Administrator only)", coerce=int, validators=[Optional()])
    is_active_account = BooleanField("Account active", default=True)
    password = PasswordField("Password", validators=[Optional(), Length(min=10)])
    submit = SubmitField("Save user")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.role_id.choices = [(r.id, r.name) for r in Role.query.order_by(Role.name).all()]
        self.school_id.choices = [(0, "-- None --")] + [
            (s.id, s.name) for s in School.query.order_by(School.name).all()
        ]


class VendorForm(FlaskForm):
    name = StringField("Vendor name", validators=[DataRequired(), Length(max=150)])
    website = StringField("Website", validators=[Optional(), Length(max=255)])
    support_email = StringField("Support email", validators=[Optional(), Email(), Length(max=255)])
    support_phone = StringField("Support phone", validators=[Optional(), Length(max=50)])
    account_manager = StringField("Account manager", validators=[Optional(), Length(max=150)])
    account_number = StringField("Account number", validators=[Optional(), Length(max=100)])
    notes = TextAreaField("Notes", validators=[Optional()])
    submit = SubmitField("Save vendor")


class SchoolForm(FlaskForm):
    name = StringField("School name", validators=[DataRequired(), Length(max=150)])
    code = StringField("School code", validators=[DataRequired(), Length(max=30)])
    school_type = SelectField("School type", choices=[(t, t) for t in School.TYPES], validators=[DataRequired()])
    address = StringField("Address", validators=[Optional(), Length(max=255)])
    principal = StringField("Principal", validators=[Optional(), Length(max=150)])
    grades = GradesField("Grades served", choices=[(g, g) for g in School.GRADES])
    student_count = IntegerField("Student count", validators=[Optional(), NumberRange(min=0)], default=0)
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save school")


class CategoryForm(FlaskForm):
    name = StringField("Category name", validators=[DataRequired(), Length(max=100)])
    submit = SubmitField("Save category")


class LicenseForm(FlaskForm):
    """Vendor is implicit: a license is always created from its contract's
    detail page, and takes that contract's vendor rather than asking
    again. Start/expiration/renewal dates live on the Contract instead of
    here, since a license's dates are just its contract's terms."""
    name = StringField("License name", validators=[DataRequired(), Length(max=150)])
    category_id = SelectField("Category", coerce=int, validators=[Optional()])
    description = TextAreaField("Description", validators=[Optional()])
    license_count = IntegerField("Total license count", validators=[DataRequired(), NumberRange(min=0)])
    po_number = StringField("PO number", validators=[Optional(), Length(max=100)])
    support_url = StringField("Support URL", validators=[Optional(), Length(max=255)])
    login_url = StringField("Login URL", validators=[Optional(), Length(max=255)])
    notes = TextAreaField("Notes", validators=[Optional()])
    status = SelectField("Status", choices=[(s, s) for s in License.STATUSES], validators=[DataRequired()])
    submit = SubmitField("Save license")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from app.models import Category
        self.category_id.choices = [(0, "-- None --")] + [
            (c.id, c.name) for c in Category.query.order_by(Category.name).all()
        ]


class AllocationForm(FlaskForm):
    school_id = SelectField("School", coerce=int, validators=[DataRequired()])
    allocated_count = IntegerField("Allocated licenses", validators=[DataRequired(), NumberRange(min=0)])
    notes = StringField("Notes", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Save allocation")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.school_id.choices = [(s.id, s.name) for s in School.query.filter_by(is_active=True).order_by(School.name).all()]


class ContractForm(FlaskForm):
    """Vendor is implicit: a contract is always created and edited from
    its vendor's detail page, and takes that vendor rather than asking
    again - one or more Licenses get added to it afterward. Annual cost and
    vendor contact are terms of this specific agreement, so they live here
    rather than per-license (a contract's total covers everything bundled
    under it). PO number is the one identifying number for a contract -
    there's no separate contract number."""
    po_number = StringField("PO number", validators=[DataRequired(), Length(max=100)])
    vendor_contact = StringField("Vendor contact", validators=[Optional(), Length(max=150)])
    start_date = DateField("Start date", validators=[DataRequired()])
    end_date = DateField("End date", validators=[DataRequired()])
    renewal_date = DateField("Renewal date", validators=[Optional()])
    annual_cost = DecimalField("Annual cost", validators=[Optional(), NumberRange(min=0)], places=2, default=0)
    payment_frequency = SelectField("Payment frequency", choices=[(p, p) for p in Contract.PAYMENT_FREQUENCIES], validators=[DataRequired()])
    auto_renewal = BooleanField("Auto renewal")
    cancellation_deadline = DateField("Cancellation deadline", validators=[Optional()])
    notes = TextAreaField("Notes", validators=[Optional()])
    submit = SubmitField("Save contract")

    def validate_end_date(self, field):
        if self.start_date.data and field.data and field.data <= self.start_date.data:
            raise ValidationError("End date must be after the start date.")


class CsvImportForm(FlaskForm):
    file = FileField("CSV file", validators=[FileRequired(), FileAllowed(["csv"], "CSV files only.")])
    submit = SubmitField("Preview import")


class SettingsForm(FlaskForm):
    critical_days = IntegerField("Critical threshold (days remaining)", validators=[DataRequired(), NumberRange(min=1)])
    warning_days = IntegerField("Warning threshold (days remaining)", validators=[DataRequired(), NumberRange(min=1)])
    upcoming_days = IntegerField("Upcoming threshold (days remaining)", validators=[DataRequired(), NumberRange(min=1)])
    high_utilization_pct = IntegerField("High utilization threshold (%)", validators=[DataRequired(), NumberRange(min=1, max=100)])
    over_allocated_pct = IntegerField("Over-allocated threshold (%)", validators=[DataRequired(), NumberRange(min=1, max=200)])
    submit = SubmitField("Save settings")

    def validate_warning_days(self, field):
        if self.critical_days.data and field.data and field.data <= self.critical_days.data:
            raise ValidationError("Warning threshold must be greater than the critical threshold.")

    def validate_upcoming_days(self, field):
        if self.warning_days.data and field.data and field.data <= self.warning_days.data:
            raise ValidationError("Upcoming threshold must be greater than the warning threshold.")
