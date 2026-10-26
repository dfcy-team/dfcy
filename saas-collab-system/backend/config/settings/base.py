"""Base settings shared by all backend environments."""
from pathlib import Path
import os

from celery.schedules import crontab
from dotenv import load_dotenv
from corsheaders.defaults import default_headers


BASE_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BASE_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")

# The API, intranet worker and disposable import target are independent roles.
# These gates remain off unless explicitly configured for that role.
DEMO_DATA_SYNC_ENABLED = os.getenv("DEMO_DATA_SYNC_ENABLED", "false").lower() == "true"
DEMO_DATA_SYNC_WORKER_ENABLED = os.getenv("DEMO_DATA_SYNC_WORKER_ENABLED", "false").lower() == "true"
DEMO_DATA_SYNC_IMPORT_ENABLED = os.getenv("DEMO_DATA_SYNC_IMPORT_ENABLED", "false").lower() == "true"
DEMO_DATA_SYNC_ARTIFACT_ROOT = os.getenv("DEMO_DATA_SYNC_ARTIFACT_ROOT", "")
DEMO_DATA_SYNC_ALLOWED_HOSTS = [x.strip() for x in os.getenv("DEMO_DATA_SYNC_ALLOWED_HOSTS", "").split(",") if x.strip()]
DEMO_DATA_SYNC_SOURCES = {"default": {
    "url": os.getenv("DEMO_DATA_SYNC_SOURCE_URL", ""),
    "tenant_id": int(os.getenv("DEMO_DATA_SYNC_TENANT_ID", "0")),
    "client_id_env": "DEMO_SYNC_CLIENT_ID", "client_secret_env": "DEMO_SYNC_CLIENT_SECRET",
    "masking_key_env": "DEMO_SYNC_MASKING_KEY",
    "ca_bundle": os.getenv("DEMO_DATA_SYNC_CA_BUNDLE", ""),
}}


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")

# Module rollout controls.  An empty ENABLED_MODULES keeps the legacy
# all-enabled behavior; production should provide an explicit allowlist and
# local Sandbox profiles can select a development subset through
# LOCAL_SANDBOX_MODULE.
ENABLED_MODULES = env_list("ENABLED_MODULES")
LOCAL_SANDBOX_MODULE = os.getenv("LOCAL_SANDBOX_MODULE", "").strip().lower()

# Marketplace access remains fail-closed until every production control is
# explicitly configured by the operator.  These settings expose the handoff
# capability without enabling live network traffic or embedding credentials.
PLATFORM_NETWORK_MODE = os.getenv("PLATFORM_NETWORK_MODE", "")
LIVE_PLATFORM_SECURITY_APPROVED = env_bool("LIVE_PLATFORM_SECURITY_APPROVED", False)
LIVE_PLATFORM_ALLOWED_HOSTS = env_list("LIVE_PLATFORM_ALLOWED_HOSTS")
LIVE_HTTPS_PROXY_URL = os.getenv("LIVE_HTTPS_PROXY_URL", "").strip()
LIVE_TIKTOK_TOKEN_PROXY_URL = os.getenv("LIVE_TIKTOK_TOKEN_PROXY_URL", "").strip()
LIVE_TIKTOK_ADS_PROXY_URL = os.getenv("LIVE_TIKTOK_ADS_PROXY_URL", "").strip()
LIVE_PLATFORM_CONNECT_TIMEOUT = float(os.getenv("LIVE_PLATFORM_CONNECT_TIMEOUT", "3"))
LIVE_PLATFORM_READ_TIMEOUT = float(os.getenv("LIVE_PLATFORM_READ_TIMEOUT", "8"))
LIVE_PLATFORM_MAX_RETRIES = int(os.getenv("LIVE_PLATFORM_MAX_RETRIES", "2"))
LIVE_PLATFORM_BACKOFF_BASE = float(os.getenv("LIVE_PLATFORM_BACKOFF_BASE", "0.5"))
LIVE_PLATFORM_MAX_RETRY_WAIT = float(os.getenv("LIVE_PLATFORM_MAX_RETRY_WAIT", "8"))
LIVE_PLATFORM_MAX_TOTAL_WAIT = float(os.getenv("LIVE_PLATFORM_MAX_TOTAL_WAIT", "15"))
LIVE_READONLY_SYNC_ENABLED = env_bool("LIVE_READONLY_SYNC_ENABLED", False)

