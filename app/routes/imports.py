import os
import secrets

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.extensions import db
from app.forms import CsvImportForm
from app.integrations.csv_import import commit_import, validate_csv
from app.models import ImportHistory
from app.services.audit import log_action
from app.utils.decorators import permission_required

imports_bp = Blueprint("imports", __name__, url_prefix="/licenses/import")


def _temp_path(token):
    # Filename is a server-generated random token, never derived from user
    # input, so there is no path-traversal surface here even though the
    # upload folder is fixed and known.
    safe_name = secure_filename(token) + ".csv"
    return os.path.join(current_app.config["UPLOAD_FOLDER"], safe_name)


@imports_bp.route("/", methods=["GET", "POST"])
@login_required
@permission_required("manage_import")
def upload():
    form = CsvImportForm()
    if form.validate_on_submit():
        upload_file = form.file.data
        original_name = secure_filename(upload_file.filename or "import.csv")
        ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
        if ext not in current_app.config["ALLOWED_IMPORT_EXTENSIONS"]:
            flash("Only .csv files are allowed.", "danger")
            return redirect(url_for("imports.upload"))

        token = secrets.token_hex(16)
        temp_path = _temp_path(token)
        upload_file.save(temp_path)

        with open(temp_path, "r", encoding="utf-8-sig", errors="replace") as f:
            preview = validate_csv(f)

        session["import_token"] = token
        session["import_filename"] = original_name

        return render_template("licenses/import_preview.html", preview=preview, filename=original_name)

    return render_template("licenses/import.html", form=form)


@imports_bp.route("/commit", methods=["POST"])
@login_required
@permission_required("manage_import")
def commit():
    token = session.get("import_token")
    filename = session.get("import_filename", "import.csv")
    if not token:
        flash("Your import session expired. Please upload the file again.", "danger")
        return redirect(url_for("imports.upload"))

    temp_path = _temp_path(token)
    if not os.path.exists(temp_path):
        flash("Your import session expired. Please upload the file again.", "danger")
        return redirect(url_for("imports.upload"))

    with open(temp_path, "r", encoding="utf-8-sig", errors="replace") as f:
        preview = validate_csv(f)

    created, updated, allocation_errors = commit_import(preview, imported_by=current_user)

    history = ImportHistory(
        filename=filename,
        imported_by_id=current_user.id,
        total_records=preview.total,
        valid_records=preview.valid,
        warning_records=preview.warnings,
        error_records=preview.errors,
        status="completed",
    )
    history.details = {"created": created, "updated": updated, "allocation_errors": allocation_errors}
    db.session.add(history)
    log_action("import", "license", None, {"filename": filename, "created": created, "updated": updated})
    db.session.commit()

    os.remove(temp_path)
    session.pop("import_token", None)
    session.pop("import_filename", None)

    flash(f"Import complete: {created} license(s) created, {updated} updated.", "success")
    if allocation_errors:
        flash(f"{len(allocation_errors)} row(s) could not be allocated - see import history for details.", "warning")
    return redirect(url_for("licenses.list_licenses"))


@imports_bp.route("/cancel", methods=["POST"])
@login_required
@permission_required("manage_import")
def cancel():
    token = session.pop("import_token", None)
    session.pop("import_filename", None)
    if token:
        temp_path = _temp_path(token)
        if os.path.exists(temp_path):
            os.remove(temp_path)
    flash("Import cancelled.", "info")
    return redirect(url_for("imports.upload"))


@imports_bp.route("/history")
@login_required
@permission_required("manage_import")
def history():
    records = ImportHistory.query.order_by(ImportHistory.imported_at.desc()).limit(50).all()
    return render_template("licenses/import_history.html", records=records)
