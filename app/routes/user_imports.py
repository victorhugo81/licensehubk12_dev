import os
import secrets

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.extensions import db
from app.forms import CsvImportForm, FtpSettingsForm
from app.integrations.ftp_users import FtpUsersIntegration
from app.integrations.user_csv_import import commit_import, validate_csv
from app.models import FtpImportSettings, ImportHistory
from app.services.audit import log_action
from app.utils.decorators import permission_required

user_imports_bp = Blueprint("user_imports", __name__, url_prefix="/administration/users/import")


def _temp_path(token):
    # Filename is a server-generated random token, never derived from user
    # input, so there is no path-traversal surface here even though the
    # upload folder is fixed and known.
    safe_name = secure_filename(f"userimport-{token}") + ".csv"
    return os.path.join(current_app.config["UPLOAD_FOLDER"], safe_name)


@user_imports_bp.route("/", methods=["GET", "POST"])
@login_required
@permission_required("manage_users")
def upload():
    form = CsvImportForm()
    if form.validate_on_submit():
        upload_file = form.file.data
        original_name = secure_filename(upload_file.filename or "users.csv")
        ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
        if ext not in current_app.config["ALLOWED_IMPORT_EXTENSIONS"]:
            flash("Only .csv files are allowed.", "danger")
            return redirect(url_for("user_imports.upload"))

        token = secrets.token_hex(16)
        temp_path = _temp_path(token)
        upload_file.save(temp_path)

        with open(temp_path, "r", encoding="utf-8-sig", errors="replace") as f:
            preview = validate_csv(f)

        session["user_import_token"] = token
        session["user_import_filename"] = original_name

        return render_template("users/import_preview.html", preview=preview, filename=original_name)

    return render_template("users/import.html", form=form)


@user_imports_bp.route("/commit", methods=["POST"])
@login_required
@permission_required("manage_users")
def commit():
    token = session.get("user_import_token")
    filename = session.get("user_import_filename", "users.csv")
    if not token:
        flash("Your import session expired. Please upload the file again.", "danger")
        return redirect(url_for("user_imports.upload"))

    temp_path = _temp_path(token)
    if not os.path.exists(temp_path):
        flash("Your import session expired. Please upload the file again.", "danger")
        return redirect(url_for("user_imports.upload"))

    with open(temp_path, "r", encoding="utf-8-sig", errors="replace") as f:
        preview = validate_csv(f)

    created, updated, results = commit_import(preview)

    history = ImportHistory(
        kind="user", filename=filename, imported_by_id=current_user.id,
        total_records=preview.total, valid_records=preview.valid,
        warning_records=preview.warnings, error_records=preview.errors,
        status="completed",
    )
    history.details = {"created": created, "updated": updated, "results": results}
    db.session.add(history)
    log_action("import", "user", None, {"filename": filename, "created": created, "updated": updated})
    db.session.commit()

    os.remove(temp_path)
    session.pop("user_import_token", None)
    session.pop("user_import_filename", None)

    return render_template("users/import_results.html", results=results, updated=updated)


@user_imports_bp.route("/cancel", methods=["POST"])
@login_required
@permission_required("manage_users")
def cancel():
    token = session.pop("user_import_token", None)
    session.pop("user_import_filename", None)
    if token:
        temp_path = _temp_path(token)
        if os.path.exists(temp_path):
            os.remove(temp_path)
    flash("Import cancelled.", "info")
    return redirect(url_for("user_imports.upload"))


@user_imports_bp.route("/history")
@login_required
@permission_required("manage_users")
def history():
    records = ImportHistory.query.filter_by(kind="user").order_by(ImportHistory.imported_at.desc()).limit(50).all()
    return render_template("users/import_history.html", records=records)


@user_imports_bp.route("/ftp", methods=["GET", "POST"])
@login_required
@permission_required("manage_users")
def ftp_settings():
    settings = FtpImportSettings.get_or_create()
    form = FtpSettingsForm()
    if request.method == "GET":
        # Never populate the password field from storage, even with the
        # decrypted value - it would land in the rendered HTML and browser
        # autofill/history. Leaving it blank means "keep current password".
        form.is_enabled.data = settings.is_enabled
        form.host.data = settings.host
        form.port.data = settings.port or 21
        form.username.data = settings.username
        form.remote_path.data = settings.remote_path
        form.use_tls.data = settings.use_tls

    if form.validate_on_submit():
        if not form.password.data and not settings.password:
            form.password.errors.append("Password is required the first time you configure FTP import.")
        else:
            settings.is_enabled = form.is_enabled.data
            settings.host = form.host.data.strip()
            settings.port = form.port.data
            settings.username = form.username.data.strip()
            if form.password.data:
                settings.password = form.password.data
            settings.remote_path = form.remote_path.data.strip()
            settings.use_tls = form.use_tls.data
            log_action("update", "ftp_import_settings", settings.id, {
                "host": settings.host, "is_enabled": settings.is_enabled, "use_tls": settings.use_tls,
            })
            db.session.commit()
            flash("FTP import settings saved.", "success")
            if not settings.use_tls:
                flash(
                    "FTPS (TLS) is off - the username, password, and user data will be transmitted "
                    "in cleartext to this server. Enable FTPS unless the server truly doesn't support it.",
                    "warning",
                )
            return redirect(url_for("user_imports.ftp_settings"))

    return render_template("users/ftp_settings.html", form=form, settings=settings)


@user_imports_bp.route("/ftp/run", methods=["POST"])
@login_required
@permission_required("manage_users")
def ftp_run():
    settings = FtpImportSettings.get_or_create()
    result = FtpUsersIntegration(settings).sync()
    log_action("import", "user", None, {"source": "ftp", "success": result.success, "message": result.message})
    db.session.commit()
    flash(result.message, "success" if result.success else "danger")
    return redirect(url_for("user_imports.ftp_settings"))
