import hashlib
import json
import secrets
import time
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
    MarketplaceOAuthResourceLease,
    MarketplaceStoreAuthorization,
    PlatformIntegrationConfig,
    authorization_service_write,
    oauth_lease_write,
    oauth_service_write,
)
from .oauth_adapters import OAuthAdapterError, SyntheticCustodyGateway, SyntheticMarketplaceAdapter
from .store_authorization_service import (
    assert_operation_fence,
    create_store_authorization,
    rotate_store_authorization_references,
    transition_store_authorization,
)


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
    _require_synthetic()
    key = _action_key(request)
    key_hash = _hash(f"{actor.tenant_id}:{actor.pk}:{action}:{key}")
    fingerprint = _request_fingerprint({
        "method": request.method.upper(),
        "path": request.path,
        "action": action,
        "object_type": object_type,
        "object_id": str(object_id or ""),
        "body": payload or {},
    })
    session_hash = _session_hash(request)
    try:
        with transaction.atomic():
            existing = MarketplaceOAuthAction.objects.select_for_update().filter(
                tenant=actor.tenant,
                internal_user=actor,
                action=action,
                idempotency_key_hash=key_hash,
            ).first()
            if existing:
                if (
                    existing.request_fingerprint_hash != fingerprint
                    or existing.session_hash != session_hash
                    or existing.object_type != object_type
                    or existing.object_id != str(object_id or "")
                ):
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
        if (
            existing.request_fingerprint_hash != fingerprint
            or existing.session_hash != session_hash
            or existing.object_type != object_type
            or existing.object_id != str(object_id or "")
        ):
            raise StateConflict("The Idempotency-Key was already used for another action request.")
        return existing, True


def claim_oauth_action(action, *, lease_seconds=60, allow_recovery=False):
    _require_synthetic()
    owner = secrets.token_hex(24)
    with transaction.atomic():
        locked = MarketplaceOAuthAction.objects.select_for_update().get(pk=action.pk)
        # Recompute "now" after each blocking row lock so expiry decisions reflect the
        # moment the lock is actually held, not the moment the wait started.
        now = timezone.now()
        if locked.status == MarketplaceOAuthAction.Status.SUCCEEDED:
            return locked, False
        if not allow_recovery and locked.status in {
            MarketplaceOAuthAction.Status.FAILED,
            MarketplaceOAuthAction.Status.RECONCILE_REQUIRED,
        }:
            return locked, False
        if (
            locked.status == MarketplaceOAuthAction.Status.RUNNING
            and locked.lease_expires_at
            and locked.lease_expires_at > now
        ):
            return locked, False
        with oauth_lease_write():
            resource_lease, _created = MarketplaceOAuthResourceLease.objects.select_for_update().get_or_create(
                tenant=locked.tenant,
                object_type=locked.object_type,
                object_id=locked.object_id,
            )
        now = timezone.now()
        if (
            resource_lease.execution_owner
            and resource_lease.lease_expires_at
            and resource_lease.lease_expires_at > now
            and resource_lease.execution_owner != locked.execution_owner
        ):
            return locked, False
        resource_lease.fence_token += 1
        resource_lease.execution_owner = owner
        resource_lease.lease_expires_at = now + timedelta(seconds=lease_seconds)
        with oauth_lease_write():
            resource_lease.save(update_fields=["fence_token", "execution_owner", "lease_expires_at", "updated_at"])
        locked.status = MarketplaceOAuthAction.Status.RUNNING
        locked.execution_owner = owner
        locked.execution_fence = resource_lease.fence_token
        locked.lease_expires_at = now + timedelta(seconds=lease_seconds)
        with oauth_service_write():
            locked.save(update_fields=["status", "execution_owner", "execution_fence", "lease_expires_at", "updated_at"])
            operation = MarketplaceOAuthOperation.objects.select_for_update().get(
                operation_id_hash=locked.operation_id_hash
            )
            operation.execution_owner = owner
            operation.execution_fence = locked.execution_fence
            operation.lease_expires_at = locked.lease_expires_at
            operation.save(update_fields=["execution_owner", "execution_fence", "lease_expires_at", "updated_at"])
        return locked, True


def wait_for_oauth_action(action, *, timeout_seconds=2):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        current = MarketplaceOAuthAction.objects.get(pk=action.pk)
        if current.status in {
            MarketplaceOAuthAction.Status.SUCCEEDED,
            MarketplaceOAuthAction.Status.FAILED,
            MarketplaceOAuthAction.Status.RECONCILE_REQUIRED,
        }:
            return current
        time.sleep(0.05)
    return MarketplaceOAuthAction.objects.get(pk=action.pk)


