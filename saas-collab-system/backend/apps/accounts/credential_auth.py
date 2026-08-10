"""Shared authentication checks for short-lived local UAT credentials."""

from __future__ import annotations

from datetime import datetime

from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed


UAT_USER_PREFIX = "SC-UAT-"
UAT_TENANT_PREFIX = "SC-UAT-"


def is_uat_subject(user) -> bool:
    """Return whether ``user`` is a synthetic UAT identity.

    Ordinary accounts (including existing accounts with all lease fields NULL)
    deliberately retain their previous authentication behavior.  Any identity
    carrying the frozen UAT markers is fail-closed until the credential tool
    has written a valid lease.
    """

    if user is None:
        return False
    username = str(getattr(user, "username", "") or "")
    tenant = getattr(user, "tenant", None)
    tenant_code = str(getattr(tenant, "code", "") or "")
    return username.startswith(UAT_USER_PREFIX) and tenant_code.startswith(UAT_TENANT_PREFIX)


def credential_lease_active(user, *, now: datetime | None = None) -> bool:
    """Return whether a UAT credential lease permits authentication."""

    if user is None or not bool(getattr(user, "is_active", False)):
        return False
    if not is_uat_subject(user):
        return True
    activated_at = getattr(user, "uat_credential_activated_at", None)
    expires_at = getattr(user, "uat_credential_expires_at", None)
    batch_digest = str(getattr(user, "uat_credential_batch_digest", "") or "").strip()
    lease_status = str(getattr(user, "uat_credential_status", "never") or "never").strip().lower()
    current = now or timezone.now()
    return bool(lease_status == "active" and activated_at and expires_at and batch_digest and expires_at > current)


def require_credential_lease(user, *, now: datetime | None = None) -> None:
    """Raise the standard authentication failure for an unavailable UAT lease."""

    if not credential_lease_active(user, now=now):
        if is_uat_subject(user):
            raise AuthenticationFailed("The UAT credential is expired, revoked, or not activated.")
        raise AuthenticationFailed("No active account found for the given credentials.")