# RAW payloads remain inline unless an operator configures a dedicated Django
# STORAGES alias and a deployment-specific namespace for private persistent storage.
RAW_PAYLOAD_STORAGE_ALIAS = os.getenv("RAW_PAYLOAD_STORAGE_ALIAS", "").strip()
RAW_DAILY_ADS_DEDUP_ENABLED = env_bool("RAW_DAILY_ADS_DEDUP_ENABLED", False)
_raw_daily_ads_job_ids_value = os.getenv("RAW_DAILY_ADS_DEDUP_JOB_IDS", "").strip()
_raw_daily_ads_job_ids = _raw_daily_ads_job_ids_value.split(",") if _raw_daily_ads_job_ids_value else []
try:
    RAW_DAILY_ADS_DEDUP_JOB_IDS = frozenset(int(value) for value in _raw_daily_ads_job_ids)
except ValueError as exc:
    raise ValueError("RAW_DAILY_ADS_DEDUP_JOB_IDS must contain only positive integer IDs.") from exc
if any(value <= 0 for value in RAW_DAILY_ADS_DEDUP_JOB_IDS):
    raise ValueError("RAW_DAILY_ADS_DEDUP_JOB_IDS must contain only positive integer IDs.")
RAW_PAYLOAD_STORAGE_NAMESPACE = os.getenv("RAW_PAYLOAD_STORAGE_NAMESPACE", "").strip()

# Register private RAW backends only when an operator supplies a destination.
# Registration alone does not enable writes: RAW_PAYLOAD_STORAGE_ALIAS remains
# empty by default. Keep this alias configured after disabling external writes.
if os.getenv("RAW_OSS_BUCKET", "").strip() or os.getenv("RAW_LOCAL_ROOT", "").strip():
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    if os.getenv("RAW_LOCAL_ROOT", "").strip():
        STORAGES["raw_local"] = {
            "BACKEND": "apps.integrations.raw_local_storage.PrivateRawLocalStorage",
            "OPTIONS": {
                "location": os.getenv("RAW_LOCAL_ROOT", "").strip(),
                "namespace": RAW_PAYLOAD_STORAGE_NAMESPACE,
                "min_free_bytes": int(os.getenv("RAW_LOCAL_MIN_FREE_BYTES", "10737418240")),
            },
        }
    if os.getenv("RAW_OSS_BUCKET", "").strip():
        STORAGES["raw_oss"] = {
            "BACKEND": "apps.integrations.raw_oss_storage.PrivateRawOSSStorage",
            "OPTIONS": {
                "endpoint": os.getenv("RAW_OSS_ENDPOINT", "").strip(),
                "region": os.getenv("RAW_OSS_REGION", "").strip(),
                "bucket": os.getenv("RAW_OSS_BUCKET", "").strip(),
                "credential_file": os.getenv("RAW_OSS_CREDENTIAL_FILE", "").strip(),
                "namespace": RAW_PAYLOAD_STORAGE_NAMESPACE,
                "connect_timeout": float(os.getenv("RAW_OSS_CONNECT_TIMEOUT", "3")),
                "read_timeout": float(os.getenv("RAW_OSS_READ_TIMEOUT", "10")),
            },
        }

# Production execution dependencies.  Credentials are deliberately kept out
# of Django models and logs.  The file form is the preferred transport; the
# environment value remains a compatibility fallback for existing installs.
OPENAI_API_KEY_FILE = os.getenv("OPENAI_API_KEY_FILE", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_API_BASE_URL = os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini").strip()
OPENAI_CONNECT_TIMEOUT = max(1.0, min(float(os.getenv("OPENAI_CONNECT_TIMEOUT", "5")), 30.0))
OPENAI_READ_TIMEOUT = max(1.0, min(float(os.getenv("OPENAI_READ_TIMEOUT", "30")), 120.0))
OPENAI_MAX_RETRIES = max(0, min(int(os.getenv("OPENAI_MAX_RETRIES", "2")), 3))
OPENAI_RETRY_BACKOFF = max(0.0, min(float(os.getenv("OPENAI_RETRY_BACKOFF", "0.5")), 8.0))
OPENAI_MAX_INPUT_CHARS = max(256, min(int(os.getenv("OPENAI_MAX_INPUT_CHARS", "12000")), 50000))
OPENAI_MAX_OUTPUT_TOKENS = max(16, min(int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "1200")), 4000))
OPENAI_MAX_RESPONSE_BYTES = max(4096, min(int(os.getenv("OPENAI_MAX_RESPONSE_BYTES", "1048576")), 10485760))
OPENAI_ALLOW_INSECURE_FOR_TESTS = env_bool("OPENAI_ALLOW_INSECURE_FOR_TESTS", False)
# Periodic compensation closes the small post-commit/publish gap and makes a
# worker crash after claiming a job observable. These values are deliberately
# bounded so a deployment cannot silently leave work unobserved for days.
GOVERNANCE_EVALUATION_DISPATCH_STALE_SECONDS = max(
    30, min(int(os.getenv("GOVERNANCE_EVALUATION_DISPATCH_STALE_SECONDS", "60")), 3600)
)
GOVERNANCE_EVALUATION_STALE_SECONDS = max(
    300, min(int(os.getenv("GOVERNANCE_EVALUATION_STALE_SECONDS", "600")), 86400)
)
GOVERNANCE_EVALUATION_DATA_CLASSES = tuple(
    env_list("GOVERNANCE_EVALUATION_DATA_CLASSES", "public_demo")
)