def claim_oauth_operation(operation, *, lease_seconds=60):
    _require_synthetic()
    owner = secrets.token_hex(24)
    with transaction.atomic():
        locked = MarketplaceOAuthOperation.objects.select_for_update().get(pk=operation.pk)
        # Recompute "now" after the blocking row lock so the expiry decision reflects the
        # moment the lock is actually held, not the moment the wait started.
        now = timezone.now()
        if (
            locked.execution_owner
            and locked.lease_expires_at
            and locked.lease_expires_at > now
        ):
            return locked, False
        locked.execution_fence += 1
        locked.execution_owner = owner
        locked.lease_expires_at = now + timedelta(seconds=lease_seconds)
        with oauth_service_write():
            locked.save(update_fields=["execution_owner", "execution_fence", "lease_expires_at", "updated_at"])
        return locked, True


def _assert_operation_claim(operation, claim):
    if not claim or not claim.execution_owner:
        raise StateConflict("OAuth operation requires an active execution claim.")
    if (
        operation.execution_owner != claim.execution_owner
        or operation.execution_fence != claim.execution_fence
        or not operation.lease_expires_at
        or operation.lease_expires_at <= timezone.now()
    ):
        raise StateConflict("OAuth operation execution claim is stale.")


def _update_operation(operation_id_hash, *, claim, status=None, phase=None, error_code="", metadata=None, authorization=None, attempt=None, release=False):
    _require_synthetic()
    with transaction.atomic():
        operation = MarketplaceOAuthOperation.objects.select_for_update().get(operation_id_hash=operation_id_hash)
        _assert_operation_claim(operation, claim)
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
        if release:
            operation.execution_owner = ""
            operation.lease_expires_at = None
        with oauth_service_write():
            operation.save(update_fields=[
                "status", "phase", "last_error_code", "metadata", "authorization", "attempt",
                "execution_owner", "lease_expires_at", "updated_at"
            ])
        return operation


_OAUTH_OPERATION_TERMINAL_PHASES = {
    "initiate": "initiate_completed",
    "refresh": "refresh_completed",
    "revoke": "revoke_completed",
    "retry": "retry_completed",
    "exchange": "completed",
}
_OAUTH_OPERATION_TERMINAL_STATUSES = {
    MarketplaceOAuthOperation.Status.SUCCEEDED,
    MarketplaceOAuthOperation.Status.FAILED,
    MarketplaceOAuthOperation.Status.COMPENSATION_REQUIRED,
    MarketplaceOAuthOperation.Status.RECONCILE_REQUIRED,
}


def complete_oauth_action(action, data, *, response_status=200, authorization=None, attempt=None):
    _require_synthetic()
    with transaction.atomic():
        locked = MarketplaceOAuthAction.objects.select_for_update().get(pk=action.pk)
        if locked.status == MarketplaceOAuthAction.Status.SUCCEEDED:
            return locked
        if (
            not action.execution_owner
            or locked.execution_owner != action.execution_owner
            or locked.execution_fence != action.execution_fence
            or not locked.lease_expires_at
            or locked.lease_expires_at <= timezone.now()
        ):
            raise StateConflict("OAuth action execution claim is stale.")
        resource_lease = MarketplaceOAuthResourceLease.objects.select_for_update().get(
            tenant=locked.tenant,
            object_type=locked.object_type,
            object_id=locked.object_id,
        )
        if (
            resource_lease.execution_owner != action.execution_owner
            or resource_lease.fence_token != action.execution_fence
        ):
            raise StateConflict("OAuth resource execution claim is stale.")
        locked.status = MarketplaceOAuthAction.Status.SUCCEEDED
        locked.response_data = dict(data or {})
        locked.response_status = response_status
        locked.error_code = ""
        locked.lease_expires_at = None
        locked.execution_owner = ""
        resource_lease.execution_owner = ""
        resource_lease.lease_expires_at = None
        if authorization is not None:
            locked.authorization = authorization
        if attempt is not None:
            locked.attempt = attempt
        with oauth_service_write():
            locked.save(update_fields=[
                "status", "response_data", "response_status", "error_code", "execution_owner", "lease_expires_at", "authorization", "attempt", "updated_at"
            ])
            operation = MarketplaceOAuthOperation.objects.select_for_update().get(
                operation_id_hash=locked.operation_id_hash
            )
            _assert_operation_claim(operation, action)
            if operation.status not in _OAUTH_OPERATION_TERMINAL_STATUSES:
                operation.status = MarketplaceOAuthOperation.Status.SUCCEEDED
                operation.phase = _OAUTH_OPERATION_TERMINAL_PHASES.get(operation.action, "completed")
                if authorization is not None and operation.authorization_id is None:
                    operation.authorization = authorization
                if attempt is not None and operation.attempt_id is None:
                    operation.attempt = attempt
            operation.execution_owner = ""
            operation.lease_expires_at = None
            with oauth_service_write():
                operation.save(update_fields=[
                    "status", "phase", "authorization", "attempt",
                    "execution_owner", "lease_expires_at", "updated_at"
                ])
        with oauth_lease_write():
            resource_lease.save(update_fields=["execution_owner", "lease_expires_at", "updated_at"])
        return locked


