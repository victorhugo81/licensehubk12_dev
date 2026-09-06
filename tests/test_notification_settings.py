from app.extensions import db as _db
from app.models import Notification, Setting
from app.services import notifications
from tests.conftest import login


def test_notification_created_by_default(db):
    note = notifications.notify(
        "contract_expiration", "Contract X expiring", "details",
        severity="warning", related_object_type="contract", related_object_id=1,
    )
    assert note is not None
    _db.session.commit()
    assert Notification.query.filter_by(type="contract_expiration").count() == 1


def test_notification_suppressed_when_category_disabled(db):
    Setting.set_value("notify_contract_expiring", "0")
    _db.session.commit()

    note = notifications.notify(
        "contract_expiration", "Contract X expiring", "details",
        severity="warning", related_object_type="contract", related_object_id=1,
    )
    assert note is None
    _db.session.commit()
    assert Notification.query.filter_by(type="contract_expiration").count() == 0


def test_license_expired_shares_toggle_with_license_expiration(db):
    Setting.set_value("notify_license_expiring", "0")
    _db.session.commit()

    assert notifications.notify("license_expiration", "t", "m", related_object_id=1) is None
    assert notifications.notify("license_expired", "t", "m", related_object_id=1) is None


def test_license_added_notification_fires_on_web_create(client, admin_user, contract):
    login(client, admin_user.email)
    resp = client.post(f"/contracts/{contract.id}/licenses/add", data={
        "name": "Brand New App", "category_id": 0, "license_count": 100, "status": "Active",
    }, follow_redirects=True)
    assert resp.status_code == 200

    note = Notification.query.filter_by(type="license_added").first()
    assert note is not None
    assert "Brand New App" in note.message


def test_license_added_notification_suppressed_when_disabled(client, admin_user, contract, db):
    Setting.set_value("notify_license_added", "0")
    db.session.commit()

    login(client, admin_user.email)
    client.post(f"/contracts/{contract.id}/licenses/add", data={
        "name": "Another App", "category_id": 0, "license_count": 50, "status": "Active",
    }, follow_redirects=True)

    assert Notification.query.filter_by(type="license_added").count() == 0


def test_notification_settings_page_requires_manage_settings_permission(client, viewer_user):
    login(client, viewer_user.email)
    resp = client.get("/administration/settings/")
    assert resp.status_code == 403


def test_notification_settings_save_persists_toggles(client, admin_user, db):
    login(client, admin_user.email)
    resp = client.get("/administration/settings/")
    assert b"Notification Settings" in resp.data
    assert b"License Expiring or Expired" in resp.data
    assert b"New License Added" in resp.data

    data = {
        # Only these two categories checked - notify_license_expiring and
        # notify_license_added - everything else omitted (unchecked
        # checkboxes never submit a value).
        "notify_license_expiring": "y",
        "notify_license_added": "y",
    }
    resp = client.post("/administration/settings/notifications", data=data, follow_redirects=True)
    assert resp.status_code == 200

    assert Setting.get_bool("notify_license_expiring", False) is True
    assert Setting.get_bool("notify_license_added", False) is True
    assert Setting.get_bool("notify_contract_expiring", True) is False
    assert Setting.get_bool("notify_high_utilization", True) is False
