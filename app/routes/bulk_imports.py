"""Combined "Bulk Import" page: upload a users CSV and/or a schools
("sites") CSV in one submission, review one combined preview, then commit
both in one go - schools first, then users, so a user row referencing a
school from the *same* upload can already resolve it.

This is a thin UI layer over the two existing, independently-tested
importers (app/integrations/user_csv_import.py,
app/integrations/school_csv_import.py) - it doesn't duplicate their
validation/commit logic, just orchestrates uploading and running both from
one page. The FTP tab on this page is the existing user-FTP-import feature
(app/routes/user_imports.py); there is no scheduled FTP pull for schools.
"""
import os
import secrets

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.extensions import db
from app.forms import FtpSettingsForm
from app.integrations import school_csv_import, user_csv_import
from app.models import FtpImportSettings, ImportHistory, Role, School
from app.services.audit import log_action
from app.utils.decorators import can_write

bulk_imports_bp = Blueprint("bulk_imports", __name__, url_prefix="/administration/import")

# Schools and users are gated by their own existing permissions
# (manage_schools / manage_users) rather than one blanket decorator on this
# page, since they're Administrator/IT-Administrator and Administrator-only
# respectively - an IT Administrator can use the schools half of this page
# but not the users half.
_KIND_PERMISSIONS = {"school": "manage_schools", "user": "manage_users"}
_KIND_LABELS = {"school": "Sites", "user": "Users"}


def _temp_path(kind, token):
    # Filename is a server-generated random token, never derived from user
    # input, so there is no path-traversal surface here even though the
    # upload folder is fixed and known.
    safe_name = secure_filename(f"bulkimport-{kind}-{token}") + ".csv"
    return os.path.join(current_app.config["UPLOAD_FOLDER"], safe_name)


def _sniff_kind(filename, header_line):
    name = (filename or "").lower()
    if "site" in name or "school" in name:
        return "school"
    if "user" in name:
        return "user"
    header_line = (header_line or "").lower()
    if "site_type" in header_line or "site_name" in header_line or "site_code" in header_line:
        return "school"
    if "role" in header_line and "email" in header_line:
        return "user"
    return None


def _clear_session_files():
    pending = session.pop("bulk_import_pending", {})
    for entry in pending.values():
        path = _temp_path(entry["kind"], entry["token"])
        if os.path.exists(path):
            os.remove(path)


def _ftp_context():
    settings = FtpImportSettings.get_or_create()
    form = FtpSettingsForm()
    if request.method == "GET":
        # Never populate the password field from storage - see
        # user_imports.ftp_settings() for the same rule.
        form.is_enabled.data = settings.is_enabled
        form.host.data = settings.host
        form.port.data = settings.port or 21
        form.username.data = settings.username
        form.remote_path.data = settings.remote_path
        form.use_tls.data = settings.use_tls
    return form, settings


