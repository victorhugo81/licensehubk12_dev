import io

from app.integrations.school_csv_import import MAX_ROWS, commit_import, validate_csv
from app.models import School
from tests.conftest import login


def test_missing_columns_rejected():
    csv_text = "site_name,site_code\nFoo,F-1\n"
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.column_errors
    assert preview.total == 0


def test_valid_row_passes(db):
    csv_text = "site_name,site_code,site_type\nNorth High,NH-1,High School\n"
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.total == 1
    assert preview.valid == 1
    assert preview.errors == 0


def test_invalid_school_type_is_an_error(db):
    csv_text = "site_name,site_code,site_type\nNorth High,NH-1,Not A Real Type\n"
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.errors == 1


def test_site_type_shorthand_is_normalized(db):
    csv_text = (
        "site_name,site_code,site_type\n"
        "North High,NH-1,hs\n"
        "North Middle,NM-1,MS\n"
        "North Elementary,NE-1,Es\n"
    )
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.errors == 0
    assert preview.valid == 3
    types_by_code = {r.data["site_code"]: r.data["site_type"] for r in preview.rows}
    assert types_by_code == {"NH-1": "High School", "NM-1": "Middle School", "NE-1": "Elementary"}

    created, updated = commit_import(preview)
    assert created == 3
    assert School.query.filter_by(code="NH-1").first().school_type == "High School"
    assert School.query.filter_by(code="NM-1").first().school_type == "Middle School"
    assert School.query.filter_by(code="NE-1").first().school_type == "Elementary"


def test_duplicate_code_in_file_is_an_error(db):
    csv_text = (
        "site_name,site_code,site_type\n"
        "North High,NH-1,High School\n"
        "North High Annex,NH-1,High School\n"
    )
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.errors == 1  # the second occurrence


def test_existing_code_is_a_warning_not_error(db, school):
    csv_text = f"site_name,site_code,site_type\nUpdated Name,{school.code},Middle School\n"
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.warnings == 1
    assert preview.errors == 0


def test_invalid_student_count_is_an_error(db):
    csv_text = "site_name,site_code,site_type,student_count\nNorth High,NH-1,High School,not-a-number\n"
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.errors == 1


def test_unknown_grade_is_a_warning(db):
    csv_text = "site_name,site_code,site_type,grades\nNorth High,NH-1,High School,\"9,10,99\"\n"
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.warnings == 1
    assert preview.errors == 0


def test_commit_creates_new_school(db):
    csv_text = (
        "site_name,site_code,site_type,site_address,prnfirstn,prnlastn,grades,student_count\n"
        "North High,NH-1,High School,1 Main St,Jane,Doe,\"9,10,11,12\",500\n"
    )
    preview = validate_csv(io.StringIO(csv_text))
    created, updated = commit_import(preview)

    assert created == 1
    assert updated == 0
    school = School.query.filter_by(code="NH-1").first()
    assert school is not None
    assert school.name == "North High"
    assert school.principal == "Jane Doe"
    assert school.student_count == 500
    assert school.grades == "9,10,11,12"


def test_commit_updates_existing_school_by_code(db, school):
    csv_text = f"site_name,site_code,site_type,student_count\nRenamed School,{school.code},High School,999\n"
    preview = validate_csv(io.StringIO(csv_text))
    created, updated = commit_import(preview)

    assert created == 0
    assert updated == 1
    refreshed = School.query.filter_by(code=school.code).first()
    assert refreshed.name == "Renamed School"
    assert refreshed.school_type == "High School"
    assert refreshed.student_count == 999


def test_commit_never_imports_error_rows(db):
    csv_text = (
        "site_name,site_code,site_type\n"
        "Good School,GS-1,High School\n"
        "Bad School,,High School\n"
    )
    preview = validate_csv(io.StringIO(csv_text))
    created, updated = commit_import(preview)
    assert created == 1
    assert School.query.filter_by(name="Bad School").first() is None


def test_row_count_over_the_limit_is_rejected(db):
    header = "site_name,site_code,site_type\n"
    row = "School,CODE,High School\n"
    csv_text = header + row * (MAX_ROWS + 1)
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.column_errors
    assert preview.total == 0


def test_import_upload_requires_manage_schools_permission(client, viewer_user):
    login(client, viewer_user.email)
    resp = client.get("/administration/schools/import/")
    assert resp.status_code == 403


def test_import_upload_page_loads_for_admin(client, admin_user):
    login(client, admin_user.email)
    resp = client.get("/administration/schools/import/")
    assert resp.status_code == 200
    assert b"Import Schools" in resp.data


def test_full_upload_commit_flow(client, admin_user, app):
    login(client, admin_user.email)
    csv_content = b"site_name,site_code,site_type\nSmoke Test School,STS-1,High School\n"
    data = {"file": (io.BytesIO(csv_content), "smoke_schools.csv")}
    resp = client.post("/administration/schools/import/", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert b"Import 1 record" in resp.data

    resp2 = client.post("/administration/schools/import/commit", follow_redirects=True)
    assert resp2.status_code == 200

    with app.app_context():
        assert School.query.filter_by(code="STS-1").first() is not None
