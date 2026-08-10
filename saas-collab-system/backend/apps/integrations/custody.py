"""Credential custody boundary for live marketplace authorization.

Only an approved custody boundary can handle live secrets. The default backend
refuses every secret operation. Local-file custody must use an operator-owned
volume outside Git and the application database.
"""

from abc import ABC, abstractmethod

from django.conf import settings

from .file_custody import FileCredentialStore, FileCustodyError
from .oauth_errors import OAUTH_PROVIDER_UNAVAILABLE, OAuthFlowError


class CustodyError(OAuthFlowError):
    def __init__(self, detail=None):
        super().__init__(OAUTH_PROVIDER_UNAVAILABLE, detail or "Credential custody operation failed.")


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
        "previous_reference_status": payload.get("previous_reference_status", "not_required"),
    }


class HttpCustodyBackend(CustodyBackend):
    """Thin adapter to an approved custody service with atomic rotation support."""

    def __init__(self, base_url, client):
        self.base_url = str(base_url).rstrip("/")
        self._client = client

    def _request_json(self, method, path, *, body=None):
        response = self._client.request(method, f"{self.base_url}{path}", json_body=body)
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
        return _reference_result(self._request_json("POST", "/tokens", body=kwargs))

    def rotate_secrets(self, **kwargs):
        result = _reference_result(self._request_json("POST", "/tokens/rotate", body=kwargs))
        if result["previous_reference_status"] != "revoked":
            raise CustodyError("Custody did not atomically revoke the previous reference.")
        return result

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
            reference = self._store.store(
                {key: value for key, value in payload.items() if key in self._SECRET_KEYS},
                version=int(payload.pop("reference_version", 1)),
                expires_at=payload.pop("expires_at", None),
                idempotency_key=payload.pop("idempotency_key", None),
                operation_id=payload.pop("operation_id", None),
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
            reference = self._store.rotate(
                credential_id or token_id,
                {key: value for key, value in payload.items() if key in self._SECRET_KEYS},
                expected_version=current["version"],
                expires_at=payload.pop("expires_at", None),
                idempotency_key=payload.pop("idempotency_key", None),
                operation_id=payload.pop("operation_id", None),
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


def get_custody_backend():
    global _cached_backend
    if _cached_backend is not None:
        return _cached_backend
    backend = getattr(settings, "LIVE_CUSTODY_BACKEND", "refuse")
    if backend == "file":
        path = getattr(settings, "CREDENTIAL_CUSTODY_PATH", "")
        if not path:
            raise CustodyError("CREDENTIAL_CUSTODY_PATH is required for file custody.")
        try:
            _cached_backend = FileCustodyBackend(path)
        except FileCustodyError as exc:
            raise CustodyError(str(exc)) from None
        return _cached_backend
    if backend != "http":
        _cached_backend = RefusingCustodyBackend()
        return _cached_backend
    base_url = getattr(settings, "LIVE_CUSTODY_SERVICE_URL", "")
    if not base_url:
        raise CustodyError("LIVE_CUSTODY_SERVICE_URL is required for approved custody.")
    from .net_guard import PlatformHttpClient
    _cached_backend = HttpCustodyBackend(base_url, PlatformHttpClient())
    return _cached_backend


def reset_custody_backend_cache():
    global _cached_backend
    _cached_backend = None
