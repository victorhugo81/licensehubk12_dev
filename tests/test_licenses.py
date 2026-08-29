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


def test_software_computed_properties(software, db):
    software.license_count = 100
    assert software.available_licenses == 100
    assert software.utilization_pct == 0

    allocation_service.set_allocation(software, _make_school(db, "A"), 40)
    db.session.commit()
    assert software.assigned_licenses == 40
    assert software.available_licenses == 60
    assert software.utilization_pct == 40.0


def _make_school(db, suffix):
    from app.models import School
    s = School(name=f"School {suffix}", code=f"S-{suffix}", school_type="Elementary")
    db.session.add(s)
    db.session.commit()
    return s


def test_allocation_cannot_exceed_district_total(software, db):
    school_a = _make_school(db, "A")
    school_b = _make_school(db, "B")

    allocation_service.set_allocation(software, school_a, 60)
    db.session.commit()

    with pytest.raises(allocation_service.AllocationError):
        allocation_service.set_allocation(software, school_b, 50)  # 60 + 50 > 100
    db.session.rollback()

    # Exactly at the limit is fine.
    allocation_service.set_allocation(software, school_b, 40)
    db.session.commit()
    assert software.assigned_licenses == 100


def test_allocation_update_excludes_its_own_previous_value(software, db):
    school_a = _make_school(db, "A")
    allocation_service.set_allocation(software, school_a, 90)
    db.session.commit()

    # Updating the same school's allocation shouldn't double-count its old value.
    allocation_service.set_allocation(software, school_a, 100)
    db.session.commit()
    assert software.assigned_licenses == 100


def test_allocation_negative_rejected(software, db):
    school_a = _make_school(db, "A")
    with pytest.raises(allocation_service.AllocationError):
        allocation_service.set_allocation(software, school_a, -5)


def test_software_crud_via_web(client, db, admin_user, vendor):
    login(client, "admin@example.com")

    resp = client.post("/software/add", data={
        "name": "NewSoft", "vendor_id": vendor.id, "category_id": 0, "license_type": "Subscription",
        "license_count": "50", "annual_cost": "1000", "status": "Active",
    }, follow_redirects=True)
    assert resp.status_code == 200

    from app.models import Software
    sw = Software.query.filter_by(name="NewSoft").first()
    assert sw is not None
    assert sw.license_count == 50

    resp = client.post(f"/software/{sw.id}/edit", data={
        "name": "NewSoft", "vendor_id": vendor.id, "category_id": 0, "license_type": "Subscription",
        "license_count": "75", "annual_cost": "1000", "status": "Active",
    }, follow_redirects=True)
    db.session.refresh(sw)
    assert sw.license_count == 75

    resp = client.post(f"/software/{sw.id}/delete", follow_redirects=True)
    assert Software.query.filter_by(name="NewSoft").first() is None
