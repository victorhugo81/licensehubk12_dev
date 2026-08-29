from tests.conftest import login


def test_login_success(client, admin_user):
    resp = login(client, "admin@example.com")
    assert resp.status_code == 200
    resp = client.get("/")
    assert resp.status_code == 200


def test_login_wrong_password(client, admin_user):
    resp = login(client, "admin@example.com", password="wrong-password")
    assert b"Invalid email or password" in resp.data


def test_login_unknown_user(client):
    resp = login(client, "nobody@example.com")
    assert b"Invalid email or password" in resp.data


def test_account_lockout_after_failed_attempts(client, admin_user, db):
    for _ in range(5):
        login(client, "admin@example.com", password="wrong-password")
    db.session.refresh(admin_user)
    assert admin_user.is_locked()

    resp = login(client, "admin@example.com")  # correct password, but locked
    assert b"temporarily locked" in resp.data


def test_inactive_account_cannot_login(client, admin_user, db):
    admin_user.is_active_account = False
    db.session.commit()
    resp = login(client, "admin@example.com")
    assert b"Invalid email or password" in resp.data


def test_logout_requires_login(client):
    resp = client.get("/auth/logout", follow_redirects=True)
    assert b"Sign in" in resp.data or b"sign in" in resp.data.lower()


def test_change_password_requires_current_password(client, admin_user):
    login(client, "admin@example.com")
    resp = client.post("/auth/change-password", data={
        "current_password": "wrong", "password": "NewPassword123!", "confirm_password": "NewPassword123!",
    }, follow_redirects=True)
    assert b"Current password is incorrect" in resp.data
