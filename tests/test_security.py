import pytest

from app import create_app
from app.extensions import db as _db
from app.models import Role
from tests.conftest import login


@pytest.fixture()
def csrf_app():
    app = create_app("testing")
    app.config["WTF_CSRF_ENABLED"] = True
    with app.app_context():
        _db.create_all()
        for name in Role.ALL:
            _db.session.add(Role(name=name))
        _db.session.commit()

        from tests.conftest import make_user
        make_user(_db, "admin@example.com", Role.ADMINISTRATOR)
        _db.session.commit()
        yield app
        _db.session.remove()
        _db.drop_all()


def test_post_without_csrf_token_is_rejected(csrf_app):
    client = csrf_app.test_client()
    # Login form itself is exempt from needing a pre-existing token issue,
    # but any other state-changing POST without a valid token must fail.
    resp = client.post("/schools/add", data={"name": "X", "code": "X-1", "school_type": "Elementary"})
    assert resp.status_code in (400, 302, 403)  # never a silent 200 success
    from app.models import School
    assert School.query.filter_by(code="X-1").first() is None


def test_password_never_stored_in_plaintext(csrf_app):
    from app.models import User
    with csrf_app.app_context():
        user = User.query.filter_by(email="admin@example.com").first()
        assert user.password_hash != "Password123!"
        assert user.check_password("Password123!")
        assert "pbkdf2" in user.password_hash or "scrypt" in user.password_hash


def test_session_cookie_secure_flags_in_production_config():
    app = create_app("production")
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["DEBUG"] is False


def test_api_write_without_csrf_token_is_rejected(csrf_app):
    # The JSON API blueprint is no longer CSRF-exempt (it has no separate
    # bearer-token mechanism anymore) - a logged-in session alone must not
    # be enough to drive a state-changing API request.
    import re
    client = csrf_app.test_client()
    login_page = client.get("/auth/login")
    token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', login_page.get_data(as_text=True)).group(1)
    resp = client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "Password123!", "csrf_token": token},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    resp = client.post("/api/licenses", json={"name": "Blocked"})
    assert resp.status_code in (400, 403)
    from app.models import License
    assert License.query.filter_by(name="Blocked").first() is None


def test_security_headers_present_on_every_response(client):
    resp = client.get("/auth/login")
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in resp.headers
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]


def test_csp_script_nonce_is_unique_per_request(client, admin_user):
    login(client, "admin@example.com")
    resp1 = client.get("/")
    resp2 = client.get("/")
    nonce1 = resp1.headers["Content-Security-Policy"].split("nonce-")[1].split("'")[0]
    nonce2 = resp2.headers["Content-Security-Policy"].split("nonce-")[1].split("'")[0]
    assert nonce1 != nonce2
    assert f'nonce="{nonce1}"' in resp1.get_data(as_text=True)


def test_get_config_refuses_to_default_to_development(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    from config import get_config
    with pytest.raises(RuntimeError):
        get_config(None)


def test_get_config_rejects_unknown_environment():
    from config import get_config
    with pytest.raises(RuntimeError):
        get_config("staging")


def test_seed_refuses_to_run_against_production():
    prod_app = create_app("production")
    with prod_app.app_context():
        from app.seed import run_seed
        with pytest.raises(RuntimeError):
            run_seed()


def test_common_password_rejected_on_reset(csrf_app):
    import re
    from app.models import User
    with csrf_app.app_context():
        user = User.query.filter_by(email="admin@example.com").first()
        user.reset_token = "test-reset-token"
        from app.models import utcnow
        from datetime import timedelta
        user.reset_token_expires = utcnow() + timedelta(hours=1)
        _db.session.commit()

    client = csrf_app.test_client()
    page = client.get("/auth/reset-password/test-reset-token")
    token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.get_data(as_text=True)).group(1)
    resp = client.post(
        "/auth/reset-password/test-reset-token",
        data={"password": "password123", "confirm_password": "password123", "csrf_token": token},
    )
    assert b"too common" in resp.data.lower()
