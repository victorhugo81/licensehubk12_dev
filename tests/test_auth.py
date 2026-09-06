from tests.conftest import login


def test_login_rejects_protocol_relative_next_redirect(client, admin_user):
    # "//evil.com" starts with "/" but browsers resolve it as a
    # scheme-relative URL to a different host - a classic open redirect if
    # the app only checks startswith("/").
    resp = client.post(
        "/auth/login?next=//evil.com/phish",
        data={"email": "admin@example.com", "password": "Password123!"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"


def test_login_allows_safe_relative_next_redirect(client, admin_user):
    resp = client.post(
        "/auth/login?next=/schools/",
        data={"email": "admin@example.com", "password": "Password123!"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/schools/"


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

    # Correct password, but locked - still rejected, and with the exact
    # same generic message as any other failed login (a distinct "this
    # account is locked" message would let anyone confirm the email is
    # registered just by tripping its lockout - see auth.login()).
    resp = login(client, "admin@example.com")
    assert b"Invalid email or password" in resp.data
    assert b"temporarily locked" not in resp.data


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


def test_password_change_invalidates_old_session_id(app, db, admin_user):
    # Simulates a stolen session: get_id() at the moment of an earlier login
    # embeds the password's security_stamp. Changing the password rotates
    # that stamp (User.set_password), so the login_manager's user_loader
    # must reject the old id string outright while still accepting the
    # fresh one - otherwise "reset your password if you think someone has
    # access" doesn't actually revoke anything, since Flask-Login sessions
    # here are stateless signed cookies with no other server-side check.
    old_session_id = admin_user.get_id()

    admin_user.set_password("BrandNewPassphrase456")
    db.session.commit()

    with app.app_context():
        loader = app.login_manager.user_callback
        assert loader(old_session_id) is None
        assert loader(admin_user.get_id()) is not None


def test_get_id_embeds_security_stamp(admin_user):
    assert admin_user.get_id() == f"{admin_user.id}.{admin_user.security_stamp}"
