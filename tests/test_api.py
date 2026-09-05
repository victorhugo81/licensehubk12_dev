from tests.conftest import login


def test_api_requires_authentication(client):
    resp = client.get("/api/licenses")
    assert resp.status_code == 401


def test_api_get_works_with_session_login(client, admin_user, license_):
    login(client, "admin@example.com")
    resp = client.get("/api/licenses")
    assert resp.status_code == 200
    names = [item["name"] for item in resp.get_json()]
    assert "TestSoft" in names


def test_api_write_requires_authentication(client, vendor):
    resp = client.post("/api/licenses", json={"name": "Blocked", "vendor_id": vendor.id})
    assert resp.status_code == 401


def test_api_write_succeeds_with_session_login(client, admin_user, contract):
    login(client, "admin@example.com")
    resp = client.post(
        "/api/licenses",
        json={"name": "ApiCreated", "contract_id": contract.id, "license_count": 20},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["name"] == "ApiCreated"
    assert body["license_count"] == 20


def test_api_permission_denied_for_viewer_write(client, viewer_user, vendor):
    login(client, "viewer@example.com")
    resp = client.post("/api/licenses", json={"name": "ShouldFail", "vendor_id": vendor.id})
    assert resp.status_code == 403


def test_api_delete_license(client, admin_user, license_, db):
    login(client, "admin@example.com")
    resp = client.delete(f"/api/licenses/{license_.id}")
    assert resp.status_code == 200

    from app.models import License
    assert db.session.get(License, license_.id) is None


def test_api_expiring_endpoint(client, admin_user, license_, db):
    from datetime import date, timedelta
    license_.expiration_date = date.today() + timedelta(days=10)
    db.session.commit()
    login(client, "admin@example.com")
    resp = client.get("/api/expiring?days=30")
    assert resp.status_code == 200
    names = [item["name"] for item in resp.get_json()]
    assert "TestSoft" in names
