import base64
import hashlib
import json
from datetime import datetime
from typing import Any

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .custody import (
    CredentialCustody,
    CredentialReference,
    FileCredentialStore,
)
from .security import mask_secret, sanitize_payload


class EncryptionProvider:
    provider_name = "base"

    def encrypt(self, credentials, key_version):
        raise NotImplementedError

    def decrypt(self, ciphertext):
        raise NotImplementedError


class TestOnlyEncryptionProvider(EncryptionProvider):
    provider_name = "test-only"

    def encrypt(self, credentials, key_version):
        payload = {"key_version": key_version, "credentials": credentials}
        encoded = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode()
        return f"{self.provider_name}:{encoded}"

    def decrypt(self, ciphertext):
        prefix = f"{self.provider_name}:"
        if not ciphertext.startswith(prefix):
            raise ValidationError("Unsupported test ciphertext format.")
        encoded = ciphertext.removeprefix(prefix)
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode()).decode())
        return payload["credentials"]


class UnconfiguredProductionEncryptionProvider(EncryptionProvider):
    provider_name = "unconfigured-production"

    def encrypt(self, credentials, key_version):
        raise ValidationError("Production encryption provider is not configured.")

    def decrypt(self, ciphertext):
        raise ValidationError("Production encryption provider is not configured.")


def get_encryption_provider():
    # The reversible provider is retained solely as an explicit local/test
    # compatibility shim.  New integration writes must use CredentialCustody.
    provider_name = getattr(settings, "INTEGRATION_ENCRYPTION_PROVIDER", "unconfigured-production")
    if provider_name == "test-only":
        return TestOnlyEncryptionProvider()
    return UnconfiguredProductionEncryptionProvider()


