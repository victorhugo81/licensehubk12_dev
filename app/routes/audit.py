from flask import Blueprint, render_template, request
from flask_login import login_required

from app.models import AuditLog, User
from app.utils.decorators import permission_required

audit_bp = Blueprint("audit", __name__, url_prefix="/audit-log")

PER_PAGE = 30


@audit_bp.route("/")
@login_required
@permission_required("view_audit_log")
def index():
    query = AuditLog.query

    user_id = request.args.get("user_id", type=int)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)

    object_type = request.args.get("object_type", "").strip()
    if object_type:
        query = query.filter(AuditLog.object_type == object_type)

    action = request.args.get("action", "").strip()
    if action:
        query = query.filter(AuditLog.action == action)

    q = request.args.get("q", "").strip()
    if q:
        query = query.filter(AuditLog.object_type.ilike(f"%{q}%"))

    page = request.args.get("page", 1, type=int)
    pagination = query.order_by(AuditLog.timestamp.desc()).paginate(page=page, per_page=PER_PAGE, error_out=False)

    object_types = [row[0] for row in AuditLog.query.with_entities(AuditLog.object_type).distinct().all()]
    actions = [row[0] for row in AuditLog.query.with_entities(AuditLog.action).distinct().all()]

    return render_template(
        "audit/list.html",
        pagination=pagination, logs=pagination.items,
        users=User.query.order_by(User.last_name).all(),
        object_types=object_types, actions=actions,
    )
