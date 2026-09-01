import pytest

from app import create_app
from app.extensions import db as _db
from app.models import Category, License, LicenseAllocation, Role, School, Vendor


@pytest.fixture()
def app():
    app = create_app("testing")
    with app.app_context():
        _db.create_all()
        for name in Role.ALL:
            _db.session.add(Role(name=name))
        _db.session.commit()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture()
def client(app):
    return app.test_client()


def make_user(db, email, role_name, school_id=None, password="Password123!"):
    from app.models import User
    role = Role.query.filter_by(name=role_name).first()
    user = User(email=email, first_name="Test", last_name="User", role_id=role.id, school_id=school_id)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def admin_user(db):
    return make_user(db, "admin@example.com", Role.ADMINISTRATOR)


@pytest.fixture()
def viewer_user(db):
    return make_user(db, "viewer@example.com", Role.VIEWER)


@pytest.fixture()
def school(db):
    s = School(name="Test Elementary", code="TE-01", school_type="Elementary")
    db.session.add(s)
    db.session.commit()
    return s


@pytest.fixture()
def school_admin_user(db, school):
    return make_user(db, "schooladmin@example.com", Role.SCHOOL_ADMINISTRATOR, school_id=school.id)


@pytest.fixture()
def vendor(db):
    v = Vendor(name="Test Vendor")
    db.session.add(v)
    db.session.commit()
    return v


@pytest.fixture()
def license_(db, vendor):
    lic = License(name="TestSoft", vendor=vendor, license_count=100, status="Active")
    db.session.add(lic)
    db.session.commit()
    return lic


def login(client, email, password="Password123!"):
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=True)
