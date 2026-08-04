import hashlib
import re

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.common.exceptions import StateConflict

from .models import IntegrationAuditLog, PlatformIntegrationConfig


SYNTHETIC_REFERENCE_PATTERN = re.compile(r"^synthetic-[a-z0-9][a-z0-9._:-]{5,149}$")
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


def reference_mask(reference_id):
    prefix = str(reference_id).split("-", 2)[:2]
    return f"{'-'.join(prefix)}-***"


def reference_fingerprint(credential_id, token_id):
    value = f"{credential_id}:{token_id}".encode()
    return hashlib.sha256(value).hexdigest()


def build_reference_metadata(credential_id, token_id, version):
    credential_id = validate_synthetic_reference(credential_id, "credential_id")
    token_id = validate_synthetic_reference(token_id, "token_id")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValidationError({"credential_reference_version": "Reference version must be a positive integer."})
    return {
        "credential_id": credential_id,
        "token_id": token_id,
        "credential_mask": {
            "credential": reference_mask(credential_id),
            "token": reference_mask(token_id),
        },
        "credential_reference_version": version,
        "credential_fingerprint": reference_fingerprint(credential_id, token_id),
        "credential_key_version": f"reference-v{version}",
    }


@transaction.atomic
def rotate_config_references(config, *, credential_id, token_id, version, actor):
    locked = PlatformIntegrationConfig.objects.select_for_update().get(pk=config.pk, tenant_id=config.tenant_id)
    metadata = build_reference_metadata(credential_id, token_id, version)
    if version <= locked.credential_reference_version:
        raise StateConflict("Credential reference version must increase.")

    previous = {
        "credential_id": locked.credential_id,
        "token_id": locked.token_id,
        "credential_mask": locked.credential_mask,
        "reference_version": locked.credential_reference_version,
    }
    for field, value in metadata.items():
        setattr(locked, field, value)
    locked.save(update_fields=[*metadata.keys(), "updated_at"])
    IntegrationAuditLog.objects.create(
        tenant=locked.tenant,
        integration_config=locked,
        action="rotate_config_reference",
        actor=actor,
        result=IntegrationAuditLog.Result.SUCCESS,
        masked_detail={
            "previous_reference": previous,
            "credential_id": locked.credential_id,
            "token_id": locked.token_id,
            "credential_mask": locked.credential_mask,
            "reference_version": locked.credential_reference_version,
            "status": locked.status,
        },
    )
    return locked
