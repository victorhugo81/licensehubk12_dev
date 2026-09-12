from app.models import Role, User
from tests.conftest import login


def test_list_shows_middle_name_column(client, admin_user, db, school):
    from tests.conftest import make_user
    u = make_user(db, "middle@example.com", Role.VIEWER, school_id=school.id)
    u.middle_name = "Elena"
    db.session.commit()

    login(client, admin_user.email)
    resp = client.get("/administration/users/")
    assert resp.status_code == 200
    assert b"Middle Name" in resp.data
    assert b"Elena" in resp.data
    assert school.name.encode() in resp.data


def test_list_filters_by_role(client, admin_user, db, viewer_user):
    login(client, admin_user.email)
    admin_role_id = admin_user.role_id
    viewer_role_id = viewer_user.role_id

    resp = client.get(f"/administration/users/?role_id={viewer_role_id}")
    assert resp.status_code == 200
    assert viewer_user.email.encode() in resp.data
    assert admin_user.email.encode() not in resp.data

    resp = client.get(f"/administration/users/?role_id={admin_role_id}")
    assert admin_user.email.encode() in resp.data
    assert viewer_user.email.encode() not in resp.data


def test_list_filters_by_school(client, admin_user, db, school):
    from tests.conftest import make_user
    with_school = make_user(db, "hasschool@example.com", Role.VIEWER, school_id=school.id)
    without_school = make_user(db, "noschool@example.com", Role.VIEWER)

    login(client, admin_user.email)
    resp = client.get(f"/administration/users/?school_id={school.id}")
    assert resp.status_code == 200
    assert with_school.email.encode() in resp.data
    assert without_school.email.encode() not in resp.data


def test_list_filters_by_status(client, admin_user, db, viewer_user):
    viewer_user.is_active_account = False
    db.session.commit()

    login(client, admin_user.email)
    resp = client.get("/administration/users/?status=inactive")
    assert resp.status_code == 200
    assert viewer_user.email.encode() in resp.data
    assert admin_user.email.encode() not in resp.data

    resp = client.get("/administration/users/?status=active")
    assert admin_user.email.encode() in resp.data
    assert viewer_user.email.encode() not in resp.data


def test_add_user_persists_middle_name(client, admin_user, db):
    login(client, admin_user.email)
    viewer_role = Role.query.filter_by(name=Role.VIEWER).first()

    resp = client.post("/administration/users/add", data={
        "first_name": "Jane",
        "middle_name": "Marie",
        "last_name": "Doe",
        "email": "jane.doe@example.com",
        "role_id": viewer_role.id,
        "school_id": 0,
        "password": "SomeStrongPassword1",
    }, follow_redirects=True)
    assert resp.status_code == 200

    user = User.query.filter_by(email="jane.doe@example.com").first()
    assert user is not None
    assert user.middle_name == "Marie"


def test_edit_user_updates_middle_name(client, admin_user, db, viewer_user):
    login(client, admin_user.email)

    resp = client.post(f"/administration/users/{viewer_user.id}/edit", data={
        "first_name": viewer_user.first_name,
        "middle_name": "Updated",
        "last_name": viewer_user.last_name,
        "email": viewer_user.email,
        "role_id": viewer_user.role_id,
        "school_id": 0,
        "is_active_account": "y",
        "password": "",
    }, follow_redirects=True)
    assert resp.status_code == 200

    refreshed = User.query.get(viewer_user.id)
    assert refreshed.middle_name == "Updated"
