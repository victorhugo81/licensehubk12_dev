import secrets
from datetime import timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db, limiter
from app.forms import ChangePasswordForm, LoginForm, RequestResetForm, ResetPasswordForm
from app.models import User, utcnow
from app.services.audit import log_action

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter(db.func.lower(User.email) == form.email.data.strip().lower()).first()

        if user and user.is_locked():
            flash("This account is temporarily locked due to repeated failed sign-in attempts. Try again later.", "danger")
            return render_template("login.html", form=form)

        if user and user.is_active_account and user.check_password(form.password.data):
            user.failed_login_attempts = 0
            user.locked_until = None
            user.last_login_at = utcnow()
            db.session.commit()

            login_user(user, remember=form.remember_me.data)
            session.permanent = True
            log_action("login", "user", user.id)
            db.session.commit()

            next_url = request.args.get("next")
            if next_url and next_url.startswith("/"):
                return redirect(next_url)
            return redirect(url_for("dashboard.index"))

        if user:
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                user.locked_until = utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
                flash("Too many failed attempts. This account is locked for 15 minutes.", "danger")
            db.session.commit()

        flash("Invalid email or password.", "danger")

    return render_template("login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    log_action("logout", "user", current_user.id)
    db.session.commit()
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/reset-password", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def request_reset():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = RequestResetForm()
    if form.validate_on_submit():
        user = User.query.filter(db.func.lower(User.email) == form.email.data.strip().lower()).first()
        if user:
            user.reset_token = secrets.token_urlsafe(48)
            user.reset_token_expires = utcnow() + timedelta(hours=1)
            db.session.commit()
            # In production this link is emailed via Flask-Mail; logged
            # here so the flow is testable without an SMTP server.
            from flask import current_app
            current_app.logger.info(
                "Password reset link for %s: /auth/reset-password/%s", user.email, user.reset_token
            )
        # Always show the same message, whether or not the email exists,
        # so this endpoint can't be used to enumerate accounts.
        flash("If that email is registered, a reset link has been sent.", "info")
        return redirect(url_for("auth.login"))

    return render_template("reset_request.html", form=form)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    user = User.query.filter_by(reset_token=token).first()
    if not user or not user.reset_token_expires or user.reset_token_expires < utcnow():
        flash("That reset link is invalid or has expired.", "danger")
        return redirect(url_for("auth.request_reset"))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        user.reset_token = None
        user.reset_token_expires = None
        user.failed_login_attempts = 0
        user.locked_until = None
        db.session.commit()
        log_action("password_reset", "user", user.id)
        db.session.commit()
        flash("Your password has been reset. You can now sign in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("reset_password.html", form=form)


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Current password is incorrect.", "danger")
        else:
            current_user.set_password(form.password.data)
            db.session.commit()
            log_action("password_change", "user", current_user.id)
            db.session.commit()
            flash("Password updated.", "success")
            return redirect(url_for("dashboard.index"))

    return render_template("change_password.html", form=form)
