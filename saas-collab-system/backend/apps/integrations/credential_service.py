import hashlib
import json
import re

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.common.exceptions import StateConflict

from .custody import CustodyError, get_custody_backend
from .models import (
    CredentialMutationRequest,
    IntegrationAuditLog,
    PlatformIntegrationConfig,
    authorization_service_write,
)


SYNTHETIC_REFERENCE_PATTERN = re.compile(r"^synthetic-[a-z0-9][a-z0-9._:-]{5,149}$")
LIVE_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{7,159}$")
RAW_CREDENTIAL_FIELDS = {
    "access_token",
    "refresh_token",
    "secret",
    "app_secret",
    "partner_key",
    "signing_secret",
    "webhook_secret",
    "api_key",
    "api_secret",
    "credentials",
    "credential_ciphertext",
    "cookie",
    "session",
    "authorization_code",
    "bearer",
}


def reject_raw_credential_fields(payload):
    keys = {str(key).lower() for key in (payload or {})}
    if keys.intersection(RAW_CREDENTIAL_FIELDS):
        raise ValidationError("Raw credentials are forbidden; submit custody reference metadata only.")


def validate_synthetic_reference(reference_id, field_name):
    value = str(reference_id or "").strip()
    if not SYNTHETIC_REFERENCE_PATTERN.fullmatch(value):
        raise ValidationError({field_name: "Only synthetic reference IDs are accepted in this foundation phase."})
    return value


def validate_live_reference(reference_id, field_name):
    value = str(reference_id or "").strip()
    if not LIVE_REFERENCE_PATTERN.fullmatch(value) or value.startswith("synthetic-"):
        raise ValidationError({field_name: "Custody returned an invalid opaque reference ID."})
    return value


def reference_mask(reference_id):
    prefix = str(reference_id).split("-", 2)[:2]
    return f"{'-'.join(prefix)}-***"


def reference_fingerprint(credential_id, token_id):
    value = f"{credential_id}:{token_id}".encode()
    return hashlib.sha256(value).hexdigest()


def build_reference_metadata(credential_id, token_id, version, *, credential_mask=None, allow_live=False):
    validator = validate_live_reference if allow_live else validate_synthetic_reference
    credential_id = validator(credential_id, "credential_id")
    token_id = validator(token_id, "token_id")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValidationError({"credential_reference_version": "Reference version must be a positive integer."})
    if credential_mask and allow_live:
        mask_keys = {str(key) for key, value in credential_mask.items() if value} if isinstance(credential_mask, dict) else set()
        credential_mask = {key: "********" for key in mask_keys & {"credential", "token", "configured"}}
        if not credential_mask:
            credential_mask = {"configured": "********"}
    return {
        "credential_id": credential_id,
        "token_id": token_id,
        "credential_mask": credential_mask or {
            "credential": reference_mask(credential_id),
            "token": reference_mask(token_id),
        },
        "credential_reference_version": version,
        "credential_fingerprint": reference_fingerprint(credential_id, token_id),
        "credential_key_version": f"reference-v{version}",
    }


def revoke_synthetic_references(credential_id, token_id):
    if not credential_id and not token_id:
        return {"status": "not_required", "error_code": ""}
    validate_synthetic_reference(credential_id, "credential_id")
    validate_synthetic_reference(token_id, "token_id")
    return {"status": "revoked", "error_code": ""}


def _revoke_old_references(revoker, previous):
    try:
        result = revoker(previous["credential_id"], previous["token_id"])
    except Exception:
        return {"status": "failed", "error_code": "REFERENCE_REVOCATION_FAILED"}
    if not isinstance(result, dict) or result.get("status") not in {"revoked", "not_required"}:
        error_code = result.get("error_code") if isinstance(result, dict) else None
        error_code = str(error_code or "REFERENCE_REVOCATION_FAILED")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,79}", error_code):
            error_code = "REFERENCE_REVOCATION_FAILED"
        return {
            "status": "failed",
            "error_code": error_code,
        }
    return {"status": result["status"], "error_code": ""}


