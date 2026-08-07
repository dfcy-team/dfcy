import hashlib
import re

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.common.exceptions import StateConflict

from .models import IntegrationAuditLog, PlatformIntegrationConfig, authorization_service_write


SYNTHETIC_REFERENCE_PATTERN = re.compile(r"^synthetic-[a-z0-9][a-z0-9._:-]{5,149}$")
LIVE_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{7,159}$")
RAW_CREDENTIAL_FIELDS = {
    "access_token",
    "refresh_token",
    "secret",
    "api_key",
    "api_secret",
    "credentials",
    "credential_ciphertext",
    "cookie",
    "session",
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