def fail_oauth_action(action, error_code, *, reconcile=False, data=None):
    _require_synthetic()
    with transaction.atomic():
        locked = MarketplaceOAuthAction.objects.select_for_update().get(pk=action.pk)
        if locked.status == MarketplaceOAuthAction.Status.SUCCEEDED:
            return locked
        if (
            not action.execution_owner
            or locked.execution_owner != action.execution_owner
            or locked.execution_fence != action.execution_fence
            or not locked.lease_expires_at
            or locked.lease_expires_at <= timezone.now()
        ):
            raise StateConflict("OAuth action execution claim is stale.")
        resource_lease = MarketplaceOAuthResourceLease.objects.select_for_update().get(
            tenant=locked.tenant,
            object_type=locked.object_type,
            object_id=locked.object_id,
        )
        if (
            resource_lease.execution_owner != action.execution_owner
            or resource_lease.fence_token != action.execution_fence
        ):
            raise StateConflict("OAuth resource execution claim is stale.")
        locked.status = (
            MarketplaceOAuthAction.Status.RECONCILE_REQUIRED
            if reconcile
            else MarketplaceOAuthAction.Status.FAILED
        )
        locked.error_code = error_code
        locked.response_data = dict(data or {})
        locked.lease_expires_at = None
        locked.execution_owner = ""
        resource_lease.execution_owner = ""
        resource_lease.lease_expires_at = None
        with oauth_service_write():
            locked.save(update_fields=["status", "error_code", "response_data", "execution_owner", "lease_expires_at", "updated_at"])
            operation = MarketplaceOAuthOperation.objects.select_for_update().get(
                operation_id_hash=locked.operation_id_hash
            )
            _assert_operation_claim(operation, action)
            if operation.status not in _OAUTH_OPERATION_TERMINAL_STATUSES:
                operation.status = (
                    MarketplaceOAuthOperation.Status.RECONCILE_REQUIRED
                    if reconcile
                    else MarketplaceOAuthOperation.Status.FAILED
                )
                operation.phase = "action_failed"
                operation.last_error_code = error_code
            operation.execution_owner = ""
            operation.lease_expires_at = None
            with oauth_service_write():
                operation.save(update_fields=[
                    "status", "phase", "last_error_code",
                    "execution_owner", "lease_expires_at", "updated_at"
                ])
        with oauth_lease_write():
            resource_lease.save(update_fields=["execution_owner", "lease_expires_at", "updated_at"])
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
        object_type="store_target",
        object_id=store.id,
        payload=payload,
    )
    if replay:
        attempt = action.attempt
        if not attempt:
            raise StateConflict("The original OAuth initiation is still being prepared.")
        return attempt, None, False
    action, claimed = claim_oauth_action(action)
    if not claimed:
        action = wait_for_oauth_action(action)
        if action.status == MarketplaceOAuthAction.Status.SUCCEEDED and action.attempt_id:
            return action.attempt, None, False
        raise StateConflict("The OAuth initiation is already being processed.")

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
            _update_operation(operation_hash, claim=action, phase="attempt_created", attempt=attempt)
            complete_oauth_action(action, _safe_attempt_data(attempt), response_status=201, attempt=attempt)
            _audit(config, actor, "oauth_initiate", attempt=attempt, operation_id=operation_id)
    except IntegrityError as exc:
        fail_oauth_action(action, "OAUTH_INITIATE_CONFLICT")
        raise StateConflict("The OAuth initiation conflicted with another request.") from exc
    return attempt, _adapter.build_authorization_url(platform=platform, state=state, attempt_id=attempt.pk), True