# The runner URL, host allow-list and bearer token are deployment settings, not
# request fields.  In production the runner client accepts HTTPS only. Tests
# may opt into an HTTP endpoint explicitly through the test-only override.
PILOT_RUNNER_URL = os.getenv(
    "PILOT_RUNNER_URL",
    os.getenv("PILOT_EXECUTION_RUNNER_URL", ""),
).strip().rstrip("/")
PILOT_RUNNER_ALLOWED_HOSTS = env_list(
    "PILOT_RUNNER_ALLOWED_HOSTS",
    os.getenv("PILOT_EXECUTION_RUNNER_ALLOWED_HOSTS", ""),
)
PILOT_RUNNER_TOKEN_FILE = os.getenv(
    "PILOT_RUNNER_TOKEN_FILE",
    os.getenv("PILOT_EXECUTION_RUNNER_TOKEN_FILE", ""),
).strip()
PILOT_RUNNER_TOKEN = os.getenv(
    "PILOT_RUNNER_TOKEN",
    os.getenv("PILOT_EXECUTION_RUNNER_TOKEN", ""),
).strip()
PILOT_RUNNER_CA_FILE = os.getenv(
    "PILOT_RUNNER_CA_FILE",
    os.getenv("PILOT_EXECUTION_RUNNER_CA_FILE", ""),
).strip()
PILOT_RUNNER_CONNECT_TIMEOUT = max(1.0, min(float(os.getenv("PILOT_RUNNER_CONNECT_TIMEOUT", "5")), 30.0))
PILOT_RUNNER_READ_TIMEOUT = max(1.0, min(float(os.getenv("PILOT_RUNNER_READ_TIMEOUT", "30")), 120.0))
PILOT_RUNNER_MAX_RETRIES = max(0, min(int(os.getenv("PILOT_RUNNER_MAX_RETRIES", "2")), 3))
PILOT_RUNNER_RETRY_BACKOFF = max(0.0, min(float(os.getenv("PILOT_RUNNER_RETRY_BACKOFF", "0.5")), 8.0))
PILOT_RUNNER_MAX_POLLS = max(0, min(int(os.getenv("PILOT_RUNNER_MAX_POLLS", "30")), 120))
PILOT_RUNNER_POLL_INTERVAL = max(0.0, min(float(os.getenv("PILOT_RUNNER_POLL_INTERVAL", "1")), 10.0))
PILOT_RUNNER_POLL_RETRY_DELAY = max(1.0, min(float(os.getenv("PILOT_RUNNER_POLL_RETRY_DELAY", "5")), 60.0))
PILOT_RUNNER_EXECUTION_DEADLINE_SECONDS = max(60, min(int(os.getenv("PILOT_RUNNER_EXECUTION_DEADLINE_SECONDS", "3600")), 86400))
PILOT_RUNNER_MAX_TASK_RETRIES = max(1, min(int(os.getenv("PILOT_RUNNER_MAX_TASK_RETRIES", "720")), 2000))
PILOT_RUNNER_MAX_RESPONSE_BYTES = max(4096, min(int(os.getenv("PILOT_RUNNER_MAX_RESPONSE_BYTES", "1048576")), 10485760))
PILOT_RUNNER_ALLOW_INSECURE_FOR_TESTS = env_bool("PILOT_RUNNER_ALLOW_INSECURE_FOR_TESTS", False)
PILOT_EXECUTION_DISPATCH_STALE_SECONDS = max(
    30, min(int(os.getenv("PILOT_EXECUTION_DISPATCH_STALE_SECONDS", "120")), 3600)
)