def rotate_config_references(config, *, credential_id, token_id, version, actor, revoker=None):
    if actor.tenant_id != config.tenant_id:
        raise ValidationError("Credential rotation actor must belong to the config tenant.")
    metadata = build_reference_metadata(credential_id, token_id, version)
    failed = None
    with transaction.atomic():
        locked = PlatformIntegrationConfig.objects.select_for_update().get(pk=config.pk, tenant_id=config.tenant_id)
        if version <= locked.credential_reference_version:
            raise StateConflict("Credential reference version must increase.")
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
            for field, value in metadata.items():
                setattr(locked, field, value)
            with authorization_service_write():
                locked.save(update_fields=[*metadata.keys(), "updated_at"])
            IntegrationAuditLog.objects.create(
                tenant=locked.tenant,
                integration_config=locked,
                action="rotate_config_reference",
                actor=actor,
                result=IntegrationAuditLog.Result.SUCCESS,
                masked_detail={
                    "previous_reference": previous,
                    "new_reference": {
                        "credential_id": locked.credential_id,
                        "token_id": locked.token_id,
                        "credential_mask": locked.credential_mask,
                        "reference_version": locked.credential_reference_version,
                    },
                    "revocation": revocation,
                    "status": locked.status,
                },
            )
            return locked

    locked, previous, revocation = failed
    IntegrationAuditLog.objects.create(
        tenant=locked.tenant,
        integration_config=locked,
        action="rotate_config_reference",
        actor=actor,
        result=IntegrationAuditLog.Result.FAILED,
        masked_detail={
            "previous_reference": previous,
            "attempted_reference": {
                "credential_mask": metadata["credential_mask"],
                "reference_version": metadata["credential_reference_version"],
            },
            "revocation": revocation,
            "status": locked.status,
        },
    )
    raise StateConflict("Previous credential references could not be revoked; rotation was not applied.")


