import hashlib
import json
import secrets
import threading
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.exceptions import DataScopeDenied, ScopedResourceNotFound, StateConflict
from apps.masterdata.models import StoreMaster
from apps.permissions.ui_p6_scopes import integration_values_allowed

from .models import (
    IntegrationAuditLog,
    MarketplaceOAuthAction,
    MarketplaceOAuthAttempt,
    MarketplaceOAuthOperation,
    MarketplaceStoreAuthorization,
    PlatformIntegrationConfig,
    authorization_service_write,
    oauth_service_write,
)
from .oauth_adapters import OAuthAdapterError, SyntheticCustodyGateway, SyntheticMarketplaceAdapter
from .store_authorization_service import (
    create_store_authorization,
    rotate_store_authorization_references,
    transition_store_authorization,
)


OAUTH_TTL = timedelta(minutes=5)
OAUTH_PLATFORMS = {"shopee", "tiktok"}
_adapter = SyntheticMarketplaceAdapter()
_custody = SyntheticCustodyGateway()
_STATE_VAULT = {}
_STATE_VAULT_LOCK = threading.RLock()
_ACTION_LOCK = threading.RLock()


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


def _operation_hash(operation_id):
    value = str(operation_id)
    if len(value) == 64 and all(char in "0123456789abcdef" for char in value.lower()):
        return value
    return _hash(value)


def _require_synthetic():
    if not settings.MARKETPLACE_OAUTH_SYNTHETIC_ENABLED:
        raise OAuthAdapterError("OAUTH_SYNTHETIC_DISABLED", 503)
    if settings.MARKETPLACE_OAUTH_NETWORK_ENABLED:
        raise OAuthAdapterError("OAUTH_NETWORK_DISABLED", 503)


def _vault_put(state_hash, state, expires_at):
    with _STATE_VAULT_LOCK:
        _STATE_VAULT[state_hash] = (state, expires_at)


def _vault_get(state_hash):
    with _STATE_VAULT_LOCK:
        value = _STATE_VAULT.get(state_hash)
        if not value:
            return None
        state, expires_at = value
        if expires_at <= timezone.now():
            _STATE_VAULT.pop(state_hash, None)
            return None
        return state


def _audit(config, actor, action, result=IntegrationAuditLog.Result.SUCCESS, *, attempt=None, operation_id=None, error_code=""):
    return IntegrationAuditLog.objects.create(
        tenant=config.tenant,
        integration_config=config,
        action=action,
        actor=actor,
        result=result,
        masked_detail={
            "attempt_id": getattr(attempt, "pk", None),
            "operation_id_hash": _operation_hash(operation_id) if operation_id else "",
            "error_code": error_code,
            "contract_version": getattr(attempt, "contract_version", _adapter.contract_version),
        },
    )


def _safe_attempt_data(attempt):
    return {
        "id": attempt.pk,
        "attempt_id": attempt.pk,
        "platform": attempt.platform,
        "store_id": attempt.store_id,
        "region": attempt.region,
        "redirect_target_code": attempt.redirect_target_code,
        "status": attempt.status,
        "expires_at": attempt.expires_at.isoformat(),
        "consumed_at": attempt.consumed_at.isoformat() if attempt.consumed_at else None,
        "last_error_code": attempt.last_error_code,
        "request_id": str(attempt.request_id),
        "contract_version": attempt.contract_version,
    }


def _safe_action_result(action):
    return dict(action.response_data or {})


def _action_key(request):
    key = str(request.headers.get("Idempotency-Key", "")).strip()
    if not 16 <= len(key) <= 128:
        raise ValidationError({"Idempotency-Key": "Idempotency-Key must be 16 to 128 characters."})
    return key


