"""Credential custody boundary for live marketplace authorization.

Only an approved custody backend can handle live secrets. The default backend
refuses every secret operation. The file backend is limited to local
synthetic/test use and never falls back to the application database. Live mode
requires an independently operated HTTP custody service with authentication.
"""

from abc import ABC, abstractmethod
import os
from pathlib import Path
import stat
import urllib.parse

from django.conf import settings

from .file_custody import FileCredentialStore, FileCustodyError
from .oauth_errors import OAUTH_PROVIDER_UNAVAILABLE, OAuthFlowError
from .production_settings import get_runtime_config, get_runtime_setting


class CustodyError(OAuthFlowError):
    def __init__(self, detail=None):
        super().__init__(OAUTH_PROVIDER_UNAVAILABLE, detail or "Credential custody operation failed.")


MAX_SERVICE_TOKEN_FILE_BYTES = 4096


def _read_owner_secret_file(path, *, setting_name, read_only=False, max_bytes=MAX_SERVICE_TOKEN_FILE_BYTES):
    """Read a mounted secret without following links or accepting broad modes.

    The service token may be owner-readable/writable (0600) because the
    runtime secret manager commonly creates it that way.  The sidecar Fernet
    key is stricter and must be owner-readable only (0400).  Neither file is
    ever written by the application.
    """
    raw_path = str(path or "").strip()
    candidate = Path(raw_path).expanduser()
    if not raw_path or not candidate.is_absolute():
        raise CustodyError(f"{setting_name} must be an absolute file path.")
    try:
        link_stat = candidate.lstat()
    except OSError:
        raise CustodyError(f"{setting_name} is unavailable.") from None
    if stat.S_ISLNK(link_stat.st_mode) or not stat.S_ISREG(link_stat.st_mode):
        raise CustodyError(f"{setting_name} is unavailable.")
    mode = stat.S_IMODE(link_stat.st_mode)
    if os.name != "nt":
        # Reject group/other access and execute bits.  A key is explicitly
        # read-only; a service token may use the conventional 0600 mount.
        if mode & 0o077 or mode & 0o111 or not mode & 0o400:
            raise CustodyError(f"{setting_name} permissions are unsafe.")
        if read_only and mode != 0o400:
            raise CustodyError(f"{setting_name} permissions are unsafe.")
        if not read_only and mode not in {0o400, 0o600}:
            raise CustodyError(f"{setting_name} permissions are unsafe.")
    try:
        flags = os.O_RDONLY
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        if no_follow:
            flags |= no_follow
        descriptor = os.open(str(candidate), flags)
        try:
            opened_stat = os.fstat(descriptor)
            if not stat.S_ISREG(opened_stat.st_mode):
                raise CustodyError(f"{setting_name} is unavailable.")
            if no_follow and (
                opened_stat.st_dev != link_stat.st_dev or opened_stat.st_ino != link_stat.st_ino
            ):
                raise CustodyError(f"{setting_name} is unavailable.")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = None
                data = handle.read(max_bytes + 1)
        finally:
            if descriptor is not None:
                os.close(descriptor)
    except CustodyError:
        raise
    except (OSError, UnicodeError):
        raise CustodyError(f"{setting_name} is unavailable.") from None
    if len(data) > max_bytes:
        raise CustodyError(f"{setting_name} is unavailable.")
    try:
        value = data.decode("utf-8").strip()
    except UnicodeDecodeError:
        raise CustodyError(f"{setting_name} is unavailable.") from None
    if not value:
        raise CustodyError(f"{setting_name} is unavailable.")
    return value


def read_service_token_file(path):
    """Read the configured bearer token file, failing closed on any issue."""
    return _read_owner_secret_file(path, setting_name="LIVE_CUSTODY_SERVICE_TOKEN_FILE")


def resolve_service_auth_token(explicit=None):
    """Resolve the sidecar bearer token with token-file precedence."""
    if explicit is not None:
        return str(explicit).strip()
    token_file = str(get_runtime_setting("custody", "auth_file_path", default="") or "").strip()
    if token_file:
        return read_service_token_file(token_file)
    # Keep the legacy environment token only as a compatibility fallback. It
    # is never persisted or returned by the production settings API.
    return str(
        getattr(settings, "LIVE_CUSTODY_SERVICE_TOKEN", "")
        or getattr(settings, "LIVE_CUSTODY_SERVICE_AUTH_TOKEN", "")
        or ""
    ).strip()