# File custody is a local synthetic/test aid only.  A production process must
# explicitly use an independent HTTP custody service; the safe default is to
# refuse all secret operations.
LIVE_CUSTODY_BACKEND = os.getenv("LIVE_CUSTODY_BACKEND", "refuse").strip().lower()
LIVE_CUSTODY_SERVICE_URL = os.getenv("LIVE_CUSTODY_SERVICE_URL", "").strip()
LIVE_CUSTODY_SERVICE_HOST = os.getenv("LIVE_CUSTODY_SERVICE_HOST", "").strip()
LIVE_CUSTODY_SERVICE_TOKEN = os.getenv(
    "LIVE_CUSTODY_SERVICE_TOKEN",
    os.getenv("LIVE_CUSTODY_SERVICE_AUTH_TOKEN", ""),
).strip()
# A token file is the preferred production transport for the sidecar bearer
# credential. It is intentionally empty by default and is validated by the
# custody client before it can satisfy the live capability gate.
LIVE_CUSTODY_SERVICE_TOKEN_FILE = os.getenv(
    "LIVE_CUSTODY_SERVICE_TOKEN_FILE",
    os.getenv("LIVE_CUSTODY_SERVICE_AUTH_TOKEN_FILE", ""),
).strip()
# Optional private CA bundle for the custody endpoint. It is consulted only
# for the exact custody host/port, while platform traffic retains the system
# trust store. Keep the setting as a path, never certificate contents.
LIVE_CUSTODY_CA_FILE = os.getenv("LIVE_CUSTODY_CA_FILE", "").strip()
CREDENTIAL_CUSTODY_PATH = os.getenv(
    "CREDENTIAL_CUSTODY_PATH",
    "/var/lib/saas-collab/credentials" if DEBUG else "",
)
LIVE_OAUTH_REDIRECT_ALLOWLIST = env_list("LIVE_OAUTH_REDIRECT_ALLOWLIST")

LIVE_LAZADA_APP_KEY = os.getenv("LIVE_LAZADA_APP_KEY", "")
LIVE_LAZADA_APP_SECRET_REFERENCE = os.getenv("LIVE_LAZADA_APP_SECRET_REFERENCE", "")
LIVE_LAZADA_REDIRECT_URI = os.getenv("LIVE_LAZADA_REDIRECT_URI", "")
LIVE_LAZADA_CONTRACT_APPROVED = env_bool("LIVE_LAZADA_CONTRACT_APPROVED", False)
LIVE_LAZADA_AUTH_URL = os.getenv("LIVE_LAZADA_AUTH_URL", "https://auth.lazada.com/oauth/authorize")
LIVE_LAZADA_API_HOST = os.getenv("LIVE_LAZADA_API_HOST", "https://api.lazada.com")
LIVE_LAZADA_TOKEN_HOST = os.getenv("LIVE_LAZADA_TOKEN_HOST", "https://auth.lazada.com")
LIVE_LAZADA_TOKEN_PATH = os.getenv("LIVE_LAZADA_TOKEN_PATH", "/rest/auth/token/create")
LIVE_LAZADA_REFRESH_PATH = os.getenv("LIVE_LAZADA_REFRESH_PATH", "/rest/auth/token/refresh")
LIVE_LAZADA_ORDER_LIST_PATH = os.getenv("LIVE_LAZADA_ORDER_LIST_PATH", "/rest/orders/get")
LIVE_LAZADA_ORDER_ITEMS_PATH = os.getenv("LIVE_LAZADA_ORDER_ITEMS_PATH", "/rest/order/items/get")
LIVE_LAZADA_RETURN_LIST_PATH = os.getenv(
    "LIVE_LAZADA_RETURN_LIST_PATH", "/rest/reverse/getreverseordersforseller"
)
LIVE_LAZADA_FINANCE_TRANSACTION_PATH = os.getenv(
    "LIVE_LAZADA_FINANCE_TRANSACTION_PATH",
    "/rest/finance/transaction/details/get",
)

