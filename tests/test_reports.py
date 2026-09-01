from tests.conftest import login


def test_reports_index_requires_login(client):
    resp = client.get("/reports/", follow_redirects=False)
    assert resp.status_code == 302


def test_inventory_report_renders(client, admin_user, license_):
    login(client, "admin@example.com")
    resp = client.get("/reports/inventory")
    assert resp.status_code == 200
    assert b"TestSoft" in resp.data


def test_inventory_export_csv(client, admin_user, license_):
    login(client, "admin@example.com")
    resp = client.get("/reports/inventory?format=csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert b"TestSoft" in resp.data


def test_inventory_export_excel(client, admin_user, license_):
    login(client, "admin@example.com")
    resp = client.get("/reports/inventory?format=excel")
    assert resp.status_code == 200
    assert resp.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_inventory_export_pdf(client, admin_user, license_):
    login(client, "admin@example.com")
    resp = client.get("/reports/inventory?format=pdf")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"


def test_expiring_report_filters_by_days(client, admin_user, license_, db):
    from datetime import date, timedelta
    license_.expiration_date = date.today() + timedelta(days=45)
    db.session.commit()

    login(client, "admin@example.com")
    resp = client.get("/reports/expiring?days=30")
    assert b"TestSoft" not in resp.data

    resp = client.get("/reports/expiring?days=90")
    assert b"TestSoft" in resp.data


def test_school_administrator_reports_scoped_to_own_school(client, db, license_, school_admin_user):
    from app.services import allocation as allocation_service
    other_school = school_admin_user.school

    login(client, "schooladmin@example.com")
    resp = client.get("/reports/inventory")
    assert resp.status_code == 200
    assert b"TestSoft" not in resp.data  # not allocated to their school yet

    allocation_service.set_allocation(license_, other_school, 10)
    db.session.commit()

    resp = client.get("/reports/inventory")
    assert b"TestSoft" in resp.data
