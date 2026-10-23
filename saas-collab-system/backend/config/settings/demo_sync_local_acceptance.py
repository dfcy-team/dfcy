"""Explicitly selected, synthetic-only localhost MySQL acceptance profile."""
import os
from django.core.exceptions import ImproperlyConfigured
from .settlement_test import *  # noqa: F401,F403

ROLE_DATABASES = {
    "source": "saas_collab_demo_source_acceptance",
    "control": "saas_collab_sync_acceptance",
    "target": "saas_collab_demo_target_acceptance",
}
ROLE = os.environ.get("DEMO_ACCEPTANCE_ROLE", "")
if ROLE not in ROLE_DATABASES or os.environ.get("DEMO_ACCEPTANCE_CONFIRM") != "synthetic-local-only":
    raise ImproperlyConfigured("Local acceptance requires an explicit synthetic role and confirmation.")
if not os.environ.get("DEMO_ACCEPTANCE_MYSQL_PASSWORD"):
    raise ImproperlyConfigured("Local acceptance MySQL credentials are missing.")
DATABASES = {"default": {
    "ENGINE": "django.db.backends.mysql", "NAME": ROLE_DATABASES[ROLE],
    "USER": "root", "PASSWORD": os.environ["DEMO_ACCEPTANCE_MYSQL_PASSWORD"],
    "HOST": "127.0.0.1", "PORT": "13326", "OPTIONS": {"charset": "utf8mb4"},
}}
SECRET_KEY = os.environ["DEMO_ACCEPTANCE_DJANGO_KEY"]
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
CORS_ALLOWED_ORIGINS = ["http://127.0.0.1:5180"]
DEMO_SYNC_LOCAL_ACCEPTANCE = True
DEMO_DATA_SYNC_TEST_OVERRIDE = False
DEMO_DATA_SYNC_ENABLED = ROLE == "control"
DEMO_DATA_SYNC_WORKER_ENABLED = ROLE == "control"
DEMO_DATA_SYNC_SERVICE_INSTANCE = ROLE == "control"
DEMO_DATA_SYNC_IMPORT_ENABLED = ROLE == "target"
DEMO_DATA_SYNC_ARTIFACT_ROOT = os.environ.get("DEMO_ACCEPTANCE_ARTIFACT_ROOT", "")
DEMO_DATA_SYNC_ALLOWED_HOSTS = ["localhost"]
DEMO_DATA_SYNC_SOURCES = {"default": {
    "url": "https://localhost:8443",
    "tenant_id": int(os.environ.get("DEMO_ACCEPTANCE_CONTROL_TENANT", "1")),
    "client_id_env": "DEMO_SYNC_CLIENT_ID", "client_secret_env": "DEMO_SYNC_CLIENT_SECRET",
    "masking_key_env": "DEMO_SYNC_MASKING_KEY", "page_size": 1,
    "ca_bundle": os.environ.get("DEMO_ACCEPTANCE_CA_BUNDLE", ""),
}}
CELERY_BEAT_SCHEDULE = {}
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