def begin_oauth_action(*, request, actor, action, object_type, object_id="", payload, attempt=None, authorization=None):
    """Create or lock a durable, user/session/action-scoped idempotency record."""
    key = _action_key(request)
    key_hash = _hash(f"{actor.tenant_id}:{actor.pk}:{action}:{key}")
    fingerprint = _request_fingerprint(payload)
    session_hash = _session_hash(request)
    with _ACTION_LOCK:
        try:
            with transaction.atomic():
                existing = MarketplaceOAuthAction.objects.select_for_update().filter(
                    tenant=actor.tenant,
                    internal_user=actor,
                    action=action,
                    idempotency_key_hash=key_hash,
                ).first()
                if existing:
                    if existing.request_fingerprint_hash != fingerprint or existing.session_hash != session_hash:
                        raise StateConflict("The Idempotency-Key was already used for another action request.")
                    return existing, True
                operation_id = _operation_id()
                with oauth_service_write():
                    operation = MarketplaceOAuthOperation.objects.create(
                        tenant=actor.tenant,
                        action=action,
                        operation_id_hash=_operation_hash(operation_id),
                        attempt=attempt,
                        authorization=authorization,
                    )
                    record = MarketplaceOAuthAction.objects.create(
                        tenant=actor.tenant,
                        internal_user=actor,
                        action=action,
                        object_type=object_type,
                        object_id=str(object_id or ""),
                        session_hash=session_hash,
                        idempotency_key_hash=key_hash,
                        request_fingerprint_hash=fingerprint,
                        operation_id_hash=operation.operation_id_hash,
                        attempt=attempt,
                        authorization=authorization,
                    )
                return record, False
        except IntegrityError:
            existing = MarketplaceOAuthAction.objects.get(
                tenant=actor.tenant,
                internal_user=actor,
                action=action,
                idempotency_key_hash=key_hash,
            )
            if existing.request_fingerprint_hash != fingerprint or existing.session_hash != session_hash:
                raise StateConflict("The Idempotency-Key was already used for another action request.")
            return existing, True


def _update_operation(operation_id_hash, *, status=None, phase=None, error_code="", metadata=None, authorization=None, attempt=None):
    with transaction.atomic():
        operation = MarketplaceOAuthOperation.objects.select_for_update().get(operation_id_hash=operation_id_hash)
        if status:
            operation.status = status
        if phase:
            operation.phase = phase
        if error_code:
            operation.last_error_code = error_code
        if metadata:
            operation.metadata = {**(operation.metadata or {}), **metadata}
        if authorization is not None:
            operation.authorization = authorization
        if attempt is not None:
            operation.attempt = attempt
        with oauth_service_write():
            operation.save(update_fields=[
                "status", "phase", "last_error_code", "metadata", "authorization", "attempt", "updated_at"
            ])
        return operation


def complete_oauth_action(action, data, *, response_status=200, authorization=None, attempt=None):
    with transaction.atomic():
        locked = MarketplaceOAuthAction.objects.select_for_update().get(pk=action.pk)
        if locked.status == MarketplaceOAuthAction.Status.SUCCEEDED:
            return locked
        locked.status = MarketplaceOAuthAction.Status.SUCCEEDED
        locked.response_data = dict(data or {})
        locked.response_status = response_status
        locked.error_code = ""
        if authorization is not None:
            locked.authorization = authorization
        if attempt is not None:
            locked.attempt = attempt
        with oauth_service_write():
            locked.save(update_fields=[
                "status", "response_data", "response_status", "error_code", "authorization", "attempt", "updated_at"
            ])
        return locked


def fail_oauth_action(action, error_code, *, reconcile=False, data=None):
    with transaction.atomic():
        locked = MarketplaceOAuthAction.objects.select_for_update().get(pk=action.pk)
        if locked.status == MarketplaceOAuthAction.Status.SUCCEEDED:
            return locked
        locked.status = (
            MarketplaceOAuthAction.Status.RECONCILE_REQUIRED
            if reconcile
            else MarketplaceOAuthAction.Status.FAILED
        )
        locked.error_code = error_code
        locked.response_data = dict(data or {})
        with oauth_service_write():
            locked.save(update_fields=["status", "error_code", "response_data", "updated_at"])
        return locked


