import io
import os

from app.models import Contract
from tests.conftest import login

_FORM_BASE = {
    "po_number": "PO-TEST-1", "payment_frequency": "Annual", "annual_cost": "1000",
    "start_date": "2026-01-01", "end_date": "2027-01-01",
}


def _cleanup_uploaded_file(app, contract_id):
    with app.app_context():
        c = Contract.query.get(contract_id)
        if c and c.contract_file_path:
            path = os.path.join(app.config["UPLOAD_FOLDER"], "contracts", c.contract_file_path)
            if os.path.exists(path):
                os.remove(path)


def test_upload_pdf_on_contract_edit(client, admin_user, contract, app):
    login(client, admin_user.email)
    data = dict(_FORM_BASE)
    data["contract_file"] = (io.BytesIO(b"%PDF-1.4 fake pdf content"), "agreement.pdf")

    resp = client.post(
        f"/vendors/{contract.vendor_id}/contracts/{contract.id}/edit",
        data=data, content_type="multipart/form-data", follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        c = Contract.query.get(contract.id)
        assert c.contract_file_name == "agreement.pdf"
        assert c.contract_file_path is not None
        stored_path = os.path.join(app.config["UPLOAD_FOLDER"], "contracts", c.contract_file_path)
        assert os.path.exists(stored_path)

    _cleanup_uploaded_file(app, contract.id)


def test_rejects_disallowed_extension(client, admin_user, contract, app):
    login(client, admin_user.email)
    data = dict(_FORM_BASE)
    data["contract_file"] = (io.BytesIO(b"malicious"), "payload.exe")

    resp = client.post(
        f"/vendors/{contract.vendor_id}/contracts/{contract.id}/edit",
        data=data, content_type="multipart/form-data", follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        c = Contract.query.get(contract.id)
        assert c.contract_file_path is None


def test_download_requires_login(client, contract):
    resp = client.get(f"/contracts/{contract.id}/file")
    assert resp.status_code in (302, 401)


def test_download_returns_404_without_file(client, admin_user, contract):
    login(client, admin_user.email)
    resp = client.get(f"/contracts/{contract.id}/file")
    assert resp.status_code == 404


def test_download_serves_uploaded_file(client, admin_user, contract, app):
    login(client, admin_user.email)
    data = dict(_FORM_BASE)
    data["contract_file"] = (io.BytesIO(b"%PDF-1.4 fake pdf content"), "agreement.pdf")
    client.post(
        f"/vendors/{contract.vendor_id}/contracts/{contract.id}/edit",
        data=data, content_type="multipart/form-data",
    )

    resp = client.get(f"/contracts/{contract.id}/file")
    assert resp.status_code == 200
    assert b"fake pdf content" in resp.data
    assert "agreement.pdf" in resp.headers.get("Content-Disposition", "")

    _cleanup_uploaded_file(app, contract.id)


def test_uploading_replacement_deletes_old_file(client, admin_user, contract, app):
    login(client, admin_user.email)
    data1 = dict(_FORM_BASE)
    data1["contract_file"] = (io.BytesIO(b"first version"), "v1.pdf")
    client.post(
        f"/vendors/{contract.vendor_id}/contracts/{contract.id}/edit",
        data=data1, content_type="multipart/form-data",
    )
    with app.app_context():
        old_path = os.path.join(app.config["UPLOAD_FOLDER"], "contracts", Contract.query.get(contract.id).contract_file_path)
    assert os.path.exists(old_path)

    data2 = dict(_FORM_BASE)
    data2["contract_file"] = (io.BytesIO(b"second version"), "v2.pdf")
    client.post(
        f"/vendors/{contract.vendor_id}/contracts/{contract.id}/edit",
        data=data2, content_type="multipart/form-data",
    )

    assert not os.path.exists(old_path)
    with app.app_context():
        c = Contract.query.get(contract.id)
        assert c.contract_file_name == "v2.pdf"

    _cleanup_uploaded_file(app, contract.id)


def test_remove_file_route(client, admin_user, contract, app):
    login(client, admin_user.email)
    data = dict(_FORM_BASE)
    data["contract_file"] = (io.BytesIO(b"content"), "doc.pdf")
    client.post(
        f"/vendors/{contract.vendor_id}/contracts/{contract.id}/edit",
        data=data, content_type="multipart/form-data",
    )
    with app.app_context():
        stored_path = os.path.join(app.config["UPLOAD_FOLDER"], "contracts", Contract.query.get(contract.id).contract_file_path)
    assert os.path.exists(stored_path)

    resp = client.post(f"/vendors/{contract.vendor_id}/contracts/{contract.id}/file/delete", follow_redirects=True)
    assert resp.status_code == 200
    assert not os.path.exists(stored_path)

    with app.app_context():
        c = Contract.query.get(contract.id)
        assert c.contract_file_name is None
        assert c.contract_file_path is None


def test_upload_requires_manage_contracts_permission(client, viewer_user, contract):
    login(client, viewer_user.email)
    data = dict(_FORM_BASE)
    data["contract_file"] = (io.BytesIO(b"content"), "doc.pdf")
    resp = client.post(
        f"/vendors/{contract.vendor_id}/contracts/{contract.id}/edit",
        data=data, content_type="multipart/form-data",
    )
    assert resp.status_code == 403


def test_preview_serves_pdf_inline(client, admin_user, contract, app):
    login(client, admin_user.email)
    data = dict(_FORM_BASE)
    data["contract_file"] = (io.BytesIO(b"%PDF-1.4 fake pdf content"), "agreement.pdf")
    client.post(
        f"/vendors/{contract.vendor_id}/contracts/{contract.id}/edit",
        data=data, content_type="multipart/form-data",
    )

    resp = client.get(f"/contracts/{contract.id}/file/preview")
    assert resp.status_code == 200
    assert b"fake pdf content" in resp.data
    disposition = resp.headers.get("Content-Disposition", "")
    assert "attachment" not in disposition

    _cleanup_uploaded_file(app, contract.id)


def test_preview_404s_for_non_pdf(client, admin_user, contract, app):
    login(client, admin_user.email)
    data = dict(_FORM_BASE)
    data["contract_file"] = (io.BytesIO(b"fake docx content"), "agreement.docx")
    client.post(
        f"/vendors/{contract.vendor_id}/contracts/{contract.id}/edit",
        data=data, content_type="multipart/form-data",
    )

    resp = client.get(f"/contracts/{contract.id}/file/preview")
    assert resp.status_code == 404

    _cleanup_uploaded_file(app, contract.id)


def test_preview_404s_without_file(client, admin_user, contract):
    login(client, admin_user.email)
    resp = client.get(f"/contracts/{contract.id}/file/preview")
    assert resp.status_code == 404


def test_file_is_previewable_property(app, contract, db):
    with app.app_context():
        contract.contract_file_name = "agreement.pdf"
        assert contract.file_is_previewable is True
        contract.contract_file_name = "agreement.docx"
        assert contract.file_is_previewable is False
        contract.contract_file_name = None
        assert contract.file_is_previewable is False