def _fingerprint(credentials):
    encoded = json.dumps(credentials, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def encrypt_credentials(credentials, key_version="test-v1", provider=None):
    provider = provider or get_encryption_provider()
    return provider.encrypt(credentials, key_version), _fingerprint(credentials)


def decrypt_credentials(ciphertext, provider=None):
    provider = provider or get_encryption_provider()
    return provider.decrypt(ciphertext)


def mask_credentials(credentials):
    if not isinstance(credentials, dict):
        return "***"
    return {key: mask_secret(value) for key, value in sanitize_payload(credentials).items()}


def get_credential_custody(path=None, *, store=None):
    """Return the independent local custody service.

    ``store`` is injectable for tests and for a future process/RPC adapter.
    The function intentionally does not import or initialise a cloud secret
    manager.
    """
    if store is not None:
        return store
    return CredentialCustody(path)


def _expiry_for_model(value):
    """Convert custody's ISO metadata to a Django datetime where possible."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            # Custody validates timestamps before returning them.  This guard
            # keeps compatibility with a custom store implementation.
            return None
    return None


def _apply_reference_metadata(config, reference: CredentialReference):
    """Write only non-sensitive custody metadata to an integration model."""
    data = reference.to_dict() if hasattr(reference, "to_dict") else dict(reference)
    fields = []
    assignments = {
        "credential_id": data.get("credential_id", ""),
        "token_id": data.get("token_id", ""),
        "credential_mask": data.get("mask", "***"),
        "credential_version": data.get("version", 1),
        "credential_expires_at": _expiry_for_model(data.get("expires_at")),
        "credential_operation_id_hash": data.get("operation_id_hash") or "",
        "credential_revoked_at": timezone.now() if data.get("status") == "revoked" else None,
    }
    # APIIntegrationConfig already has credential_status; platform configs
    # receive it in migration 0014.  A custom model may expose only a subset
    # while rolling forward, so assign fields conditionally.
    assignments["credential_status"] = data.get("status", "active")
    for field, value in assignments.items():
        if hasattr(config, field):
            setattr(config, field, value)
            fields.append(field)
    if hasattr(config, "credential_ref"):
        # ``credential_ref`` is a historical alias.  New code stores only the
        # opaque ID; no provider URI or secret-derived value is written.
        config.credential_ref = data.get("credential_id", "")
        fields.append("credential_ref")
    if hasattr(config, "credential_key_version"):
        # Keep a coarse version label for old response contracts, never a
        # ciphertext or key material.
        config.credential_key_version = str(data.get("version", 1))
        fields.append("credential_key_version")
    return list(dict.fromkeys(fields))


def store_credentials(
    credentials: Any,
    *,
    config=None,
    path=None,
    store=None,
    expires_at=None,
    idempotency_key=None,
    operation_id=None,
    **kwargs,
):
    """Store credentials outside the business database.

    Returns a metadata-only :class:`CredentialReference`.  If ``config`` is
    provided, only its custody reference fields are updated; legacy ciphertext
    columns are deliberately untouched.
    """
    custody = get_credential_custody(path, store=store)
    reference = custody.store(
        credentials,
        expires_at=expires_at,
        idempotency_key=idempotency_key,
        operation_id=operation_id,
        **kwargs,
    )
    if config is not None:
        fields = _apply_reference_metadata(config, reference)
        if fields:
            if hasattr(config, "updated_at"):
                fields.append("updated_at")
            config.save(update_fields=list(dict.fromkeys(fields)))
    return reference


def rotate_stored_credentials(
    config_or_identifier,
    credentials,
    *,
    path=None,
    store=None,
    expected_version=None,
    expires_at=None,
    idempotency_key=None,
    operation_id=None,
):
    """Rotate a custody value and update optional model metadata only."""
    identifier = getattr(config_or_identifier, "credential_id", None) or config_or_identifier
    custody = get_credential_custody(path, store=store)
    reference = custody.rotate(
        identifier,
        credentials,
        expected_version=expected_version,
        expires_at=expires_at,
        idempotency_key=idempotency_key,
        operation_id=operation_id,
    )
    if hasattr(config_or_identifier, "save"):
        fields = _apply_reference_metadata(config_or_identifier, reference)
        if fields:
            if hasattr(config_or_identifier, "updated_at"):
                fields.append("updated_at")
            config_or_identifier.save(update_fields=list(dict.fromkeys(fields)))
    return reference


def revoke_credentials(
    config_or_identifier,
    *,
    path=None,
    store=None,
    idempotency_key=None,
    operation_id=None,
):
    """Revoke a custody value and return its safe metadata reference."""
    identifier = getattr(config_or_identifier, "credential_id", None) or config_or_identifier
    custody = get_credential_custody(path, store=store)
    reference = custody.revoke(
        identifier,
        idempotency_key=idempotency_key,
        operation_id=operation_id,
    )
    if hasattr(config_or_identifier, "save"):
        fields = _apply_reference_metadata(config_or_identifier, reference)
        if fields:
            if hasattr(config_or_identifier, "updated_at"):
                fields.append("updated_at")
            config_or_identifier.save(update_fields=list(dict.fromkeys(fields)))
    return reference


def get_reference(
    config_or_identifier,
    *,
    path=None,
    store=None,
):
    """Read-only reference lookup; no secret retrieval API is exposed."""
    identifier = getattr(config_or_identifier, "credential_id", None) or config_or_identifier
    custody = get_credential_custody(path, store=store)
    return custody.get_reference(identifier)


def rotate_credentials(config, credentials, key_version=None, actor=None, **kwargs):
    """Compatibility wrapper for the old integration endpoint.

    Development/tests may explicitly opt into the historical base64 provider;
    all records already managed by custody, and all non-test environments, use
    the independent store.  The function returns the model for the legacy
    path and a safe reference for the custody path.
    """
    provider_name = getattr(settings, "INTEGRATION_ENCRYPTION_PROVIDER", "unconfigured-production")
    use_legacy = kwargs.pop("use_legacy", None)
    has_custody_ref = bool(getattr(config, "credential_id", ""))
    if use_legacy is None:
        use_legacy = provider_name == "test-only" and not has_custody_ref
    if use_legacy:
        ciphertext, fingerprint = encrypt_credentials(credentials, key_version=key_version or "test-v1")
        config.credential_ciphertext = ciphertext
        config.credential_key_version = key_version or "test-v1"
        config.credential_fingerprint = fingerprint
        config.save(
            update_fields=[
                "credential_ciphertext",
                "credential_key_version",
                "credential_fingerprint",
                "updated_at",
            ]
        )
        return config
    return rotate_stored_credentials(
        config,
        credentials,
        path=kwargs.pop("path", None),
        store=kwargs.pop("store", None),
        expected_version=kwargs.pop("expected_version", None),
        expires_at=kwargs.pop("expires_at", None),
        idempotency_key=kwargs.pop("idempotency_key", None),
        operation_id=kwargs.pop("operation_id", None),
    )


__all__ = [
    "CredentialCustody",
    "FileCredentialStore",
    "CredentialReference",
    "encrypt_credentials",
    "decrypt_credentials",
    "get_encryption_provider",
    "mask_credentials",
    "get_credential_custody",
    "store_credentials",
    "rotate_stored_credentials",
    "rotate_credentials",
    "revoke_credentials",
    "get_reference",
]
