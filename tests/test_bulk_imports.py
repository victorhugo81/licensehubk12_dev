import io

from app.models import School, User
from tests.conftest import login


def test_index_requires_manage_users_or_manage_schools(client, viewer_user):
    login(client, viewer_user.email)
    resp = client.get("/administration/import/")
    assert resp.status_code == 403


def test_index_loads_for_admin(client, admin_user):
    login(client, admin_user.email)
    resp = client.get("/administration/import/")
    assert resp.status_code == 200
    assert b"users.csv" in resp.data
    assert b"sites.csv" in resp.data
    assert b"Review Upload Log" in resp.data


def test_sniff_kind_by_filename():
    from app.routes.bulk_imports import _sniff_kind
    assert _sniff_kind("sites.csv", "") == "school"
    assert _sniff_kind("schools.csv", "") == "school"
    assert _sniff_kind("users.csv", "") == "user"
    assert _sniff_kind("mystery.csv", "site_name,site_code,site_type") == "school"
    assert _sniff_kind("mystery.csv", "first_name,email,role") == "user"
    assert _sniff_kind("mystery.csv", "foo,bar") is None


def test_upload_both_files_shows_combined_preview(client, admin_user):
    login(client, admin_user.email)
    sites_csv = b"site_name,site_code,site_type\nNorth High,NH-1,High School\n"
    users_csv = b"first_name,last_name,email,role,site_name\nJane,Doe,jane@example.com,Viewer,\n"
    data = {
        "files": [
            (io.BytesIO(sites_csv), "sites.csv"),
            (io.BytesIO(users_csv), "users.csv"),
        ],
    }
    resp = client.post("/administration/import/", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert b"Sites" in resp.data
    assert b"North High" in resp.data
    assert b"Users" in resp.data
    assert b"jane@example.com" in resp.data


def test_commit_processes_schools_before_users_in_same_batch(client, admin_user, db):
    login(client, admin_user.email)
    sites_csv = b"site_name,site_code,site_type\nNorth High,NH-1,High School\n"
    users_csv = b"first_name,last_name,email,role,site_name\nJane,Doe,jane@example.com,School Administrator,North High\n"
    data = {
        "files": [
            (io.BytesIO(sites_csv), "sites.csv"),
            (io.BytesIO(users_csv), "users.csv"),
        ],
    }
    client.post("/administration/import/", data=data, content_type="multipart/form-data")
    resp = client.post("/administration/import/commit", follow_redirects=True)
    assert resp.status_code == 200

    school = School.query.filter_by(code="NH-1").first()
    assert school is not None
    user = User.query.filter_by(email="jane@example.com").first()
    assert user is not None
    # the user row referenced the school from the *same* upload - only
    # resolvable if schools committed first.
    assert user.school_id == school.id


def test_unrecognized_filename_is_rejected(client, admin_user):
    login(client, admin_user.email)
    data = {"files": [(io.BytesIO(b"a,b\n1,2\n"), "mystery.csv")]}
    resp = client.post("/administration/import/", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Couldn" in resp.data


def test_school_only_admin_cannot_import_users_file(client, db):
    from app.models import Role
    from tests.conftest import make_user
    it_admin = make_user(db, "itadmin@example.com", Role.IT_ADMINISTRATOR)
    login(client, it_admin.email)

    # IT Administrator has manage_schools but not manage_users.
    users_csv = b"first_name,last_name,email,role,site_name\nJane,Doe,jane@example.com,Viewer,\n"
    data = {"files": [(io.BytesIO(users_csv), "users.csv")]}
    resp = client.post("/administration/import/", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert resp.status_code == 200
    assert b"don" in resp.data.lower() and b"permission" in resp.data.lower()
