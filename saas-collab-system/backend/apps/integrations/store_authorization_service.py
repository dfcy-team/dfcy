import re

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.exceptions import StateConflict

from .credential_service import _revoke_old_references, build_reference_metadata, revoke_synthetic_references
from .models import (
    IntegrationAuditLog,
    MarketplaceOAuthOperation,
    MarketplaceStoreAuthorization,
    authorization_service_write,
    marketplace_identity_key,
)


ALLOWED_TRANSITIONS = {
    MarketplaceStoreAuthorization.Status.PENDING: {
        MarketplaceStoreAuthorization.Status.ACTIVE,
        MarketplaceStoreAuthorization.Status.REVOKING,
        MarketplaceStoreAuthorization.Status.REVOKED,
        MarketplaceStoreAuthorization.Status.ERROR,
    },
    MarketplaceStoreAuthorization.Status.ACTIVE: {
        MarketplaceStoreAuthorization.Status.EXPIRED,
        MarketplaceStoreAuthorization.Status.REVOKING,
        MarketplaceStoreAuthorization.Status.REVOKED,
        MarketplaceStoreAuthorization.Status.RECONCILE_REQUIRED,
        MarketplaceStoreAuthorization.Status.ERROR,
    },
    MarketplaceStoreAuthorization.Status.REVOKING: {
        MarketplaceStoreAuthorization.Status.REVOKED,
        MarketplaceStoreAuthorization.Status.RECONCILE_REQUIRED,
        MarketplaceStoreAuthorization.Status.ERROR,
    },
    MarketplaceStoreAuthorization.Status.EXPIRED: {
        MarketplaceStoreAuthorization.Status.ACTIVE,
        MarketplaceStoreAuthorization.Status.REVOKED,
        MarketplaceStoreAuthorization.Status.ERROR,
    },
    MarketplaceStoreAuthorization.Status.ERROR: {
        MarketplaceStoreAuthorization.Status.ACTIVE,
        MarketplaceStoreAuthorization.Status.REVOKED,
        MarketplaceStoreAuthorization.Status.EXPIRED,
        MarketplaceStoreAuthorization.Status.RECONCILE_REQUIRED,
    },
    MarketplaceStoreAuthorization.Status.RECONCILE_REQUIRED: {
        MarketplaceStoreAuthorization.Status.REVOKING,
        MarketplaceStoreAuthorization.Status.ACTIVE,
        MarketplaceStoreAuthorization.Status.REVOKED,
        MarketplaceStoreAuthorization.Status.ERROR,
    },
    MarketplaceStoreAuthorization.Status.REVOKED: set(),
}


def _validate_actor_tenant(actor, tenant_id):
    if actor.tenant_id != tenant_id:
        raise ValidationError("Authorization actor must belong to the authorization tenant.")


def assert_operation_fence(operation_claim):
    """Fail closed unless the OAuth execution claim still owns the durable operation fence.

    Must run inside the caller's transaction so the operation row lock is held until the
    fenced business write commits; after a takeover the old owner sees the bumped fence
    or owner change and performs zero business writes.
    """
    if operation_claim is None:
        return
    if not getattr(operation_claim, "execution_owner", "") or not getattr(operation_claim, "operation_id_hash", ""):
        raise StateConflict("OAuth operation requires an active execution claim.")
    locked = MarketplaceOAuthOperation.objects.select_for_update().get(
        operation_id_hash=operation_claim.operation_id_hash
    )
    if (
        locked.execution_owner != operation_claim.execution_owner
        or locked.execution_fence != operation_claim.execution_fence
        or not locked.lease_expires_at
        or locked.lease_expires_at <= timezone.now()
    ):
        raise StateConflict("OAuth operation execution claim is stale.")


def _audit(record, actor, action, result=IntegrationAuditLog.Result.SUCCESS, extra=None):
    detail = {
        "credential_id": record.credential_id,
        "token_id": record.token_id,
        "credential_mask": record.credential_mask,
        "status": record.status,
        "error_code": record.last_error_code,
        "reference_version": record.credential_reference_version,
    }
    detail.update(extra or {})
    return IntegrationAuditLog.objects.create(
        tenant=record.tenant,
        integration_config=record.integration_config,
        store_authorization=record,
        action=action,
        actor=actor,
        result=result,
        masked_detail=detail,
    )


@transaction.atomic
def create_store_authorization(
    *,
    tenant,
    integration_config,
    store,
    platform,
    region,
    platform_store_id,
    merchant_subject_id,
    shop_cipher,
    credential_id,
    token_id,
    scopes,
    actor,
    operation_claim=None,
):
    _validate_actor_tenant(actor, tenant.id)
    assert_operation_fence(operation_claim)
    metadata = build_reference_metadata(credential_id, token_id, 1)
    identity_key = marketplace_identity_key(platform, region, platform_store_id)
    if MarketplaceStoreAuthorization.objects.filter(
        platform=platform,
        platform_identity_key=identity_key,
    ).exists():
        raise StateConflict("The platform store is already bound in an authorized tenant scope.")
    record = MarketplaceStoreAuthorization(
        tenant=tenant,
        integration_config=integration_config,
        store=store,
        platform=platform,
        region=str(region).upper(),
        platform_store_id=str(platform_store_id),
        platform_identity_key=identity_key,
        merchant_subject_id=str(merchant_subject_id),
        shop_cipher=str(shop_cipher or ""),
        credential_id=metadata["credential_id"],
        token_id=metadata["token_id"],
        credential_mask=metadata["credential_mask"],
        credential_reference_version=metadata["credential_reference_version"],
        status=MarketplaceStoreAuthorization.Status.PENDING,
        scopes=list(scopes or []),
        created_by=actor,
        updated_by=actor,
    )
    try:
        with authorization_service_write():
            record.save()
    except IntegrityError as exc:
        raise StateConflict("The platform store is already bound in an authorized tenant scope.") from exc
    _audit(record, actor, "authorize")
    return record


