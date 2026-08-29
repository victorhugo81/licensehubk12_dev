from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.forms import ContractForm
from app.models import Contract, Vendor
from app.services.audit import diff_changes, log_action
from app.utils.decorators import permission_required

contracts_bp = Blueprint("contracts", __name__, url_prefix="/contracts")

PER_PAGE = 20


def _form_data(c):
    return {
        "contract_number": c.contract_number, "vendor_id": c.vendor_id, "software_id": c.software_id,
        "start_date": c.start_date, "end_date": c.end_date, "renewal_date": c.renewal_date,
        "contract_amount": c.contract_amount, "payment_frequency": c.payment_frequency,
        "auto_renewal": c.auto_renewal, "cancellation_deadline": c.cancellation_deadline,
        "po_number": c.po_number,
    }


@contracts_bp.route("/")
@login_required
def list_contracts():
    query = Contract.query
    vendor_id = request.args.get("vendor_id", type=int)
    if vendor_id:
        query = query.filter(Contract.vendor_id == vendor_id)
    q = request.args.get("q", "").strip()
    if q:
        query = query.filter(Contract.contract_number.ilike(f"%{q}%"))

    page = request.args.get("page", 1, type=int)
    pagination = query.order_by(Contract.end_date).paginate(page=page, per_page=PER_PAGE, error_out=False)
    return render_template(
        "contracts/list.html", pagination=pagination, contracts=pagination.items,
        vendors=Vendor.query.order_by(Vendor.name).all(),
    )


@contracts_bp.route("/add", methods=["GET", "POST"])
@login_required
@permission_required("manage_contracts")
def add_contract():
    form = ContractForm()
    if form.validate_on_submit():
        contract = Contract()
        form.populate_obj(contract)
        contract.software_id = form.software_id.data or None
        db.session.add(contract)
        db.session.commit()
        log_action("create", "contract", contract.id, {"contract_number": contract.contract_number})
        db.session.commit()
        flash(f"Contract {contract.contract_number} added.", "success")
        return redirect(url_for("contracts.view_contract", id=contract.id))
    return render_template("contracts/form.html", form=form, contract=None)


@contracts_bp.route("/<int:id>")
@login_required
def view_contract(id):
    contract = Contract.query.get_or_404(id)
    return render_template("contracts/detail.html", contract=contract)


@contracts_bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_contracts")
def edit_contract(id):
    contract = Contract.query.get_or_404(id)
    before = _form_data(contract)
    form = ContractForm(obj=contract)
    if request.method == "GET":
        form.software_id.data = contract.software_id or 0
    if form.validate_on_submit():
        form.populate_obj(contract)
        contract.software_id = form.software_id.data or None
        db.session.commit()
        changes = diff_changes(before, _form_data(contract))
        log_action("update", "contract", contract.id, changes)
        db.session.commit()
        flash(f"Contract {contract.contract_number} updated.", "success")
        return redirect(url_for("contracts.view_contract", id=contract.id))
    return render_template("contracts/form.html", form=form, contract=contract)


@contracts_bp.route("/<int:id>/delete", methods=["POST"])
@login_required
@permission_required("manage_contracts")
def delete_contract(id):
    contract = Contract.query.get_or_404(id)
    number = contract.contract_number
    db.session.delete(contract)
    log_action("delete", "contract", id, {"contract_number": number})
    db.session.commit()
    flash(f"Contract {number} deleted.", "success")
    return redirect(url_for("contracts.list_contracts"))
