import hashlib
import hmac
import ipaddress
import re
import socket
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
        operation_hash = hashlib.sha256(str(operation_id).encode()).hexdigest()
        version = authorization.credential_reference_version + 1
        return {
            "credential_id": f"synthetic-refresh-{authorization.pk}-{version}-{operation_hash[:12]}-credential",
            "token_id": f"synthetic-refresh-{authorization.pk}-{version}-{operation_hash[:12]}-token",
            "credential_reference_version": version,
            "expires_at": None,
            "operation_id_hash": operation_hash,
        }

    def revoke(self, *, authorization, operation_id, scenario=""):
        self._scenario(str(scenario))
        return {
            "status": "revoked",
            "operation_id_hash": hashlib.sha256(str(operation_id).encode()).hexdigest(),
        }

    def compensate_exchange(self, *, result, operation_id):
        return {"status": "revoked", "error_code": "", "operation_id_hash": hashlib.sha256(str(operation_id).encode()).hexdigest()}

    def compensate_refresh(self, *, result, operation_id):
        return {"status": "revoked", "error_code": "", "operation_id_hash": hashlib.sha256(str(operation_id).encode()).hexdigest()}


# ---------------------------------------------------------------------------
# Real Sandbox adapters (contract a2-sandbox-v1)
#
# Every path fails closed: without frozen contract values, without the double
# network gate, or outside the egress allowlist nothing reaches the network.
# Real callbacks carry no signature field, so validation is a strict field
# whitelist + one-time state consumption + exchange-response shop identity check.
# ---------------------------------------------------------------------------

REAL_CONTRACT_VERSION = "a2-sandbox-v1"


def real_oauth_contract():
    return getattr(settings, "MARKETPLACE_OAUTH_REAL_CONTRACT", None) or {}


def assert_network_egress(host):
    """Double gate: global switch + exact host allowlist + DNS must not resolve private."""
    if not settings.MARKETPLACE_OAUTH_NETWORK_ENABLED:
        raise OAuthAdapterError("OAUTH_NETWORK_DISABLED", 503)
    allowlist = tuple(getattr(settings, "MARKETPLACE_OAUTH_NETWORK_ALLOWLIST", ()) or ())
    if host not in allowlist:
        raise OAuthAdapterError("OAUTH_NETWORK_HOST_NOT_ALLOWED", 503)
    try:
        resolved = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise OAuthAdapterError("OAUTH_NETWORK_DNS_FAILURE", 503) from exc
    for info in resolved:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise OAuthAdapterError("OAUTH_NETWORK_PRIVATE_ADDRESS", 503)


@dataclass(frozen=True)
class RealCallback:
    code: str
    platform_store_id: str


class RealMarketplaceAdapter:
    """Base adapter for real Sandbox OAuth; contract values are read from the frozen registry."""

    platform = ""
    contract_version = REAL_CONTRACT_VERSION
    callback_allowed_fields = {"state", "code"}
    platform_store_field = ""

    def _platform_contract(self):
        if not self.platform:
            raise OAuthAdapterError("OAUTH_CONTRACT_PENDING", 503)
        contract = real_oauth_contract().get(self.platform) or {}
        if not contract:
            raise OAuthAdapterError("OAUTH_CONTRACT_PENDING", 503)
        return contract

    @staticmethod
    def _require_field(contract, field):
        value = contract.get(field)
        if not value:
            raise OAuthAdapterError("OAUTH_CONTRACT_PENDING", 503)
        return value

    def build_authorization_url(self, *, platform, state, attempt_id):
        if platform != self.platform:
            raise OAuthAdapterError("OAUTH_CALLBACK_INVALID", 400)
        contract = self._platform_contract()
        entry = self._require_field(contract, "authorization_entry")
        callback_url = self._require_field(contract, "callback_url")
        scopes = contract.get("minimum_read_scopes") or []
        if not scopes:
            raise OAuthAdapterError("OAUTH_CONTRACT_PENDING", 503)
        params = {
            "state": state,
            "redirect_uri": callback_url,
            "scope": ",".join(scopes),
        }
        app_reference = contract.get("app_reference")
        if app_reference:
            params["client_reference"] = app_reference
        return f"{entry}?{urlencode(params)}"

    def validate_callback(self, *, platform, query, expected_state):
        if platform != self.platform:
            raise OAuthAdapterError("OAUTH_CALLBACK_INVALID", 400)
        if set(query) - self.callback_allowed_fields:
            raise OAuthAdapterError("OAUTH_CALLBACK_INVALID", 400)
        if not expected_state or query.get("state") != expected_state:
            raise OAuthAdapterError("OAUTH_STATE_INVALID", 422)
        code = query.get("code", "")
        if not code or len(code) > 300 or not code.isascii():
            raise OAuthAdapterError("OAUTH_CALLBACK_INVALID", 400)
        platform_store_id = ""
        if self.platform_store_field:
            platform_store_id = query.get(self.platform_store_field, "")
            if platform_store_id and (len(platform_store_id) > 120 or not platform_store_id.isascii()):
                raise OAuthAdapterError("OAUTH_CALLBACK_INVALID", 400)
        return RealCallback(code=code, platform_store_id=platform_store_id)

    @staticmethod
    def verify_exchange_identity(*, callback_platform_store_id, exchange_platform_store_id):
        """The exchange response must identify the same shop the callback carried."""
        if not callback_platform_store_id:
            return
        if str(callback_platform_store_id) != str(exchange_platform_store_id):
            raise OAuthAdapterError("OAUTH_IDENTITY_MISMATCH", 422)


class ShopeeAdapter(RealMarketplaceAdapter):
    platform = "shopee"
    callback_allowed_fields = {"state", "code", "shop_id"}
    platform_store_field = "shop_id"


class TikTokShopAdapter(RealMarketplaceAdapter):
    platform = "tiktok"
    callback_allowed_fields = {"state", "code"}
    platform_store_field = ""


class RealCustodyGateway:
    """Real custody boundary: the business layer hands over the code, receives references.

    HMAC-SHA256 request signing happens only on the custody side. Token material
    never crosses into the business layer. The HTTP transport is intentionally not
    wired yet: once the custody contract and an approved HTTP dependency exist, the
    gated call sites below execute it; until then they fail closed.
    """

    contract_version = REAL_CONTRACT_VERSION

    def _gated_host(self):
        contract = real_oauth_contract().get("custody") or {}
        host = contract.get("host")
        if not host:
            raise OAuthAdapterError("OAUTH_CONTRACT_PENDING", 503)
        assert_network_egress(host)
        # Gate passed but the transport remains unwired until the custody contract
        # evidence is registered and the HTTP dependency is separately approved.
        raise OAuthAdapterError("OAUTH_NETWORK_CLIENT_PENDING", 503)

    def exchange_and_store(self, *, platform, code, operation_id, attempt_id):
        return self._gated_host()

    def refresh_and_store(self, *, authorization, operation_id, scenario=""):
        return self._gated_host()

    def revoke(self, *, authorization, operation_id, scenario=""):
        return self._gated_host()

    def fetch_shop_info(self, *, platform, credential_reference):
        """TikTok post-exchange /authorization/{version}/shops lookup lives behind custody."""
        return self._gated_host()