def initiate_oauth(*, request, payload, actor, permission_code="integrations.store.authorize"):
    _require_synthetic()
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
        config = PlatformIntegrationConfig.objects.get(tenant=actor.tenant, pk=config_id, platform=platform)
        unscoped_store = StoreMaster.objects.select_related("platform").get(pk=store_id)
        if unscoped_store.tenant_id != actor.tenant_id:
            raise DataScopeDenied("OAuth target is outside the current tenant.", error_code="DATA_SCOPE_FORBIDDEN")
        store = StoreMaster.objects.select_related("platform").get(tenant=actor.tenant, pk=store_id)
    except PlatformIntegrationConfig.DoesNotExist as exc:
        raise ScopedResourceNotFound("Integration config does not exist in the authorized tenant scope.") from exc
    except StoreMaster.DoesNotExist as exc:
        raise ScopedResourceNotFound("Store does not exist in the authorized tenant scope.") from exc
    if store.platform.platform_type != platform:
        raise ValidationError("Store platform does not match the OAuth platform.")
    if not integration_values_allowed(actor, permission_code, platform=platform, config_id=config.id, store_id=store.id):
        raise DataScopeDenied("OAuth target is outside the authorized permission scope.", error_code="DATA_SCOPE_FORBIDDEN")

    action, replay = begin_oauth_action(
        request=request,
        actor=actor,
        action=MarketplaceOAuthAction.Action.INITIATE,
        object_type="oauth_attempt",
        payload=payload,
    )
    if replay:
        attempt = action.attempt
        if not attempt:
            raise StateConflict("The original OAuth initiation is still being prepared.")
        state = _vault_get(attempt.state_hash)
        if not state:
            raise StateConflict("The original OAuth state is no longer available; use a new Idempotency-Key.")
        return attempt, _adapter.build_authorization_url(platform=attempt.platform, state=state, attempt_id=attempt.pk), False

    # The durable action already owns an operation ID; use it as the stable gateway key.
    operation_hash = action.operation_id_hash
    operation_id = operation_hash
    now = timezone.now()
    state = secrets.token_urlsafe(32)
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
        idempotency_key_hash=_hash(f"{actor.tenant_id}:{actor.pk}:initiate:{request.headers.get('Idempotency-Key', '')}"),
        request_fingerprint_hash=_request_fingerprint(payload),
        status=MarketplaceOAuthAttempt.Status.INITIATED,
        expires_at=now + OAUTH_TTL,
        request_id=uuid.uuid4(),
        operation_id_hash=operation_hash,
    )
    try:
        with transaction.atomic():
            with oauth_service_write():
                attempt.save()
                action.attempt = attempt
                action.save(update_fields=["attempt", "updated_at"])
            _update_operation(operation_hash, phase="attempt_created", attempt=attempt)
            complete_oauth_action(action, _safe_attempt_data(attempt), response_status=201, attempt=attempt)
            _audit(config, actor, "oauth_initiate", attempt=attempt, operation_id=operation_id)
    except IntegrityError as exc:
        fail_oauth_action(action, "OAUTH_INITIATE_CONFLICT")
        raise StateConflict("The OAuth initiation conflicted with another request.") from exc
    _vault_put(attempt.state_hash, state, attempt.expires_at)
    return attempt, _adapter.build_authorization_url(platform=platform, state=state, attempt_id=attempt.pk), True


def consume_callback(*, platform, state, request):
    with transaction.atomic():
        attempt = MarketplaceOAuthAttempt.objects.select_for_update().filter(state_hash=_hash(state)).first()
        if not attempt or attempt.platform != platform:
            raise OAuthAdapterError("OAUTH_STATE_INVALID", 422)
        if attempt.session_hash != _session_hash(request, create=False):
            raise OAuthAdapterError("OAUTH_STATE_INVALID", 422)
        now = timezone.now()
        if attempt.consumed_at or attempt.status != MarketplaceOAuthAttempt.Status.INITIATED:
            raise OAuthAdapterError("OAUTH_STATE_CONSUMED", 409)
        if attempt.expires_at <= now:
            with oauth_service_write():
                attempt.consumed_at = now
                attempt.status = MarketplaceOAuthAttempt.Status.EXPIRED
                attempt.last_error_code = "OAUTH_STATE_EXPIRED"
                attempt.save(update_fields=["consumed_at", "status", "last_error_code", "updated_at"])
            expired = True
        else:
            with oauth_service_write():
                attempt.consumed_at = now
                attempt.status = MarketplaceOAuthAttempt.Status.CALLBACK_RECEIVED
                attempt.save(update_fields=["consumed_at", "status", "updated_at"])
            expired = False
    if expired:
        _audit(attempt.integration_config, attempt.internal_user, "oauth_callback_expired", result=IntegrationAuditLog.Result.FAILED, attempt=attempt, error_code="OAUTH_STATE_EXPIRED")
        raise OAuthAdapterError("OAUTH_STATE_EXPIRED", 422)
    return attempt


