"""Optional in-process scheduler wiring.

The automated checks in app/services/checks.py are scheduler-agnostic by
design - they're plain functions with no dependency on *how* they get
invoked. This module is one optional way to invoke them (via
Flask-APScheduler, in-process, daily) for deployments that don't want to
rely on system cron/Task Scheduler/Celery. It's opt-in via SCHEDULER_ENABLED
and does nothing unless explicitly turned on.
"""
from flask_apscheduler import APScheduler

scheduler = APScheduler()


def init_scheduler(app):
    if not app.config.get("SCHEDULER_ENABLED"):
        return

    scheduler.init_app(app)

    @scheduler.task("cron", id="run_license_checks", hour=6, minute=0)
    def run_license_checks():
        from app.services.checks import run_all_checks
        with app.app_context():
            run_all_checks()

    scheduler.start()