def begin_callback_handoff(*, platform, state, request, lease_seconds=60):
    """Validate callback ownership, consume state, and claim its operation atomically."""
    _require_synthetic()
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
            _audit(
                attempt.integration_config,
                attempt.internal_user,
                "oauth_callback_expired",
                result=IntegrationAuditLog.Result.FAILED,
                attempt=attempt,
                error_code="OAUTH_STATE_EXPIRED",
            )
            expired = True
            operation = None
        else:
            operation_id = _operation_id()
            with oauth_service_write():
                operation = MarketplaceOAuthOperation.objects.create(
                    tenant=attempt.tenant,
                    action="exchange",
                    operation_id_hash=_operation_hash(operation_id),
                    attempt=attempt,
                    phase="callback_received",
                    execution_owner=secrets.token_hex(24),
                    execution_fence=1,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                )
                attempt.consumed_at = now
                attempt.status = MarketplaceOAuthAttempt.Status.CALLBACK_RECEIVED
                attempt.save(update_fields=["consumed_at", "status", "updated_at"])
            expired = False
    if expired:
        error = OAuthAdapterError("OAUTH_STATE_EXPIRED", 422)
        error.attempt = attempt
        raise error
    return attempt, operation


def expire_oauth_attempts(*, now=None, limit=500, exclude_state_hash=""):
    """Mark stale initiated attempts expired without deleting their audit trail."""
    _require_synthetic()
    now = now or timezone.now()
    expired_ids = list(
        MarketplaceOAuthAttempt.objects.filter(
            status=MarketplaceOAuthAttempt.Status.INITIATED,
            expires_at__lte=now,
        ).exclude(state_hash=exclude_state_hash).order_by("pk").values_list("pk", flat=True)[:limit]
    )
    for attempt_id in expired_ids:
        with transaction.atomic():
            attempt = MarketplaceOAuthAttempt.objects.select_for_update().get(pk=attempt_id)
            if attempt.status != MarketplaceOAuthAttempt.Status.INITIATED or attempt.expires_at > now:
                continue
            with oauth_service_write():
                attempt.status = MarketplaceOAuthAttempt.Status.EXPIRED
                attempt.consumed_at = attempt.consumed_at or now
                attempt.last_error_code = "OAUTH_STATE_EXPIRED"
                attempt.save(update_fields=["status", "consumed_at", "last_error_code", "updated_at"])
            _audit(
                attempt.integration_config,
                attempt.internal_user,
                "oauth_attempt_expired",
                result=IntegrationAuditLog.Result.FAILED,
                attempt=attempt,
                error_code="OAUTH_STATE_EXPIRED",
            )
    return len(expired_ids)


def fail_attempt(attempt, *, error_code, actor=None):
    _require_synthetic()
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
    _require_synthetic()
    operation_id = operation_id or _operation_id()
    with oauth_service_write():
        return MarketplaceOAuthOperation.objects.create(
            tenant=tenant,
            action=action,
            operation_id_hash=_operation_hash(operation_id),
            attempt=attempt,
            authorization=authorization,
        ), operation_id


def _set_reconcile_required(authorization, actor, error_code, operation_id=None, operation_claim=None):
    _require_synthetic()
    with transaction.atomic():
        assert_operation_fence(operation_claim)
        locked = MarketplaceStoreAuthorization.objects.select_for_update().get(pk=authorization.pk)
        locked.status = MarketplaceStoreAuthorization.Status.RECONCILE_REQUIRED
        locked.last_error_code = error_code
        locked.updated_by = actor
        with authorization_service_write():
            locked.save(update_fields=["status", "last_error_code", "updated_by", "updated_at"])
        _audit(locked.integration_config, actor, "oauth_reconcile_required", result=IntegrationAuditLog.Result.FAILED, operation_id=operation_id, error_code=error_code)
        return locked


def _safe_custody_reference(result):
    return {
        "credential_id": result["credential_id"],
        "token_id": result["token_id"],
        "credential_reference_version": int(result["credential_reference_version"]),
        "expires_at": result.get("expires_at"),
    }


def _audit_once(config, actor, action, *, attempt=None, operation_id=None):
    operation_hash = _operation_hash(operation_id) if operation_id else ""
    if IntegrationAuditLog.objects.filter(
        integration_config=config,
        action=action,
        masked_detail__operation_id_hash=operation_hash,
    ).exists():
        return None
    return _audit(config, actor, action, attempt=attempt, operation_id=operation_id)


