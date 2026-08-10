"""Base settings shared by all backend environments."""
from pathlib import Path
import os

from dotenv import load_dotenv
from corsheaders.defaults import default_headers


BASE_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BASE_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Real-platform connection (task A-REAL-PLATFORM-CONNECTION)
#
# Every value here defaults to a fail-closed state. The system talks to real
# Shopee / TikTok Shop platforms ONLY when:
#   * PLATFORM_NETWORK_MODE == "approved-live-test" (explicit, audited), AND
#   * LIVE_PLATFORM_SECURITY_APPROVED == True (dedicated security sign-off).
# Endpoints/secrets are placeholders that refuse to run until an operator
# supplies values CONFIRMED against the official console/docs on execution day.
# ---------------------------------------------------------------------------
PLATFORM_NETWORK_MODE = os.getenv("PLATFORM_NETWORK_MODE", "")
LIVE_PLATFORM_SECURITY_APPROVED = env_bool("LIVE_PLATFORM_SECURITY_APPROVED", False)

LIVE_PLATFORM_ALLOWED_HOSTS = env_list("LIVE_PLATFORM_ALLOWED_HOSTS")
LIVE_PLATFORM_CONNECT_TIMEOUT = float(os.getenv("LIVE_PLATFORM_CONNECT_TIMEOUT", "3"))
LIVE_PLATFORM_READ_TIMEOUT = float(os.getenv("LIVE_PLATFORM_READ_TIMEOUT", "8"))
LIVE_PLATFORM_MAX_RETRIES = int(os.getenv("LIVE_PLATFORM_MAX_RETRIES", "2"))
LIVE_PLATFORM_BACKOFF_BASE = float(os.getenv("LIVE_PLATFORM_BACKOFF_BASE", "0.5"))
LIVE_PLATFORM_MAX_RETRY_WAIT = float(os.getenv("LIVE_PLATFORM_MAX_RETRY_WAIT", "8"))
LIVE_PLATFORM_MAX_TOTAL_WAIT = float(os.getenv("LIVE_PLATFORM_MAX_TOTAL_WAIT", "15"))

LIVE_CUSTODY_BACKEND = os.getenv("LIVE_CUSTODY_BACKEND", "refuse")  # refuse | file | http
LIVE_CUSTODY_SERVICE_URL = os.getenv("LIVE_CUSTODY_SERVICE_URL", "")
LIVE_CUSTODY_SERVICE_HOST = os.getenv("LIVE_CUSTODY_SERVICE_HOST", "")
CREDENTIAL_CUSTODY_PATH = os.getenv("CREDENTIAL_CUSTODY_PATH", "")

LIVE_OAUTH_REDIRECT_ALLOWLIST = env_list("LIVE_OAUTH_REDIRECT_ALLOWLIST")
LIVE_OAUTH_RESULT_REDIRECT_URI = os.getenv("LIVE_OAUTH_RESULT_REDIRECT_URI", "")
LIVE_OAUTH_RESULT_REDIRECT_ALLOWLIST = env_list("LIVE_OAUTH_RESULT_REDIRECT_ALLOWLIST")

# Placeholder endpoints -- MUST be confirmed against official docs before use.
LIVE_SHOPEE_PARTNER_ID = os.getenv("LIVE_SHOPEE_PARTNER_ID", "")
LIVE_SHOPEE_APP_SECRET_REFERENCE = os.getenv("LIVE_SHOPEE_APP_SECRET_REFERENCE", "")
LIVE_SHOPEE_REDIRECT_URI = os.getenv("LIVE_SHOPEE_REDIRECT_URI", "")
LIVE_SHOPEE_CONTRACT_APPROVED = env_bool("LIVE_SHOPEE_CONTRACT_APPROVED", False)
LIVE_SHOPEE_AUTH_URL = os.getenv("LIVE_SHOPEE_AUTH_URL", "https://open.shopee.com/auth")
LIVE_SHOPEE_TOKEN_PATH = os.getenv("LIVE_SHOPEE_TOKEN_PATH", "REPLACE_ME_CONFIRMED_ON_EXECUTION_DAY")
LIVE_SHOPEE_REFRESH_PATH = os.getenv("LIVE_SHOPEE_REFRESH_PATH", "REPLACE_ME_CONFIRMED_ON_EXECUTION_DAY")
LIVE_SHOPEE_REVOKE_PATH = os.getenv("LIVE_SHOPEE_REVOKE_PATH", "REPLACE_ME_CONFIRMED_ON_EXECUTION_DAY")
LIVE_SHOPEE_SHOP_PATH = os.getenv("LIVE_SHOPEE_SHOP_PATH", "REPLACE_ME_CONFIRMED_ON_EXECUTION_DAY")
LIVE_SHOPEE_SIGN_SCHEME = os.getenv("LIVE_SHOPEE_SIGN_SCHEME", "v2")
LIVE_SHOPEE_DEFAULT_REGION = os.getenv("LIVE_SHOPEE_DEFAULT_REGION", "")
LIVE_SHOPEE_DEFAULT_HOST = os.getenv("LIVE_SHOPEE_DEFAULT_HOST", "REPLACE_ME_CONFIRMED_ON_EXECUTION_DAY")
LIVE_SHOPEE_API_HOSTS = {}

