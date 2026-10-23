"""Dedicated disposable Demo target. Does not start or schedule platform work."""
from .dev import *  # noqa: F401,F403

LIVE_PLATFORM_SECURITY_APPROVED = False
LIVE_READONLY_SYNC_ENABLED = False
PLATFORM_NETWORK_MODE = "mock"
LIVE_CUSTODY_BACKEND = "refuse"
CELERY_BEAT_SCHEDULE = {}
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
DEMO_DATA_SYNC_WORKER_ENABLED = False
