import json
import os
import socket
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.integrations import capability
from apps.integrations.credential_service import build_reference_metadata
from apps.integrations.custody import HttpCustodyBackend, RefusingCustodyBackend
from apps.integrations.live_providers import ShopeeLiveOAuthProvider, TikTokLiveOAuthProvider, build_live_provider
from apps.integrations.marketplace_oauth_service import _revoke_uncommitted_exchange
from apps.integrations.net_guard import HttpResponse, PlatformHttpClient
from apps.integrations.oauth_errors import (
    OAUTH_CALLBACK_REJECTED,
    OAUTH_PROVIDER_ERROR,
    OAUTH_PROVIDER_UNAVAILABLE,
    OAUTH_RATE_LIMITED,
    OAuthFlowError,
)

SHOPEE_CALLBACK = "https://callback.example.test/api/internal/integrations/store-authorizations/oauth/callback/shopee/"
TIKTOK_CALLBACK = "https://callback.example.test/api/internal/integrations/store-authorizations/oauth/callback/tiktok/"


class FakeHttpClient:
    def __init__(self):
        self.responses = []
        self.calls = []

    def add(self, fragment, payload, status=200, headers=None):
        self.responses.append((fragment, HttpResponse(status, headers or {}, json.dumps(payload))))

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        for fragment, response in self.responses:
            if fragment in url:
                return response
        raise AssertionError(f"Unexpected fake HTTP request: {method} {urllib.parse.urlsplit(url).path}")


class MemoryCustody:
    def __init__(self):
        self.counter = 0
        self.tokens = {}
        self.revoked = []

    def retrieve_secret(self, reference_id):
        return "synthetic-test-signing-material"

    def store_secrets(self, **kwargs):
        self.counter += 1
        credential_id = f"custody:credential:{self.counter:04d}"
        token_id = f"custody:token:{self.counter:04d}"
        self.tokens[token_id] = dict(kwargs)
        return {
            "credential_id": credential_id,
            "token_id": token_id,
            "credential_mask": {"credential": "custody-***", "token": "custody-***"},
            "expires_at": kwargs.get("expires_at"),
            "reference_version": kwargs.get("reference_version"),
        }

    def rotate_secrets(self, **kwargs):
        raise NotImplementedError

    def retrieve_access_token(self, token_id):
        return self.tokens[token_id]["access_token"]

    def retrieve_refresh_token(self, token_id):
        return self.tokens[token_id]["refresh_token"]

    def revoke(self, credential_id, token_id):
        self.revoked.append((credential_id, token_id))
        return {"status": "revoked", "error_code": ""}


@pytest.fixture
def live_gate(monkeypatch, settings):
    monkeypatch.setattr(capability, "live_network_mode_enabled", lambda: True)
    monkeypatch.setattr(capability, "live_platform_security_approved", lambda: True)
    settings.LIVE_CUSTODY_BACKEND = "http"
    settings.DEBUG = False
    settings.LIVE_CUSTODY_SERVICE_URL = "https://custody.example.test"
    settings.LIVE_CUSTODY_SERVICE_HOST = "custody.example.test"
    settings.LIVE_PLATFORM_ALLOWED_HOSTS = [
        "partner.shopeemobile.com",
        "services.tiktokshop.com",
        "auth.tiktok-shops.com",
        "open-api.tiktokglobalshop.com",
    ]
    settings.LIVE_OAUTH_REDIRECT_ALLOWLIST = [SHOPEE_CALLBACK, TIKTOK_CALLBACK]


def _secret_resolver(platform):
    return {"app_secret": "synthetic-test-signing-material"}


def _tiktok_provider(http=None, custody=None, **overrides):
    config = {
        "contract_approved": True,
        "app_id": "synthetic-test-app-key",
        "service_id": "synthetic-test-service-id",
        "redirect_uri": TIKTOK_CALLBACK,
        "market": "ROW",
        "auth_url": "https://services.tiktokshop.com/open/authorize",
        "api_host": "https://open-api.tiktokglobalshop.com",
        "token_host": "https://auth.tiktok-shops.com",
        "token_path": "/api/v2/token/get",
        "refresh_path": "/api/v2/token/refresh",
        "revoke_path": "/api/v2/token/revoke",
        "authorized_shops_path": "/authorization/202309/shops",
        "metadata_path": "/seller/202309/permissions",
    }
    config.update(overrides)
    return TikTokLiveOAuthProvider(
        config,
        secret_resolver=_secret_resolver,
        http_client=http or FakeHttpClient(),
        custody=custody or MemoryCustody(),
    )