LIVE_SHOPEE_PARTNER_ID = os.getenv("LIVE_SHOPEE_PARTNER_ID", "")
LIVE_SHOPEE_APP_SECRET_REFERENCE = os.getenv("LIVE_SHOPEE_APP_SECRET_REFERENCE", "")
LIVE_SHOPEE_REDIRECT_URI = os.getenv("LIVE_SHOPEE_REDIRECT_URI", "")
LIVE_SHOPEE_CONTRACT_APPROVED = env_bool("LIVE_SHOPEE_CONTRACT_APPROVED", False)
LIVE_SHOPEE_PRODUCT_CONTRACT_APPROVED = env_bool("LIVE_SHOPEE_PRODUCT_CONTRACT_APPROVED", False)
LIVE_SHOPEE_AUTH_URL = os.getenv("LIVE_SHOPEE_AUTH_URL", "https://partner.shopeemobile.com/api/v2/shop/auth_partner")
LIVE_SHOPEE_TOKEN_PATH = os.getenv("LIVE_SHOPEE_TOKEN_PATH", "/api/v2/auth/token/get")
LIVE_SHOPEE_REFRESH_PATH = os.getenv("LIVE_SHOPEE_REFRESH_PATH", "/api/v2/auth/access_token/get")
LIVE_SHOPEE_REVOKE_PATH = os.getenv("LIVE_SHOPEE_REVOKE_PATH", "/api/v2/shop/cancel_auth_partner")
LIVE_SHOPEE_SHOP_PATH = os.getenv("LIVE_SHOPEE_SHOP_PATH", "/api/v2/shop/get_shop_info")
LIVE_SHOPEE_SIGN_SCHEME = os.getenv("LIVE_SHOPEE_SIGN_SCHEME", "v2")
LIVE_SHOPEE_DEFAULT_REGION = os.getenv("LIVE_SHOPEE_DEFAULT_REGION", "")
LIVE_SHOPEE_DEFAULT_HOST = os.getenv("LIVE_SHOPEE_DEFAULT_HOST", "https://partner.shopeemobile.com")
LIVE_SHOPEE_API_HOSTS = {}
LIVE_SHOPEE_ORDER_LIST_PATH = os.getenv("LIVE_SHOPEE_ORDER_LIST_PATH", "/api/v2/order/get_order_list")
LIVE_SHOPEE_ORDER_DETAIL_PATH = os.getenv("LIVE_SHOPEE_ORDER_DETAIL_PATH", "/api/v2/order/get_order_detail")
LIVE_SHOPEE_RETURN_LIST_PATH = os.getenv("LIVE_SHOPEE_RETURN_LIST_PATH", "/api/v2/returns/get_return_list")
LIVE_SHOPEE_RETURN_DETAIL_PATH = os.getenv("LIVE_SHOPEE_RETURN_DETAIL_PATH", "/api/v2/returns/get_return_detail")
LIVE_SHOPEE_PRODUCT_LIST_PATH = os.getenv("LIVE_SHOPEE_PRODUCT_LIST_PATH", "/api/v2/product/get_item_list")
LIVE_SHOPEE_PRODUCT_BASE_INFO_PATH = os.getenv("LIVE_SHOPEE_PRODUCT_BASE_INFO_PATH", "/api/v2/product/get_item_base_info")
LIVE_SHOPEE_PRODUCT_MODEL_LIST_PATH = os.getenv("LIVE_SHOPEE_PRODUCT_MODEL_LIST_PATH", "/api/v2/product/get_model_list")
LIVE_SHOPEE_FINANCE_LIST_PATH = os.getenv("LIVE_SHOPEE_FINANCE_LIST_PATH", "/api/v2/payment/get_escrow_list")
LIVE_SHOPEE_FINANCE_DETAIL_PATH = os.getenv("LIVE_SHOPEE_FINANCE_DETAIL_PATH", "/api/v2/payment/get_escrow_detail")

LIVE_TIKTOK_APP_KEY = os.getenv("LIVE_TIKTOK_APP_KEY", "")
LIVE_TIKTOK_ADS_APP_ID = os.getenv("LIVE_TIKTOK_ADS_APP_ID", "")
LIVE_TIKTOK_APP_SECRET_REFERENCE = os.getenv("LIVE_TIKTOK_APP_SECRET_REFERENCE", "")
LIVE_TIKTOK_REDIRECT_URI = os.getenv("LIVE_TIKTOK_REDIRECT_URI", "")
LIVE_TIKTOK_CONTRACT_APPROVED = env_bool("LIVE_TIKTOK_CONTRACT_APPROVED", False)
LIVE_TIKTOK_PRODUCT_CONTRACT_APPROVED = env_bool("LIVE_TIKTOK_PRODUCT_CONTRACT_APPROVED", False)
TIKTOK_OAUTH_CLEANUP_ENABLED = env_bool("TIKTOK_OAUTH_CLEANUP_ENABLED", False)
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
LIVE_TIKTOK_FINANCE_STATEMENT_PATH = os.getenv(
    "LIVE_TIKTOK_FINANCE_STATEMENT_PATH", "/finance/202309/statements"
)
LIVE_TIKTOK_FINANCE_TRANSACTION_PATH = os.getenv(
    "LIVE_TIKTOK_FINANCE_TRANSACTION_PATH",
    "/finance/202501/statements/{statement_id}/statement_transactions",
)
LIVE_TIKTOK_ORDER_LIST_PATH = os.getenv("LIVE_TIKTOK_ORDER_LIST_PATH", "/order/202309/orders/search")
LIVE_TIKTOK_ORDER_DETAIL_PATH = os.getenv("LIVE_TIKTOK_ORDER_DETAIL_PATH", "/order/202309/orders")
LIVE_TIKTOK_RETURN_LIST_PATH = os.getenv("LIVE_TIKTOK_RETURN_LIST_PATH", "/return_refund/202602/returns/search")
LIVE_TIKTOK_PRODUCT_SEARCH_PATH = os.getenv("LIVE_TIKTOK_PRODUCT_SEARCH_PATH", "/product/202502/products/search")
LIVE_TIKTOK_PRODUCT_DETAIL_PATH = os.getenv("LIVE_TIKTOK_PRODUCT_DETAIL_PATH", "/product/202309/products/{product_id}")