LIVE_TIKTOK_APP_KEY = os.getenv("LIVE_TIKTOK_APP_KEY", "")
LIVE_TIKTOK_APP_SECRET_REFERENCE = os.getenv("LIVE_TIKTOK_APP_SECRET_REFERENCE", "")
LIVE_TIKTOK_REDIRECT_URI = os.getenv("LIVE_TIKTOK_REDIRECT_URI", "")
LIVE_TIKTOK_CONTRACT_APPROVED = env_bool("LIVE_TIKTOK_CONTRACT_APPROVED", False)
LIVE_TIKTOK_SERVICE_ID = os.getenv("LIVE_TIKTOK_SERVICE_ID", "")
LIVE_TIKTOK_MARKET = os.getenv("LIVE_TIKTOK_MARKET", "ROW")
LIVE_TIKTOK_DEFAULT_AUTH_URL = os.getenv("LIVE_TIKTOK_DEFAULT_AUTH_URL", "REPLACE_ME_CONFIRMED_ON_EXECUTION_DAY")
LIVE_TIKTOK_DEFAULT_OPEN_HOST = os.getenv("LIVE_TIKTOK_DEFAULT_OPEN_HOST", "REPLACE_ME_CONFIRMED_ON_EXECUTION_DAY")
LIVE_TIKTOK_TOKEN_HOST = os.getenv("LIVE_TIKTOK_TOKEN_HOST", "https://auth.tiktok-shops.com")
LIVE_TIKTOK_AUTH_URLS = {}
LIVE_TIKTOK_OPEN_API_HOSTS = {}
LIVE_TIKTOK_TOKEN_PATH = os.getenv("LIVE_TIKTOK_TOKEN_PATH", "/api/v2/token/get")
LIVE_TIKTOK_REFRESH_PATH = os.getenv("LIVE_TIKTOK_REFRESH_PATH", "/api/v2/token/refresh")
LIVE_TIKTOK_REVOKE_PATH = os.getenv("LIVE_TIKTOK_REVOKE_PATH", "REPLACE_ME_CONFIRMED_ON_EXECUTION_DAY")
LIVE_TIKTOK_AUTHORIZED_SHOPS_PATH = os.getenv("LIVE_TIKTOK_AUTHORIZED_SHOPS_PATH", "/authorization/202309/shops")
LIVE_TIKTOK_METADATA_PATH = os.getenv("LIVE_TIKTOK_METADATA_PATH", "/seller/202309/permissions")
LIVE_TIKTOK_DEFAULT_SCOPE = os.getenv("LIVE_TIKTOK_DEFAULT_SCOPE", "")



SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "apps.tenants",
    "apps.accounts",
    "apps.permissions",
    "apps.rpa",
    "apps.integrations",
    "apps.audit",
    "apps.files",
    "apps.products",
    "apps.purchasing",
    "apps.suppliers",
    "apps.finance",
    "apps.reports",
    "apps.alerts",
    "apps.replenishment",
    "apps.configcenter",
    "apps.masterdata",
    "apps.workflows",
    "apps.governance",
    "apps.pilot",
    "apps.common",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.sqlite3"),
        "NAME": os.getenv("DB_NAME", BASE_DIR / "db.sqlite3"),
        "USER": os.getenv("DB_USER", ""),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", ""),
        "PORT": os.getenv("DB_PORT", ""),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.CustomUser"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "EXCEPTION_HANDLER": "apps.common.exceptions.custom_exception_handler",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
}

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_HEADERS = (*default_headers, "idempotency-key", "x-request-id")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
SYNC_JOB_LEASE_SECONDS = max(60, min(int(os.getenv("SYNC_JOB_LEASE_SECONDS", "900")), 3600))

# UI-P4 collaboration remains mock-only until a separate production security review.
UI_P4_COLLABORATION_MODE = os.getenv("UI_P4_COLLABORATION_MODE", "mock")
UI_P4_MOCK_WEBHOOK_SECRET = os.getenv("UI_P4_MOCK_WEBHOOK_SECRET", "not-a-real-ui-p4-secret")

# Safe default: production credential storage stays disabled unless a provider is explicitly configured.
INTEGRATION_ENCRYPTION_PROVIDER = os.getenv(
    "INTEGRATION_ENCRYPTION_PROVIDER",
    "unconfigured-production",
)
