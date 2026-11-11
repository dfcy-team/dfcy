"""Admin-only shared runtime for the disposable Demo snapshot."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .prod import *  # noqa: F401,F403


if DATABASES["default"].get("ENGINE") != "django.db.backends.mysql":
    raise ImproperlyConfigured("Shared Demo requires MySQL.")
if not str(DATABASES["default"].get("NAME", "")).startswith("saas_collab_demo_"):
    raise ImproperlyConfigured("Shared Demo requires a dedicated saas_collab_demo_ database.")


def _admin_ids(raw):
    pieces = [piece.strip() for piece in raw.split(",")]
    if not pieces or any(not piece or not piece.isdecimal() or int(piece) <= 0 for piece in pieces):
        raise ImproperlyConfigured("DEMO_SHARED_ADMIN_IDS must be a non-empty comma-separated list of positive IDs.")
    ids = [int(piece) for piece in pieces]
    if len(ids) != len(set(ids)):
        raise ImproperlyConfigured("DEMO_SHARED_ADMIN_IDS must not contain duplicate IDs.")
    return frozenset(ids)


DEMO_SHARED_ADMIN_IDS = _admin_ids(os.getenv("DEMO_SHARED_ADMIN_IDS", ""))
DEMO_SHARED_SNAPSHOT_INSTANCE = True
DEMO_SHARED_ADMIN_ONLY = True
STATIC_ROOT = Path(os.getenv("STATIC_ROOT", BASE_DIR / "staticfiles")).resolve()

_maintenance_raw = os.getenv("DEMO_SHARED_MAINTENANCE_FILE", "").strip()
_maintenance_path = Path(_maintenance_raw)
if not _maintenance_raw or not _maintenance_path.is_absolute():
    raise ImproperlyConfigured("DEMO_SHARED_MAINTENANCE_FILE must be an absolute path.")

# Reject symlinked components, including the marker itself, so an operator
# cannot silently redirect the runtime gate through a mutable link.
_walk = Path(_maintenance_path.anchor)
for _part in _maintenance_path.parts[1:]:
    _walk = _walk / _part
    if _walk.is_symlink():
        raise ImproperlyConfigured("DEMO_SHARED_MAINTENANCE_FILE cannot contain symlink components.")

_resolved_maintenance_path = _maintenance_path.resolve(strict=False)
for _protected_root in (Path(MEDIA_ROOT), STATIC_ROOT):
    _resolved_root = _protected_root.resolve(strict=False)
    try:
        _resolved_maintenance_path.relative_to(_resolved_root)
    except ValueError:
        continue
    raise ImproperlyConfigured("DEMO_SHARED_MAINTENANCE_FILE must be outside media and static roots.")
DEMO_SHARED_MAINTENANCE_FILE = str(_maintenance_path)

MIDDLEWARE = [
    *MIDDLEWARE[:MIDDLEWARE.index("django.contrib.auth.middleware.AuthenticationMiddleware") + 1],
    "apps.demo_sync.shared_middleware.SharedDemoGateMiddleware",
    *MIDDLEWARE[MIDDLEWARE.index("django.contrib.auth.middleware.AuthenticationMiddleware") + 1:],
]

LIVE_PLATFORM_SECURITY_APPROVED = False
LIVE_READONLY_SYNC_ENABLED = False
PLATFORM_NETWORK_MODE = "mock"
LIVE_CUSTODY_BACKEND = "refuse"
CELERY_BEAT_SCHEDULE = {}
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
DEMO_DATA_SYNC_ENABLED = False
DEMO_DATA_SYNC_WORKER_ENABLED = False
DEMO_DATA_SYNC_IMPORT_ENABLED = False
DEMO_DATA_SYNC_SERVICE_INSTANCE = False
DEMO_LOCAL_UPDATE_ENABLED = False
