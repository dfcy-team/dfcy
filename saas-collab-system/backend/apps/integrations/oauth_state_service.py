import hashlib
import secrets
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import OAuthStateSession, PlatformChoices, oauth_state_service_write
from .oauth_errors import (
    OAUTH_PLATFORM_MISMATCH,
    OAUTH_SESSION_MISMATCH,
    OAUTH_STATE_CONSUMED,
    OAUTH_STATE_EXPIRED,
    OAUTH_STATE_INVALID,
    raise_oauth_error,
)


ALLOWED_OAUTH_PLATFORMS = {PlatformChoices.LAZADA, PlatformChoices.SHOPEE, PlatformChoices.TIKTOK}
OAUTH_STATE_TTL = timedelta(minutes=10)
MAX_OAUTH_STATE_TTL = timedelta(minutes=30)


def oauth_state_digest(state_plaintext):
    return hashlib.sha256(str(state_plaintext or "").encode()).hexdigest()


def _session_binding(actor, state_plaintext):
    return hashlib.sha256(f"{actor.id}:{state_plaintext}".encode()).hexdigest()


def create_oauth_state(
    *,
    tenant,
    platform,
    actor,
    integration_config,
    store,
    region,
    redirect_uri,
    scopes,
    ttl=None,
):
    if platform not in ALLOWED_OAUTH_PLATFORMS:
        raise ValidationError({"platform": "OAuth start only supports Lazada, Shopee or TikTok Shop."})
    if actor.tenant_id != tenant.id:
        raise ValidationError("OAuth start actor must belong to the initiating tenant.")
    if integration_config is None or integration_config.tenant_id != tenant.id or integration_config.platform != platform:
        raise ValidationError("Integration config must match the initiating tenant and platform.")
    if store is None:
        raise ValidationError("OAuth start requires a pre-bound internal store.")
    if store.tenant_id != tenant.id:
        raise ValidationError("OAuth start store must belong to the initiating tenant.")
    if store.platform.platform_type != platform:
        raise ValidationError("OAuth start store platform must match the requested platform.")
    redirect_uri = str(redirect_uri or "").strip()
    if not redirect_uri.startswith("https://"):
        raise ValidationError({"redirect_uri": "OAuth redirect URI must be an https URL."})
    requested_ttl = ttl or OAUTH_STATE_TTL
    if requested_ttl > MAX_OAUTH_STATE_TTL:
        raise ValidationError({"ttl": "OAuth state TTL exceeds the allowed maximum."})
    state_plaintext = secrets.token_urlsafe(48)
    session = OAuthStateSession(
        tenant=tenant,
        platform=platform,
        initiated_by=actor,
        store=store,
        integration_config=integration_config,
        region=str(region).upper(),
        state_hash=oauth_state_digest(state_plaintext),
        redirect_uri=redirect_uri,
        requested_scopes=list(scopes or []),
        session_binding=_session_binding(actor, state_plaintext),
        status=OAuthStateSession.Status.PENDING,
        expires_at=timezone.now() + requested_ttl,
    )
    with oauth_state_service_write():
        session.save()
    return state_plaintext, session


def _mark_failed(session, result_code):
    with oauth_state_service_write():
        OAuthStateSession.objects.filter(pk=session.pk, status=OAuthStateSession.Status.CONSUMED).update(
            status=OAuthStateSession.Status.FAILED,
            result_code=result_code,
        )
    session.refresh_from_db()


def consume_oauth_state(state_plaintext, *, platform, redirect_uri=None):
    """Atomically consume a pending state; replay, expiry and tamper are rejected."""

    now = timezone.now()
    digest = oauth_state_digest(state_plaintext)
    with oauth_state_service_write():
        updated = OAuthStateSession.objects.filter(
            state_hash=digest,
            status=OAuthStateSession.Status.PENDING,
            expires_at__gt=now,
        ).update(status=OAuthStateSession.Status.CONSUMED, consumed_at=now)
    if not updated:
        session = OAuthStateSession.objects.filter(state_hash=digest).first()
        if session is None:
            raise_oauth_error(OAUTH_STATE_INVALID)
        if session.status == OAuthStateSession.Status.PENDING:
            raise_oauth_error(OAUTH_STATE_EXPIRED)
        raise_oauth_error(OAUTH_STATE_CONSUMED)
    session = OAuthStateSession.objects.get(state_hash=digest)
    if session.session_binding != _session_binding(session.initiated_by, state_plaintext):
        _mark_failed(session, OAUTH_SESSION_MISMATCH)
        raise_oauth_error(OAUTH_SESSION_MISMATCH)
    if session.platform != platform:
        _mark_failed(session, OAUTH_PLATFORM_MISMATCH)
        raise_oauth_error(OAUTH_PLATFORM_MISMATCH)
    if redirect_uri is not None and session.redirect_uri != str(redirect_uri):
        _mark_failed(session, OAUTH_SESSION_MISMATCH)
        raise_oauth_error(OAUTH_SESSION_MISMATCH)
    return session


def fail_oauth_state(session, result_code):
    """Record a controlled failure on a consumed session; never deletes evidence."""

    _mark_failed(session, result_code)
    return session


def expire_oauth_states(before=None):
    moment = before or timezone.now()
    with oauth_state_service_write():
        return OAuthStateSession.objects.filter(
            status=OAuthStateSession.Status.PENDING,
            expires_at__lte=moment,
        ).update(status=OAuthStateSession.Status.EXPIRED)
