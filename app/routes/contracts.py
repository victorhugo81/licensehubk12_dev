import os
import secrets
from datetime import date, timedelta

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import login_required
from sqlalchemy import and_, false, or_
from werkzeug.utils import secure_filename

from app.extensions import db
from app.forms import ContractForm
from app.models import Contract, Vendor
from app.services.audit import diff_changes, log_action
from app.services.status import (
    STATUS_ACTIVE, STATUS_CRITICAL, STATUS_EXPIRED, STATUS_UPCOMING, STATUS_WARNING,
    compute_expiration_status, get_thresholds,
)
from app.utils.decorators import permission_required

# Adding/editing/deleting a contract is still done from its vendor's
# detail page (see add_contract/edit_contract/delete_contract below) - but
# `list_contracts` gives a district-wide view across all vendors, linked
# from the main nav.
contracts_bp = Blueprint("contracts", __name__)

PER_PAGE = 20
ALL_STATUSES = [STATUS_ACTIVE, STATUS_UPCOMING, STATUS_WARNING, STATUS_CRITICAL, STATUS_EXPIRED]


@contracts_bp.route("/contracts")
@login_required
def list_contracts():
    query = Contract.query

    vendor_id = request.args.get("vendor_id", type=int)
    if vendor_id:
        query = query.filter(Contract.vendor_id == vendor_id)

    q = request.args.get("q", "").strip()
    if q:
        query = query.filter(Contract.po_number.ilike(f"%{q}%"))

    thresholds = get_thresholds()

    status_filtered = "status_filtered" in request.args
    if status_filtered:
        selected_statuses = request.args.getlist("status")
    else:
        selected_statuses = [s for s in ALL_STATUSES if s != STATUS_EXPIRED]

    if set(selected_statuses) != set(ALL_STATUSES):
        today = date.today()
        critical_cutoff = today + timedelta(days=thresholds["critical_days"])
        warning_cutoff = today + timedelta(days=thresholds["warning_days"])
        upcoming_cutoff = today + timedelta(days=thresholds["upcoming_days"])
        conditions = []
        if STATUS_EXPIRED in selected_statuses:
            conditions.append(Contract.end_date < today)
        if STATUS_CRITICAL in selected_statuses:
            conditions.append(and_(Contract.end_date >= today, Contract.end_date <= critical_cutoff))
        if STATUS_WARNING in selected_statuses:
            conditions.append(and_(Contract.end_date > critical_cutoff, Contract.end_date <= warning_cutoff))
        if STATUS_UPCOMING in selected_statuses:
            conditions.append(and_(Contract.end_date > warning_cutoff, Contract.end_date <= upcoming_cutoff))
        if STATUS_ACTIVE in selected_statuses:
            conditions.append(Contract.end_date > upcoming_cutoff)
        query = query.filter(or_(*conditions) if conditions else false())

    page = request.args.get("page", 1, type=int)
    pagination = query.order_by(Contract.end_date).paginate(page=page, per_page=PER_PAGE, error_out=False)
    return render_template(
        "contracts/list.html", pagination=pagination, contracts=pagination.items,
        vendors=Vendor.query.order_by(Vendor.name).all(),
        statuses=ALL_STATUSES, selected_statuses=selected_statuses,
        thresholds=thresholds,
        compute_expiration_status=compute_expiration_status,
    )


@contracts_bp.route("/contracts/new")
@login_required
@permission_required("add_contracts")
def new_contract_redirect():
    vendor_id = request.args.get("vendor_id", type=int)
    if not vendor_id:
        flash("Choose a vendor to add a contract for.", "danger")
        return redirect(url_for("contracts.list_contracts"))
    Vendor.query.get_or_404(vendor_id)
    return redirect(url_for("contracts.add_contract", vendor_id=vendor_id))


def _form_data(c):
    return {
        "po_number": c.po_number, "start_date": c.start_date, "end_date": c.end_date,
        "renewal_date": c.renewal_date, "annual_cost": c.annual_cost,
        "vendor_contact": c.vendor_contact, "payment_frequency": c.payment_frequency,
        "auto_renewal": c.auto_renewal, "cancellation_deadline": c.cancellation_deadline,
    }


def _contracts_upload_dir():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], "contracts")
    os.makedirs(path, exist_ok=True)
    return path


def _delete_contract_file(contract):
    if not contract.contract_file_path:
        return
    old_path = os.path.join(_contracts_upload_dir(), contract.contract_file_path)
    if os.path.exists(old_path):
        os.remove(old_path)
    contract.contract_file_name = None
    contract.contract_file_path = None


def _save_contract_file(contract, upload_file):
    """Replaces any previously attached file. Filename on disk is a random
    token, never derived from the upload - only the original name (kept
    solely for display/download) ever touches user input."""
    original_name = secure_filename(upload_file.filename or "contract")
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext not in current_app.config["ALLOWED_CONTRACT_FILE_EXTENSIONS"]:
        return False

    _delete_contract_file(contract)
    stored_name = f"{secrets.token_hex(16)}.{ext}"
    upload_file.save(os.path.join(_contracts_upload_dir(), stored_name))
    contract.contract_file_name = original_name
    contract.contract_file_path = stored_name
    return True


