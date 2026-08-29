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

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

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
    PERMANENT_SESSION_LIFETIME = timedelta(
        minutes=int(os.environ.get("SESSION_TIMEOUT_MINUTES", 60))
    )

    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH_MB", 5)) * 1024 * 1024
    UPLOAD_FOLDER = os.path.join(basedir, os.environ.get("UPLOAD_FOLDER", "instance/uploads"))
    ALLOWED_IMPORT_EXTENSIONS = {"csv"}

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

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False


class TestingConfig(Config):
    TESTING = True
    DEBUG = False
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    RATELIMIT_ENABLED = False


class ProductionConfig(Config):
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
    name = name or os.environ.get("FLASK_ENV", "default")
    return config_by_name.get(name, DevelopmentConfig)