def _shopee_provider(http=None, custody=None, **overrides):
    config = {
        "contract_approved": True,
        "app_id": "123456",
        "redirect_uri": SHOPEE_CALLBACK,
        "auth_url": "https://partner.shopeemobile.com/api/v2/shop/auth_partner",
        "api_host": "https://partner.shopeemobile.com",
        "token_path": "/api/v2/auth/token/get",
        "refresh_path": "/api/v2/auth/access_token/get",
        "revoke_path": "/api/v2/shop/cancel_auth_partner",
        "shop_path": "/api/v2/shop/get_shop_info",
        "region": "SG",
    }
    config.update(overrides)
    return ShopeeLiveOAuthProvider(
        config,
        secret_resolver=_secret_resolver,
        http_client=http or FakeHttpClient(),
        custody=custody or MemoryCustody(),
    )


def test_capability_defaults_to_pending_mock(settings):
    settings.PLATFORM_NETWORK_MODE = ""
    settings.LIVE_PLATFORM_SECURITY_APPROVED = False
    assert capability.get_capability_status("shopee") == "pending/mock"
    assert capability.get_capability_status("tiktok") == "pending/mock"


def test_live_gate_requires_approved_http_custody(monkeypatch, settings):
    monkeypatch.setattr(capability, "live_network_mode_enabled", lambda: True)
    monkeypatch.setattr(capability, "live_platform_security_approved", lambda: True)
    settings.LIVE_CUSTODY_BACKEND = "refuse"
    with pytest.raises(OAuthFlowError) as exc:
        capability.require_live_mode("test")
    assert exc.value.controlled_code == OAUTH_PROVIDER_UNAVAILABLE


def test_live_gate_accepts_explicit_file_custody(monkeypatch, settings, tmp_path):
    monkeypatch.setattr(capability, "live_network_mode_enabled", lambda: True)
    monkeypatch.setattr(capability, "live_platform_security_approved", lambda: True)
    settings.LIVE_CUSTODY_BACKEND = "file"
    settings.CREDENTIAL_CUSTODY_PATH = str(tmp_path / "credential-custody")
    settings.LIVE_PLATFORM_ALLOWED_HOSTS = ["partner.shopeemobile.com"]
    settings.DEBUG = False

    capability.require_live_mode("test")
    assert capability.get_capability_status("shopee") == "pending/live-validation"


def test_capability_never_auto_reports_connected(live_gate):
    assert capability.get_capability_status("shopee") == "pending/live-validation"


def test_live_providers_use_separate_approved_redirects(settings):
    settings.LIVE_SHOPEE_REDIRECT_URI = SHOPEE_CALLBACK
    settings.LIVE_TIKTOK_REDIRECT_URI = TIKTOK_CALLBACK

    assert build_live_provider("shopee").config["redirect_uri"] == SHOPEE_CALLBACK
    assert build_live_provider("tiktok").config["redirect_uri"] == TIKTOK_CALLBACK


@pytest.mark.parametrize(
    ("platform", "platform_config", "expected"),
    (
        ("shopee", {"partner_id": "123456"}, {"app_id": "123456"}),
        (
            "tiktok",
            {"app_key": "approved-app-key", "service_id": "approved-service-id"},
            {"app_id": "approved-app-key", "service_id": "approved-service-id"},
        ),
    ),
)
def test_live_provider_uses_scoped_integration_config(settings, platform, platform_config, expected):
    callback = SHOPEE_CALLBACK if platform == "shopee" else TIKTOK_CALLBACK
    integration_config = SimpleNamespace(
        platform=platform,
        platform_config=platform_config,
        callback_url=callback,
        contract_version="v2" if platform == "shopee" else "202407",
        environment="pilot",
        network_enabled=True,
        sync_read_enabled=False,
        sync_write_enabled=False,
        status="configured",
        credential_status="configured",
        credential_id="custody:credential:config-0001",
    )

    provider = build_live_provider(platform, integration_config=integration_config)

    assert provider.config["app_secret_reference"] == integration_config.credential_id
    assert provider.config["redirect_uri"] == callback
    assert provider.config["integration_config_ready"] is True
    for key, value in expected.items():
        assert provider.config[key] == value