def _complete_exchange(*, attempt, operation_claim, reference, platform_store_id):
    operation_hash = operation_claim.operation_id_hash
    operation = MarketplaceOAuthOperation.objects.get(operation_id_hash=operation_hash)
    authorization = MarketplaceStoreAuthorization.objects.filter(
        tenant=attempt.tenant,
        store=attempt.store,
        platform=attempt.platform,
    ).first()
    target_version = reference["credential_reference_version"]
    if authorization and authorization.status in {
        MarketplaceStoreAuthorization.Status.RECONCILE_REQUIRED,
        MarketplaceStoreAuthorization.Status.ERROR,
    }:
        if not (
            authorization.credential_reference_version == target_version
            and authorization.credential_id == reference["credential_id"]
            and authorization.token_id == reference["token_id"]
        ):
            target_version = max(target_version, authorization.credential_reference_version + 1)
        prepared_reference = {**reference, "credential_reference_version": target_version}
        _update_operation(
            operation_hash,
            claim=operation_claim,
            phase="reference_prepared",
            metadata={"custody_reference": prepared_reference, "platform_store_id": platform_store_id},
        )
        if not (
            authorization.credential_reference_version == target_version
            and authorization.credential_id == reference["credential_id"]
            and authorization.token_id == reference["token_id"]
        ):
            authorization = rotate_store_authorization_references(
                authorization,
                credential_id=reference["credential_id"],
                token_id=reference["token_id"],
                version=target_version,
                actor=attempt.internal_user,
                operation_claim=operation_claim,
            )
    elif authorization:
        same_reference = (
            authorization.credential_id == reference["credential_id"]
            and authorization.token_id == reference["token_id"]
        )
        if operation.authorization_id != authorization.pk and not same_reference:
            raise StateConflict("The store already has an unrelated authorization.")
    else:
        authorization = create_store_authorization(
            tenant=attempt.tenant,
            integration_config=attempt.integration_config,
            store=attempt.store,
            platform=attempt.platform,
            region=attempt.region,
            platform_store_id=platform_store_id,
            merchant_subject_id=f"synthetic-subject-{attempt.platform}-{attempt.store_id}",
            shop_cipher=f"synthetic-cipher-{attempt.store_id}" if attempt.platform == "tiktok" else "",
            credential_id=reference["credential_id"],
            token_id=reference["token_id"],
            scopes=["oauth.synthetic.read"],
            actor=attempt.internal_user,
            operation_claim=operation_claim,
        )
    _update_operation(
        operation_hash,
        claim=operation_claim,
        phase="authorization_created",
        authorization=authorization,
        metadata={"custody_reference": {**reference, "credential_reference_version": target_version}},
    )
    authorization.refresh_from_db()
    if authorization.status != MarketplaceStoreAuthorization.Status.ACTIVE:
        authorization = transition_store_authorization(
            authorization,
            target_status=MarketplaceStoreAuthorization.Status.ACTIVE,
            actor=attempt.internal_user,
            operation_claim=operation_claim,
        )
    with transaction.atomic():
        assert_operation_fence(operation_claim)
        locked = MarketplaceOAuthAttempt.objects.select_for_update().get(pk=attempt.pk)
        if locked.status != MarketplaceOAuthAttempt.Status.SUCCEEDED:
            with oauth_service_write():
                locked.status = MarketplaceOAuthAttempt.Status.SUCCEEDED
                locked.last_error_code = ""
                locked.save(update_fields=["status", "last_error_code", "updated_at"])
        _audit_once(
            locked.integration_config,
            locked.internal_user,
            "oauth_callback_succeeded",
            attempt=locked,
            operation_id=operation_hash,
        )
    _update_operation(
        operation_hash,
        claim=operation_claim,
        status=MarketplaceOAuthOperation.Status.SUCCEEDED,
        phase="completed",
        authorization=authorization,
        attempt=locked,
        release=True,
    )
    return authorization