@contracts_bp.route("/vendors/<int:vendor_id>/contracts/add", methods=["GET", "POST"])
@login_required
@permission_required("add_contracts")
def add_contract(vendor_id):
    vendor = Vendor.query.get_or_404(vendor_id)
    form = ContractForm()
    if form.validate_on_submit():
        contract = Contract(vendor=vendor)
        form.populate_obj(contract)
        if form.contract_file.data and form.contract_file.data.filename:
            if not _save_contract_file(contract, form.contract_file.data):
                flash("Only PDF or Word documents are allowed for the contract file.", "danger")
                return render_template("contracts/form.html", form=form, contract=None, vendor=vendor)
        db.session.add(contract)
        db.session.commit()
        log_action("create", "contract", contract.id, {"po_number": contract.po_number, "vendor": vendor.name})
        db.session.commit()
        flash(f"Contract {contract.po_number} added.", "success")
        return redirect(url_for("contracts.view_contract", id=contract.id))
    return render_template("contracts/form.html", form=form, contract=None, vendor=vendor)


@contracts_bp.route("/contracts/<int:id>")
@login_required
def view_contract(id):
    contract = Contract.query.get_or_404(id)
    thresholds = get_thresholds()
    return render_template(
        "contracts/detail.html", contract=contract,
        thresholds=thresholds, compute_expiration_status=compute_expiration_status,
    )


@contracts_bp.route("/vendors/<int:vendor_id>/contracts/<int:id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_contracts")
def edit_contract(vendor_id, id):
    contract = Contract.query.get_or_404(id)
    if contract.vendor_id != vendor_id:
        abort(404)
    vendor = contract.vendor
    before = _form_data(contract)
    form = ContractForm(obj=contract)
    if form.validate_on_submit():
        form.populate_obj(contract)
        if form.contract_file.data and form.contract_file.data.filename:
            if not _save_contract_file(contract, form.contract_file.data):
                flash("Only PDF or Word documents are allowed for the contract file.", "danger")
                return render_template("contracts/form.html", form=form, contract=contract, vendor=vendor)
        db.session.commit()
        changes = diff_changes(before, _form_data(contract))
        log_action("update", "contract", contract.id, changes)
        db.session.commit()
        flash(f"Contract {contract.po_number} updated.", "success")
        return redirect(url_for("contracts.view_contract", id=contract.id))
    return render_template("contracts/form.html", form=form, contract=contract, vendor=vendor)


@contracts_bp.route("/contracts/<int:id>/file")
@login_required
def download_file(id):
    contract = Contract.query.get_or_404(id)
    if not contract.contract_file_path:
        abort(404)
    return send_from_directory(
        _contracts_upload_dir(), contract.contract_file_path,
        as_attachment=True, download_name=contract.contract_file_name,
    )


@contracts_bp.route("/contracts/<int:id>/file/preview")
@login_required
def preview_file(id):
    contract = Contract.query.get_or_404(id)
    if not contract.contract_file_path or not contract.file_is_previewable:
        abort(404)
    # as_attachment=False so the browser renders the PDF inline instead of
    # downloading it - same file, same access rule as download_file above.
    return send_from_directory(
        _contracts_upload_dir(), contract.contract_file_path,
        as_attachment=False, download_name=contract.contract_file_name,
    )


@contracts_bp.route("/vendors/<int:vendor_id>/contracts/<int:id>/file/delete", methods=["POST"])
@login_required
@permission_required("manage_contracts")
def delete_file(vendor_id, id):
    contract = Contract.query.get_or_404(id)
    if contract.vendor_id != vendor_id:
        abort(404)
    _delete_contract_file(contract)
    db.session.commit()
    log_action("update", "contract", contract.id, {"contract_file": {"from": "attached", "to": None}})
    db.session.commit()
    flash("Contract file removed.", "success")
    return redirect(url_for("contracts.view_contract", id=contract.id))


@contracts_bp.route("/vendors/<int:vendor_id>/contracts/<int:id>/delete", methods=["POST"])
@login_required
@permission_required("manage_contracts")
def delete_contract(vendor_id, id):
    contract = Contract.query.get_or_404(id)
    if contract.vendor_id != vendor_id:
        abort(404)
    if contract.licenses:
        flash(f"Cannot delete contract {contract.po_number} while licenses are linked to it.", "danger")
        return redirect(url_for("contracts.view_contract", id=id))
    number = contract.po_number
    db.session.delete(contract)
    log_action("delete", "contract", id, {"po_number": number})
    db.session.commit()
    flash(f"Contract {number} deleted.", "success")
    return redirect(url_for("vendors.view_vendor", id=vendor_id))
