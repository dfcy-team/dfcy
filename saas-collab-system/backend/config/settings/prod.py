"""Production settings."""
import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403


DEBUG = False

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set in production.")

if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must be set in production.")

if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    raise ImproperlyConfigured("SQLite is not allowed in production. Configure MySQL through DB_* environment variables.")

required_database_env = {
    "DB_ENGINE": DATABASES["default"].get("ENGINE"),
    "DB_NAME": DATABASES["default"].get("NAME"),
    "DB_USER": DATABASES["default"].get("USER"),
    "DB_PASSWORD": DATABASES["default"].get("PASSWORD"),
    "DB_HOST": DATABASES["default"].get("HOST"),
    "DB_PORT": DATABASES["default"].get("PORT"),
}

missing_database_env = [name for name, value in required_database_env.items() if not value]
if missing_database_env:
    raise ImproperlyConfigured(
        "Production MySQL configuration is incomplete. Missing: " + ", ".join(missing_database_env)
    )

try:
    DB_LOCK_WAIT_TIMEOUT_SECONDS = int(os.getenv("DB_LOCK_WAIT_TIMEOUT_SECONDS", "60"))
except ValueError as exc:
    raise ImproperlyConfigured("DB_LOCK_WAIT_TIMEOUT_SECONDS must be an integer.") from exc
if not 1 <= DB_LOCK_WAIT_TIMEOUT_SECONDS <= 300:
    raise ImproperlyConfigured("DB_LOCK_WAIT_TIMEOUT_SECONDS must be between 1 and 300 seconds.")
if DATABASES["default"]["ENGINE"] == "django.db.backends.mysql":
    DATABASES["default"].setdefault("OPTIONS", {})["init_command"] = (
        f"SET SESSION lock_wait_timeout = {DB_LOCK_WAIT_TIMEOUT_SECONDS}"
    )

INTEGRATION_ENCRYPTION_PROVIDER = os.getenv(
    "INTEGRATION_ENCRYPTION_PROVIDER",
    "unconfigured-production",
)
if INTEGRATION_ENCRYPTION_PROVIDER == "test-only":
    raise ImproperlyConfigured("The test-only integration encryption provider is forbidden in production.")

# UI-P4 only defines a mock callback contract. Production enablement requires a separate review.
UI_P4_COLLABORATION_MODE = "disabled"
