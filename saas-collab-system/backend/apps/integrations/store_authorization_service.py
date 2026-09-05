import re

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.exceptions import StateConflict

from .credential_service import _revoke_old_references, build_reference_metadata, revoke_synthetic_references
from .models import (
    IntegrationAuditLog,
    MarketplaceStoreAuthorization,
    authorization_service_write,
    marketplace_identity_key,
    marketplace_store_binding_key,
)
from .audit_sanitizer import sanitize_audit_detail as _sanitize_audit_detail


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


def _validate_actor_tenant(actor, tenant_id):
    if actor.tenant_id != tenant_id:
        raise ValidationError("Authorization actor must belong to the authorization tenant.")


def _audit(record, actor, action, result=IntegrationAuditLog.Result.SUCCESS, extra=None):
    detail = {
        "platform": record.platform,
        "store_id": str(record.store_id),
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
        masked_detail=_sanitize_audit_detail(detail),
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
    credential_mask=None,
    allow_live_references=False,
    scopes,
    actor,
):
    _validate_actor_tenant(actor, tenant.id)
    metadata = build_reference_metadata(
        credential_id,
        token_id,
        1,
        credential_mask=credential_mask,
        allow_live=allow_live_references,
    )
    identity_key = marketplace_identity_key(platform, region, platform_store_id)
    if MarketplaceStoreAuthorization.objects.filter(active_platform_identity_key=identity_key).exists():
        raise StateConflict("The platform store is already bound in an authorized tenant scope.")
    record = MarketplaceStoreAuthorization(
        tenant=tenant,
        integration_config=integration_config,
        store=store,
        platform=platform,
        region=str(region).upper(),
        platform_store_id=str(platform_store_id),
        platform_identity_key=identity_key,
        active_platform_identity_key=identity_key,
        active_store_binding_key=marketplace_store_binding_key(tenant.id, platform, store.id),
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
    _audit(
        record,
        actor,
        "authorize",
        extra={"previous_status": None, "new_status": record.status},
    )
    return record


def _validate_transition(current, target):
    if target not in ALLOWED_TRANSITIONS[current]:
        raise StateConflict(f"Authorization cannot transition from {current} to {target}.")


@transaction.atomic
def transition_store_authorization(record, *, target_status, actor, error_code="", expires_at=None):
    _validate_actor_tenant(actor, record.tenant_id)
    locked = MarketplaceStoreAuthorization.objects.select_for_update().get(pk=record.pk)
    previous_status = locked.status
    _validate_transition(previous_status, target_status)
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
        locked.active_platform_identity_key = None
        locked.active_store_binding_key = None
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
        extra={"previous_status": previous_status, "new_status": target_status},
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
    credential_mask=None,
    allow_live_references=False,
    new_reference_revoker=None,
):
    _validate_actor_tenant(actor, record.tenant_id)
    metadata = build_reference_metadata(
        credential_id,
        token_id,
        version,
        credential_mask=credential_mask,
        allow_live=allow_live_references,
    )
    if allow_live_references:
        return _rotate_live_store_authorization_references(
            record,
            metadata=metadata,
            actor=actor,
            expires_at=expires_at,
            previous_revoker=revoker,
            new_revoker=new_reference_revoker,
        )
    failed = None
    with transaction.atomic():
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


def _rotate_live_store_authorization_references(
    record,
    *,
    metadata,
    actor,
    expires_at,
    previous_revoker,
    new_revoker,
):
    """Commit a live reference once, then reconcile external revocation.

    A competing refresh that loses the version race revokes its newly-created
    custody reference. If old-reference revocation fails after the database
    commit, the new reference remains traceable but the authorization moves to
    ``error`` and the call fails; it is never reported as a complete refresh.
    """
    if previous_revoker is None or new_revoker is None:
        raise ValidationError("Live reference rotation requires custody revocation callbacks.")
    previous = None
    try:
        with transaction.atomic():
            locked = MarketplaceStoreAuthorization.objects.select_for_update().get(pk=record.pk)
            if locked.status == MarketplaceStoreAuthorization.Status.REVOKED:
                raise StateConflict("Revoked authorization references cannot be rotated.")
            if metadata["credential_reference_version"] <= locked.credential_reference_version:
                raise StateConflict("Reference version must increase atomically.")
            previous = {
                "credential_id": locked.credential_id,
                "token_id": locked.token_id,
                "credential_mask": locked.credential_mask,
                "reference_version": locked.credential_reference_version,
            }
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
                "rotate_reference_prepare",
                extra={
                    "previous_reference": previous,
                    "new_reference": {
                        "credential_id": locked.credential_id,
                        "token_id": locked.token_id,
                        "credential_mask": locked.credential_mask,
                        "reference_version": locked.credential_reference_version,
                    },
                    "phase": "custody_revocation_pending",
                },
            )
    except Exception:
        _revoke_old_references(
            new_revoker,
            {"credential_id": metadata["credential_id"], "token_id": metadata["token_id"]},
        )
        raise

    revocation = _revoke_old_references(previous_revoker, previous)
    if revocation["status"] == "failed":
        with transaction.atomic():
            failed = MarketplaceStoreAuthorization.objects.select_for_update().get(pk=record.pk)
            failed.status = MarketplaceStoreAuthorization.Status.ERROR
            failed.last_error_code = revocation["error_code"]
            failed.updated_by = actor
            with authorization_service_write():
                failed.save()
            _audit(
                failed,
                actor,
                "rotate_reference",
                result=IntegrationAuditLog.Result.FAILED,
                extra={
                    "previous_reference": previous,
                    "new_reference": {
                        "credential_id": failed.credential_id,
                        "token_id": failed.token_id,
                        "credential_mask": failed.credential_mask,
                        "reference_version": failed.credential_reference_version,
                    },
                    "revocation": revocation,
                    "previous_status": record.status,
                    "new_status": failed.status,
                },
            )
        raise StateConflict("Previous custody reference could not be revoked; authorization requires review.")

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
            "previous_status": record.status,
            "new_status": locked.status,
        },
    )
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