def fail_attempt(attempt, *, error_code, actor=None):
    with transaction.atomic():
        locked = MarketplaceOAuthAttempt.objects.select_for_update().get(pk=attempt.pk)
        if locked.status == MarketplaceOAuthAttempt.Status.EXPIRED:
            return locked
        with oauth_service_write():
            locked.status = MarketplaceOAuthAttempt.Status.FAILED
            locked.last_error_code = error_code
            locked.save(update_fields=["status", "last_error_code", "updated_at"])
        _audit(locked.integration_config, actor or locked.internal_user, "oauth_callback_failed", result=IntegrationAuditLog.Result.FAILED, attempt=locked, error_code=error_code)
    return locked


def create_oauth_operation(*, tenant, action, attempt=None, authorization=None, operation_id=None):
    operation_id = operation_id or _operation_id()
    with oauth_service_write():
        return MarketplaceOAuthOperation.objects.create(
            tenant=tenant,
            action=action,
            operation_id_hash=_operation_hash(operation_id),
            attempt=attempt,
            authorization=authorization,
        ), operation_id


def _set_reconcile_required(authorization, actor, error_code, operation_id=None):
    with transaction.atomic():
        locked = MarketplaceStoreAuthorization.objects.select_for_update().get(pk=authorization.pk)
        locked.status = MarketplaceStoreAuthorization.Status.RECONCILE_REQUIRED
        locked.last_error_code = error_code
        locked.updated_by = actor
        with authorization_service_write():
            locked.save(update_fields=["status", "last_error_code", "updated_by", "updated_at"])
        _audit(locked.integration_config, actor, "oauth_reconcile_required", result=IntegrationAuditLog.Result.FAILED, operation_id=operation_id, error_code=error_code)
        return locked


def exchange_callback(*, attempt, callback, operation_id):
    operation_hash = _operation_hash(operation_id)
    operation = MarketplaceOAuthOperation.objects.get(operation_id_hash=operation_hash)
    if operation.status == MarketplaceOAuthOperation.Status.SUCCEEDED and operation.authorization_id:
        return operation.authorization
    try:
        result = _custody.exchange_and_store(platform=attempt.platform, code=callback.code, operation_id=operation_id, attempt_id=attempt.pk)
    except OAuthAdapterError as exc:
        _update_operation(operation_hash, status=MarketplaceOAuthOperation.Status.FAILED, phase="custody_failed", error_code=exc.error_code)
        raise
    _update_operation(operation_hash, phase="custody_exchanged", metadata={"step": "custody_exchanged"})
    platform_store_id = callback.platform_store_id or f"synthetic-store-{attempt.store_id}"
    if platform_store_id != f"synthetic-store-{attempt.store_id}":
        _update_operation(operation_hash, status=MarketplaceOAuthOperation.Status.FAILED, phase="store_mismatch", error_code="OAUTH_STORE_MISMATCH")
        raise OAuthAdapterError("OAUTH_STORE_MISMATCH", 422)
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
        _update_operation(operation_hash, phase="authorization_created", authorization=authorization)
        transition_store_authorization(authorization, target_status=MarketplaceStoreAuthorization.Status.ACTIVE, actor=attempt.internal_user)
    except Exception as exc:
        compensation = _custody.compensate_exchange(result=result, operation_id=operation_id)
        reconciled = None
        if "authorization" in locals():
            reconciled = _set_reconcile_required(
                authorization,
                attempt.internal_user,
                "OAUTH_EXCHANGE_RECONCILE_REQUIRED",
                operation_id=operation_id,
            )
        op_status = (
            MarketplaceOAuthOperation.Status.COMPENSATION_REQUIRED
            if compensation["status"] != "revoked"
            else MarketplaceOAuthOperation.Status.FAILED
        )
        _update_operation(operation_hash, status=op_status, phase="compensation", error_code="OAUTH_EXCHANGE_LOCAL_FAILED", metadata={"compensation": compensation}, authorization=reconciled)
        raise exc
    with transaction.atomic():
        locked = MarketplaceOAuthAttempt.objects.select_for_update().get(pk=attempt.pk)
        with oauth_service_write():
            locked.status = MarketplaceOAuthAttempt.Status.EXCHANGED
            locked.save(update_fields=["status", "updated_at"])
            locked.status = MarketplaceOAuthAttempt.Status.SUCCEEDED
            locked.save(update_fields=["status", "updated_at"])
        _update_operation(operation_hash, status=MarketplaceOAuthOperation.Status.SUCCEEDED, phase="completed", authorization=authorization, attempt=locked)
        _audit(locked.integration_config, locked.internal_user, "oauth_callback_succeeded", attempt=locked, operation_id=operation_id)
    return authorization