def test_network_guard_rejects_http_and_unknown_host(settings):
    settings.LIVE_PLATFORM_ALLOWED_HOSTS = ["allowed.example.test"]
    client = PlatformHttpClient(transport=lambda *args, **kwargs: None)
    for url in ("http://allowed.example.test/x", "https://unknown.example.test/x"):
        with pytest.raises(OAuthFlowError) as exc:
            client.request("GET", url)
        assert exc.value.controlled_code == OAUTH_PROVIDER_UNAVAILABLE


def test_network_guard_has_separate_timeouts_and_bounded_retry(settings):
    settings.LIVE_PLATFORM_ALLOWED_HOSTS = ["allowed.example.test"]
    settings.LIVE_PLATFORM_MAX_RETRY_WAIT = 1
    settings.LIVE_PLATFORM_MAX_TOTAL_WAIT = 2
    calls = []
    sleeps = []

    def transport(*args, **kwargs):
        calls.append(kwargs)
        return HttpResponse(429, {"retry-after": "99"}, "{}")

    client = PlatformHttpClient(transport=transport, max_retries=2, sleeper=sleeps.append)
    with pytest.raises(OAuthFlowError) as exc:
        client.request("GET", "https://allowed.example.test/x", connect_timeout=2, read_timeout=4)
    assert exc.value.controlled_code == OAUTH_RATE_LIMITED
    assert len(calls) == 3
    assert sleeps == [1.0, 1.0]
    assert calls[0]["connect_timeout"] == 2
    assert calls[0]["read_timeout"] == 4


@pytest.mark.parametrize("failure", [socket.timeout(), socket.gaierror(), ConnectionResetError()])
def test_network_guard_retries_transport_failures(settings, failure):
    settings.LIVE_PLATFORM_ALLOWED_HOSTS = ["allowed.example.test"]
    settings.LIVE_PLATFORM_MAX_RETRY_WAIT = 1
    settings.LIVE_PLATFORM_MAX_TOTAL_WAIT = 1
    attempts = []

    def transport(*args, **kwargs):
        attempts.append(1)
        raise failure

    with pytest.raises(OAuthFlowError) as exc:
        PlatformHttpClient(transport=transport, max_retries=1, sleeper=lambda value: None).request(
            "GET", "https://allowed.example.test/x"
        )
    assert exc.value.controlled_code == OAUTH_PROVIDER_UNAVAILABLE
    assert len(attempts) == 2


def test_network_guard_retries_5xx_with_bound(settings):
    settings.LIVE_PLATFORM_ALLOWED_HOSTS = ["allowed.example.test"]
    settings.LIVE_PLATFORM_MAX_RETRY_WAIT = 1
    settings.LIVE_PLATFORM_MAX_TOTAL_WAIT = 1
    with pytest.raises(OAuthFlowError) as exc:
        PlatformHttpClient(
            transport=lambda *args, **kwargs: HttpResponse(503, {}, "{}"),
            max_retries=1,
            sleeper=lambda value: None,
        ).request("GET", "https://allowed.example.test/x")
    assert exc.value.controlled_code == OAUTH_PROVIDER_ERROR


def test_refusing_custody_has_no_local_fallback():
    custody = RefusingCustodyBackend()
    with pytest.raises(OAuthFlowError):
        custody.store_secrets(access_token="synthetic-test-access", refresh_token="synthetic-test-refresh")


