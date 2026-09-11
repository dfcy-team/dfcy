from unittest.mock import Mock

import pytest

from apps.integrations.live_providers import TikTokLiveOAuthProvider
from apps.integrations.oauth_errors import OAuthFlowError, OAUTH_CALLBACK_REJECTED


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(TikTokLiveOAuthProvider, "_preflight", lambda *args: None)
    return TikTokLiveOAuthProvider({"app_id": "FAKE_APP_KEY"}, http_client=Mock(), custody=Mock())


def callback_params():
    return {"code": "FAKE_CODE", "state": "FAKE_STATE", "app_key": "FAKE_APP_KEY",
        "locale": "zh-CN", "shop_region": "PH"}


def test_accepts_matching_callback_metadata_without_forwarding_it(provider):
    result = provider.validate_callback(callback_params(), {"region": "PH", "scopes": ["shop"]})
    assert result == {"code": "FAKE_CODE", "region": "PH", "scopes": ["shop"]}
    provider.http.request.assert_not_called()
    provider.custody.store_secrets.assert_not_called()


def test_existing_minimal_callback_remains_supported(provider):
    assert provider.validate_callback({"code": "FAKE_CODE", "state": "FAKE_STATE"},
        {"region": "PH"})["region"] == "PH"


@pytest.mark.parametrize("extra", [
    {"app_key": "OTHER_APP"}, {"app_key": ""}, {"shop_region": "US"}, {"shop_region": ""},
    {"unexpected": "FAKE_VALUE"}, {"access_token": "FAKE_TOKEN"},
    {"code": ""}, {"error": "FAKE_REJECTION"},
])
def test_rejects_invalid_callback_without_network_or_secret_output(provider, extra):
    with pytest.raises(OAuthFlowError) as caught:
        provider.validate_callback({**callback_params(), **extra}, {"region": "PH"})
    assert caught.value.controlled_code == OAUTH_CALLBACK_REJECTED
    assert "FAKE_" not in str(caught.value)
    assert "OTHER_APP" not in str(caught.value)
    provider.http.request.assert_not_called()


def test_region_metadata_cannot_replace_missing_bound_region(provider):
    with pytest.raises(OAuthFlowError):
        provider.validate_callback(callback_params(), {})
