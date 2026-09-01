from datetime import date, timedelta

import pytest

from app.services import allocation as allocation_service
from app.services.status import (
    STATUS_ACTIVE, STATUS_CRITICAL, STATUS_EXPIRED, STATUS_UPCOMING, STATUS_WARNING,
    compute_expiration_status,
)
from tests.conftest import login


def test_expiration_status_thresholds():
    today = date(2026, 1, 1)
    thresholds = {"critical_days": 30, "warning_days": 60, "upcoming_days": 90}

    assert compute_expiration_status(today - timedelta(days=1), thresholds, today) == STATUS_EXPIRED
    assert compute_expiration_status(today, thresholds, today) == STATUS_CRITICAL
    assert compute_expiration_status(today + timedelta(days=30), thresholds, today) == STATUS_CRITICAL
    assert compute_expiration_status(today + timedelta(days=31), thresholds, today) == STATUS_WARNING
    assert compute_expiration_status(today + timedelta(days=60), thresholds, today) == STATUS_WARNING
    assert compute_expiration_status(today + timedelta(days=61), thresholds, today) == STATUS_UPCOMING
    assert compute_expiration_status(today + timedelta(days=90), thresholds, today) == STATUS_UPCOMING
    assert compute_expiration_status(today + timedelta(days=91), thresholds, today) == STATUS_ACTIVE
    assert compute_expiration_status(None, thresholds, today) == "unknown"


def test_license_computed_properties(license_, db):
    license_.license_count = 100
    assert license_.available_licenses == 100
    assert license_.utilization_pct == 0

    allocation_service.set_allocation(license_, _make_school(db, "A"), 40)
    db.session.commit()
    assert license_.assigned_licenses == 40
    assert license_.available_licenses == 60
    assert license_.utilization_pct == 40.0


def _make_school(db, suffix):
    from app.models import School
    s = School(name=f"School {suffix}", code=f"S-{suffix}", school_type="Elementary")
    db.session.add(s)
    db.session.commit()
    return s


def test_allocation_cannot_exceed_district_total(license_, db):
    school_a = _make_school(db, "A")
    school_b = _make_school(db, "B")

    allocation_service.set_allocation(license_, school_a, 60)
    db.session.commit()

    with pytest.raises(allocation_service.AllocationError):
        allocation_service.set_allocation(license_, school_b, 50)  # 60 + 50 > 100
    db.session.rollback()

    # Exactly at the limit is fine.
    allocation_service.set_allocation(license_, school_b, 40)
    db.session.commit()
    assert license_.assigned_licenses == 100


def test_allocation_update_excludes_its_own_previous_value(license_, db):
    school_a = _make_school(db, "A")
    allocation_service.set_allocation(license_, school_a, 90)
    db.session.commit()

    # Updating the same school's allocation shouldn't double-count its old value.
    allocation_service.set_allocation(license_, school_a, 100)
    db.session.commit()
    assert license_.assigned_licenses == 100


def test_allocation_negative_rejected(license_, db):
    school_a = _make_school(db, "A")
    with pytest.raises(allocation_service.AllocationError):
        allocation_service.set_allocation(license_, school_a, -5)


def test_license_crud_via_web(client, db, admin_user, vendor):
    login(client, "admin@example.com")

    resp = client.post("/licenses/add", data={
        "name": "NewSoft", "vendor_id": vendor.id, "category_id": 0,
        "license_count": "50", "status": "Active",
    }, follow_redirects=True)
    assert resp.status_code == 200

    from app.models import License
    lic = License.query.filter_by(name="NewSoft").first()
    assert lic is not None
    assert lic.license_count == 50

    resp = client.post(f"/licenses/{lic.id}/edit", data={
        "name": "NewSoft", "vendor_id": vendor.id, "category_id": 0,
        "license_count": "75", "status": "Active",
    }, follow_redirects=True)
    db.session.refresh(lic)
    assert lic.license_count == 75

    resp = client.post(f"/licenses/{lic.id}/delete", follow_redirects=True)
    assert License.query.filter_by(name="NewSoft").first() is None
