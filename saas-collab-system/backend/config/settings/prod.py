"""Production settings."""
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403


DEBUG = False

if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set in production.")

if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must be set in production.")
