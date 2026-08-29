from tests.conftest import login


def test_api_requires_authentication(client):
    resp = client.get("/api/software")
    assert resp.status_code == 401


def test_api_get_works_with_session_login(client, admin_user, software):
    login(client, "admin@example.com")
    resp = client.get("/api/software")
    assert resp.status_code == 200
    names = [item["name"] for item in resp.get_json()]
    assert "TestSoft" in names


def test_api_write_rejected_without_bearer_token(client, admin_user, vendor):
    login(client, "admin@example.com")
    resp = client.post("/api/software", json={"name": "Blocked", "vendor_id": vendor.id})
    assert resp.status_code == 401


def test_api_write_succeeds_with_bearer_token(client, admin_user, vendor, db):
    admin_user.generate_api_key()
    db.session.commit()

    resp = client.post(
        "/api/software",
        headers={"Authorization": f"Bearer {admin_user.api_key}"},
        json={"name": "ApiCreated", "vendor_id": vendor.id, "license_count": 20},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["name"] == "ApiCreated"
    assert body["license_count"] == 20


def test_api_rejects_invalid_bearer_token(client):
    resp = client.get("/api/software", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_api_permission_denied_for_viewer_write(client, viewer_user, vendor, db):
    viewer_user.generate_api_key()
    db.session.commit()
    resp = client.post(
        "/api/software",
        headers={"Authorization": f"Bearer {viewer_user.api_key}"},
        json={"name": "ShouldFail", "vendor_id": vendor.id},
    )
    assert resp.status_code == 403


def test_api_delete_software(client, admin_user, software, db):
    admin_user.generate_api_key()
    db.session.commit()
    resp = client.delete(f"/api/software/{software.id}", headers={"Authorization": f"Bearer {admin_user.api_key}"})
    assert resp.status_code == 200

    from app.models import Software
    assert Software.query.get(software.id) is None


def test_api_expiring_endpoint(client, admin_user, software, db):
    from datetime import date, timedelta
    software.expiration_date = date.today() + timedelta(days=10)
    db.session.commit()
    login(client, "admin@example.com")
    resp = client.get("/api/expiring?days=30")
    assert resp.status_code == 200
    names = [item["name"] for item in resp.get_json()]
    assert "TestSoft" in names