def exchange_callback(*, attempt, callback, operation_id, operation_claim):
    _require_synthetic()
    operation_hash = _operation_hash(operation_id)
    operation = MarketplaceOAuthOperation.objects.get(operation_id_hash=operation_hash)
    _assert_operation_claim(operation, operation_claim)
    if operation.status == MarketplaceOAuthOperation.Status.SUCCEEDED and operation.authorization_id:
        return operation.authorization
    platform_store_id = callback.platform_store_id or f"synthetic-store-{attempt.store_id}"
    if platform_store_id != f"synthetic-store-{attempt.store_id}":
        raise OAuthAdapterError("OAUTH_STORE_MISMATCH", 422)
    try:
        result = _custody.exchange_and_store(
            platform=attempt.platform,
            code=callback.code,
            operation_id=operation_id,
            attempt_id=attempt.pk,
        )
    except OAuthAdapterError as exc:
        _update_operation(
            operation_hash,
            claim=operation_claim,
            status=MarketplaceOAuthOperation.Status.FAILED,
            phase="custody_failed",
            error_code=exc.error_code,
        )
        raise
    reference = _safe_custody_reference(result)
    _update_operation(
        operation_hash,
        claim=operation_claim,
        phase="custody_exchanged",
        metadata={"custody_reference": reference, "platform_store_id": platform_store_id},
    )
    try:
        return _complete_exchange(
            attempt=attempt,
            operation_claim=operation_claim,
            reference=reference,
            platform_store_id=platform_store_id,
        )
    except Exception:
        compensation = _custody.compensate_exchange(result=result, operation_id=operation_id)
        _update_operation(
            operation_hash,
            claim=operation_claim,
            status=(
                MarketplaceOAuthOperation.Status.COMPENSATION_REQUIRED
                if compensation["status"] != "revoked"
                else MarketplaceOAuthOperation.Status.FAILED
            ),
            phase="compensation",
            error_code="OAUTH_EXCHANGE_LOCAL_FAILED",
            metadata={"compensation": compensation},
        )
        raise


def refresh_authorization(*, authorization, actor, operation_id, operation_claim, scenario=""):
    _require_synthetic()
    operation_hash = _operation_hash(operation_id)
    operation = MarketplaceOAuthOperation.objects.get(operation_id_hash=operation_hash)
    _assert_operation_claim(operation, operation_claim)
    if operation.status == MarketplaceOAuthOperation.Status.SUCCEEDED:
        return operation.authorization or authorization
    reference = (operation.metadata or {}).get("custody_reference")
    if not reference:
        try:
            result = _custody.refresh_and_store(
                authorization=authorization,
                operation_id=operation_id,
                scenario=scenario,
            )
        except OAuthAdapterError as exc:
            _update_operation(
                operation_hash,
                claim=operation_claim,
                status=MarketplaceOAuthOperation.Status.FAILED,
                phase="custody_failed",
                error_code=exc.error_code,
            )
            raise
        reference = _safe_custody_reference(result)
        _update_operation(
            operation_hash,
            claim=operation_claim,
            phase="new_reference_created",
            metadata={"custody_reference": reference},
        )
    authorization.refresh_from_db()
    target_version = int(reference["credential_reference_version"])
    if not (
        authorization.credential_reference_version == target_version
        and authorization.credential_id == reference["credential_id"]
        and authorization.token_id == reference["token_id"]
    ):
        authorization = rotate_store_authorization_references(
            authorization,
            credential_id=reference["credential_id"],
            token_id=reference["token_id"],
            version=target_version,
            actor=actor,
            operation_claim=operation_claim,
        )
    _update_operation(
        operation_hash,
        claim=operation_claim,
        status=MarketplaceOAuthOperation.Status.SUCCEEDED,
        phase="completed",
        authorization=authorization,
    )
    _audit_once(authorization.integration_config, actor, "oauth_refresh", operation_id=operation_id)
    return authorization


