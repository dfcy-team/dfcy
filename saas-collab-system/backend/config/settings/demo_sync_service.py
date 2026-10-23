"""Intranet control plane and worker share their own DB, never production DB."""
from django.core.exceptions import ImproperlyConfigured
from .prod import *  # noqa: F401,F403

if not str(DATABASES["default"]["NAME"]).startswith("saas_collab_sync_"):
    raise ImproperlyConfigured("The sync service requires its own saas_collab_sync_ database.")

DEMO_DATA_SYNC_SERVICE_INSTANCE = True
DEMO_DATA_SYNC_IMPORT_ENABLED = False
LIVE_PLATFORM_SECURITY_APPROVED = False
LIVE_READONLY_SYNC_ENABLED = False
PLATFORM_NETWORK_MODE = "mock"
LIVE_CUSTODY_BACKEND = "refuse"
CELERY_BEAT_SCHEDULE = {}
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