LIVE_JIFENG_WMS_INVENTORY_PATH = os.getenv("LIVE_JIFENG_WMS_INVENTORY_PATH", "/api/inventory/queryInventory")

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
    "apps.demo_sync",
    "apps.audit",
    "apps.files",
    "apps.products",
    "apps.development",
    "apps.listings",
    "apps.purchasing",
    "apps.supply_chain",
    "apps.packing",
    "apps.consolidation",
    "apps.shipping",
    "apps.suppliers",
    "apps.finance",
    "apps.reports",
    "apps.commerce",
    "apps.sales_management",
    "apps.alerts",
    "apps.replenishment",
    "apps.configcenter",
    "apps.masterdata",
    "apps.influencers",
    "apps.workflows",
    "apps.governance",
    "apps.pilot",
    "apps.releases",
    "apps.common",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.supply_chain.cutover.LegacySupplyWriteFence",
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
SUPPLY_CHAIN_TIME_ZONE = os.getenv("SUPPLY_CHAIN_TIME_ZONE", "Asia/Shanghai")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
REPORT_EXPORT_ROOT = Path(os.getenv("REPORT_EXPORT_ROOT", MEDIA_ROOT / "report_exports"))
REPORT_EXPORT_TTL_SECONDS = max(300, min(int(os.getenv("REPORT_EXPORT_TTL_SECONDS", "86400")), 604800))
REPORT_EXPORT_WRITE_STORAGE_ALIAS = os.getenv("REPORT_EXPORT_WRITE_STORAGE_ALIAS", "").strip()
REPORT_EXPORT_ALLOWED_STORAGE_ALIASES = ("report_exports_oss",)
# Configuring a destination never enables writes. Keep the alias readable after
# turning new writes off; existing rows retain their original storage identity.
if os.getenv("REPORT_EXPORT_OSS_BUCKET", "").strip():
    STORAGES = {**globals().get("STORAGES", {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }), "report_exports_oss": {
        "BACKEND": "apps.reports.oss_storage.PrivateReportOSSStorage",
        "OPTIONS": {
            "endpoint": os.getenv("REPORT_EXPORT_OSS_ENDPOINT", "").strip(),
            "region": os.getenv("REPORT_EXPORT_OSS_REGION", "").strip(),
            "bucket": os.getenv("REPORT_EXPORT_OSS_BUCKET", "").strip(),
            "credential_file": os.getenv("REPORT_EXPORT_OSS_CREDENTIAL_FILE", "").strip(),
            "namespace": os.getenv("REPORT_EXPORT_OSS_NAMESPACE", "exports").strip(),
        },
    }}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.CustomUser"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.accounts.authentication.UATAwareJWTAuthentication",
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
CORS_ALLOW_HEADERS = (*default_headers, "idempotency-key", "x-request-id", "x-org-membership")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
# A public login must select one application and an explicitly registered,
# same-origin callback. An unset value keeps password login as the only entry.
FEISHU_LOGIN_APP_ID = os.getenv("FEISHU_LOGIN_APP_ID", "").strip()
FEISHU_LOGIN_REDIRECT_URI = os.getenv("FEISHU_LOGIN_REDIRECT_URI", "").strip()
INTERNAL_READONLY_TRUSTED_PROXY_CIDRS = [
    item.strip() for item in os.getenv("INTERNAL_READONLY_TRUSTED_PROXY_CIDRS", "").split(",") if item.strip()
]
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
# No live egress until deployment enables this AND a channel has real pilot evidence.
SUPPLY_NOTIFICATION_DELIVERY_ENABLED = os.getenv('SUPPLY_NOTIFICATION_DELIVERY_ENABLED', 'false').lower() == 'true'
SUPPLY_NOTIFICATION_PUBLIC_BASE_URL = os.getenv('SUPPLY_NOTIFICATION_PUBLIC_BASE_URL', 'https://xtsy.dingfengchuangyu.com')
# Deployment-only rollback switch; procurement cannot enable old writes in the UI.
SUPPLY_CHAIN_LEGACY_WRITES_ENABLED = os.getenv('SUPPLY_CHAIN_LEGACY_WRITES_ENABLED', 'false').lower() == 'true'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_DEFAULT_QUEUE = "celery"
CELERY_TASK_DEFAULT_PRIORITY = 5
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_TRANSPORT_OPTIONS = {"queue_order_strategy": "round_robin", "socket_timeout": 2, "socket_connect_timeout": 2}
# The new inventory materializer is opt-in independently at both scheduling
# and execution boundaries. This also safely drains any tasks queued before a
# deployment rollback disables their schedule.
INVENTORY_DECISION_BACKGROUND_SCHEDULE_ENABLED = env_bool("INVENTORY_DECISION_BACKGROUND_SCHEDULE_ENABLED", False)
INVENTORY_DECISION_BACKGROUND_TASKS_ENABLED = env_bool("INVENTORY_DECISION_BACKGROUND_TASKS_ENABLED", False)
REPLENISHMENT_MAINTENANCE_ENABLED = env_bool("REPLENISHMENT_MAINTENANCE_ENABLED", False)
CELERY_TASK_ROUTES = {
    "apps.integrations.tasks.dispatch_due_readonly_sync_jobs": {"queue": "sync-control"},
    "apps.integrations.tasks.run_readonly_sync_job": {"queue": "sync", "priority": 5},
    "apps.integrations.tasks.refresh_due_integration_credentials": {"queue": "credential-refresh"},
}
CELERY_BEAT_SCHEDULE = {
    "purge-expired-report-analysis": {
        "task": "apps.reports.analysis_jobs.purge_analysis_jobs",
        "schedule": 300.0,
    },
    'dispatch-supply-notifications': {
        'task': 'apps.supply_chain.tasks.dispatch_notifications',
        'schedule': 5.0,
    },
    "dispatch-feishu-deliveries": {
        "task": "apps.integrations.tasks.dispatch_feishu_deliveries",
        "schedule": 60.0,
    },
    "activate-due-config-versions": {
        "task": "configcenter.activate_due_config_versions",
        "schedule": 60.0,
        "args": (),
    },
    "dispatch-daily-affiliate-order-attribution-refreshes": {
        "task": "influencers.dispatch_daily_affiliate_order_attribution_refreshes",
        # Celery runs in UTC; 19:00 UTC is 03:00 the next day in Asia/Shanghai.
        "schedule": crontab(minute=0, hour=19),
        "args": (),
    },
    "refresh-due-integration-credentials": {
        "task": "apps.integrations.tasks.refresh_due_integration_credentials",
        "schedule": 60.0,
        "options": {"queue": "credential-refresh", "expires": 55},
    },
    "refresh-country-cny-exchange-rates": {
        "task": "apps.masterdata.tasks.refresh_country_cny_exchange_rates",
        "schedule": crontab(minute=30, hour=18),
        "args": (),
    },
    "mark-overdue-sample-fulfillments": {
        "task": "influencers.mark_overdue_sample_fulfillments",
        # Celery runs in UTC; 18:00 UTC is 02:00 the next day in Asia/Shanghai.
        "schedule": crontab(minute=0, hour=18),
        "args": (),
    },
    "dispatch-due-readonly-sync-jobs": {
        "task": "apps.integrations.tasks.dispatch_due_readonly_sync_jobs",
        "schedule": 60.0,
        "args": (20,),
    },
    "dispatch-stale-governance-evaluations": {
        "task": "governance.dispatch_stale_evaluations",
        "schedule": 60.0,
        "args": (50,),
    },
    "reconcile-stale-governance-evaluations": {
        "task": "governance.reconcile_stale_evaluations",
        "schedule": 60.0,
        "args": (50,),
    },
    "dispatch-stale-pilot-executions": {
        "task": "pilot.dispatch_stale_executions",
        "schedule": 60.0,
        "args": (50,),
    },
}
if REPLENISHMENT_MAINTENANCE_ENABLED:
    CELERY_BEAT_SCHEDULE.update({
        "purge-expired-replenishment-calculations": {
            "task": "apps.supply_chain.tasks.purge_replenishment_jobs",
            "schedule": 300.0,
        },
        "recover-replenishment-calculations": {
            "task": "apps.supply_chain.tasks.recover_replenishment_jobs",
            "schedule": 60.0,
        },
    })
