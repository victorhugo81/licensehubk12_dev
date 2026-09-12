import os
import secrets

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.extensions import db
from app.forms import CsvImportForm
from app.integrations.school_csv_import import commit_import, validate_csv
from app.models import ImportHistory, School
from app.services.audit import log_action
from app.utils.decorators import permission_required

school_imports_bp = Blueprint("school_imports", __name__, url_prefix="/administration/schools/import")


def _temp_path(token):
    # Filename is a server-generated random token, never derived from user
    # input, so there is no path-traversal surface here even though the
    # upload folder is fixed and known.
    safe_name = secure_filename(f"schoolimport-{token}") + ".csv"
    return os.path.join(current_app.config["UPLOAD_FOLDER"], safe_name)


@school_imports_bp.route("/", methods=["GET", "POST"])
@login_required
@permission_required("manage_schools")
def upload():
    form = CsvImportForm()
    if form.validate_on_submit():
        upload_file = form.file.data
        original_name = secure_filename(upload_file.filename or "schools.csv")
        ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
        if ext not in current_app.config["ALLOWED_IMPORT_EXTENSIONS"]:
            flash("Only .csv files are allowed.", "danger")
            return redirect(url_for("school_imports.upload"))

        token = secrets.token_hex(16)
        temp_path = _temp_path(token)
        upload_file.save(temp_path)

        with open(temp_path, "r", encoding="utf-8-sig", errors="replace") as f:
            preview = validate_csv(f)

        session["school_import_token"] = token
        session["school_import_filename"] = original_name

        return render_template("schools/import_preview.html", preview=preview, filename=original_name)

    return render_template("schools/import.html", form=form, school_types=School.TYPES)


@school_imports_bp.route("/commit", methods=["POST"])
@login_required
@permission_required("manage_schools")
def commit():
    token = session.get("school_import_token")
    filename = session.get("school_import_filename", "schools.csv")
    if not token:
        flash("Your import session expired. Please upload the file again.", "danger")
        return redirect(url_for("school_imports.upload"))

    temp_path = _temp_path(token)
    if not os.path.exists(temp_path):
        flash("Your import session expired. Please upload the file again.", "danger")
        return redirect(url_for("school_imports.upload"))

    with open(temp_path, "r", encoding="utf-8-sig", errors="replace") as f:
        preview = validate_csv(f)

    created, updated = commit_import(preview)

    history = ImportHistory(
        kind="school", filename=filename, imported_by_id=current_user.id,
        total_records=preview.total, valid_records=preview.valid,
        warning_records=preview.warnings, error_records=preview.errors,
        status="completed",
    )
    history.details = {"created": created, "updated": updated}
    db.session.add(history)
    log_action("import", "school", None, {"filename": filename, "created": created, "updated": updated})
    db.session.commit()

    os.remove(temp_path)
    session.pop("school_import_token", None)
    session.pop("school_import_filename", None)

    flash(f"Import complete: {created} school(s) created, {updated} updated.", "success")
    return redirect(url_for("schools.list_schools"))


@school_imports_bp.route("/cancel", methods=["POST"])
@login_required
@permission_required("manage_schools")
def cancel():
    token = session.pop("school_import_token", None)
    session.pop("school_import_filename", None)
    if token:
        temp_path = _temp_path(token)
        if os.path.exists(temp_path):
            os.remove(temp_path)
    flash("Import cancelled.", "info")
    return redirect(url_for("school_imports.upload"))


@school_imports_bp.route("/history")
@login_required
@permission_required("manage_schools")
def history():
    records = ImportHistory.query.filter_by(kind="school").order_by(ImportHistory.imported_at.desc()).limit(50).all()
    return render_template("schools/import_history.html", records=records)
