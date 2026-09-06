from app.extensions import db as _db
from app.models import Notification
from tests.conftest import login


def test_link_url_for_license_notification(app, license_):
    with app.test_request_context():
        note = Notification(type="license_expiration", title="t", message="m",
                             related_object_type="license", related_object_id=license_.id)
        assert note.link_url == f"/licenses/{license_.id}"


def test_link_url_for_contract_notification(app, contract):
    with app.test_request_context():
        note = Notification(type="contract_expiration", title="t", message="m",
                             related_object_type="contract", related_object_id=contract.id)
        assert note.link_url == f"/contracts/{contract.id}"


def test_link_url_none_without_related_object(app):
    with app.test_request_context():
        note = Notification(type="unused_licenses", title="t", message="m")
        assert note.link_url is None


def test_clicking_unread_notification_marks_read_and_redirects_to_target(client, admin_user, license_, db):
    login(client, admin_user.email)
    note = Notification(type="license_expiration", title="t", message="m",
                         related_object_type="license", related_object_id=license_.id)
    db.session.add(note)
    db.session.commit()

    resp = client.post(f"/notifications/{note.id}/read")
    assert resp.status_code == 302
    assert resp.headers["Location"] == f"/licenses/{license_.id}"

    _db.session.refresh(note)
    assert note.is_read is True


def test_notification_list_renders_clickable_row(client, admin_user, license_, db):
    login(client, admin_user.email)
    note = Notification(type="license_added", title="New license added: Foo",
                         message="Foo was added.", related_object_type="license",
                         related_object_id=license_.id)
    db.session.add(note)
    db.session.commit()

    resp = client.get("/notifications/")
    body = resp.get_data(as_text=True)
    assert f'/notifications/{note.id}/read' in body
