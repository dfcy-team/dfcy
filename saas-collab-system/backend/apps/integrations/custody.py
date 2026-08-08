"""Credential custody boundary for live marketplace authorization.

Only an approved HTTPS custody service can handle live secrets. The default
backend refuses every secret operation. No filesystem or application-database
fallback exists.
"""

from abc import ABC, abstractmethod

from django.conf import settings

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


_cached_backend = None


def get_custody_backend():
    global _cached_backend
    if _cached_backend is not None:
        return _cached_backend
    if getattr(settings, "LIVE_CUSTODY_BACKEND", "refuse") != "http":
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
