import pytest

from app import create_app
from app.extensions import db as _db
from app.models import Role


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


def test_api_bearer_token_not_accepted_as_query_param(csrf_app):
    client = csrf_app.test_client()
    from app.models import User
    with csrf_app.app_context():
        user = User.query.filter_by(email="admin@example.com").first()
        user.generate_api_key()
        _db.session.commit()
        token = user.api_key
    # Passing the token as a query string must not authenticate - only the
    # Authorization header is honored.
    resp = client.get(f"/api/software?api_key={token}")
    assert resp.status_code == 401
