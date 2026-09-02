import io
import json
import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from apps.integrations.custody_service import (
    CustodyService,
    CustodyServiceConfigurationError,
    EncryptedFileCredentialStore,
)


def _write_secret(path: Path, value: str, mode=0o400):
    path.write_text(value, encoding="utf-8")
    if os.name != "nt":
        os.chmod(path, mode)
    return path


def _request(service, path, *, method="POST", payload=None, token="sidecar-token", content_type="application/json"):
    body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
        "HTTP_AUTHORIZATION": f"Bearer {token}" if token is not None else "",
    }
    captured = {}

    def start_response(status, headers):
        captured["status"] = int(status.split(" ", 1)[0])
        captured["headers"] = dict(headers)

    result = b"".join(service(environ, start_response))
    captured["body"] = json.loads(result.decode("utf-8"))
    return captured


@pytest.fixture
def service(tmp_path):
    key_file = _write_secret(tmp_path / "fernet.key", Fernet.generate_key().decode("ascii"))
    token_file = _write_secret(tmp_path / "service.token", "sidecar-token")
    return CustodyService(
        storage_path=tmp_path / "records",
        encryption_key_file=key_file,
        auth_token_file=token_file,
    )


def test_healthz_is_public_and_does_not_disclose_configuration(service):
    response = _request(service, "/healthz", method="GET", token=None, payload=None)

    assert response["status"] == 200
    assert response["body"] == {"status": "ok"}


def test_sidecar_requires_bearer_auth_and_json(service):
    unauthenticated = _request(service, "/tokens", token=None, payload={"app_secret": "secret"})
    wrong_content_type = _request(
        service,
        "/tokens",
        payload={"app_secret": "secret"},
        content_type="text/plain",
    )

    assert unauthenticated["status"] == 401
    assert wrong_content_type["status"] == 400
    assert "secret" not in json.dumps(unauthenticated)
    assert "secret" not in json.dumps(wrong_content_type)


def test_sidecar_encrypts_and_resolves_tokens_with_contract(service):
    stored = _request(
        service,
        "/tokens",
        payload={
            "credential_type": "shopee",
            "reference_version": 1,
            "metadata": {"tenant_id": 1, "integration_config_id": 2},
            "idempotency_key": "store-operation-001",
            "operation_id": "operation-001",
            "app_secret": "app-secret-value",
            "access_token": "access-token-value",
            "refresh_token": "refresh-token-value",
        },
    )

    assert stored["status"] == 200
    refs = stored["body"]
    assert refs["credential_id"].startswith("cred_")
    assert refs["token_id"].startswith("tok_")
    assert refs["credential_mask"] == {"configured": "********"}
    files = list((service._store._store.path).glob("cred_*.json"))
    assert len(files) == 1
    on_disk = files[0].read_text(encoding="utf-8")
    assert "app-secret-value" not in on_disk
    assert "access-token-value" not in on_disk
    assert "credentials_encrypted" in on_disk
    assert '"credentials"' not in on_disk

    secret = _request(service, "/secrets/resolve", payload={"reference_id": refs["credential_id"]})
    access = _request(
        service,
        "/tokens/resolve",
        payload={"token_id": refs["token_id"], "kind": "access"},
    )
    refresh = _request(
        service,
        "/tokens/resolve",
        payload={"token_id": refs["token_id"], "kind": "refresh"},
    )
    assert secret["body"] == {"value": "app-secret-value"}
    assert access["body"] == {"value": "access-token-value"}
    assert refresh["body"] == {"value": "refresh-token-value"}


def test_sidecar_rotation_is_atomic_and_revoke_is_contract_compatible(service):
    stored = _request(service, "/tokens", payload={"app_secret": "old-secret", "access_token": "old-access"})
    refs = stored["body"]
    rotated = _request(
        service,
        "/tokens/rotate",
        payload={
            "previous_credential_id": refs["credential_id"],
            "previous_token_id": refs["token_id"],
            "reference_version": 2,
            "app_secret": "new-secret",
            "access_token": "new-access",
        },
    )
    next_refs = rotated["body"]
    assert rotated["status"] == 200
    assert next_refs["previous_reference_status"] == "revoked"
    assert next_refs["reference_version"] == 2
    assert next_refs["token_id"] != refs["token_id"]
    assert _request(
        service,
        "/tokens/resolve",
        payload={"token_id": refs["token_id"], "kind": "access"},
    )["status"] == 400
    assert _request(
        service,
        "/tokens/resolve",
        payload={"token_id": next_refs["token_id"], "kind": "access"},
    )["body"] == {"value": "new-access"}

    revoked = _request(
        service,
        "/tokens/revoke",
        payload={"credential_id": next_refs["credential_id"], "token_id": next_refs["token_id"]},
    )
    assert revoked["status"] == 200
    assert revoked["body"]["status"] == "revoked"


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode checks are not available on Windows")
def test_key_file_requires_absolute_owner_read_only_non_symlink_path(tmp_path):
    token_file = _write_secret(tmp_path / "service.token", "sidecar-token")
    key_file = _write_secret(tmp_path / "fernet.key", Fernet.generate_key().decode("ascii"))
    with pytest.raises(CustodyServiceConfigurationError):
        CustodyService(storage_path=tmp_path / "records", encryption_key_file="relative.key", auth_token="x")
    os.chmod(key_file, 0o644)
    with pytest.raises(CustodyServiceConfigurationError):
        CustodyService(storage_path=tmp_path / "records-unsafe", encryption_key_file=key_file, auth_token="x")
    os.chmod(key_file, 0o400)
    link = tmp_path / "fernet-link.key"
    link.symlink_to(key_file)
    with pytest.raises(CustodyServiceConfigurationError):
        CustodyService(storage_path=tmp_path / "records-link", encryption_key_file=link, auth_token="x")
    assert EncryptedFileCredentialStore(tmp_path / "records-ok", key_file)
    assert token_file.exists()


def test_request_size_and_unknown_route_are_generic(service):
    oversized = _request(service, "/tokens", payload={"app_secret": "x" * (70 * 1024)})
    unknown = _request(service, "/debug/config", method="GET", token=None, payload=None)

    assert oversized["status"] == 413
    assert unknown["status"] == 404
    assert "CUSTODY_SERVICE" not in json.dumps(unknown)
