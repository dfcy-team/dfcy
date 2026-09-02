"""Marketplace capability gating for real-platform connection (task A-REAL-PLATFORM-CONNECTION).

This module is the single source of truth for whether the backend is allowed to
talk to *real* Lazada / Shopee / TikTok Shop platforms.

Design rules (from the task book):
- Default capability is ``pending/mock``. The system must never perform real
  OAuth unless every gate is satisfied.
- Real (live) providers are only selectable when BOTH:
    1. ``PLATFORM_NETWORK_MODE == "approved-live-test"`` (explicit, audited), AND
    2. ``LIVE_PLATFORM_SECURITY_APPROVED`` is truthy (the dedicated security
       approval for real platform connection).
- Code never auto-marks a platform ``connected``. That decision belongs to the
  independently reviewed evidence record and is not configurable here.
"""

from pathlib import Path
import urllib.parse

from django.conf import settings

from .custody import CustodyError, resolve_service_auth_token, validate_custody_service_url

CAPABILITY_MOCK = "pending/mock"
CAPABILITY_LIVE_VALIDATION = "pending/live-validation"
CAPABILITY_CONNECTED = "connected"

LIVE_NETWORK_MODE = "approved-live-test"


def live_network_mode_enabled():
    """True only when an operator explicitly opted into the approved live test network."""
    return getattr(settings, "PLATFORM_NETWORK_MODE", "") == LIVE_NETWORK_MODE


def live_platform_security_approved():
    """True only when the dedicated real-platform security approval is on record."""
    return bool(getattr(settings, "LIVE_PLATFORM_SECURITY_APPROVED", False))


def approved_custody_configured():
    """Return whether the selected custody backend is safe for its environment.

    The filesystem adapter is intentionally restricted to the local
    development/test process.  It must never satisfy the gates for a real
    platform connection.  Live mode requires an independently operated HTTP
    custody service and a non-empty service authentication token.
    """
    backend = str(getattr(settings, "LIVE_CUSTODY_BACKEND", "refuse") or "").strip().lower()
    if backend == "http":
        service_url = str(getattr(settings, "LIVE_CUSTODY_SERVICE_URL", "") or "").strip()
        configured_host = str(getattr(settings, "LIVE_CUSTODY_SERVICE_HOST", "") or "").strip().lower()
        try:
            parsed = urllib.parse.urlparse(validate_custody_service_url(service_url))
            service_token = resolve_service_auth_token()
        except CustodyError:
            return False
        if configured_host and configured_host != str(parsed.hostname or "").lower():
            return False
        return bool(service_token)
    if backend == "file":
        # File custody can support explicit local synthetic/test operations,
        # but it is never an approved live credential boundary.
        if not bool(getattr(settings, "DEBUG", False)):
            return False
        path = str(getattr(settings, "CREDENTIAL_CUSTODY_PATH", "") or "").strip()
        return bool(path) and Path(path).is_absolute()
    return False


def live_mode_allowed():
    """All non-secret gates required before selecting a live provider."""
    return (
        live_network_mode_enabled()
        and live_platform_security_approved()
        and approved_custody_configured()
        and bool(getattr(settings, "LIVE_PLATFORM_ALLOWED_HOSTS", []))
        and not bool(getattr(settings, "DEBUG", False))
    )


def get_capability_status(platform=None):
    """Return the capability status string for a platform (or the global default).

    The function never returns ``connected``; no environment override can
    promote a platform capability.
    """
    if not live_mode_allowed():
        return CAPABILITY_MOCK
    return CAPABILITY_LIVE_VALIDATION


def require_live_mode(context="real platform connection"):
    """Raise a controlled error if live mode is not fully enabled.

    Call this at the very start of any code path that would perform a real
    platform interaction, so the system fails closed.
    """
    from .oauth_errors import OAUTH_PROVIDER_UNAVAILABLE, OAuthFlowError

    if not live_network_mode_enabled():
        raise OAuthFlowError(
            OAUTH_PROVIDER_UNAVAILABLE,
            f"Live platform interaction is disabled (PLATFORM_NETWORK_MODE is not '{LIVE_NETWORK_MODE}'). "
            f"Refusing {context}.",
        )
    if not live_platform_security_approved():
        raise OAuthFlowError(
            OAUTH_PROVIDER_UNAVAILABLE,
            "Live platform interaction requires dedicated security approval (LIVE_PLATFORM_SECURITY_APPROVED). "
            f"Refusing {context}.",
        )
    if not approved_custody_configured():
        raise OAuthFlowError(
            OAUTH_PROVIDER_UNAVAILABLE,
            "Live mode requires an authenticated independent HTTP credential custody service.",
        )
    if not getattr(settings, "LIVE_PLATFORM_ALLOWED_HOSTS", []):
        raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Live outbound host allowlist is empty.")
    if getattr(settings, "DEBUG", False):
        raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Live platform interaction is forbidden with DEBUG enabled.")
