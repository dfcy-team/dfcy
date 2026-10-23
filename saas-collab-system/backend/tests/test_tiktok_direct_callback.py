"""Direct callbacks use fake codes and deny every real provider call."""
from unittest.mock import Mock

import pytest

from apps.integrations import marketplace_oauth_service as service
from apps.integrations.models import MarketplaceStoreAuthorization, OAuthStateSession
from apps.integrations.tiktok_direct_callback import prepare_direct_callback
from tests.test_lazada_store_authorization import lazada_context
from tests.test_marketplace_callback_acceptance import marketplace_callback
from tests.test_tiktok_manual_callback_recovery import recovery

pytestmark = pytest.mark.django_db(transaction=True)
ENDPOINT = "/api/internal/integrations/store-authorizations/oauth/tiktok-direct-callback/"
CALLBACK = "https://example.test/integrations/tiktok/shop-callback"
VERIFIER = "synthetic_browser_verifier_0123456789_ABCDEFGHIJKLMN"


@pytest.fixture
def direct(recovery, settings):
    client, store, config, manual, exchange, result, cleanup, provider = recovery
    settings.TIKTOK_SHOP_DIRECT_CALLBACK_URL = CALLBACK
    config.callback_url = CALLBACK
    config.save()
    session = OAuthStateSession.objects.get()
    from apps.integrations.models import oauth_state_service_write
    from apps.integrations.oauth_state_service import configuration_digest
    with oauth_state_service_write():
        session.redirect_uri = CALLBACK
        session.configuration_digest = configuration_digest(config)
        session.save(update_fields=["redirect_uri", "configuration_digest"])
    context = prepare_direct_callback(session=session, state=manual["tiktok_pending_token"], verifier=VERIFIER)
    params = {"code": "FAKE_CODE", "state": manual["tiktok_pending_token"], "app_key": "FAKE_APP", "shop_region": store.country_code}
    return client, store, config, session, {"browser_token": context["browser_token"], "browser_verifier": VERIFIER,
        "callback_params": params}, exchange, result, cleanup, provider


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
def test_direct_known_shop_completes_once_without_relay(direct, monkeypatch):
    client, store, _, _, payload, exchange, _, _, _ = direct
    monkeypatch.setattr("apps.integrations.tiktok_browser_bridge.bridge_key", Mock(side_effect=AssertionError("relay forbidden")))
    response = client.post(ENDPOINT, payload, format="json")
    assert response.status_code == 200, response.data
    assert response["Cache-Control"] == "no-store"
    assert MarketplaceStoreAuthorization.objects.get(store=store).platform_store_id == store.external_store_id
    assert exchange.call_count == 1
    assert client.post(ENDPOINT, payload, format="json").status_code == 409
    assert exchange.call_count == 1
    assert "FAKE_CODE" not in str(response.data) and payload["browser_token"] not in str(response.data)


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
@pytest.mark.parametrize("mutation", ["signature", "verifier", "state", "empty_state", "config", "store", "region", "extra", "actor"])
def test_direct_invalid_context_never_consumes_or_exchanges(direct, mutation):
    client, store, config, _, payload, exchange, _, _, _ = direct
    if mutation == "signature":
        payload["browser_token"] += "tampered"
    elif mutation == "verifier":
        payload["browser_verifier"] = "Z" * 48
    elif mutation == "state":
        payload["callback_params"]["state"] = "FAKE_OTHER_STATE"
    elif mutation == "empty_state":
        payload["callback_params"]["state"] = ""
    elif mutation == "config":
        config.config_version += 1
        config.save()
    elif mutation == "store":
        type(store).objects.filter(pk=store.pk).update(external_store_id="OTHER_SHOP")
    elif mutation == "region":
        payload["callback_params"]["shop_region"] = "TH"
    elif mutation == "extra":
        payload["callback_params"]["access_token"] = "FORBIDDEN"
    else:
        client.force_authenticate(None)
    assert client.post(ENDPOINT, payload, format="json").status_code >= 400
    exchange.assert_not_called()
    assert OAuthStateSession.objects.get().status == "pending"
    assert not MarketplaceStoreAuthorization.objects.exists()


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
def test_known_shop_without_state_still_checks_exact_api_identity(direct):
    client, _, _, _, payload, exchange, _, _, _ = direct
    payload["callback_params"].pop("state")
    assert client.post(ENDPOINT, payload, format="json").status_code == 200
    assert exchange.call_args.args[0]["target_shop_id"]


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
def test_unknown_shop_without_returned_state_never_exchanges(direct):
    client, store, _, session, payload, exchange, _, _, _ = direct
    store.external_store_id = ""
    store.save(update_fields=["external_store_id"])
    session.store = store
    state = payload["callback_params"].pop("state")
    payload["browser_token"] = prepare_direct_callback(session=session, state=state, verifier=VERIFIER)["browser_token"]
    response = client.post(ENDPOINT, payload, format="json")
    assert response.status_code == 409
    assert response.data["data"]["reason_code"] == "OAUTH_BINDING_IDENTITY_REQUIRED"
    exchange.assert_not_called()
    assert OAuthStateSession.objects.get().status == "pending"


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
def test_missing_direct_configuration_never_uses_bridge(recovery, monkeypatch, settings):
    client, store, config, _, exchange, _, _, provider = recovery
    settings.TIKTOK_SHOP_DIRECT_CALLBACK_URL = ""
    monkeypatch.setattr("apps.integrations.capability.live_network_mode_enabled", lambda: True)
    monkeypatch.setattr(provider, "validate_start_configuration", lambda _: None)
    monkeypatch.setattr(provider, "build_authorization_url", lambda context: {"url": "https://services.tiktokshop.com/open/authorize?service_id=FAKE&state=" + context["state"]})
    response = client.post("/api/internal/integrations/store-authorizations/oauth/start/", {
        "platform": "tiktok", "integration_config_id": config.pk, "store_id": store.pk,
        "region": store.country_code, "redirect_uri": config.callback_url, "scopes": [],
        "tiktok_browser_verifier": VERIFIER}, format="json")
    assert response.status_code == 400
    assert "browser_bridge_url" not in str(response.data)
    exchange.assert_not_called()
