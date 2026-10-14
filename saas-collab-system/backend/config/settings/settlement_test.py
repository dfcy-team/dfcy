"""Synthetic settlement tests only; no credentials, database server or broker."""

from .base import *  # noqa: F401,F403

DEBUG = False
SECRET_KEY = "synthetic-settlement-tests-not-a-production-key"
ALLOWED_HOSTS = ["testserver", "localhost"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:",
                         "TEST": {"NAME": ":memory:"}}}
PLATFORM_NETWORK_MODE = "mock"
LIVE_PLATFORM_SECURITY_APPROVED = False
LIVE_READONLY_SYNC_ENABLED = False
LIVE_CUSTODY_BACKEND = "refuse"
INTEGRATION_ENCRYPTION_PROVIDER = "test-only"
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
CELERY_TASK_ALWAYS_EAGER = False
MEDIA_ROOT = "/tmp/settlement-test-media"
