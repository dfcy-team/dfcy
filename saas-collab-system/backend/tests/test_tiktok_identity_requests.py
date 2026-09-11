import json
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from apps.integrations.live_providers import TikTokLiveOAuthProvider
from apps.integrations.net_guard import HttpResponse
from apps.integrations.oauth_diagnostics import failure_diagnostic
from apps.integrations.oauth_errors import OAuthFlowError


@pytest.fixture
def provider():
    http, custody = Mock(), Mock()
    custody.retrieve_access_token.return_value = "FAKE_ACCESS"
    custody.retrieve_secret.return_value = "FAKE_SECRET"
    http.request.return_value = HttpResponse(200, {}, json.dumps({"code": 0, "data": {
        "shops": [{"id": "FAKE_SHOP", "cipher": "FAKE_CIPHER", "region": "PH"}]}}))
    return TikTokLiveOAuthProvider({"app_id": "FAKE_APP", "app_secret_reference": "FAKE_REF",
        "api_host": "https://example.test", "authorized_shops_path": "/authorization/202309/shops",
        "metadata_path": "/seller/202309/permissions"}, http_client=http, custody=custody)


def test_shop_discovery_is_signed_without_assuming_shop_cipher(provider):
    provider._authorized_shops("FAKE_REFERENCE")
    request = provider.http.request.call_args
    assert urlsplit(request.args[1]).path == "/authorization/202309/shops"
    assert set(parse_qs(urlsplit(request.args[1]).query)) == {"app_key", "timestamp", "sign"}
    assert request.kwargs["headers"]["x-tts-access-token"] == "FAKE_ACCESS"


def test_identity_http_error_records_safe_operation_not_identity_mismatch(provider):
    error = OAuthFlowError("OAUTH_PROVIDER_ERROR", "FAKE_SECRET")
    error.http_status = 400
    error.platform_error_code = "36009004"
    provider.http.request.side_effect = error
    with pytest.raises(OAuthFlowError) as caught:
        provider._authorized_shops("FAKE_REFERENCE")
    diagnostic = failure_diagnostic(caught.value, SimpleNamespace(platform="tiktok", integration_config_id=1, pk=1))
    assert diagnostic["operation"] == "get_authorized_shops"
    assert diagnostic["category"] == "platform_error"
    assert diagnostic["platform_error_code"] == "36009004"
    assert "FAKE_" not in json.dumps(diagnostic) + str(caught.value)


def test_unknown_operation_is_not_exposed():
    error = OAuthFlowError("OAUTH_PROVIDER_ERROR")
    error.operation = "FAKE_SECRET"
    diagnostic = failure_diagnostic(error, SimpleNamespace(platform="tiktok", integration_config_id=1, pk=1))
    assert "operation" not in diagnostic
