import json
import multiprocessing
import os

import pytest

from apps.integrations.custody import CustodyError, FileCustodyBackend, get_custody_backend, reset_custody_backend_cache
from apps.integrations.file_custody import (
    FileCredentialStore,
    FileCustodyIdempotencyConflict,
    FileCustodyRevokedError,
    FileCustodyVersionConflict,
)


def _rotate_worker(path, credential_id, ready, start, results):
    store = FileCredentialStore(path)
    ready.put(True)
    start.wait(10)
    try:
        reference = store.rotate(credential_id, {"api_secret": f"unit-worker-{os.getpid()}"}, expected_version=1)
    except FileCustodyVersionConflict:
        results.put(("conflict", 1))
    else:
        results.put(("success", reference["version"]))


def test_file_store_returns_metadata_only_and_restricts_files(tmp_path):
    root = tmp_path / "credential-custody"
    store = FileCredentialStore(root)
    reference = store.store(
        {"access_token": "unit-access-value", "refresh_token": "unit-refresh-value"},
        idempotency_key="store-request-1",
    )

    assert set(reference) == {
        "credential_id",
        "token_id",
        "mask",
        "version",
        "expires_at",
        "status",
        "operation_id_hash",
    }
    assert "unit-access-value" not in json.dumps(reference)
    assert "unit-refresh-value" not in json.dumps(reference)
    record = next(root.glob("cred_*.json"))
    if os.name != "nt":
        assert root.stat().st_mode & 0o777 == 0o700
        assert record.stat().st_mode & 0o777 == 0o600


def test_file_store_enforces_idempotency_and_monotonic_version(tmp_path):
    store = FileCredentialStore(tmp_path / "credential-custody")
    first = store.store({"api_secret": "unit-one"}, idempotency_key="same-request")
    assert store.store({"api_secret": "unit-one"}, idempotency_key="same-request") == first
    with pytest.raises(FileCustodyIdempotencyConflict):
        store.store({"api_secret": "unit-other"}, idempotency_key="same-request")

    rotated = store.rotate(first["credential_id"], {"api_secret": "unit-two"}, expected_version=1)
    assert rotated["version"] == 2
    assert rotated["token_id"] != first["token_id"]
    with pytest.raises(FileCustodyVersionConflict):
        store.rotate(rotated["credential_id"], {"api_secret": "unit-three"}, expected_version=1)


def test_file_store_dual_process_rotation_commits_one_version(tmp_path):
    root = tmp_path / "credential-custody"
    first = FileCredentialStore(root).store({"api_secret": "unit-initial"})
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    start = context.Event()
    results = context.Queue()
    workers = [
        context.Process(target=_rotate_worker, args=(str(root), first["credential_id"], ready, start, results))
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    assert ready.get(timeout=10)
    assert ready.get(timeout=10)
    start.set()
    outcomes = [results.get(timeout=15), results.get(timeout=15)]
    for worker in workers:
        worker.join(timeout=15)
        assert worker.exitcode == 0

    assert sorted(outcomes) == [("conflict", 1), ("success", 2)]
    assert FileCredentialStore(root).get_reference(first["credential_id"])["version"] == 2


def test_file_store_revoke_erases_values_and_is_irreversible(tmp_path):
    root = tmp_path / "credential-custody"
    store = FileCredentialStore(root)
    reference = store.store({"app_secret": "unit-secret-value"})
    revoked = store.revoke(reference["credential_id"])

    assert revoked["status"] == "revoked"
    with pytest.raises(FileCustodyRevokedError):
        store._resolve_credentials(reference["credential_id"])
    assert "unit-secret-value" not in next(root.glob("cred_*.json")).read_text(encoding="utf-8")


def test_file_backend_satisfies_runtime_custody_contract(tmp_path):
    backend = FileCustodyBackend(tmp_path / "credential-custody")
    first = backend.store_secrets(
        credential_type="shopee",
        reference_version=1,
        app_secret="unit-app-secret",
        access_token="synthetic-test-access-token",
        refresh_token="synthetic-test-refresh-token",
        idempotency_key="backend-store-1",
    )

    assert first["credential_mask"] == {"configured": "********"}
    assert backend.retrieve_secret(first["credential_id"]) == "unit-app-secret"
    rotated = backend.rotate_secrets(
        previous_credential_id=first["credential_id"],
        previous_token_id=first["token_id"],
        credential_type="shopee",
        reference_version=2,
        access_token="synthetic-test-new-access",
        refresh_token="synthetic-test-new-refresh",
        idempotency_key="backend-rotate-1",
    )
    assert rotated["reference_version"] == 2
    assert rotated["previous_reference_status"] == "revoked"
    assert backend.revoke(rotated["credential_id"], rotated["token_id"])["status"] == "revoked"
    assert backend.revoke(rotated["credential_id"], rotated["token_id"])["status"] == "revoked"


def test_expired_access_is_rejected_but_refresh_remains_available(tmp_path):
    backend = FileCustodyBackend(tmp_path / "credential-custody")
    reference = backend.store_secrets(
        credential_type="tiktok",
        reference_version=1,
        access_token="synthetic-test-expired-access",
        refresh_token="synthetic-test-usable-refresh",
        expires_at="2000-01-01T00:00:00Z",
    )

    with pytest.raises(CustodyError):
        backend.retrieve_access_token(reference["token_id"])
    assert backend.retrieve_refresh_token(reference["token_id"]) == "synthetic-test-usable-refresh"


def test_file_backend_requires_explicit_settings(settings, tmp_path):
    settings.LIVE_CUSTODY_BACKEND = "file"
    settings.CREDENTIAL_CUSTODY_PATH = str(tmp_path / "credential-custody")
    reset_custody_backend_cache()
    try:
        assert isinstance(get_custody_backend(), FileCustodyBackend)
    finally:
        reset_custody_backend_cache()
