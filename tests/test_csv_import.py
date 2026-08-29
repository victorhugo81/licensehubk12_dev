import io

from app.integrations.csv_import import commit_import, validate_csv
from app.models import LicenseAllocation, School, Software


def _school(db, name, code):
    s = School(name=name, code=code, school_type="Elementary")
    db.session.add(s)
    db.session.commit()
    return s


def test_missing_columns_rejected():
    csv_text = "software,vendor\nFoo,Bar\n"
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.column_errors
    assert preview.total == 0


def test_valid_row_passes(db):
    _school(db, "Test School", "TS-1")
    csv_text = (
        "software,vendor,school,total_licenses,assigned_licenses,expiration_date,annual_cost\n"
        "IXL,IXL Learning,Test School,1000,500,2027-06-30,25000\n"
    )
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.total == 1
    assert preview.valid == 1
    assert preview.errors == 0


def test_unknown_school_is_an_error(db):
    csv_text = (
        "software,vendor,school,total_licenses,assigned_licenses,expiration_date,annual_cost\n"
        "IXL,IXL Learning,Nonexistent School,1000,500,2027-06-30,25000\n"
    )
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.errors == 1


def test_assigned_exceeds_total_is_an_error(db):
    _school(db, "Test School", "TS-1")
    csv_text = (
        "software,vendor,school,total_licenses,assigned_licenses,expiration_date,annual_cost\n"
        "IXL,IXL Learning,Test School,100,500,2027-06-30,25000\n"
    )
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.errors == 1


def test_cross_row_allocation_exceeding_total_is_an_error(db):
    _school(db, "School A", "SA-1")
    _school(db, "School B", "SB-1")
    csv_text = (
        "software,vendor,school,total_licenses,assigned_licenses,expiration_date,annual_cost\n"
        "IXL,IXL Learning,School A,100,60,2027-06-30,25000\n"
        "IXL,IXL Learning,School B,100,60,2027-06-30,25000\n"
    )
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.errors == 2  # both rows for the over-subscribed software flagged


def test_invalid_records_are_never_imported(db):
    _school(db, "School A", "SA-1")
    csv_text = (
        "software,vendor,school,total_licenses,assigned_licenses,expiration_date,annual_cost\n"
        "GoodApp,Vendor A,School A,100,50,2027-06-30,5000\n"
        "BadApp,Vendor A,Nonexistent School,100,50,2027-06-30,5000\n"
    )
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.valid == 1
    assert preview.errors == 1

    created, updated, errors = commit_import(preview)
    assert Software.query.filter_by(name="GoodApp").first() is not None
    assert Software.query.filter_by(name="BadApp").first() is None


def test_commit_creates_allocation(db):
    school = _school(db, "School A", "SA-1")
    csv_text = (
        "software,vendor,school,total_licenses,assigned_licenses,expiration_date,annual_cost\n"
        "GoodApp,Vendor A,School A,100,50,2027-06-30,5000\n"
    )
    preview = validate_csv(io.StringIO(csv_text))
    commit_import(preview)

    sw = Software.query.filter_by(name="GoodApp").first()
    allocation = LicenseAllocation.query.filter_by(software_id=sw.id, school_id=school.id).first()
    assert allocation.allocated_count == 50


def test_expired_date_in_past_is_a_warning_not_error(db):
    _school(db, "School A", "SA-1")
    csv_text = (
        "software,vendor,school,total_licenses,assigned_licenses,expiration_date,annual_cost\n"
        "OldApp,Vendor A,School A,100,50,2020-01-01,5000\n"
    )
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.warnings == 1
    assert preview.errors == 0
