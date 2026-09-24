"""Non-debug, loopback-only profile for explicitly approved local live testing."""
import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403

DEBUG = False
approved_database = os.getenv("LOCAL_LIVE_DATABASE_NAME", "saas_collab_live_local_20260909").strip()
if not SECRET_KEY or not approved_database or DATABASES['default']['NAME'] != approved_database:
    raise ImproperlyConfigured('Local live testing requires its dedicated database and secret key.')
if DATABASES['default']['HOST'] != '127.0.0.1':
    raise ImproperlyConfigured('Local live testing cannot use a remote database.')
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
local_live_origins = env_list("LOCAL_LIVE_ALLOWED_ORIGINS")
CORS_ALLOWED_ORIGINS = local_live_origins or [
    'http://127.0.0.1:3000',
    'http://localhost:3000',
    'http://127.0.0.1:3001',
]
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS
# HTTP is restricted to this machine; custody and platform traffic require TLS.
SECURE_SSL_REDIRECT = False
UI_P4_COLLABORATION_MODE = 'disabled'
EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'
INTEGRATION_ENCRYPTION_PROVIDER = 'unconfigured-production'
CELERY_BEAT_SCHEDULE = {}
CELERY_TASK_DEFAULT_QUEUE = 'local-live-readonly'
CELERY_BROKER_CONNECTION_TIMEOUT = 2
CELERY_BROKER_TRANSPORT_OPTIONS = {'socket_connect_timeout': 2, 'socket_timeout': 2}
