"""Development settings."""
import os

from django.core.management.utils import get_random_secret_key

from .base import *  # noqa: F401,F403


DEBUG = True
SECRET_KEY = SECRET_KEY or get_random_secret_key()
ALLOWED_HOSTS = ALLOWED_HOSTS or ["localhost", "127.0.0.1"]

# Development placeholder only. Configure concrete origins in .env when needed.
CORS_ALLOWED_ORIGINS = CORS_ALLOWED_ORIGINS or [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# The reversible provider is intentionally limited to local development and tests.
INTEGRATION_ENCRYPTION_PROVIDER = os.getenv("INTEGRATION_ENCRYPTION_PROVIDER", "test-only")