if INVENTORY_DECISION_BACKGROUND_SCHEDULE_ENABLED:
    CELERY_BEAT_SCHEDULE.update({
        'build-inventory-decision-views': {
            'task': 'apps.alerts.tasks.build_inventory_decision_views',
            'schedule': 5.0,
        },
        'refresh-inventory-decisions': {
            'task': 'apps.alerts.tasks.refresh_inventory_decisions',
            'schedule': 60.0,
            'args': (50,),
        },
    })
if TIKTOK_OAUTH_CLEANUP_ENABLED:
    CELERY_BEAT_SCHEDULE.update({
        "cleanup-tiktok-shop-bindings": {
            "task": "apps.integrations.tasks.cleanup_tiktok_shop_bindings",
            "schedule": 60.0,
            "options": {"queue": "credential-refresh", "expires": 55},
        },
        "cleanup-tiktok-ads-authorizations": {
            "task": "apps.integrations.tasks.cleanup_tiktok_ads_authorizations",
            "schedule": 60.0,
            "options": {"queue": "credential-refresh", "expires": 55},
        },
    })
SYNC_JOB_LEASE_SECONDS = max(60, min(int(os.getenv("SYNC_JOB_LEASE_SECONDS", "900")), 3600))
TIKTOK_SHOP_DIRECT_CALLBACK_URL = os.getenv("TIKTOK_SHOP_DIRECT_CALLBACK_URL", "").strip()
TIKTOK_ADS_DIRECT_CALLBACK_URL = os.getenv("TIKTOK_ADS_DIRECT_CALLBACK_URL", "").strip()
SYNC_JOB_MAX_RUNTIME_SECONDS = max(960, int(os.getenv("SYNC_JOB_MAX_RUNTIME_SECONDS", "960")))

