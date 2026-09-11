import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.integrations.live_providers import TikTokLiveOAuthProvider
from apps.integrations.net_guard import HttpResponse
from apps.integrations.oauth_diagnostics import failure_diagnostic, response_metadata
from apps.integrations.oauth_errors import OAuthFlowError


@pytest.mark.parametrize("code", [36004004, "36004004", 36009004, 36004001, 106001, 106013])
def test_documented_tiktok_codes_survive_safe_metadata(code):
    response = HttpResponse(200, {}, json.dumps({"code": code, "message": "FAKE_SECRET", "data": {"access_token": "FAKE_TOKEN"}}))
    assert response_metadata(response, "tiktok") == {"http_status": 200, "platform_error_code": str(code)}


@pytest.mark.parametrize("code", ["FAKE_SECRET", 99999999, {"secret": "FAKE_SECRET"}, [36004004], 36004004.0, True])
def test_unreviewed_or_malformed_codes_remain_unclassified(code):
    response = HttpResponse(200, {}, json.dumps({"code": code}))
    assert response_metadata(response, "tiktok")["platform_error_code"] == "UNCLASSIFIED"


def test_tiktok_exchange_failure_keeps_code_without_retry_or_secret_output(monkeypatch):
    monkeypatch.setattr(TikTokLiveOAuthProvider, "_preflight", lambda *args: None)
    http, custody = Mock(), Mock()
    http.request.return_value = HttpResponse(200, {}, json.dumps({"code": 36004004,
        "message": "FAKE_SECRET FAKE_CODE", "request_id": "FAKE_REQUEST"}))
    custody.retrieve_secret.return_value = "FAKE_SECRET"
    provider = TikTokLiveOAuthProvider({"app_id": "FAKE_APP", "app_secret_reference": "FAKE_REF",
        "token_host": "https://example.test", "token_path": "/token"}, http_client=http, custody=custody)
    with pytest.raises(OAuthFlowError) as caught:
        provider.exchange_authorization_code({"code": "FAKE_CODE"})
    diagnostic = failure_diagnostic(caught.value, SimpleNamespace(platform="tiktok", integration_config_id=1, pk=1))
    assert diagnostic["stage"] == "exchange_token"
    assert diagnostic["platform_error_code"] == "36004004"
    assert diagnostic["http_status"] == 200
    assert "FAKE_" not in json.dumps(diagnostic) + str(caught.value)
    http.request.assert_called_once()
    assert http.request.call_args.kwargs["retry"] is False
    custody.store_secrets.assert_not_called()
