from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import login_required

from app.extensions import db
from app.forms import SettingsForm
from app.models import Setting
from app.services.audit import log_action
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

    return render_template("settings/index.html", form=form)
