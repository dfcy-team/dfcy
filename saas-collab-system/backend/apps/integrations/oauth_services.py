import hashlib
import json
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.exceptions import DataScopeDenied, ScopedResourceNotFound, StateConflict
from apps.masterdata.models import StoreMaster
from apps.permissions.ui_p6_scopes import integration_values_allowed

from .models import (
    IntegrationAuditLog,
    MarketplaceOAuthAttempt,
    MarketplaceStoreAuthorization,
    PlatformIntegrationConfig,
    oauth_service_write,
)
from .oauth_adapters import OAuthAdapterError, SyntheticCustodyGateway, SyntheticMarketplaceAdapter
from .store_authorization_service import create_store_authorization, rotate_store_authorization_references, transition_store_authorization


OAUTH_TTL = timedelta(minutes=5)
OAUTH_PLATFORMS = {"shopee", "tiktok"}
_adapter = SyntheticMarketplaceAdapter()
_custody = SyntheticCustodyGateway()


def _hash(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def _request_fingerprint(payload):
    return _hash(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _session_hash(request, *, create=True):
    if not request.session.session_key and create:
        request.session.create()
    return _hash(request.session.session_key or "")


def _operation_id():
    return str(uuid.uuid4())


def _audit(config, actor, action, result=IntegrationAuditLog.Result.SUCCESS, *, attempt=None, operation_id=None, error_code=""):
    return IntegrationAuditLog.objects.create(
        tenant=config.tenant,
        integration_config=config,
        action=action,
        actor=actor,
        result=result,
        masked_detail={
            "attempt_id": getattr(attempt, "pk", None),
            "operation_id_hash": _hash(operation_id) if operation_id else "",
            "error_code": error_code,
            "contract_version": getattr(attempt, "contract_version", _adapter.contract_version),
        },
    )


def _cached_authorization_url(attempt):
    return cache.get(f"oauth-url:{attempt.idempotency_key_hash}")


def initiate_oauth(*, request, payload, actor, permission_code="integrations.store.authorize"):
    if settings.MARKETPLACE_OAUTH_NETWORK_ENABLED:
        raise ValidationError("Real marketplace OAuth network is disabled until A2-00 approval.")
    allowed = {"integration_config_id", "store_id", "platform", "region", "redirect_target_code"}
    if set(payload) - allowed or set(payload) != allowed:
        raise ValidationError("OAuth initiate fields must match the frozen contract.")
    platform = str(payload["platform"]).lower()
    if platform not in OAUTH_PLATFORMS:
        raise ValidationError({"platform": "Only Shopee and TikTok Shop are supported."})
    region = str(payload["region"]).upper()
    if not region.isascii() or not 2 <= len(region) <= 8 or not region.replace("-", "").isalnum():
        raise ValidationError({"region": "Region must be a short ASCII country or region code."})
    redirect_code = str(payload["redirect_target_code"])
    if redirect_code not in settings.MARKETPLACE_OAUTH_REDIRECT_TARGETS:
        raise ValidationError({"redirect_target_code": "Redirect target is not allowlisted."})
    try:
        config_id = int(payload["integration_config_id"])
        store_id = int(payload["store_id"])
    except (ValueError, TypeError):
        raise ValidationError("Integration config and store IDs must be positive integers.")
    try:
        config = PlatformIntegrationConfig.objects.get(
            tenant=actor.tenant,
            pk=config_id,
            platform=platform,
        )
        unscoped_store = StoreMaster.objects.select_related("platform").get(pk=store_id)
        if unscoped_store.tenant_id != actor.tenant_id:
            raise DataScopeDenied("OAuth target is outside the current tenant.", error_code="DATA_SCOPE_FORBIDDEN")
        store = StoreMaster.objects.select_related("platform").get(
            tenant=actor.tenant,
            pk=store_id,
        )
    except PlatformIntegrationConfig.DoesNotExist as exc:
        raise ScopedResourceNotFound("Integration config does not exist in the authorized tenant scope.") from exc
    except StoreMaster.DoesNotExist as exc:
        raise ScopedResourceNotFound("Store does not exist in the authorized tenant scope.") from exc
    if store.platform.platform_type != platform:
        raise ValidationError("Store platform does not match the OAuth platform.")
    if not integration_values_allowed(
        actor,
        permission_code,
        platform=platform,
        config_id=config.id,
        store_id=store.id,
    ):
        from apps.common.error_codes import ErrorCode
        from apps.common.exceptions import DataScopeDenied

        raise DataScopeDenied("OAuth target is outside the authorized permission scope.", error_code=ErrorCode.DATA_SCOPE_FORBIDDEN)

    idempotency_key = str(request.headers.get("Idempotency-Key", "")).strip()
    if not 16 <= len(idempotency_key) <= 128:
        raise ValidationError({"Idempotency-Key": "Idempotency-Key must be 16 to 128 characters."})
    idem_hash = _hash(f"{actor.tenant_id}:{idempotency_key}")
    fingerprint = _request_fingerprint(payload)
    existing = MarketplaceOAuthAttempt.objects.filter(
        tenant=actor.tenant,
        idempotency_key_hash=idem_hash,
    ).first()
    if existing:
        if existing.request_fingerprint_hash != fingerprint:
            raise StateConflict("The Idempotency-Key was already used for another OAuth request.")
        cached_url = _cached_authorization_url(existing)
        if not cached_url:
            raise StateConflict("The original OAuth initiation result is no longer available for replay.")
        return existing, cached_url, False

    state = secrets.token_urlsafe(32)
    operation_id = _operation_id()
    now = timezone.now()
    attempt = MarketplaceOAuthAttempt(
        tenant=actor.tenant,
        internal_user=actor,
        session_hash=_session_hash(request),
        platform=platform,
        integration_config=config,
        store=store,
        region=region,
        redirect_target_code=redirect_code,
        state_hash=_hash(state),
        idempotency_key_hash=idem_hash,
        request_fingerprint_hash=fingerprint,
        status=MarketplaceOAuthAttempt.Status.INITIATED,
        expires_at=now + OAUTH_TTL,
        request_id=uuid.uuid4(),
        operation_id_hash=_hash(operation_id),
    )
    try:
        with oauth_service_write():
            attempt.save()
    except IntegrityError as exc:
        raise StateConflict("The OAuth initiation conflicted with another request.") from exc
    authorization_url = _adapter.build_authorization_url(
        platform=platform,
        state=state,
        attempt_id=attempt.pk,
    )
    cache.set(f"oauth-url:{idem_hash}", authorization_url, timeout=int(OAUTH_TTL.total_seconds()))
    _audit(config, actor, "oauth_initiate", attempt=attempt, operation_id=operation_id)
    return attempt, authorization_url, True


@transaction.atomic
def consume_callback(*, platform, state, request):
    attempt = MarketplaceOAuthAttempt.objects.select_for_update().filter(state_hash=_hash(state)).first()
    if not attempt or attempt.platform != platform:
        raise OAuthAdapterError("OAUTH_STATE_INVALID", 422)
    now = timezone.now()
    if attempt.consumed_at or attempt.status != MarketplaceOAuthAttempt.Status.INITIATED:
        raise OAuthAdapterError("OAUTH_STATE_CONSUMED", 409)
    with oauth_service_write():
        attempt.consumed_at = now
        attempt.status = MarketplaceOAuthAttempt.Status.CALLBACK_RECEIVED
        attempt.save(update_fields=["consumed_at", "status", "updated_at"])
    if attempt.expires_at <= now:
        with oauth_service_write():
            attempt.status = MarketplaceOAuthAttempt.Status.EXPIRED
            attempt.last_error_code = "OAUTH_STATE_EXPIRED"
            attempt.save(update_fields=["status", "last_error_code", "updated_at"])
        raise OAuthAdapterError("OAUTH_STATE_EXPIRED", 422)
    if attempt.session_hash != _session_hash(request, create=False):
        raise OAuthAdapterError("OAUTH_STATE_INVALID", 422)
    return attempt


def fail_attempt(attempt, *, error_code, actor=None):
    with transaction.atomic():
        locked = MarketplaceOAuthAttempt.objects.select_for_update().get(pk=attempt.pk)
        with oauth_service_write():
            locked.status = MarketplaceOAuthAttempt.Status.FAILED
            locked.last_error_code = error_code
            locked.save(update_fields=["status", "last_error_code", "updated_at"])
        _audit(locked.integration_config, actor or locked.internal_user, "oauth_callback_failed", result=IntegrationAuditLog.Result.FAILED, attempt=locked, error_code=error_code)
    return locked


def exchange_callback(*, attempt, callback, operation_id):
    result = _custody.exchange_and_store(
        platform=attempt.platform,
        code=callback.code,
        operation_id=operation_id,
        attempt_id=attempt.pk,
    )
    platform_store_id = callback.platform_store_id or f"synthetic-store-{attempt.store_id}"
    merchant_subject_id = f"synthetic-subject-{attempt.platform}-{attempt.store_id}"
    shop_cipher = f"synthetic-cipher-{attempt.store_id}" if attempt.platform == "tiktok" else ""
    try:
        authorization = create_store_authorization(
            tenant=attempt.tenant,
            integration_config=attempt.integration_config,
            store=attempt.store,
            platform=attempt.platform,
            region=attempt.region,
            platform_store_id=platform_store_id,
            merchant_subject_id=merchant_subject_id,
            shop_cipher=shop_cipher,
            credential_id=result["credential_id"],
            token_id=result["token_id"],
            scopes=["oauth.synthetic.read"],
            actor=attempt.internal_user,
        )
        transition_store_authorization(
            authorization,
            target_status=MarketplaceStoreAuthorization.Status.ACTIVE,
            actor=attempt.internal_user,
        )
    except IntegrityError as exc:
        raise StateConflict("The store authorization already exists or conflicts with another request.") from exc
    with transaction.atomic():
        locked = MarketplaceOAuthAttempt.objects.select_for_update().get(pk=attempt.pk)
        with oauth_service_write():
            locked.status = MarketplaceOAuthAttempt.Status.EXCHANGED
            locked.save(update_fields=["status", "updated_at"])
            locked.status = MarketplaceOAuthAttempt.Status.SUCCEEDED
            locked.save(update_fields=["status", "updated_at"])
        _audit(locked.integration_config, locked.internal_user, "oauth_callback_succeeded", attempt=locked, operation_id=operation_id)
    return authorization


def refresh_authorization(*, authorization, actor, scenario=""):
    operation_id = _operation_id()
    result = _custody.refresh_and_store(authorization=authorization, operation_id=operation_id, scenario=scenario)
    updated = rotate_store_authorization_references(
        authorization,
        credential_id=result["credential_id"],
        token_id=result["token_id"],
        version=result["credential_reference_version"],
        actor=actor,
    )
    _audit(updated.integration_config, actor, "oauth_refresh", operation_id=operation_id)
    return updated


def revoke_authorization(*, authorization, actor, scenario=""):
    operation_id = _operation_id()
    result = _custody.revoke(authorization=authorization, operation_id=operation_id, scenario=scenario)
    if result["status"] != "revoked":
        raise OAuthAdapterError("CUSTODY_UNAVAILABLE", 503)
    updated = transition_store_authorization(
        authorization,
        target_status=MarketplaceStoreAuthorization.Status.REVOKED,
        actor=actor,
    )
    _audit(updated.integration_config, actor, "oauth_revoke", operation_id=operation_id)
    return updated