def refresh_authorization(*, authorization, actor, operation_id, scenario=""):
    operation_hash = _operation_hash(operation_id)
    operation = MarketplaceOAuthOperation.objects.get(operation_id_hash=operation_hash)
    if operation.status == MarketplaceOAuthOperation.Status.SUCCEEDED:
        return operation.authorization or authorization
    try:
        result = _custody.refresh_and_store(authorization=authorization, operation_id=operation_id, scenario=scenario)
    except OAuthAdapterError as exc:
        _update_operation(operation_hash, status=MarketplaceOAuthOperation.Status.FAILED, phase="custody_failed", error_code=exc.error_code)
        raise
    _update_operation(operation_hash, phase="new_reference_created", metadata={"step": "new_reference_created"})
    try:
        updated = rotate_store_authorization_references(
            authorization,
            credential_id=result["credential_id"],
            token_id=result["token_id"],
            version=result["credential_reference_version"],
            actor=actor,
        )
    except Exception:
        compensation = _custody.compensate_refresh(result=result, operation_id=operation_id)
        updated = _set_reconcile_required(authorization, actor, "OAUTH_REFRESH_RECONCILE_REQUIRED", operation_id=operation_id)
        _update_operation(operation_hash, status=MarketplaceOAuthOperation.Status.RECONCILE_REQUIRED, phase="compensation", error_code="OAUTH_REFRESH_RECONCILE_REQUIRED", metadata={"compensation": compensation}, authorization=updated)
        raise
    _update_operation(operation_hash, status=MarketplaceOAuthOperation.Status.SUCCEEDED, phase="completed", authorization=updated)
    _audit(updated.integration_config, actor, "oauth_refresh", operation_id=operation_id)
    return updated


def revoke_authorization(*, authorization, actor, operation_id, scenario=""):
    operation_hash = _operation_hash(operation_id)
    operation = MarketplaceOAuthOperation.objects.get(operation_id_hash=operation_hash)
    if operation.status == MarketplaceOAuthOperation.Status.SUCCEEDED:
        return operation.authorization or authorization
    if authorization.status not in {MarketplaceStoreAuthorization.Status.REVOKING, MarketplaceStoreAuthorization.Status.RECONCILE_REQUIRED}:
        authorization = transition_store_authorization(authorization, target_status=MarketplaceStoreAuthorization.Status.REVOKING, actor=actor)
    _update_operation(operation_hash, phase="local_usage_blocked", authorization=authorization, metadata={"step": "local_usage_blocked"})
    try:
        result = _custody.revoke(authorization=authorization, operation_id=operation_id, scenario=scenario)
        if result["status"] != "revoked":
            raise OAuthAdapterError("CUSTODY_UNAVAILABLE", 503)
    except OAuthAdapterError:
        updated = _set_reconcile_required(authorization, actor, "OAUTH_REVOKE_RECONCILE_REQUIRED", operation_id=operation_id)
        _update_operation(operation_hash, status=MarketplaceOAuthOperation.Status.RECONCILE_REQUIRED, phase="reconcile_required", error_code="OAUTH_REVOKE_RECONCILE_REQUIRED", authorization=updated)
        raise
    try:
        updated = transition_store_authorization(authorization, target_status=MarketplaceStoreAuthorization.Status.REVOKED, actor=actor)
    except Exception as exc:
        updated = _set_reconcile_required(authorization, actor, "OAUTH_REVOKE_RECONCILE_REQUIRED", operation_id=operation_id)
        _update_operation(operation_hash, status=MarketplaceOAuthOperation.Status.RECONCILE_REQUIRED, phase="reconcile_required", error_code="OAUTH_REVOKE_RECONCILE_REQUIRED", authorization=updated)
        raise OAuthAdapterError("OAUTH_RECONCILE_REQUIRED", 503) from exc
    _update_operation(operation_hash, status=MarketplaceOAuthOperation.Status.SUCCEEDED, phase="completed", authorization=updated)
    _audit(updated.integration_config, actor, "oauth_revoke", operation_id=operation_id)
    return updated
