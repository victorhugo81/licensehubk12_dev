import pytest

from app.models import Role
from tests.conftest import login, make_user


@pytest.mark.parametrize("path", [
    "/vendors/add",
    "/schools/add",
    "/administration/users/",
    "/administration/settings/",
    "/audit-log/",
])
def test_viewer_cannot_access_write_or_admin_routes(client, viewer_user, path):
    login(client, "viewer@example.com")
    resp = client.get(path)
    assert resp.status_code == 403


def test_viewer_cannot_add_contract(client, viewer_user, vendor):
    login(client, "viewer@example.com")
    resp = client.get(f"/vendors/{vendor.id}/contracts/add")
    assert resp.status_code == 403


def test_viewer_cannot_add_license(client, viewer_user, contract):
    login(client, "viewer@example.com")
    resp = client.get(f"/contracts/{contract.id}/licenses/add")
    assert resp.status_code == 403


def test_viewer_can_access_read_routes(client, viewer_user, license_):
    login(client, "viewer@example.com")
    assert client.get("/").status_code == 200
    assert client.get("/licenses").status_code == 200
    assert client.get(f"/licenses/{license_.id}").status_code == 200
    assert client.get("/reports/").status_code == 200


def test_it_administrator_can_manage_vendors_but_not_users(client, db):
    make_user(db, "it@example.com", Role.IT_ADMINISTRATOR)
    login(client, "it@example.com")
    assert client.get("/vendors/add").status_code == 200
    assert client.get("/administration/users/").status_code == 403
    assert client.get("/administration/settings/").status_code == 403


def test_curriculum_administrator_can_manage_licenses_not_vendors(client, db, contract):
    make_user(db, "curriculum@example.com", Role.CURRICULUM_ADMINISTRATOR)
    login(client, "curriculum@example.com")
    assert client.get(f"/contracts/{contract.id}/licenses/add").status_code == 200
    assert client.get("/vendors/add").status_code == 403
    assert client.get("/schools/add").status_code == 403


def test_school_administrator_cannot_view_other_schools_licenses(client, db, license_, school_admin_user):
    login(client, "schooladmin@example.com")
    # `license_` fixture has no allocation to school_admin_user's school
    resp = client.get(f"/licenses/{license_.id}")
    assert resp.status_code == 403


def test_school_administrator_can_view_own_schools_allocated_licenses(client, db, license_, school_admin_user):
    from app.services import allocation as allocation_service
    allocation_service.set_allocation(license_, school_admin_user.school, 10)
    db.session.commit()

    login(client, "schooladmin@example.com")
    resp = client.get(f"/licenses/{license_.id}")
    assert resp.status_code == 200


def test_unauthenticated_requests_redirect_to_login(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_route_decorator_blocks_regardless_of_ui(client, viewer_user):
    """Guard rails must live at the route level - hitting a write endpoint
    directly (bypassing any UI) must still be rejected."""
    login(client, "viewer@example.com")
    resp = client.post("/schools/add", data={"name": "Sneaky School", "code": "SN-1", "school_type": "Elementary"})
    assert resp.status_code == 403
