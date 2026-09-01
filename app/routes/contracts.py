from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.forms import ContractForm
from app.models import Contract, Vendor
from app.services.audit import diff_changes, log_action
from app.services.status import compute_expiration_status, get_thresholds
from app.utils.decorators import permission_required

# Adding/editing/deleting a contract is still done from its vendor's
# detail page (see add_contract/edit_contract/delete_contract below) - but
# `list_contracts` gives a district-wide view across all vendors, linked
# from the main nav.
contracts_bp = Blueprint("contracts", __name__)

PER_PAGE = 20


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

    page = request.args.get("page", 1, type=int)
    pagination = query.order_by(Contract.end_date).paginate(page=page, per_page=PER_PAGE, error_out=False)
    return render_template(
        "contracts/list.html", pagination=pagination, contracts=pagination.items,
        vendors=Vendor.query.order_by(Vendor.name).all(),
    )


@contracts_bp.route("/contracts/new")
@login_required
@permission_required("manage_contracts")
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


@contracts_bp.route("/vendors/<int:vendor_id>/contracts/add", methods=["GET", "POST"])
@login_required
@permission_required("manage_contracts")
def add_contract(vendor_id):
    vendor = Vendor.query.get_or_404(vendor_id)
    form = ContractForm()
    if form.validate_on_submit():
        contract = Contract(vendor=vendor)
        form.populate_obj(contract)
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
        db.session.commit()
        changes = diff_changes(before, _form_data(contract))
        log_action("update", "contract", contract.id, changes)
        db.session.commit()
        flash(f"Contract {contract.po_number} updated.", "success")
        return redirect(url_for("contracts.view_contract", id=contract.id))
    return render_template("contracts/form.html", form=form, contract=contract, vendor=vendor)


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