def validate_custody_service_url(value):
    """Validate the independent custody endpoint without changing TLS policy."""
    raw_url = str(value or "").strip().rstrip("/")
    if not raw_url:
        raise CustodyError("LIVE_CUSTODY_SERVICE_URL is required for approved custody.")
    try:
        parsed = urllib.parse.urlparse(raw_url)
        port = parsed.port
    except (TypeError, ValueError):
        raise CustodyError("LIVE_CUSTODY_SERVICE_URL is invalid.") from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or port is not None and not 1 <= port <= 65535
    ):
        raise CustodyError("LIVE_CUSTODY_SERVICE_URL must be an approved HTTPS endpoint.")
    return raw_url


class CustodyBackend(ABC):
    @abstractmethod
    def retrieve_secret(self, reference_id): ...

    @abstractmethod
    def store_secrets(self, **kwargs): ...

    @abstractmethod
    def rotate_secrets(self, **kwargs): ...

    @abstractmethod
    def retrieve_access_token(self, token_id): ...

    @abstractmethod
    def retrieve_refresh_token(self, token_id): ...

    @abstractmethod
    def revoke(self, credential_id, token_id): ...


class RefusingCustodyBackend(CustodyBackend):
    def _refuse(self):
        raise CustodyError("Approved credential custody is not configured.")

    def retrieve_secret(self, reference_id): self._refuse()
    def store_secrets(self, **kwargs): self._refuse()
    def rotate_secrets(self, **kwargs): self._refuse()
    def retrieve_access_token(self, token_id): self._refuse()
    def retrieve_refresh_token(self, token_id): self._refuse()

    def revoke(self, credential_id, token_id):
        return {"status": "failed", "error_code": "CUSTODY_NOT_CONFIGURED"}


def _reference_result(payload):
    if not isinstance(payload, dict):
        raise CustodyError("Custody returned an invalid reference response.")
    credential_id = str(payload.get("credential_id") or "").strip()
    token_id = str(payload.get("token_id") or "").strip()
    if not credential_id or not token_id:
        raise CustodyError("Custody did not return both required references.")
    return {
        "credential_id": credential_id,
        "token_id": token_id,
        "credential_mask": payload.get("credential_mask") or {},
        "expires_at": payload.get("expires_at"),
        "reference_version": payload.get("reference_version"),
        "operation_id_hash": payload.get("operation_id_hash") or "",
        "previous_reference_status": payload.get("previous_reference_status", "not_required"),
    }


class HttpCustodyBackend(CustodyBackend):
    """Thin adapter to an approved custody service with atomic rotation support."""

    def __init__(self, base_url, client, service_auth_token=None):
        self.base_url = validate_custody_service_url(base_url)
        self._client = client
        self._service_auth_token = resolve_service_auth_token(service_auth_token)
        if not self._service_auth_token:
            raise CustodyError("Credential custody service authentication is not configured.")

    def _request_json(self, method, path, *, body=None):
        response = self._client.request(
            method,
            f"{self.base_url}{path}",
            json_body=body,
            headers={"Authorization": f"Bearer {self._service_auth_token}"},
        )
        try:
            payload = response.json()
        except (TypeError, ValueError):
            raise CustodyError("Custody returned an invalid response.")
        if not isinstance(payload, dict):
            raise CustodyError("Custody returned an invalid response.")
        return payload

    def retrieve_secret(self, reference_id):
        payload = self._request_json("POST", "/secrets/resolve", body={"reference_id": reference_id})
        value = payload.get("value")
        if not isinstance(value, str) or not value:
            raise CustodyError("Custody could not resolve the requested secret reference.")
        return value

    def store_secrets(self, **kwargs):
        try:
            return _reference_result(self._request_json("POST", "/tokens", body=kwargs))
        finally:
            kwargs.clear()

    def rotate_secrets(self, **kwargs):
        try:
            result = _reference_result(self._request_json("POST", "/tokens/rotate", body=kwargs))
            if result["previous_reference_status"] != "revoked":
                raise CustodyError("Custody did not atomically revoke the previous reference.")
            return result
        finally:
            kwargs.clear()

    def retrieve_access_token(self, token_id):
        payload = self._request_json("POST", "/tokens/resolve", body={"token_id": token_id, "kind": "access"})
        value = payload.get("value")
        if not isinstance(value, str) or not value:
            raise CustodyError("Custody could not resolve the access-token reference.")
        return value

    def retrieve_refresh_token(self, token_id):
        payload = self._request_json("POST", "/tokens/resolve", body={"token_id": token_id, "kind": "refresh"})
        value = payload.get("value")
        if not isinstance(value, str) or not value:
            raise CustodyError("Custody could not resolve the refresh-token reference.")
        return value

    def revoke(self, credential_id, token_id):
        payload = self._request_json(
            "POST", "/tokens/revoke", body={"credential_id": credential_id, "token_id": token_id}
        )
        status = payload.get("status")
        if status not in {"revoked", "not_required"}:
            return {"status": "failed", "error_code": "CUSTODY_REVOCATION_FAILED"}
        return {"status": status, "error_code": ""}


