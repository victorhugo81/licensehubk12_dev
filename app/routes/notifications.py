from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Notification
from app.services.notifications import visible_to

notifications_bp = Blueprint("notifications", __name__, url_prefix="/notifications")

PER_PAGE = 25


@notifications_bp.route("/")
@login_required
def index():
    query = visible_to(current_user).order_by(Notification.created_at.desc())
    unread_only = request.args.get("unread") == "1"
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))
    page = request.args.get("page", 1, type=int)
    pagination = query.paginate(page=page, per_page=PER_PAGE, error_out=False)
    return render_template("notifications/list.html", pagination=pagination, notifications=pagination.items, unread_only=unread_only)


@notifications_bp.route("/<int:id>/read", methods=["POST"])
@login_required
def mark_read(id):
    note = visible_to(current_user, Notification.query.filter_by(id=id)).first_or_404()
    note.is_read = True
    db.session.commit()
    return redirect(request.referrer or url_for("notifications.index"))


@notifications_bp.route("/mark-all-read", methods=["POST"])
@login_required
def mark_all_read():
    visible_to(current_user).filter(Notification.is_read.is_(False)).update({"is_read": True}, synchronize_session=False)
    db.session.commit()
    return redirect(request.referrer or url_for("notifications.index"))
