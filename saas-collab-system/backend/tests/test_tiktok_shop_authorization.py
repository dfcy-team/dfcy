import json
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest

from apps.integrations.live_providers import TikTokLiveOAuthProvider, _integration_config_overrides
from apps.integrations.net_guard import HttpResponse
from apps.integrations.oauth_errors import OAuthFlowError


@pytest.mark.parametrize(("operation", "allowed"), [
    ("refresh", True),
    ("authorized-shop verification", True),
    ("authorization", False),
    ("token exchange", False),
])
def test_callbackless_pilot_only_skips_redirect_for_refresh_and_shop_read(monkeypatch, operation, allowed):
    monkeypatch.setattr("apps.integrations.live_providers.require_live_mode", lambda *_: None)
    provider = TikTokLiveOAuthProvider({
        "contract_approved": True,
        "integration_config_ready": False,
        "callbackless_pilot_shop_refresh": True,
    }, custody=Mock())
    if allowed:
        provider._preflight(operation)
    else:
        with pytest.raises(OAuthFlowError):
            provider._preflight(operation)


@pytest.mark.parametrize(("alias", "status", "blockers", "expected"), [
    ("live-pilot-tk1ph", "verified", ["callback_missing"], True),
    ("live-pilot-tkkj1ph", "verified", ["callback_missing"], True),
    ("other-shop", "verified", ["callback_missing"], False),
    ("live-pilot-tk1ph", "draft", ["callback_missing"], False),
    ("live-pilot-tk1ph", "verified", ["callback_missing", "network_not_approved"], False),
])
def test_callbackless_pilot_requires_exact_verified_import(monkeypatch, alias, status, blockers, expected):
    monkeypatch.setattr("apps.integrations.live_providers.integration_config_oauth_blockers", lambda *_: blockers)
    monkeypatch.setattr("apps.integrations.live_providers.get_runtime_platform_config", lambda *_: {"app_id": "FAKE_APP"})
    config = SimpleNamespace(
        platform="tiktok", environment="pilot", status=status, account_alias=alias,
        sync_read_enabled=True, credential_id="FAKE_REF", callback_url="", platform_config={"app_key": "FAKE_APP"},
    )
    result = _integration_config_overrides("tiktok", config)
    assert result["callbackless_pilot_shop_refresh"] is expected


@pytest.fixture
def exchange(monkeypatch):
    monkeypatch.setattr(TikTokLiveOAuthProvider, "_preflight", lambda *args: None)
    http, custody = Mock(), Mock()
    custody.retrieve_secret.return_value = "FAKE_SECRET"
    custody.retrieve_access_token.return_value = "FAKE_ACCESS"
    custody.store_secrets.return_value = {"credential_id": "FAKE_CREDENTIAL", "token_id": "FAKE_TOKEN_REF"}
    token = {"access_token": "FAKE_ACCESS", "refresh_token": "FAKE_REFRESH", "open_id": "FAKE_SELLER",
             "access_token_expire_in": 3600, "granted_scopes": ["seller.authorization.info"]}
    shops = [{"id": "FAKE_SHOP", "cipher": "FAKE_CIPHER", "region": "PH"}]

    def request(method, url, **kwargs):
        path = urlsplit(url).path
        if path == "/api/v2/token/get":
            assert kwargs["retry"] is False
            data = token
        elif path == "/authorization/202309/shops":
            data = {"shops": shops}
        else:
            # A local shop must not depend on this cross-border-only operation.
            raise OAuthFlowError("OAUTH_AUTH_REJECTED", "Seller permissions denied.")
        return HttpResponse(200, {}, json.dumps({"code": 0, "data": data}))

    http.request.side_effect = request
    provider = TikTokLiveOAuthProvider({"app_id": "FAKE_APP", "app_secret_reference": "FAKE_REF",
        "market": "ROW", "token_host": "https://example.test", "token_path": "/api/v2/token/get",
        "api_host": "https://example.test", "authorized_shops_path": "/authorization/202309/shops",
        "metadata_path": "/seller/202309/permissions"}, http_client=http, custody=custody)
    return provider, token, shops


def authorize(provider):
    return provider.exchange_authorization_code({"code": "FAKE_CODE", "region": "PH",
                                                "scopes": ["seller.authorization.info"]})


def test_shop_authorization_does_not_require_cross_border_permissions(exchange):
    provider, _, _ = exchange
    result = authorize(provider)
    assert result["platform_store_records"] == [{"platform_store_id": "FAKE_SHOP",
                                                "shop_cipher": "FAKE_CIPHER", "region": "PH"}]
    assert result["token_id"] == "FAKE_TOKEN_REF"
    assert result["authorized_scopes"] == ["seller.authorization.info"]
    assert [urlsplit(call.args[1]).path for call in provider.http.request.call_args_list] == [
        "/api/v2/token/get", "/authorization/202309/shops"]
    provider.custody.store_secrets.assert_called_once()
    provider.custody.revoke.assert_not_called()


def test_shop_discovery_does_not_require_cross_border_permissions(exchange):
    provider, _, _ = exchange
    result = provider.fetch_authorized_stores(SimpleNamespace(token_id="FAKE_TOKEN_REF"))
    assert result[0]["platform_store_id"] == "FAKE_SHOP"
    provider.http.request.assert_called_once()
    provider.custody.store_secrets.assert_not_called()


@pytest.mark.parametrize("invalid", ["id", "cipher", "region", "wrong_region", "none", "multiple"])
def test_invalid_shop_identity_still_rejected_and_new_custody_revoked(exchange, invalid):
    provider, _, shops = exchange
    if invalid in {"id", "cipher", "region"}:
        shops[0].pop(invalid)
    elif invalid == "wrong_region":
        shops[0]["region"] = "MY"
    elif invalid == "none":
        shops.clear()
    else:
        shops.append(dict(shops[0], id="FAKE_OTHER_SHOP"))
    with pytest.raises(OAuthFlowError):
        authorize(provider)
    provider.custody.revoke.assert_called_once_with("FAKE_CREDENTIAL", "FAKE_TOKEN_REF")
    assert provider.http.request.call_count == 2


def test_missing_requested_scope_rejected_before_custody(exchange):
    provider, token, _ = exchange
    token["granted_scopes"] = []
    with pytest.raises(OAuthFlowError):
        authorize(provider)
    provider.custody.store_secrets.assert_not_called()
    provider.http.request.assert_called_once()


def test_custody_failure_cannot_be_authorization_success(exchange):
    provider, _, _ = exchange
    provider.custody.store_secrets.side_effect = OAuthFlowError("OAUTH_PROVIDER_UNAVAILABLE")
    with pytest.raises(OAuthFlowError) as caught:
        authorize(provider)
    assert caught.value.stage == "save_token"
    provider.http.request.assert_called_once()