def revoke_authorization(*, authorization, actor, operation_id, operation_claim, scenario=""):
    _require_synthetic()
    operation_hash = _operation_hash(operation_id)
    operation = MarketplaceOAuthOperation.objects.get(operation_id_hash=operation_hash)
    _assert_operation_claim(operation, operation_claim)
    if operation.status == MarketplaceOAuthOperation.Status.SUCCEEDED:
        return operation.authorization or authorization
    authorization.refresh_from_db()
    if authorization.status not in {
        MarketplaceStoreAuthorization.Status.REVOKING,
        MarketplaceStoreAuthorization.Status.RECONCILE_REQUIRED,
        MarketplaceStoreAuthorization.Status.REVOKED,
    }:
        authorization = transition_store_authorization(
            authorization,
            target_status=MarketplaceStoreAuthorization.Status.REVOKING,
            actor=actor,
            operation_claim=operation_claim,
        )
    _update_operation(
        operation_hash,
        claim=operation_claim,
        phase="local_usage_blocked",
        authorization=authorization,
    )
    if not (operation.metadata or {}).get("custody_revoked"):
        try:
            result = _custody.revoke(
                authorization=authorization,
                operation_id=operation_id,
                scenario=scenario,
            )
            if result["status"] != "revoked":
                raise OAuthAdapterError("CUSTODY_UNAVAILABLE", 503)
        except OAuthAdapterError:
            authorization = _set_reconcile_required(
                authorization,
                actor,
                "OAUTH_REVOKE_RECONCILE_REQUIRED",
                operation_id=operation_id,
                operation_claim=operation_claim,
            )
            _update_operation(
                operation_hash,
                claim=operation_claim,
                status=MarketplaceOAuthOperation.Status.RECONCILE_REQUIRED,
                phase="reconcile_required",
                error_code="OAUTH_REVOKE_RECONCILE_REQUIRED",
                authorization=authorization,
            )
            raise
        _update_operation(
            operation_hash,
            claim=operation_claim,
            phase="custody_revoked",
            metadata={"custody_revoked": True},
        )
    authorization.refresh_from_db()
    if authorization.status != MarketplaceStoreAuthorization.Status.REVOKED:
        authorization = transition_store_authorization(
            authorization,
            target_status=MarketplaceStoreAuthorization.Status.REVOKED,
            actor=actor,
            operation_claim=operation_claim,
        )
    _update_operation(
        operation_hash,
        claim=operation_claim,
        status=MarketplaceOAuthOperation.Status.SUCCEEDED,
        phase="completed",
        authorization=authorization,
    )
    _audit_once(authorization.integration_config, actor, "oauth_revoke", operation_id=operation_id)
    return authorization


