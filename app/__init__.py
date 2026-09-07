import logging
import os
from logging.handlers import RotatingFileHandler

from flask import Flask, render_template, request

from config import get_config
from app.extensions import csrf, db, limiter, login_manager, mail, migrate

# Single source of truth for the version shown in the About modal
# (includes/footer.html) - keep in sync with the latest entry in
# CHANGELOG.md and with pyproject.toml's [project] version.
APP_VERSION = "1.0.0"


def create_app(config_name=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(get_config(config_name))

    if app.config.get("BEHIND_PROXY"):
        from werkzeug.middleware.proxy_fix import ProxyFix
        # Trust exactly one hop (the reverse proxy) for client IP/proto/host -
        # trusting more than the real proxy chain lets a client spoof
        # X-Forwarded-For and defeat rate limiting / audit-log IPs entirely.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    _init_extensions(app)
    _register_blueprints(app)
    _register_error_handlers(app)
    _register_security_headers(app)
    _register_cli(app)
    _register_context_processors(app)
    _configure_logging(app)

    from app.utils.template_filters import register_filters
    register_filters(app)

    from app.services.status import badge_class, status_label
    app.jinja_env.globals["status_badge_class"] = badge_class
    app.jinja_env.globals["status_label"] = status_label

    from app.services.scheduler import init_scheduler
    init_scheduler(app)

    return app


def _init_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    mail.init_app(app)

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        # user_id is "<id>.<security_stamp>" (User.get_id()) - a stamp
        # mismatch means the password was changed/reset since this session
        # cookie was issued, so treat it as logged out rather than trusting
        # a stale, already-revoked session (see User.security_stamp).
        raw_id, _, stamp = user_id.partition(".")
        try:
            user = db.session.get(User, int(raw_id))
        except ValueError:
            return None
        if user is None or user.security_stamp != stamp:
            return None
        return user


def _register_blueprints(app):
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.licenses import licenses_bp
    from app.routes.vendors import vendors_bp
    from app.routes.schools import schools_bp
    from app.routes.contracts import contracts_bp
    from app.routes.reports import reports_bp
    from app.routes.users import users_bp
    from app.routes.api import api_bp
    from app.routes.settings import settings_bp
    from app.routes.notifications import notifications_bp
    from app.routes.audit import audit_bp
    from app.routes.imports import imports_bp
    from app.routes.user_imports import user_imports_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(licenses_bp)
    app.register_blueprint(vendors_bp)
    app.register_blueprint(schools_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(imports_bp)
    app.register_blueprint(user_imports_bp)

    app.register_blueprint(api_bp)


def _register_error_handlers(app):
    from app.services.audit import log_action
    from app.extensions import db as _db

    def render_error(code):
        return render_template(f"errors/{code}.html"), code

    @app.errorhandler(400)
    def bad_request(e):
        return render_error(400)

    @app.errorhandler(403)
    def forbidden(e):
        return render_error(403)

    @app.errorhandler(404)
    def not_found(e):
        return render_error(404)

    @app.errorhandler(429)
    def rate_limited(e):
        return render_error(429)

    @app.errorhandler(500)
    def internal_error(e):
        _db.session.rollback()
        app.logger.exception("Unhandled server error on %s", request.path)
        return render_error(500)


def _register_security_headers(app):
    import secrets as _secrets
    from flask import g

    @app.before_request
    def _make_csp_nonce():
        g.csp_nonce = _secrets.token_urlsafe(16)

    @app.context_processor
    def _inject_csp_nonce():
        return {"csp_nonce": g.get("csp_nonce", "")}

    @app.after_request
    def _set_security_headers(resp):
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if app.config.get("SESSION_COOKIE_SECURE"):
            resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        nonce = g.get("csp_nonce", "")
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net; "
            # Every template in this app styles elements with inline
            # style="..." attributes (status badges, chart sizing, etc.) -
            # 'unsafe-inline' here is a deliberate, scoped tradeoff; script-src
            # above uses a real per-request nonce instead, since script
            # injection is the higher-value target to lock down.
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            "frame-ancestors 'none'"
        )
        return resp


def _register_cli(app):
    @app.cli.command("seed")
    def seed():
        """Populate the database with fictional sample district data."""
        from app.seed import run_seed
        run_seed()
        print("Database seeded.")

    @app.cli.command("run-checks")
    def run_checks_cmd():
        """Run the automated expiration/utilization/renewal checks once.
        Scheduler-agnostic: call this from cron, Task Scheduler, Celery
        beat, or the optional built-in APScheduler job."""
        from app.services.checks import run_all_checks
        run_all_checks()
        print("Automated checks completed.")


def _register_context_processors(app):
    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        from app.models import utcnow
        from app.services.notifications import unread_count

        count = 0
        if current_user and current_user.is_authenticated:
            count = unread_count(current_user)
        return {
            "unread_notification_count": count,
            "app_name": "LicenseHubK12",
            "app_version": APP_VERSION,
            "current_year": utcnow().year,
        }


def _configure_logging(app):
    if app.testing:
        return

    log_dir = os.path.join(app.instance_path, "logs")
    os.makedirs(log_dir, exist_ok=True)

    handler = RotatingFileHandler(os.path.join(log_dir, "licensehubk12.log"), maxBytes=1_000_000, backupCount=5)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    ))
    handler.setLevel(app.config.get("LOG_LEVEL", "INFO"))
    app.logger.addHandler(handler)
    app.logger.setLevel(app.config.get("LOG_LEVEL", "INFO"))
