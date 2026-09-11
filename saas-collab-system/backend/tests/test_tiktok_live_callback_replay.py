from urllib.parse import urlencode
from unittest.mock import Mock

import pytest

from apps.integrations import marketplace_oauth_service as service
from apps.integrations.live_providers import TikTokLiveOAuthProvider
from apps.integrations.models import MarketplaceStoreAuthorization
from tests.test_marketplace_callback_acceptance import marketplace_callback, MANUAL
from tests.test_lazada_store_authorization import lazada_context


@pytest.mark.django_db
@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
@pytest.mark.parametrize("mismatch", [False, True])
def test_live_parameter_validation_preserves_one_time_exchange(marketplace_callback, monkeypatch, mismatch):
    client, store, config, synthetic_params, payload = marketplace_callback
    synthetic = service.resolve_oauth_provider("tiktok", config)
    exchange_result = synthetic.exchange_authorization_code(synthetic.validate_callback(synthetic_params,
        {"state": synthetic_params["state"], "region": store.country_code, "scopes": []}))
    live = TikTokLiveOAuthProvider({"app_id": "FAKE_APP_KEY"}, http_client=Mock(), custody=Mock())
    monkeypatch.setattr(live, "_preflight", lambda *args: None)
    exchange = Mock(return_value=exchange_result)
    monkeypatch.setattr(live, "exchange_authorization_code", exchange)
    monkeypatch.setattr(service, "resolve_oauth_provider", lambda *args: live)
    params = {"state": synthetic_params["state"], "code": "FAKE_CODE",
        "app_key": "WRONG_APP" if mismatch else "FAKE_APP_KEY",
        "locale": "zh-CN", "shop_region": store.country_code}
    payload = {**payload, "callback_url": config.callback_url + "?" + urlencode(params)}
    first = client.post(MANUAL, payload, format="json")
    assert first.status_code == (409 if mismatch else 200)
    assert MarketplaceStoreAuthorization.objects.filter(store=store).count() == (0 if mismatch else 1)
    if mismatch:
        assert first.data["data"]["reason_code"] == "OAUTH_CALLBACK_REJECTED"
        exchange.assert_not_called()
    else:
        exchange.assert_called_once()
    replay = client.post(MANUAL, payload, format="json")
    assert replay.status_code == 409
    assert replay.data["data"]["reason_code"] == "OAUTH_STATE_CONSUMED"
    assert exchange.call_count == (0 if mismatch else 1)
    live.http.request.assert_not_called()
