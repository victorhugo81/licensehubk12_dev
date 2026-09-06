import os
from datetime import timedelta

from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


def _bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    """Base configuration shared by every environment."""

    # No fallback here on purpose - a hardcoded default would ship a
    # known-to-everyone signing key in the public source tree. Sessions and
    # CSRF tokens are both signed with this key, so a leaked/guessable value
    # means forged sessions and forged CSRF tokens. DevelopmentConfig below
    # supplies its own throwaway default so local `uv run flask run` still
    # works without a .env file.
    SECRET_KEY = os.environ.get("SECRET_KEY")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(basedir, "instance", "licensehubk12.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    WTF_CSRF_ENABLED = True

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", True)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = _bool("REMEMBER_COOKIE_SECURE", True)
    # Flask-Login defaults this to 365 days when unset. Left unconfigured,
    # checking "Remember me" would silently outlive PERMANENT_SESSION_LIFETIME
    # below by more than a year - a lost/stolen device stays signed in far
    # past the app's own session-timeout policy.
    REMEMBER_COOKIE_DURATION = timedelta(days=int(os.environ.get("REMEMBER_COOKIE_DAYS", 14)))
    PERMANENT_SESSION_LIFETIME = timedelta(
        minutes=int(os.environ.get("SESSION_TIMEOUT_MINUTES", 60))
    )

    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH_MB", 5)) * 1024 * 1024
    UPLOAD_FOLDER = os.path.join(basedir, os.environ.get("UPLOAD_FOLDER", "instance/uploads"))
    ALLOWED_IMPORT_EXTENSIONS = {"csv"}

    # Set True when deployed behind exactly one reverse proxy hop (nginx,
    # the documented setup) so ProxyFix reads the real client IP from
    # X-Forwarded-For instead of the proxy's own address - this is what
    # Flask-Limiter's per-IP rate limiting and the audit log's IP column
    # both key off. Leave False for direct/local access.
    BEHIND_PROXY = _bool("BEHIND_PROXY", False)

    # memory:// keeps counters in-process, so it only enforces limits
    # correctly with a single worker. Running gunicorn with -w > 1 (the
    # README's documented production command) means each worker counts
    # independently, multiplying every rate limit (including login
    # brute-force protection) by the worker count. Point this at a shared
    # store - e.g. redis://host:6379/0 - for any multi-worker deployment.
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_DEFAULT = "200 per hour"

    MAIL_SERVER = os.environ.get("MAIL_SERVER")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = _bool("MAIL_USE_TLS", True)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER")

    # Default license-status thresholds (days remaining until expiration).
    # These seed the Setting table on first run; admins can change them at
    # runtime from Administration > Settings without a redeploy.
    DEFAULT_STATUS_THRESHOLDS = {
        "critical_days": 30,
        "warning_days": 60,
        "upcoming_days": 90,
    }
    DEFAULT_UTILIZATION_THRESHOLDS = {
        "high_utilization_pct": 90,
        "over_allocated_pct": 100,
    }

    # Integrations - all optional and disabled unless explicitly configured.
    SYNERGY_ENABLED = _bool("SYNERGY_ENABLED", False)
    SYNERGY_BASE_URL = os.environ.get("SYNERGY_BASE_URL")
    SYNERGY_API_KEY = os.environ.get("SYNERGY_API_KEY")

    CLEVER_ENABLED = _bool("CLEVER_ENABLED", False)
    CLEVER_CLIENT_ID = os.environ.get("CLEVER_CLIENT_ID")
    CLEVER_CLIENT_SECRET = os.environ.get("CLEVER_CLIENT_SECRET")

    CANVAS_ENABLED = _bool("CANVAS_ENABLED", False)
    CANVAS_BASE_URL = os.environ.get("CANVAS_BASE_URL")
    CANVAS_API_TOKEN = os.environ.get("CANVAS_API_TOKEN")

    # Opt-in in-process APScheduler job that runs the expiration/utilization/
    # renewal checks (app/services/checks.py) once a day - see
    # app/services/scheduler.py. Off by default: without it (and without an
    # external cron driving `flask run-checks`), notifications only reflect
    # whatever the last manual/scheduled run saw, however stale that is. Run
    # only one worker process when this is on, to avoid duplicate runs.
    SCHEDULER_ENABLED = _bool("SCHEDULER_ENABLED", False)

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")


class DevelopmentConfig(Config):
    ENV_NAME = "development"
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    # Only DevelopmentConfig gets a throwaway default - never Config itself -
    # so a misconfigured production run fails loudly (see ProductionConfig)
    # instead of silently signing sessions with a key visible in this file.
    SECRET_KEY = Config.SECRET_KEY or "dev-secret-key-change-me"


class TestingConfig(Config):
    ENV_NAME = "testing"
    TESTING = True
    DEBUG = False
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    RATELIMIT_ENABLED = False
    SECRET_KEY = Config.SECRET_KEY or "testing-secret-key"
    # Always off regardless of the environment's SCHEDULER_ENABLED - the
    # scheduler is a module-level singleton (app/services/scheduler.py), so
    # starting it once per test-created app would register duplicate/
    # conflicting jobs across the suite.
    SCHEDULER_ENABLED = False


class ProductionConfig(Config):
    ENV_NAME = "production"
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}


def get_config(name: str | None = None):
    name = name or os.environ.get("APP_ENV")
    if name is None:
        raise RuntimeError(
            "No environment selected. Set APP_ENV=production|development|testing "
            "before starting the app - refusing to silently fall back to "
            "development configuration (DEBUG on, insecure cookies)."
        )
    try:
        selected = config_by_name[name]
    except KeyError:
        raise RuntimeError(f"Unknown APP_ENV '{name}'. Valid values: {', '.join(config_by_name)}") from None

    if selected is ProductionConfig and not selected.SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY environment variable is not set. Refusing to start "
            "in production without an explicit, secret signing key."
        )
    return selected
