"""Outbound email, currently just the password-reset link.

Opt-in like the app/integrations/* connectors: sends for real only when
MAIL_SERVER is configured, otherwise logs that a reset was requested
without ever writing the token itself to the log (the token grants account
takeover for its validity window - see CLAUDE.md's Bulk User Import
section for the same principle applied to bulk-created accounts).
"""
from flask import current_app

from app.extensions import mail


def send_password_reset_email(user, reset_url: str) -> bool:
    """Returns True if an email was actually sent."""
    if not current_app.config.get("MAIL_SERVER"):
        current_app.logger.info(
            "Password reset requested for user_id=%s (MAIL_SERVER not configured - "
            "no email sent; use the admin-visible link flow instead).",
            user.id,
        )
        return False

    from flask_mail import Message

    msg = Message(
        subject="Reset your LicenseHubK12 password",
        recipients=[user.email],
        body=(
            f"Hi {user.first_name},\n\n"
            f"Reset your password: {reset_url}\n\n"
            "This link expires in 1 hour. If you didn't request this, you can ignore this email."
        ),
    )
    mail.send(msg)
    current_app.logger.info("Password reset email sent for user_id=%s", user.id)
    return True
