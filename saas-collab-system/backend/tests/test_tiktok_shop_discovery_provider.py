"""Shop discovery uses synthetic custody references and never performs HTTP."""
from unittest.mock import Mock

import pytest

from apps.integrations.live_providers import TikTokLiveOAuthProvider
from apps.integrations.oauth_errors import OAuthFlowError


@pytest.mark.parametrize("entry", ["https://auth.tiktok-shops.com", "https://foreign.example.test/open/authorize",
    "https://services.tiktokshop.com/open/authorize?other=1", "http://services.tiktokshop.com/open/authorize"])
def test_bad_seller_entry_is_rejected_before_redirect(monkeypatch, entry):
    provider = TikTokLiveOAuthProvider({"market": "ROW", "auth_url": entry, "redirect_uri": "https://saas.example.test/callback"},
                                      custody=Mock(), http_client=Mock())
    monkeypatch.setattr(provider, "_preflight", lambda *a: None)
    with pytest.raises(OAuthFlowError):
        provider.validate_start_configuration("https://saas.example.test/callback")


@pytest.mark.parametrize("case", ["one", "multiple", "other_country", "wrong_country", "duplicate", "invalid_id", "cleanup_failure"])
def test_discovery_returns_verified_candidates_without_selecting_a_shop(monkeypatch, case):
    custody = Mock()
    http = Mock()
    provider = TikTokLiveOAuthProvider(
        {"app_id": "FAKE_APP", "market": "ROW", "token_path": "/fake/token"},
        custody=custody, http_client=http,
    )
    monkeypatch.setattr(provider, "_preflight", lambda *args: None)
    monkeypatch.setattr(provider, "_app_secret", lambda: "FAKE_SECRET")
    monkeypatch.setattr(provider, "_token_request", Mock(return_value=({
        "access_token": "FAKE_ACCESS", "refresh_token": "FAKE_REFRESH", "open_id": "FAKE_SUBJECT",
        "granted_scopes": [], "access_token_expire_in": 3600,
    }, "FAKE_REQUEST")))
    monkeypatch.setattr(provider, "_store_tokens", lambda **kwargs: {
        "credential_id": "FAKE_CREDENTIAL", "token_id": "FAKE_TOKEN",
    })
    first = {"platform_store_id": "FAKE_SHOP_1", "region": "PH", "shop_cipher": "FAKE_CIPHER_1", "name": "Synthetic shop one"}
    second = {**first, "platform_store_id": "FAKE_SHOP_2", "shop_cipher": "FAKE_CIPHER_2"}
    shops = [first]
    if case == "multiple":
        shops.append(second)
    elif case == "other_country":
        shops.append({**second, "region": "TH"})
    elif case in {"wrong_country", "cleanup_failure"}:
        shops = [{**first, "region": "TH"}]
    elif case == "duplicate":
        shops.append(dict(first))
    elif case == "invalid_id":
        shops = [{**first, "platform_store_id": "invalid shop id"}]
    fetch = Mock(return_value=shops)
    monkeypatch.setattr(provider, "_fetch_authorized_shops_all", fetch)
    if case == "cleanup_failure":
        custody.revoke.side_effect = RuntimeError("FAKE_SECRET_MUST_NOT_LEAK")
    payload = {"code": "FAKE_CODE", "region": "PH", "scopes": [], "discover_shop_binding": True}
    if case in {"one", "multiple", "other_country"}:
        result = provider.exchange_authorization_code(payload)
        expected = [first, second] if case == "multiple" else [first]
        assert result["platform_store_records"] == expected
        custody.revoke.assert_not_called()
    else:
        with pytest.raises(OAuthFlowError) as error:
            provider.exchange_authorization_code(payload)
        assert "FAKE_SECRET" not in str(error.value)
        custody.revoke.assert_called_once_with("FAKE_CREDENTIAL", "FAKE_TOKEN")
        if case == "cleanup_failure":
            assert error.value.tiktok_cleanup_pending is True
    fetch.assert_called_once_with("FAKE_TOKEN", include_names=True)
    http.request.assert_not_called()