class FileCustodyBackend(CustodyBackend):
    """Adapter for the operator-owned local custody volume."""

    _SECRET_KEYS = {
        "secret",
        "app_secret",
        "partner_key",
        "signing_secret",
        "webhook_secret",
        "api_key",
        "api_secret",
        "access_token",
        "refresh_token",
        "private_key",
    }

    def __init__(self, path):
        self._store = FileCredentialStore(path)

    @staticmethod
    def _result(reference, *, previous_reference_status="not_required"):
        return {
            "credential_id": reference["credential_id"],
            "token_id": reference["token_id"],
            "credential_mask": {"configured": "********"},
            "expires_at": reference.get("expires_at"),
            "reference_version": reference["version"],
            "operation_id_hash": reference.get("operation_id_hash") or "",
            "previous_reference_status": previous_reference_status,
        }

    def _values(self, identifier, *, allow_expired=False):
        try:
            return self._store._resolve_credentials(identifier, allow_expired=allow_expired)
        except FileCustodyError as exc:
            raise CustodyError(str(exc)) from None

    def retrieve_secret(self, reference_id):
        values = self._values(reference_id)
        for key in ("app_secret", "partner_key", "api_secret", "signing_secret", "secret", "private_key"):
            value = values.get(key)
            if isinstance(value, str) and value:
                return value
        raise CustodyError("Custody reference does not contain an application secret.")

    def store_secrets(self, **kwargs):
        payload = dict(kwargs)
        try:
            metadata = dict(payload.pop("metadata", {}) or {})
            credential_type = str(payload.pop("credential_type", "") or "")
            if credential_type:
                metadata["credential_type"] = credential_type
            reference_version = int(payload.pop("reference_version", 1))
            expires_at = payload.pop("expires_at", None)
            idempotency_key = payload.pop("idempotency_key", None)
            operation_id = payload.pop("operation_id", None)
            credentials = {key: value for key, value in payload.items() if key in self._SECRET_KEYS}
            reference = self._store.store(
                credentials,
                version=reference_version,
                expires_at=expires_at,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
                metadata=metadata,
            )
            return self._result(reference)
        except FileCustodyError as exc:
            raise CustodyError(str(exc)) from None
        finally:
            payload.clear()
            kwargs.clear()

    def rotate_secrets(self, **kwargs):
        payload = dict(kwargs)
        try:
            credential_id = str(payload.pop("previous_credential_id", "") or "")
            token_id = str(payload.pop("previous_token_id", "") or "")
            current = self._store.get_reference(credential_id or token_id)
            if credential_id and token_id and current["token_id"] != token_id:
                raise FileCustodyError("Credential and token references do not match.")
            metadata = dict(payload.pop("metadata", {}) or {})
            credential_type = str(payload.pop("credential_type", "") or "")
            if credential_type:
                metadata["credential_type"] = credential_type
            requested_version = int(payload.pop("reference_version", current["version"] + 1))
            if requested_version != current["version"] + 1:
                raise FileCustodyError("Credential version has changed.")
            expires_at = payload.pop("expires_at", None)
            idempotency_key = payload.pop("idempotency_key", None)
            operation_id = payload.pop("operation_id", None)
            credentials = self._values(credential_id or token_id, allow_expired=True)
            credentials.update({key: value for key, value in payload.items() if key in self._SECRET_KEYS})
            reference = self._store.rotate(
                credential_id or token_id,
                credentials,
                expected_version=current["version"],
                expires_at=expires_at,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
                metadata=metadata,
            )
            return self._result(reference, previous_reference_status="revoked")
        except FileCustodyError as exc:
            raise CustodyError(str(exc)) from None
        finally:
            payload.clear()
            kwargs.clear()

    def retrieve_access_token(self, token_id):
        value = self._values(token_id).get("access_token")
        if not isinstance(value, str) or not value:
            raise CustodyError("Custody reference does not contain an access token.")
        return value

    def retrieve_refresh_token(self, token_id):
        value = self._values(token_id, allow_expired=True).get("refresh_token")
        if not isinstance(value, str) or not value:
            raise CustodyError("Custody reference does not contain a refresh token.")
        return value

    def revoke(self, credential_id, token_id):
        if not credential_id and not token_id:
            return {"status": "not_required", "error_code": "", "operation_id_hash": ""}
        try:
            current = self._store.get_reference(credential_id or token_id)
            if credential_id and token_id and current["token_id"] != token_id:
                raise FileCustodyError("Credential and token references do not match.")
            reference = self._store.revoke(credential_id or token_id)
            return {
                "status": reference["status"],
                "error_code": "",
                "operation_id_hash": reference.get("operation_id_hash") or "",
            }
        except FileCustodyError:
            return {"status": "failed", "error_code": "CUSTODY_REVOCATION_FAILED", "operation_id_hash": ""}


