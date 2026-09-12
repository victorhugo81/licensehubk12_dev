import io

from app.integrations.user_csv_import import MAX_ROWS, commit_import, validate_csv
from app.models import FtpImportSettings, Role, User
from tests.conftest import login


def test_missing_columns_rejected():
    csv_text = "first_name\nJane\n"
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.column_errors
    assert preview.total == 0


def test_role_column_not_required_in_file(db):
    # role is not a required file column at all - the standard district
    # roster export has no role column, and a missing role just defaults a
    # new user to Viewer.
    csv_text = "first_name,last_name,email\nJane,Doe,jane@example.com\n"
    preview = validate_csv(io.StringIO(csv_text))
    assert not preview.column_errors


def test_new_user_missing_role_defaults_to_viewer(db):
    csv_text = "first_name,last_name,email,site_name\nJane,Doe,jane@example.com,\n"
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.errors == 0
    created, updated, results = commit_import(preview)
    assert created == 1
    user = User.query.filter_by(email="jane@example.com").first()
    assert user.role.name == Role.VIEWER


def test_other_columns_in_file_are_ignored(db):
    csv_text = "first_name,last_name,email,rm_num,department\nJane,Doe,jane@example.com,204,Math\n"
    preview = validate_csv(io.StringIO(csv_text))
    assert not preview.column_errors
    assert preview.errors == 0


def test_valid_row_passes(db):
    csv_text = "first_name,last_name,email,role,site_name\nJane,Doe,jane@example.com,Viewer,\n"
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.total == 1
    assert preview.valid == 1
    assert preview.errors == 0


def test_invalid_email_is_an_error(db):
    csv_text = "first_name,last_name,email,role,site_name\nJane,Doe,not-an-email,Viewer,\n"
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.errors == 1


def test_unknown_role_is_an_error(db):
    csv_text = "first_name,last_name,email,role,site_name\nJane,Doe,jane@example.com,Superuser,\n"
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.errors == 1


def test_school_administrator_without_site_name_is_an_error(db):
    csv_text = "first_name,last_name,email,role,site_name\nJane,Doe,jane@example.com,School Administrator,\n"
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.errors == 1


def test_school_administrator_with_unknown_site_name_is_an_error(db):
    csv_text = (
        "first_name,last_name,email,role,site_name\n"
        "Jane,Doe,jane@example.com,School Administrator,Nonexistent School\n"
    )
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.errors == 1


def test_school_administrator_with_valid_site_name_passes(db, school):
    csv_text = (
        "first_name,last_name,email,role,site_name\n"
        f"Jane,Doe,jane@example.com,School Administrator,{school.name}\n"
    )
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.valid == 1


def test_viewer_with_site_name_is_recorded(db, school):
    # site_name is informational for every role, not just School Administrator.
    csv_text = (
        "first_name,last_name,email,role,site_name\n"
        f"Jane,Doe,jane@example.com,Viewer,{school.name}\n"
    )
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.valid == 1
    created, updated, results = commit_import(preview)
    assert created == 1
    user = User.query.filter_by(email="jane@example.com").first()
    assert user.role.name == Role.VIEWER
    assert user.school_id == school.id


def test_duplicate_email_in_file_is_an_error(db):
    csv_text = (
        "first_name,last_name,email,role,site_name\n"
        "Jane,Doe,jane@example.com,Viewer,\n"
        "Jane,Doe2,jane@example.com,Viewer,\n"
    )
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.errors == 1  # the second occurrence


def test_existing_email_is_a_warning(db, viewer_user):
    csv_text = f"first_name,last_name,email,role,site_name\nDup,User,{viewer_user.email},Viewer,\n"
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.warnings == 1
    assert preview.errors == 0


def test_commit_creates_user_with_unusable_reset_token_flow(db):
    csv_text = "first_name,last_name,email,role,site_name\nJane,Doe,jane@example.com,Viewer,\n"
    preview = validate_csv(io.StringIO(csv_text))
    created, updated, results = commit_import(preview)

    assert created == 1
    assert updated == 0
    user = User.query.filter_by(email="jane@example.com").first()
    assert user is not None
    assert user.role.name == Role.VIEWER
    assert user.reset_token is not None
    assert user.reset_token_expires is not None
    assert results[0]["email"] == "jane@example.com"
    assert results[0]["reset_token"] == user.reset_token


def test_commit_updates_existing_user_without_touching_role(db, viewer_user, school):
    original_role_id = viewer_user.role_id
    csv_text = (
        f"first_name,last_name,email,role,site_name,status\n"
        f"Updated,Name,{viewer_user.email},Administrator,{school.name},Inactive\n"
    )
    preview = validate_csv(io.StringIO(csv_text))
    created, updated, results = commit_import(preview)
    assert created == 0
    assert updated == 1

    refreshed = User.query.filter_by(email=viewer_user.email).first()
    assert refreshed.first_name == "Updated"
    assert refreshed.last_name == "Name"
    assert refreshed.is_active_account is False
    assert refreshed.role_id == original_role_id  # role column is ignored
    assert refreshed.school_id == school.id  # site_name still updates for any role


def test_commit_never_imports_error_rows(db):
    csv_text = (
        "first_name,last_name,email,role,site_name\n"
        "Good,User,good@example.com,Viewer,\n"
        "Bad,User,not-an-email,Viewer,\n"
    )
    preview = validate_csv(io.StringIO(csv_text))
    created, updated, results = commit_import(preview)
    assert created == 1
    assert User.query.filter_by(email="not-an-email").first() is None


def test_ftp_settings_password_round_trips_encrypted(app, db):
    with app.app_context():
        settings = FtpImportSettings.get_or_create()
        settings.password = "super-secret"
        db.session.commit()

        assert settings.password_encrypted != "super-secret"
        assert settings.password_encrypted  # something was actually stored
        assert settings.password == "super-secret"


def test_ftp_settings_not_configured_until_all_fields_set(app, db):
    with app.app_context():
        settings = FtpImportSettings.get_or_create()
        assert settings.is_configured() is False

        settings.is_enabled = True
        settings.host = "ftp.example.org"
        settings.username = "svc-user"
        settings.password = "secret"
        settings.remote_path = "/exports/users.csv"
        db.session.commit()
        assert settings.is_configured() is True


def test_import_upload_requires_manage_users_permission(client, viewer_user):
    login(client, viewer_user.email)
    resp = client.get("/administration/users/import/")
    assert resp.status_code == 403


def test_import_upload_page_loads_for_admin(client, admin_user):
    login(client, admin_user.email)
    resp = client.get("/administration/users/import/")
    assert resp.status_code == 200


def test_ftp_settings_page_requires_manage_users_permission(client, viewer_user):
    login(client, viewer_user.email)
    resp = client.get("/administration/users/import/ftp")
    assert resp.status_code == 403


def test_row_count_over_the_limit_is_rejected(db):
    header = "first_name,last_name,email,role,site_name\n"
    row = "Jane,Doe,jane@example.com,Viewer,\n"
    csv_text = header + row * (MAX_ROWS + 1)
    preview = validate_csv(io.StringIO(csv_text))
    assert preview.column_errors
    assert preview.total == 0