def test_http_custody_returns_only_reference_metadata():
    client = FakeHttpClient()
    client.add("/tokens", {
        "credential_id": "custody:credential:0001",
        "token_id": "custody:token:0001",
        "credential_mask": {"credential": "custody-***", "token": "custody-***"},
        "reference_version": 1,
    })
    result = HttpCustodyBackend("https://custody.example.test", client).store_secrets(
        access_token="synthetic-test-access", refresh_token="synthetic-test-refresh"
    )
    assert "synthetic-test-access" not in json.dumps(result)
    assert result["credential_id"] == "custody:credential:0001"


def test_live_reference_metadata_is_explicit_and_synthetic_rule_stays_strict():
    with pytest.raises(Exception):
        build_reference_metadata("custody:credential:0001", "custody:token:0001", 1)
    metadata = build_reference_metadata(
        "custody:credential:0001",
        "custody:token:0001",
        1,
        allow_live=True,
        credential_mask={"credential": "custody-***", "token": "custody-***"},
    )
    assert metadata["credential_reference_version"] == 1


def test_tiktok_authorization_url_uses_service_id_state_and_exact_redirect(live_gate):
    provider = _tiktok_provider()
    result = provider.build_authorization_url({"state": "state-value", "redirect_uri": TIKTOK_CALLBACK})
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(result["url"]).query)
    assert query == {"service_id": ["synthetic-test-service-id"], "state": ["state-value"]}
    with pytest.raises(OAuthFlowError):
        provider.build_authorization_url({"state": "state-value", "redirect_uri": "https://other.example.test/cb"})


def test_shopee_authorization_url_preserves_state_in_approved_redirect(live_gate):
    provider = _shopee_provider()

    result = provider.build_authorization_url({"state": "state-value", "redirect_uri": SHOPEE_CALLBACK})
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(result["url"]).query)
    redirect_query = urllib.parse.parse_qs(urllib.parse.urlsplit(query["redirect"][0]).query)

    assert "state" not in query
    assert redirect_query == {"state": ["state-value"]}


def test_tiktok_callback_does_not_trust_shop_identity(live_gate):
    provider = _tiktok_provider()
    payload = provider.validate_callback({"code": "synthetic-test-code", "state": "s"}, {"region": "SG"})
    assert set(payload) == {"code", "region", "scopes"}
    with pytest.raises(OAuthFlowError) as exc:
        provider.validate_callback(
            {"code": "synthetic-test-code", "state": "s", "shop_id": "attacker-value"},
            {"region": "SG"},
        )
    assert exc.value.controlled_code == OAUTH_CALLBACK_REJECTED


def test_tiktok_exchange_discovers_shop_and_verifies_metadata(live_gate):
    http = FakeHttpClient()
    custody = MemoryCustody()
    http.add("/api/v2/token/get", {
        "code": 0,
        "request_id": "synthetic-test-request",
        "data": {
            "access_token": "synthetic-test-access",
            "refresh_token": "synthetic-test-refresh",
            "access_token_expire_in": 4102444800,
            "open_id": "synthetic-test-open-id",
            "user_type": 0,
            "granted_scopes": ["seller.authorization.info", "seller.shop.info"],
        },
    })
    http.add("/authorization/202309/shops", {
        "code": 0,
        "data": {"shops": [{"id": "shop-001", "cipher": "ROW_cipher_001", "region": "SG"}]},
    })
    http.add("/seller/202309/permissions", {"code": 0, "data": {}})
    provider = _tiktok_provider(http=http, custody=custody)
    result = provider.exchange_authorization_code({
        "code": "synthetic-test-code",
        "region": "SG",
        "scopes": ["seller.authorization.info", "seller.shop.info"],
    })
    assert result["reference_kind"] == "custody"
    assert result["platform_subject"] == "synthetic-test-open-id"
    assert result["platform_store_records"][0]["shop_cipher"] == "ROW_cipher_001"
    assert "synthetic-test-access" not in json.dumps(
        {k: v for k, v in result.items() if not callable(v)}, default=str
    )
    token_call = next(call for call in http.calls if "/api/v2/token/get" in call["url"])
    assert token_call["method"] == "GET"
    assert "grant_type=authorized_code" in token_call["url"]
    shop_call = next(call for call in http.calls if "/authorization/202309/shops" in call["url"])
    assert shop_call["headers"]["x-tts-access-token"] == "synthetic-test-access"
    assert "sign=" in shop_call["url"]