def recover_oauth_operation(operation_id_hash, *, actor=None):
    """Claim and resume or compensate one durable synthetic OAuth operation."""
    _require_synthetic()
    operation = MarketplaceOAuthOperation.objects.select_related(
        "attempt", "authorization", "attempt__internal_user", "authorization__updated_by"
    ).get(operation_id_hash=operation_id_hash)
    actor = actor or (
        operation.authorization.updated_by
        if operation.authorization_id
        else operation.attempt.internal_user
        if operation.attempt_id
        else None
    )
    if actor is None or actor.tenant_id != operation.tenant_id:
        raise ValidationError("Recovery actor must belong to the operation tenant.")
    action_record = MarketplaceOAuthAction.objects.filter(
        operation_id_hash=operation.operation_id_hash
    ).first()
    if (
        action_record is not None
        and action_record.status in {
            MarketplaceOAuthAction.Status.SUCCEEDED,
            MarketplaceOAuthAction.Status.FAILED,
            MarketplaceOAuthAction.Status.RECONCILE_REQUIRED,
        }
        and operation.status not in _OAUTH_OPERATION_TERMINAL_STATUSES
    ):
        # Crash window: the action committed its terminal state but the bound operation did not.
        # Converge the operation to the action's terminal state idempotently; no business side
        # effect is repeated because every business write of this operation already committed
        # before the action terminal commit.
        converge_claim, claimed = claim_oauth_operation(operation)
        if not claimed:
            raise StateConflict("OAuth operation is already being recovered.")
        if action_record.status == MarketplaceOAuthAction.Status.SUCCEEDED:
            _update_operation(
                operation.operation_id_hash,
                claim=converge_claim,
                status=MarketplaceOAuthOperation.Status.SUCCEEDED,
                phase=_OAUTH_OPERATION_TERMINAL_PHASES.get(operation.action, "completed"),
                authorization=operation.authorization or action_record.authorization,
                attempt=operation.attempt or action_record.attempt,
                release=True,
            )
            return {"status": "succeeded", "operation_id_hash": operation.operation_id_hash}
        _update_operation(
            operation.operation_id_hash,
            claim=converge_claim,
            status=(
                MarketplaceOAuthOperation.Status.RECONCILE_REQUIRED
                if action_record.status == MarketplaceOAuthAction.Status.RECONCILE_REQUIRED
                else MarketplaceOAuthOperation.Status.FAILED
            ),
            phase="action_failed",
            error_code=action_record.error_code or "OAUTH_ACTION_FAILED",
            release=True,
        )
        return {
            "status": "compensated",
            "error_code": action_record.error_code or "OAUTH_ACTION_FAILED",
            "operation_id_hash": operation.operation_id_hash,
        }
    if operation.status == MarketplaceOAuthOperation.Status.SUCCEEDED:
        if action_record and action_record.status != MarketplaceOAuthAction.Status.SUCCEEDED:
            operation_claim, claimed = claim_oauth_action(action_record, allow_recovery=True)
            if not claimed:
                raise StateConflict("OAuth operation is already being recovered.")
            authorization = operation.authorization or action_record.authorization
            complete_oauth_action(
                operation_claim,
                {
                    "authorization_id": getattr(authorization, "pk", None),
                    "status": getattr(authorization, "status", "succeeded"),
                    "api_status": "mock",
                },
                authorization=authorization,
            )
        return {"status": "succeeded", "operation_id_hash": operation.operation_id_hash}
    if action_record:
        operation_claim, claimed = claim_oauth_action(action_record, allow_recovery=True)
        operation = MarketplaceOAuthOperation.objects.get(pk=operation.pk)
    else:
        operation_claim, claimed = claim_oauth_operation(operation)
        operation = operation_claim
    if not claimed:
        raise StateConflict("OAuth operation is already being recovered.")
    if operation.action == "exchange":
        reference = (operation.metadata or {}).get("custody_reference")
        platform_store_id = (operation.metadata or {}).get("platform_store_id")
        compensation = (operation.metadata or {}).get("compensation") or {}
        if operation.phase in {"compensation", "callback_failed"} and compensation:
            if compensation.get("status") != "revoked" and reference:
                compensation = _custody.compensate_exchange(
                    result=reference,
                    operation_id=operation.operation_id_hash,
                )
            if operation.authorization_id:
                _set_reconcile_required(
                    operation.authorization,
                    actor,
                    "OAUTH_EXCHANGE_COMPENSATED",
                    operation_id=operation.operation_id_hash,
                )
            if operation.attempt.status != MarketplaceOAuthAttempt.Status.FAILED:
                fail_attempt(operation.attempt, error_code="OAUTH_EXCHANGE_COMPENSATED", actor=actor)
            _update_operation(
                operation.operation_id_hash,
                claim=operation_claim,
                status=(
                    MarketplaceOAuthOperation.Status.FAILED
                    if compensation.get("status") == "revoked"
                    else MarketplaceOAuthOperation.Status.COMPENSATION_REQUIRED
                ),
                phase="compensated",
                error_code="OAUTH_EXCHANGE_COMPENSATED",
                metadata={"compensation": compensation},
                release=True,
            )
            return {
                "status": "compensated",
                "error_code": "OAUTH_EXCHANGE_COMPENSATED",
                "operation_id_hash": operation.operation_id_hash,
            }
        if reference and platform_store_id:
            authorization = _complete_exchange(
                attempt=operation.attempt,
                operation_claim=operation_claim,
                reference=reference,
                platform_store_id=platform_store_id,
            )
            return {
                "status": authorization.status,
                "authorization_id": authorization.pk,
                "operation_id_hash": operation.operation_id_hash,
            }
        if operation.attempt.status == MarketplaceOAuthAttempt.Status.CALLBACK_RECEIVED:
            fail_attempt(operation.attempt, error_code="OAUTH_EXCHANGE_COMPENSATED", actor=actor)
        _update_operation(
            operation.operation_id_hash,
            claim=operation_claim,
            status=MarketplaceOAuthOperation.Status.FAILED,
            phase="compensated_no_exchange",
            error_code="OAUTH_EXCHANGE_COMPENSATED",
            release=True,
        )
        return {
            "status": "compensated",
            "error_code": "OAUTH_EXCHANGE_COMPENSATED",
            "operation_id_hash": operation.operation_id_hash,
        }
    if not operation.authorization_id:
        raise StateConflict("OAuth operation has no recoverable authorization target.")
    if operation.action == MarketplaceOAuthAction.Action.REVOKE:
        updated = revoke_authorization(
            authorization=operation.authorization,
            actor=actor,
            operation_id=operation.operation_id_hash,
            operation_claim=operation_claim,
        )
    elif operation.action == MarketplaceOAuthAction.Action.REFRESH:
        updated = refresh_authorization(
            authorization=operation.authorization,
            actor=actor,
            operation_id=operation.operation_id_hash,
            operation_claim=operation_claim,
        )
    else:
        raise StateConflict("This OAuth operation has no recovery handler.")
    if action_record:
        complete_oauth_action(
            operation_claim,
            {"authorization_id": updated.pk, "status": updated.status, "api_status": "mock"},
            authorization=updated,
        )
    else:
        _update_operation(
            operation.operation_id_hash,
            claim=operation_claim,
            status=MarketplaceOAuthOperation.Status.SUCCEEDED,
            phase="completed",
            authorization=updated,
            release=True,
        )
    return {
        "status": updated.status,
        "authorization_id": updated.pk,
        "operation_id_hash": operation.operation_id_hash,
    }
