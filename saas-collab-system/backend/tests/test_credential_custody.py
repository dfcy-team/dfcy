"""Unit tests for the independent local credential custody boundary."""

import json
import os

import pytest

from apps.integrations.custody import (
    CredentialReference,
    CredentialRevokedError,
    FileCredentialStore,
    IdempotencyConflictError,
    VersionConflictError,
)


def test_store_returns_reference_only_and_writes_restricted_record(tmp_path):
    store = FileCredentialStore(tmp_path / "custody")
    reference = store.store(
        {"access_token": "unit-access-secret", "refresh_token": "unit-refresh-secret"},
        idempotency_key="store-1",
    )

    assert isinstance(reference, CredentialReference)
    assert set(reference) == set(CredentialReference._FIELDS)
    assert "unit-access-secret" not in json.dumps(reference)
    assert "unit-refresh-secret" not in json.dumps(reference)
    record = next((tmp_path / "custody").glob("cred_*.json"))
    # Windows does not expose POSIX mode bits; chmod is still attempted by the
    # implementation and this assertion applies on POSIX CI.
    if os.name != "nt":
        assert (tmp_path / "custody").stat().st_mode & 0o777 == 0o700
        assert record.stat().st_mode & 0o777 == 0o600


def test_idempotency_and_version_conflicts_are_safe(tmp_path):
    store = FileCredentialStore(tmp_path / "custody")
    first = store.store({"api_key": "one"}, idempotency_key="same")
    assert store.store({"api_key": "one"}, idempotency_key="same") == first
    with pytest.raises(IdempotencyConflictError):
        store.store({"api_key": "different"}, idempotency_key="same")

    rotated = store.rotate(first, {"api_key": "two"}, expected_version=1)
    assert rotated["version"] == 2
    with pytest.raises(VersionConflictError):
        store.rotate(rotated, {"api_key": "three"}, expected_version=1)


def test_revoke_and_get_reference_never_restore_secret(tmp_path):
    store = FileCredentialStore(tmp_path / "custody")
    reference = store.store({"api_secret": "unit-secret"})
    revoked = store.revoke(reference)
    assert revoked["status"] == "revoked"
    assert store.get_reference(reference)["status"] == "revoked"
    with pytest.raises(CredentialRevokedError):
        store.rotate(reference, {"api_secret": "new-secret"})
    records = list((tmp_path / "custody").glob("cred_*.json"))
    assert records and "unit-secret" not in records[0].read_text(encoding="utf-8")