@bulk_imports_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    if not (can_write("manage_schools") or can_write("manage_users")):
        abort(403)

    ftp_form, ftp_settings = _ftp_context()

    if request.method == "POST":
        uploads = [f for f in request.files.getlist("files") if f and f.filename]
        if not uploads:
            flash("Choose at least one CSV file to upload.", "danger")
            return redirect(url_for("bulk_imports.index"))

        pending = {}
        previews = {}
        for upload_file in uploads:
            original_name = secure_filename(upload_file.filename or "import.csv")
            ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
            if ext not in current_app.config["ALLOWED_IMPORT_EXTENSIONS"]:
                flash(f"'{original_name}' is not a .csv file - skipped.", "danger")
                continue

            raw = upload_file.read()
            text = raw.decode("utf-8-sig", errors="replace") if isinstance(raw, bytes) else raw
            header_line = text.splitlines()[0] if text else ""
            kind = _sniff_kind(original_name, header_line)
            if kind is None:
                flash(
                    f"Couldn't tell whether '{original_name}' is a users or a sites file - "
                    "include 'users' or 'sites'/'schools' in the filename.",
                    "danger",
                )
                continue
            if not can_write(_KIND_PERMISSIONS[kind]):
                flash(f"You don't have permission to import {_KIND_LABELS[kind].lower()} - '{original_name}' was ignored.", "danger")
                continue
            if kind in pending:
                flash(f"Only one {_KIND_LABELS[kind].lower()} file at a time - '{original_name}' was ignored.", "warning")
                continue

            token = secrets.token_hex(16)
            temp_path = _temp_path(kind, token)
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(text)

            import io
            validator = school_csv_import.validate_csv if kind == "school" else user_csv_import.validate_csv
            preview = validator(io.StringIO(text))

            pending[kind] = {"kind": kind, "token": token, "filename": original_name}
            previews[kind] = preview

        if not previews:
            return redirect(url_for("bulk_imports.index"))

        session["bulk_import_pending"] = pending
        return render_template(
            "imports/preview.html",
            school_preview=previews.get("school"), school_filename=pending.get("school", {}).get("filename"),
            user_preview=previews.get("user"), user_filename=pending.get("user", {}).get("filename"),
        )

    records = (
        ImportHistory.query.filter(ImportHistory.kind.in_(["school", "user"]))
        .order_by(ImportHistory.imported_at.desc())
        .limit(50)
        .all()
    )
    return render_template(
        "imports/index.html",
        school_types=School.TYPES, roles=Role.ALL,
        ftp_form=ftp_form, ftp_settings=ftp_settings,
        records=records,
        max_content_length_mb=(current_app.config.get("MAX_CONTENT_LENGTH") or 0) // (1024 * 1024),
    )


@bulk_imports_bp.route("/commit", methods=["POST"])
@login_required
def commit():
    pending = session.get("bulk_import_pending")
    if not pending:
        flash("Your import session expired. Please upload the file(s) again.", "danger")
        return redirect(url_for("bulk_imports.index"))

    summary = []

    # Schools first, so a users file uploaded in the same batch can already
    # resolve a school it references.
    for kind in ("school", "user"):
        entry = pending.get(kind)
        if not entry:
            continue
        temp_path = _temp_path(kind, entry["token"])
        if not can_write(_KIND_PERMISSIONS[kind]):
            flash(f"You don't have permission to import {_KIND_LABELS[kind].lower()} - skipped.", "danger")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            continue

        if not os.path.exists(temp_path):
            flash(f"The {_KIND_LABELS[kind].lower()} file expired - please upload it again.", "danger")
            continue

        with open(temp_path, "r", encoding="utf-8-sig", errors="replace") as f:
            text = f.read()

        import io
        if kind == "school":
            preview = school_csv_import.validate_csv(io.StringIO(text))
            created, updated = school_csv_import.commit_import(preview)
            details = {"created": created, "updated": updated}
            summary.append(f"{created} site(s) created, {updated} updated")
        else:
            preview = user_csv_import.validate_csv(io.StringIO(text))
            created, updated, results = user_csv_import.commit_import(preview)
            details = {"created": created, "updated": updated, "results": results}
            summary.append(f"{created} user(s) created, {updated} updated")

        history = ImportHistory(
            kind=kind, filename=entry["filename"], imported_by_id=current_user.id,
            total_records=preview.total, valid_records=preview.valid,
            warning_records=preview.warnings, error_records=preview.errors,
            status="completed",
        )
        history.details = details
        db.session.add(history)
        log_action("import", kind, None, {"filename": entry["filename"], **details})
        db.session.commit()

        os.remove(temp_path)

    session.pop("bulk_import_pending", None)
    if summary:
        flash("Import complete: " + "; ".join(summary) + ".", "success")
    return redirect(url_for("bulk_imports.index"))


@bulk_imports_bp.route("/cancel", methods=["POST"])
@login_required
def cancel():
    _clear_session_files()
    flash("Import cancelled.", "info")
    return redirect(url_for("bulk_imports.index"))