def _validate_transition(current, target):
    if target not in ALLOWED_TRANSITIONS[current]:
        raise StateConflict(f"Authorization cannot transition from {current} to {target}.")


@transaction.atomic
def transition_store_authorization(record, *, target_status, actor, error_code="", expires_at=None, operation_claim=None):
    _validate_actor_tenant(actor, record.tenant_id)
    assert_operation_fence(operation_claim)
    locked = MarketplaceStoreAuthorization.objects.select_for_update().get(pk=record.pk)
    _validate_transition(locked.status, target_status)
    locked.status = target_status
    locked.updated_by = actor
    normalized_error_code = str(error_code or "")
    if target_status == MarketplaceStoreAuthorization.Status.ERROR and not re.fullmatch(
        r"[A-Z][A-Z0-9_]{2,79}", normalized_error_code
    ):
        raise ValidationError({"error_code": "Error transitions require a controlled uppercase error code."})
    locked.last_error_code = normalized_error_code
    now = timezone.now()
    if target_status == MarketplaceStoreAuthorization.Status.ACTIVE:
        locked.authorized_at = locked.authorized_at or now
        locked.refreshed_at = now
        locked.revoked_at = None
    elif target_status == MarketplaceStoreAuthorization.Status.EXPIRED:
        locked.expires_at = expires_at or now
    elif target_status == MarketplaceStoreAuthorization.Status.REVOKED:
        locked.revoked_at = now
    elif target_status == MarketplaceStoreAuthorization.Status.RECONCILE_REQUIRED:
        locked.last_error_code = normalized_error_code or "RECONCILE_REQUIRED"
    action = {
        MarketplaceStoreAuthorization.Status.ACTIVE: "activate",
        MarketplaceStoreAuthorization.Status.EXPIRED: "expire",
        MarketplaceStoreAuthorization.Status.REVOKING: "revoke_started",
        MarketplaceStoreAuthorization.Status.REVOKED: "revoke",
        MarketplaceStoreAuthorization.Status.RECONCILE_REQUIRED: "reconcile_required",
        MarketplaceStoreAuthorization.Status.ERROR: "error",
    }[target_status]
    with authorization_service_write():
        locked.save()
    _audit(
        locked,
        actor,
        action,
        IntegrationAuditLog.Result.FAILED if target_status == MarketplaceStoreAuthorization.Status.ERROR else IntegrationAuditLog.Result.SUCCESS,
    )
    return locked


def rotate_store_authorization_references(
    record,
    *,
    credential_id,
    token_id,
    version,
    actor,
    expires_at=None,
    revoker=None,
    operation_claim=None,
):
    _validate_actor_tenant(actor, record.tenant_id)
    metadata = build_reference_metadata(credential_id, token_id, version)
    failed = None
    with transaction.atomic():
        assert_operation_fence(operation_claim)
        locked = MarketplaceStoreAuthorization.objects.select_for_update().get(pk=record.pk)
        if locked.status == MarketplaceStoreAuthorization.Status.REVOKED:
            raise StateConflict("Revoked authorization references cannot be rotated.")
        if version <= locked.credential_reference_version:
            raise StateConflict("Reference version must increase atomically.")
        previous = {
            "credential_id": locked.credential_id,
            "token_id": locked.token_id,
            "credential_mask": locked.credential_mask,
            "reference_version": locked.credential_reference_version,
        }
        revocation = _revoke_old_references(revoker or revoke_synthetic_references, previous)
        if revocation["status"] == "failed":
            failed = (locked, previous, revocation)
        else:
            for field in ("credential_id", "token_id", "credential_mask", "credential_reference_version"):
                setattr(locked, field, metadata[field])
            locked.refreshed_at = timezone.now()
            locked.expires_at = expires_at
            locked.last_error_code = ""
            locked.updated_by = actor
            with authorization_service_write():
                locked.save()
            _audit(
                locked,
                actor,
                "rotate_reference",
                extra={
                    "previous_reference": previous,
                    "new_reference": {
                        "credential_id": locked.credential_id,
                        "token_id": locked.token_id,
                        "credential_mask": locked.credential_mask,
                        "reference_version": locked.credential_reference_version,
                    },
                    "revocation": revocation,
                },
            )
            return locked

    locked, previous, revocation = failed
    _audit(
        locked,
        actor,
        "rotate_reference",
        result=IntegrationAuditLog.Result.FAILED,
        extra={
            "previous_reference": previous,
            "attempted_reference": {
                "credential_mask": metadata["credential_mask"],
                "reference_version": metadata["credential_reference_version"],
            },
            "revocation": revocation,
        },
    )
    raise StateConflict("Previous credential references could not be revoked; rotation was not applied.")


def retry_store_authorization(record, *, actor):
    if record.status != MarketplaceStoreAuthorization.Status.ERROR:
        raise StateConflict("Only failed authorizations can be retried.")
    result = transition_store_authorization(
        record,
        target_status=MarketplaceStoreAuthorization.Status.ACTIVE,
        actor=actor,
    )
    _audit(result, actor, "retry")
    return result
