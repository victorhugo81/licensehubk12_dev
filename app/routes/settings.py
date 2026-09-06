from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import login_required

from app.extensions import db
from app.forms import NotificationSettingsForm, SettingsForm
from app.models import Setting
from app.services.audit import log_action
from app.services.notifications import NOTIFICATION_CATEGORIES
from app.services.status import get_thresholds, get_utilization_thresholds
from app.utils.decorators import permission_required

settings_bp = Blueprint("settings", __name__, url_prefix="/administration/settings")


@settings_bp.route("/", methods=["GET", "POST"])
@login_required
@permission_required("manage_settings")
def index():
    thresholds = get_thresholds()
    utilization = get_utilization_thresholds()
    form = SettingsForm(data={**thresholds, **utilization})
    notification_form = NotificationSettingsForm(data={
        cat["key"]: Setting.get_bool(cat["key"], True) for cat in NOTIFICATION_CATEGORIES
    })

    if form.validate_on_submit():
        Setting.set_value("critical_days", form.critical_days.data)
        Setting.set_value("warning_days", form.warning_days.data)
        Setting.set_value("upcoming_days", form.upcoming_days.data)
        Setting.set_value("high_utilization_pct", form.high_utilization_pct.data)
        Setting.set_value("over_allocated_pct", form.over_allocated_pct.data)
        log_action("update", "settings", None, {
            "critical_days": form.critical_days.data, "warning_days": form.warning_days.data,
            "upcoming_days": form.upcoming_days.data,
        })
        db.session.commit()
        flash("Settings updated.", "success")
        return redirect(url_for("settings.index"))

    return render_template(
        "settings/index.html", form=form, notification_form=notification_form,
        notification_categories=NOTIFICATION_CATEGORIES,
    )


@settings_bp.route("/notifications", methods=["POST"])
@login_required
@permission_required("manage_settings")
def notifications():
    form = NotificationSettingsForm()
    if form.validate_on_submit():
        changes = {}
        for cat in NOTIFICATION_CATEGORIES:
            enabled = getattr(form, cat["key"]).data
            Setting.set_value(cat["key"], "1" if enabled else "0")
            changes[cat["key"]] = enabled
        log_action("update", "notification_settings", None, changes)
        db.session.commit()
        flash("Notification settings updated.", "success")
    else:
        flash("Could not save notification settings.", "danger")
    return redirect(url_for("settings.index"))
