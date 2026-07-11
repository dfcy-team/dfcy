import base64
import hashlib
import json

from django.conf import settings
from rest_framework.exceptions import ValidationError

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
    provider_name = getattr(settings, "INTEGRATION_ENCRYPTION_PROVIDER", "test-only")
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


def rotate_credentials(config, credentials, key_version, actor):
    ciphertext, fingerprint = encrypt_credentials(credentials, key_version=key_version)
    config.credential_ciphertext = ciphertext
    config.credential_key_version = key_version
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