# UI-P4 collaboration remains mock-only until a separate production security review.
FEISHU_SYSTEM_BASE_URL = os.getenv("FEISHU_SYSTEM_BASE_URL", "").strip().rstrip("/")
UI_P4_COLLABORATION_MODE = os.getenv("UI_P4_COLLABORATION_MODE", "mock")
UI_P4_MOCK_WEBHOOK_SECRET = os.getenv("UI_P4_MOCK_WEBHOOK_SECRET", "not-a-real-ui-p4-secret")

# Safe default: production credential storage stays disabled unless a provider is explicitly configured.
INTEGRATION_ENCRYPTION_PROVIDER = os.getenv(
    "INTEGRATION_ENCRYPTION_PROVIDER",
    "unconfigured-production",
)

# Mini Program authentication fails closed by default. The sandbox mode never
# calls WeChat and only accepts pre-bound, hashed development identities.
MINIAPP_AUTH_MODE = os.getenv("MINIAPP_AUTH_MODE", "disabled")
MINIAPP_APP_ID = os.getenv("MINIAPP_APP_ID", "")
MINIAPP_APP_SECRET = os.getenv("MINIAPP_APP_SECRET", "")
MINIAPP_PROVIDER_TIMEOUT_SECONDS = max(
    2,
    min(int(os.getenv("MINIAPP_PROVIDER_TIMEOUT_SECONDS", "8")), 15),
)

# Competitor analysis is an external, read-only dependency.  The empty URL is
# intentional: without explicit deployment configuration, report access fails
# closed rather than falling back to a local crawler or guessed endpoint.
COMPETITOR_REPORT_BASE_URL = os.getenv(
    "COMPETITOR_REPORT_BASE_URL",
    os.getenv("COMPETITOR_REPORT_API_BASE_URL", ""),
).strip().rstrip("/")
COMPETITOR_REPORT_TIMEOUT_SECONDS = max(
    1,
    min(int(os.getenv("COMPETITOR_REPORT_TIMEOUT_SECONDS", "5")), 60),
)
COMPETITOR_REPORT_API_BASE_URL = COMPETITOR_REPORT_BASE_URL
COMPETITOR_REPORT_API_TIMEOUT_SECONDS = COMPETITOR_REPORT_TIMEOUT_SECONDS

# Independent employee delegation requires both switches and explicit existing field policies.
EMPLOYEE_READONLY_ENABLED = os.getenv("EMPLOYEE_READONLY_ENABLED", "false").lower() == "true"
EMPLOYEE_READONLY_CLIENT_IDS = [value.strip() for value in os.getenv("EMPLOYEE_READONLY_CLIENT_IDS", "").split(",") if value.strip()]
EMPLOYEE_READONLY_FIELD_POLICIES = __import__("json").loads(os.getenv("EMPLOYEE_READONLY_FIELD_POLICIES", "{}"))

# Executing-plus-queued admission slots; worker concurrency is configured separately.
SYNC_DAILY_LANE_CAPACITY = os.getenv("SYNC_DAILY_LANE_CAPACITY", "2")
SYNC_HISTORY_LANE_CAPACITY = os.getenv("SYNC_HISTORY_LANE_CAPACITY", "2")

# Opt-in observed local09:00 sales snapshots; no report delivery is enabled.
SALES_NINE_SNAPSHOT_ENABLED = os.getenv("SALES_NINE_SNAPSHOT_ENABLED", "false").lower() == "true"
SALES_NINE_SNAPSHOT_STORE_IDS = [v.strip() for v in os.getenv("SALES_NINE_SNAPSHOT_STORE_IDS", "").split(",") if v.strip()]
if SALES_NINE_SNAPSHOT_ENABLED:
    CELERY_BEAT_SCHEDULE["capture-due-sales-nine"] = {
        "task": "apps.sales_management.tasks.capture_due_sales_nine", "schedule": 60.0,
    }
