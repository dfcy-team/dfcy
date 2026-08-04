import hashlib
import hmac
import re
from dataclasses import dataclass
from urllib.parse import urlencode

from django.conf import settings


class OAuthAdapterError(Exception):
    def __init__(self, error_code, http_status=502):
        self.error_code = error_code
        self.http_status = http_status
        super().__init__(error_code)


@dataclass(frozen=True)
class SyntheticCallback:
    code: str
    platform_store_id: str


def _signature_payload(platform, state, code, platform_store_id, error_code=""):
    return ":".join((platform, state, code, platform_store_id, error_code))


def synthetic_callback_signature(platform, state, code, platform_store_id, error_code=""):
    return hmac.new(
        str(settings.MARKETPLACE_OAUTH_SYNTHETIC_SIGNING_KEY).encode(),
        _signature_payload(platform, state, code, platform_store_id, error_code).encode(),
        hashlib.sha256,
    ).hexdigest()


class SyntheticMarketplaceAdapter:
    """Offline adapter; it never opens a network connection or calls a platform."""

    contract_version = "a2-synthetic-v1"

    def build_authorization_url(self, *, platform, state, attempt_id):
        return "https://synthetic.invalid/oauth/{}/authorize?{}".format(
            platform,
            urlencode({"attempt_id": attempt_id, "state": state}),
        )

    def validate_callback(self, *, platform, query, expected_state):
        allowed = {"state", "code", "signature", "platform_store_id", "error", "error_code"}
        if set(query) - allowed:
            raise OAuthAdapterError("OAUTH_CALLBACK_INVALID", 400)
        if query.get("state") != expected_state or not query.get("signature"):
            raise OAuthAdapterError("OAUTH_STATE_INVALID", 422)
        code = query.get("code", "")
        platform_store_id = query.get("platform_store_id", "")
        error_code = query.get("error_code", "")
        expected_signature = synthetic_callback_signature(
            platform,
            expected_state,
            code,
            platform_store_id,
            error_code,
        )
        if not hmac.compare_digest(query.get("signature", ""), expected_signature):
            raise OAuthAdapterError("OAUTH_SIGNATURE_INVALID", 400)
        if query.get("error") or error_code:
            normalized_error = str(error_code or "PLATFORM_AUTH_REJECTED")
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,79}", normalized_error):
                normalized_error = "PLATFORM_AUTH_REJECTED"
            raise OAuthAdapterError(normalized_error, 502)
        if not code or len(code) > 300:
            raise OAuthAdapterError("OAUTH_CALLBACK_INVALID", 400)
        if platform_store_id and (len(platform_store_id) > 120 or not platform_store_id.isascii()):
            raise OAuthAdapterError("OAUTH_CALLBACK_INVALID", 400)
        return SyntheticCallback(code=code, platform_store_id=platform_store_id)


class SyntheticCustodyGateway:
    """Returns synthetic reference metadata only; no credential material crosses this boundary."""

    def _scenario(self, code):
        markers = {
            "reject": ("CUSTODY_REJECTED", 502),
            "custody-fail": ("CUSTODY_UNAVAILABLE", 503),
            "rate-limit": ("PLATFORM_RATE_LIMITED", 429),
            "upstream-5xx": ("PLATFORM_UNAVAILABLE", 503),
            "timeout": ("CUSTODY_TIMEOUT", 503),
        }
        for marker, result in markers.items():
            if marker in code:
                raise OAuthAdapterError(*result)

    def exchange_and_store(self, *, platform, code, operation_id, attempt_id):
        self._scenario(code)
        if not code.startswith("synthetic-code-"):
            raise OAuthAdapterError("PLATFORM_RESPONSE_INVALID", 502)
        suffix = str(attempt_id)
        return {
            "credential_id": f"synthetic-oauth-{suffix}-credential",
            "token_id": f"synthetic-oauth-{suffix}-token",
            "credential_reference_version": 1,
            "expires_at": None,
            "operation_id_hash": hashlib.sha256(str(operation_id).encode()).hexdigest(),
        }

    def refresh_and_store(self, *, authorization, operation_id, scenario=""):
        self._scenario(str(scenario))
        return {
            "credential_id": f"synthetic-refresh-{authorization.pk}-credential",
            "token_id": f"synthetic-refresh-{authorization.pk}-token",
            "credential_reference_version": authorization.credential_reference_version + 1,
            "expires_at": None,
            "operation_id_hash": hashlib.sha256(str(operation_id).encode()).hexdigest(),
        }

    def revoke(self, *, authorization, operation_id, scenario=""):
        self._scenario(str(scenario))
        return {
            "status": "revoked",
            "operation_id_hash": hashlib.sha256(str(operation_id).encode()).hexdigest(),
        }