def _mutation_digest(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _mutation_request(config, action, idempotency_key, payload):
    key = str(idempotency_key or "").strip()
    if not 12 <= len(key) <= 200:
        raise ValidationError({"Idempotency-Key": "A 12-200 character idempotency key is required."})
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    payload_digest = _mutation_digest(payload)
    try:
        with transaction.atomic():
            operation = CredentialMutationRequest.objects.create(
                tenant=config.tenant,
                integration_config=config,
                action=action,
                idempotency_key_hash=key_hash,
                payload_digest=payload_digest,
            )
        return operation, False
    except IntegrityError:
        operation = CredentialMutationRequest.objects.get(
            tenant=config.tenant,
            idempotency_key_hash=key_hash,
        )
        if operation.integration_config_id != config.id or operation.action != action:
            raise StateConflict("The idempotency key was already used for another credential operation.")
        if operation.payload_digest != payload_digest:
            raise StateConflict("The idempotency key was already used with a different request.")
        if operation.status != CredentialMutationRequest.Status.COMPLETED:
            raise StateConflict("The credential operation is already pending or previously failed.")
        return operation, True


def _safe_expiry(value):
    if not value:
        return None
    parsed = parse_datetime(str(value))
    return parsed if parsed and timezone.is_aware(parsed) else None


def _record_failed_mutation(operation, config, actor, action, error_code, *, reconcile_required=False):
    try:
        operation.status = CredentialMutationRequest.Status.FAILED
        operation.error_code = error_code
        operation.save(update_fields=["status", "error_code", "updated_at"])
    except Exception:
        pass
    if not reconcile_required:
        return
    try:
        with transaction.atomic():
            locked = PlatformIntegrationConfig.objects.select_for_update().get(
                pk=config.pk,
                tenant_id=config.tenant_id,
            )
            locked.credential_status = PlatformIntegrationConfig.CredentialStatus.RECONCILE_REQUIRED
            with authorization_service_write():
                locked.save(update_fields=["credential_status", "updated_at"])
            IntegrationAuditLog.objects.create(
                tenant=locked.tenant,
                integration_config=locked,
                action=action,
                actor=actor,
                result=IntegrationAuditLog.Result.FAILED,
                masked_detail={"error_code": error_code, "reconcile_required": True},
            )
    except Exception:
        pass


def rotate_config_secrets(config, *, credentials, version, reason, actor, idempotency_key):
    if actor.tenant_id != config.tenant_id:
        raise ValidationError("Credential rotation actor must belong to the config tenant.")
    payload = {"version": version, "reason": reason, "credentials": credentials}
    operation, repeated = _mutation_request(
        config,
        CredentialMutationRequest.Action.ROTATE,
        idempotency_key,
        payload,
    )
    if repeated:
        return PlatformIntegrationConfig.objects.get(pk=config.pk), True

    custody = get_custody_backend()
    had_previous_reference = False
    try:
        with transaction.atomic():
            locked = PlatformIntegrationConfig.objects.select_for_update().get(
                pk=config.pk,
                tenant_id=config.tenant_id,
            )
            if locked.config_version != version:
                raise StateConflict("The configuration version changed; reload before replacing credentials.")
            had_previous_reference = bool(locked.credential_id or locked.token_id)
            next_reference_version = locked.credential_reference_version + 1
            custody_payload = {
                "credential_type": locked.platform,
                "reference_version": next_reference_version,
                "metadata": {
                    "tenant_id": locked.tenant_id,
                    "integration_config_id": locked.id,
                    "environment": locked.environment,
                },
                "idempotency_key": idempotency_key,
                "operation_id": str(operation.id),
                **credentials,
            }
            try:
                if locked.credential_id or locked.token_id:
                    stored = custody.rotate_secrets(
                        previous_credential_id=locked.credential_id,
                        previous_token_id=locked.token_id,
                        **custody_payload,
                    )
                else:
                    stored = custody.store_secrets(**custody_payload)
            finally:
                for secret_key in list(credentials):
                    custody_payload.pop(secret_key, None)
                credentials.clear()
            metadata = build_reference_metadata(
                stored["credential_id"],
                stored["token_id"],
                int(stored.get("reference_version") or next_reference_version),
                credential_mask=stored.get("credential_mask") or {"configured": "********"},
                allow_live=True,
            )
            for field, value in metadata.items():
                setattr(locked, field, value)
            locked.credential_status = PlatformIntegrationConfig.CredentialStatus.CONFIGURED
            locked.credential_revoked_at = None
            locked.credential_operation_id_hash = str(stored.get("operation_id_hash") or "")
            if locked.status == PlatformIntegrationConfig.Status.DRAFT:
                locked.status = PlatformIntegrationConfig.Status.CONFIGURED
            locked.credential_expires_at = _safe_expiry(stored.get("expires_at"))
            locked.last_rotated_at = timezone.now()
            locked.config_version += 1
            with authorization_service_write():
                locked.save(
                    update_fields=[
                        *metadata.keys(),
                        "credential_status",
                        "credential_revoked_at",
                        "credential_operation_id_hash",
                        "status",
                        "credential_expires_at",
                        "last_rotated_at",
                        "config_version",
                        "updated_at",
                    ]
                )
            IntegrationAuditLog.objects.create(
                tenant=locked.tenant,
                integration_config=locked,
                action="rotate_credential",
                actor=actor,
                result=IntegrationAuditLog.Result.SUCCESS,
                masked_detail={
                    "credential_mask": locked.credential_mask,
                    "reference_version": locked.credential_reference_version,
                    "config_version": locked.config_version,
                    "reason_recorded": bool(reason),
                },
            )
            operation.status = CredentialMutationRequest.Status.COMPLETED
            operation.response_metadata = {
                "config_version": locked.config_version,
                "reference_version": locked.credential_reference_version,
            }
            operation.save(update_fields=["status", "response_metadata", "updated_at"])
        return locked, False
    except Exception as exc:
        if "stored" in locals():
            try:
                custody.revoke(stored.get("credential_id"), stored.get("token_id"))
            except Exception:
                pass
        _record_failed_mutation(
            operation,
            config,
            actor,
            "rotate_credential",
            "CREDENTIAL_ROTATION_FAILED",
            reconcile_required=had_previous_reference and "stored" in locals(),
        )
        if isinstance(exc, (CustodyError, StateConflict, ValidationError)):
            raise
        raise CustodyError("Credential custody rotation failed.") from None


def clear_config_secrets(config, *, version, reason, actor, idempotency_key):
    if actor.tenant_id != config.tenant_id:
        raise ValidationError("Credential clear actor must belong to the config tenant.")
    payload = {"version": version, "reason": reason}
    operation, repeated = _mutation_request(
        config,
        CredentialMutationRequest.Action.CLEAR,
        idempotency_key,
        payload,
    )
    if repeated:
        return PlatformIntegrationConfig.objects.get(pk=config.pk), True
    custody = get_custody_backend()
    reference_revoked = False
    try:
        with transaction.atomic():
            locked = PlatformIntegrationConfig.objects.select_for_update().get(
                pk=config.pk,
                tenant_id=config.tenant_id,
            )
            if locked.config_version != version:
                raise StateConflict("The configuration version changed; reload before clearing credentials.")
            revocation = custody.revoke(locked.credential_id, locked.token_id)
            if revocation.get("status") not in {"revoked", "not_required"}:
                raise CustodyError("Credential custody did not confirm reference revocation.")
            reference_revoked = bool(locked.credential_id or locked.token_id)
            locked.credential_id = ""
            locked.token_id = ""
            locked.credential_mask = {}
            locked.credential_reference_version += 1
            locked.credential_key_version = ""
            locked.credential_fingerprint = ""
            locked.credential_status = PlatformIntegrationConfig.CredentialStatus.REVOKED
            locked.credential_revoked_at = timezone.now()
            locked.credential_operation_id_hash = str(revocation.get("operation_id_hash") or "")
            if locked.status in {
                PlatformIntegrationConfig.Status.CONFIGURED,
                PlatformIntegrationConfig.Status.VERIFIED,
            }:
                locked.status = PlatformIntegrationConfig.Status.DRAFT
            locked.credential_expires_at = None
            locked.last_rotated_at = timezone.now()
            locked.config_version += 1
            with authorization_service_write():
                locked.save(
                    update_fields=[
                        "credential_id",
                        "token_id",
                        "credential_mask",
                        "credential_reference_version",
                        "credential_key_version",
                        "credential_fingerprint",
                        "credential_status",
                        "credential_revoked_at",
                        "credential_operation_id_hash",
                        "status",
                        "credential_expires_at",
                        "last_rotated_at",
                        "config_version",
                        "updated_at",
                    ]
                )
            IntegrationAuditLog.objects.create(
                tenant=locked.tenant,
                integration_config=locked,
                action="clear_credential",
                actor=actor,
                result=IntegrationAuditLog.Result.SUCCESS,
                masked_detail={
                    "credential_status": locked.credential_status,
                    "reference_version": locked.credential_reference_version,
                    "config_version": locked.config_version,
                    "reason_recorded": bool(reason),
                },
            )
            operation.status = CredentialMutationRequest.Status.COMPLETED
            operation.response_metadata = {
                "config_version": locked.config_version,
                "reference_version": locked.credential_reference_version,
            }
            operation.save(update_fields=["status", "response_metadata", "updated_at"])
        return locked, False
    except Exception as exc:
        _record_failed_mutation(
            operation,
            config,
            actor,
            "clear_credential",
            "CREDENTIAL_CLEAR_FAILED",
            reconcile_required=reference_revoked,
        )
        if isinstance(exc, (CustodyError, StateConflict, ValidationError)):
            raise
        raise CustodyError("Credential custody clear failed.") from None