_cached_backend = None
_cached_backend_signature = None


def _backend_signature():
    """Return a non-secret signature so effective DB versions switch safely."""
    runtime = get_runtime_config()
    custody = runtime.get("custody", {}) if isinstance(runtime, dict) else {}
    token_file = str(custody.get("auth_file_path") or "")
    token_file_state = None
    if token_file:
        try:
            stat_result = Path(token_file).stat()
            token_file_state = (stat_result.st_mtime_ns, stat_result.st_size)
        except OSError:
            token_file_state = ("unavailable",)
    return (
        custody.get("backend", "refuse"),
        custody.get("service_url", ""),
        custody.get("service_host", ""),
        token_file,
        token_file_state,
        custody.get("ca_file_path", ""),
        bool(getattr(settings, "DEBUG", False)),
        str(getattr(settings, "CREDENTIAL_CUSTODY_PATH", "") or ""),
    )


def get_custody_backend():
    global _cached_backend, _cached_backend_signature
    signature = _backend_signature()
    if _cached_backend is not None and _cached_backend_signature == signature:
        return _cached_backend
    backend = str(signature[0] or "refuse").strip().lower()
    if backend == "file":
        if not getattr(settings, "DEBUG", False):
            raise CustodyError("File custody is available only in local synthetic/test mode.")
        path = getattr(settings, "CREDENTIAL_CUSTODY_PATH", "")
        if not path:
            raise CustodyError("CREDENTIAL_CUSTODY_PATH is required for file custody.")
        try:
            _cached_backend = FileCustodyBackend(path)
        except FileCustodyError as exc:
            raise CustodyError(str(exc)) from None
        _cached_backend_signature = signature
        return _cached_backend
    if backend != "http":
        _cached_backend = RefusingCustodyBackend()
        _cached_backend_signature = signature
        return _cached_backend
    base_url = signature[1]
    if not base_url:
        raise CustodyError("LIVE_CUSTODY_SERVICE_URL is required for approved custody.")
    service_auth_token = resolve_service_auth_token()
    if not service_auth_token:
        raise CustodyError("Credential custody service authentication is not configured.")
    from .net_guard import PlatformHttpClient
    _cached_backend = HttpCustodyBackend(base_url, PlatformHttpClient(), service_auth_token)
    _cached_backend_signature = signature
    return _cached_backend


def reset_custody_backend_cache():
    global _cached_backend, _cached_backend_signature
    _cached_backend = None
    _cached_backend_signature = None
