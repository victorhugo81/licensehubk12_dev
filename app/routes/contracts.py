from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import login_required

from app.extensions import db
from app.forms import ContractForm
from app.models import Contract, Software
from app.services.audit import diff_changes, log_action
from app.utils.decorators import permission_required

# Contracts are managed entirely from their software's detail page - there
# is no standalone contracts list. `view_contract` is the one exception,
# kept as a direct link target from the software and vendor detail pages.
contracts_bp = Blueprint("contracts", __name__)


def _form_data(c):
    return {
        "contract_number": c.contract_number, "start_date": c.start_date, "end_date": c.end_date,
        "renewal_date": c.renewal_date, "license_type": c.license_type, "annual_cost": c.annual_cost,
        "vendor_contact": c.vendor_contact, "payment_frequency": c.payment_frequency,
        "auto_renewal": c.auto_renewal, "cancellation_deadline": c.cancellation_deadline,
        "po_number": c.po_number,
    }


@contracts_bp.route("/software/<int:software_id>/contracts/add", methods=["GET", "POST"])
@login_required
@permission_required("manage_contracts")
def add_contract(software_id):
    software = Software.query.get_or_404(software_id)
    form = ContractForm()
    if form.validate_on_submit():
        contract = Contract(software=software, vendor_id=software.vendor_id)
        form.populate_obj(contract)
        db.session.add(contract)
        db.session.commit()
        log_action("create", "contract", contract.id, {"contract_number": contract.contract_number, "software": software.name})
        db.session.commit()
        flash(f"Contract {contract.contract_number} added.", "success")
        return redirect(url_for("licenses.view_software", id=software.id))
    return render_template("contracts/form.html", form=form, contract=None, software=software)


@contracts_bp.route("/contracts/<int:id>")
@login_required
def view_contract(id):
    contract = Contract.query.get_or_404(id)
    return render_template("contracts/detail.html", contract=contract)


@contracts_bp.route("/software/<int:software_id>/contracts/<int:id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_contracts")
def edit_contract(software_id, id):
    contract = Contract.query.get_or_404(id)
    if contract.software_id != software_id:
        abort(404)
    software = contract.software
    before = _form_data(contract)
    form = ContractForm(obj=contract)
    if form.validate_on_submit():
        form.populate_obj(contract)
        db.session.commit()
        changes = diff_changes(before, _form_data(contract))
        log_action("update", "contract", contract.id, changes)
        db.session.commit()
        flash(f"Contract {contract.contract_number} updated.", "success")
        return redirect(url_for("licenses.view_software", id=software.id))
    return render_template("contracts/form.html", form=form, contract=contract, software=software)


@contracts_bp.route("/software/<int:software_id>/contracts/<int:id>/delete", methods=["POST"])
@login_required
@permission_required("manage_contracts")
def delete_contract(software_id, id):
    contract = Contract.query.get_or_404(id)
    if contract.software_id != software_id:
        abort(404)
    number = contract.contract_number
    db.session.delete(contract)
    log_action("delete", "contract", id, {"contract_number": number})
    db.session.commit()
    flash(f"Contract {number} deleted.", "success")
    return redirect(url_for("licenses.view_software", id=software_id))
