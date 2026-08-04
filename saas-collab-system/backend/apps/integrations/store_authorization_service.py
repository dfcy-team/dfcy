import hashlib

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.exceptions import StateConflict

from .credential_service import build_reference_metadata
from .models import (
    IntegrationAuditLog,
    MarketplaceStoreAuthorization,
    authorization_service_write,
)


ALLOWED_TRANSITIONS = {
    MarketplaceStoreAuthorization.Status.PENDING: {
        MarketplaceStoreAuthorization.Status.ACTIVE,
        MarketplaceStoreAuthorization.Status.REVOKED,
        MarketplaceStoreAuthorization.Status.ERROR,
    },
    MarketplaceStoreAuthorization.Status.ACTIVE: {
        MarketplaceStoreAuthorization.Status.EXPIRED,
        MarketplaceStoreAuthorization.Status.REVOKED,
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
    },
    MarketplaceStoreAuthorization.Status.REVOKED: set(),
}


def marketplace_identity_key(platform, region, platform_store_id):
    normalized = f"{str(platform).lower()}:{str(region).upper()}:{str(platform_store_id).strip()}"
    return hashlib.sha256(normalized.encode()).hexdigest()


def _audit(record, actor, action, result=IntegrationAuditLog.Result.SUCCESS):
    return IntegrationAuditLog.objects.create(
        tenant=record.tenant,
        integration_config=record.integration_config,
        store_authorization=record,
        action=action,
        actor=actor,
        result=result,
        masked_detail={
            "credential_id": record.credential_id,
            "token_id": record.token_id,
            "credential_mask": record.credential_mask,
            "status": record.status,
            "error_code": record.last_error_code,
            "reference_version": record.credential_reference_version,
        },
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
):
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
def transition_store_authorization(record, *, target_status, actor, error_code="", expires_at=None):
    locked = MarketplaceStoreAuthorization.objects.select_for_update().get(pk=record.pk)
    _validate_transition(locked.status, target_status)
    locked.status = target_status
    locked.updated_by = actor
    locked.last_error_code = str(error_code or "")
    now = timezone.now()
    if target_status == MarketplaceStoreAuthorization.Status.ACTIVE:
        locked.authorized_at = locked.authorized_at or now
        locked.refreshed_at = now
        locked.revoked_at = None
    elif target_status == MarketplaceStoreAuthorization.Status.EXPIRED:
        locked.expires_at = expires_at or now
    elif target_status == MarketplaceStoreAuthorization.Status.REVOKED:
        locked.revoked_at = now
    action = {
        MarketplaceStoreAuthorization.Status.ACTIVE: "activate",
        MarketplaceStoreAuthorization.Status.EXPIRED: "expire",
        MarketplaceStoreAuthorization.Status.REVOKED: "revoke",
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


@transaction.atomic
def rotate_store_authorization_references(
    record,
    *,
    credential_id,
    token_id,
    version,
    actor,
    expires_at=None,
):
    locked = MarketplaceStoreAuthorization.objects.select_for_update().get(pk=record.pk)
    if locked.status == MarketplaceStoreAuthorization.Status.REVOKED:
        raise StateConflict("Revoked authorization references cannot be rotated.")
    if version <= locked.credential_reference_version:
        raise StateConflict("Reference version must increase atomically.")
    metadata = build_reference_metadata(credential_id, token_id, version)
    for field in ("credential_id", "token_id", "credential_mask", "credential_reference_version"):
        setattr(locked, field, metadata[field])
    locked.refreshed_at = timezone.now()
    locked.expires_at = expires_at
    locked.last_error_code = ""
    locked.updated_by = actor
    with authorization_service_write():
        locked.save()
    _audit(locked, actor, "rotate_reference")
    return locked


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