def test_tiktok_exchange_revokes_new_reference_when_identity_check_fails(live_gate):
    http = FakeHttpClient()
    custody = MemoryCustody()
    http.add("/api/v2/token/get", {
        "code": 0,
        "data": {
            "access_token": "synthetic-test-access",
            "refresh_token": "synthetic-test-refresh",
            "access_token_expire_in": 4102444800,
            "open_id": "synthetic-test-open-id",
            "user_type": 0,
            "granted_scopes": ["seller.authorization.info"],
        },
    })
    http.add("/authorization/202309/shops", {"code": 0, "data": {"shops": []}})
    provider = _tiktok_provider(http=http, custody=custody)
    with pytest.raises(OAuthFlowError):
        provider.exchange_authorization_code({
            "code": "synthetic-test-code", "region": "SG", "scopes": ["seller.authorization.info"]
        })
    assert custody.revoked == [("custody:credential:0001", "custody:token:0001")]


def test_tiktok_token_response_may_omit_user_type_when_shop_identity_is_verified(live_gate):
    http = FakeHttpClient()
    custody = MemoryCustody()
    http.add("/api/v2/token/get", {
        "code": 0,
        "data": {
            "access_token": "synthetic-test-access",
            "refresh_token": "synthetic-test-refresh",
            "access_token_expire_in": 4102444800,
            "open_id": "synthetic-test-open-id",
            "granted_scopes": ["seller.authorization.info"],
        },
    })
    http.add("/authorization/202309/shops", {
        "code": 0,
        "data": {"shops": [{"id": "shop-001", "cipher": "ROW_cipher_001", "region": "PH"}]},
    })
    http.add("/seller/202309/permissions", {"code": 0, "data": {}})

    result = _tiktok_provider(http=http, custody=custody).exchange_authorization_code({
        "code": "synthetic-test-code",
        "region": "PH",
        "scopes": ["seller.authorization.info"],
    })

    assert result["platform_store_records"][0]["platform_store_id"] == "shop-001"


def test_shopee_refuses_unapproved_contract_before_network(live_gate):
    provider = _shopee_provider(contract_approved=False)
    with pytest.raises(OAuthFlowError) as exc:
        provider.build_authorization_url({"state": "s", "redirect_uri": SHOPEE_CALLBACK})
    assert exc.value.controlled_code == OAUTH_PROVIDER_UNAVAILABLE
    assert provider.http.calls == []


def test_shopee_callback_rejects_frontend_subject_override(live_gate):
    provider = _shopee_provider()
    with pytest.raises(OAuthFlowError) as exc:
        provider.validate_callback(
            {"code": "synthetic-test-code", "shop_id": "1", "state": "s", "store_id": "internal-2"},
            {"region": "SG"},
        )
    assert exc.value.controlled_code == OAUTH_CALLBACK_REJECTED


def test_uncommitted_custody_reference_is_revoked_after_persistence_failure():
    revoked = []
    _revoke_uncommitted_exchange({
        "credential_id": "custody:credential:0001",
        "token_id": "custody:token:0001",
        "new_reference_revoker": lambda credential_id, token_id: revoked.append((credential_id, token_id)),
    })
    assert revoked == [("custody:credential:0001", "custody:token:0001")]


@pytest.mark.parametrize("environment", ["sandbox", "pilot"])
def test_nginx_callback_query_is_not_logged(environment):
    evidence_root = os.getenv("NGINX_EVIDENCE_ROOT")
    if evidence_root:
        nginx_path = Path(evidence_root) / f"{environment}.conf"
    else:
        repository_root = Path(__file__).resolve().parents[2]
        nginx_path = repository_root / "deploy" / environment / "application" / "nginx.conf"
    nginx = nginx_path.read_text(encoding="utf-8")
    callback_locations = [
        block for block in nginx.split("location ")
        if "store-authorizations/oauth/callback" in block
    ]
    assert callback_locations
    assert all("access_log off;" in block for block in callback_locations)
