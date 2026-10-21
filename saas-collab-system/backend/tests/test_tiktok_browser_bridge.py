"""Synthetic signed browser callbacks; never contact a marketplace or public relay."""
import time
from urllib.parse import parse_qsl, urlsplit
from unittest.mock import Mock

import pytest

from apps.integrations import tiktok_bridge_protocol as protocol
from apps.integrations.models import MarketplaceStoreAuthorization, OAuthStateSession
from tests.test_lazada_store_authorization import lazada_context
from tests.test_marketplace_callback_acceptance import marketplace_callback
from tests.test_tiktok_manual_callback_recovery import recovery

ENDPOINT = "/api/internal/integrations/store-authorizations/oauth/tiktok-browser-callback/"
pytestmark = pytest.mark.django_db


@pytest.fixture
def browser_recovery(recovery, monkeypatch, tmp_path):
    client, store, config, manual, exchange, result, cleanup, provider = recovery
    key = b"synthetic-browser-relay-key-not-live-00001"
    path = tmp_path / "browser-key"
    path.write_bytes(key)
    monkeypatch.setenv("TIKTOK_BROWSER_BRIDGE_KEY_FILE", str(path))
    monkeypatch.setattr(protocol, "CALLBACK_URI", config.callback_url)
    session = OAuthStateSession.objects.get()
    state = manual["tiktok_pending_token"]
    flow = {"session_id": session.pk, "state": state, "actor_id": session.initiated_by_id,
            "tenant_id": store.tenant_id, "store_id": store.pk, "config_id": config.pk,
            "platform_store_id": store.external_store_id, "callback_uri": config.callback_url,
            "app_key": "FAKE_APP", "region": store.country_code,
            "authorization_url": "https://services.tiktokshop.com/open/authorize?service_id=FAKE_SERVICE&state=" + state,
            "return_uri": protocol.RETURN_URI}
    params = dict(parse_qsl(urlsplit(manual["callback_url"]).query))
    claims = {**flow, "callback_params": params, "flow_expires_at": int(time.time()) + 500}
    return client, store, config, claims, key, exchange, result, cleanup, provider


def request_payload(claims, key, **kwargs):
    return {"receipt_token": protocol.sign_token(claims, key, "callback", **kwargs)}


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
def test_legacy_signed_callback_is_gone_without_exchange(browser_recovery):
    client, store, _, claims, key, exchange, _, _, _ = browser_recovery
    payload = request_payload(claims, key)
    response = client.post(ENDPOINT, payload, format="json")
    assert response.status_code == 410, response.data
    assert not MarketplaceStoreAuthorization.objects.exists()
    assert payload["receipt_token"] not in str(response.data) and "FAKE_CODE" not in str(response.data)
    assert client.post(ENDPOINT, payload, format="json").status_code == 410
    exchange.assert_not_called()


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
@pytest.mark.parametrize("mutation", ["signature", "actor", "tenant", "store", "config", "session", "target",
    "expired", "purpose", "region", "app", "empty_state", "wrong_state", "extra_param", "no_region", "return", "host"])
def test_invalid_signed_callback_never_exchanges(browser_recovery, mutation):
    client, store, _, claims, key, exchange, _, _, _ = browser_recovery
    if mutation in {"actor", "tenant", "store", "config", "session"}:
        claims[mutation + "_id"] += 9000
    elif mutation == "target":
        type(store).objects.filter(pk=store.pk).update(external_store_id="FAKE_OTHER_TARGET")
    elif mutation == "region":
        claims["callback_params"]["shop_region"] = "TH"
    elif mutation == "app":
        claims["callback_params"]["app_key"] = "FAKE_OTHER_APP"
    elif mutation == "empty_state":
        claims["callback_params"]["state"] = ""
    elif mutation == "wrong_state":
        claims["callback_params"]["state"] = "FAKE_OTHER_STATE"
    elif mutation == "extra_param":
        claims["callback_params"]["access_token"] = "FAKE_FORBIDDEN"
    elif mutation == "no_region":
        claims["callback_params"].pop("shop_region")
    elif mutation == "return":
        claims["return_uri"] = "https://foreign.example.test/"
    elif mutation == "host":
        claims["authorization_url"] = claims["authorization_url"].replace("services.tiktokshop.com", "foreign.example.test")
    payload = request_payload(claims, key, **({"now": int(time.time()) - 200} if mutation == "expired" else {}))
    if mutation == "signature":
        payload["receipt_token"] = payload["receipt_token"].split(".")[0] + ".invalid"
    if mutation == "purpose":
        payload["receipt_token"] = protocol.sign_token(claims, key, "start")
    assert client.post(ENDPOINT, payload, format="json").status_code >= 400
    exchange.assert_not_called()
    assert not MarketplaceStoreAuthorization.objects.exists()
    assert OAuthStateSession.objects.get().status == "pending"


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
def test_provider_identity_mismatch_still_cleans_new_custody_references(browser_recovery):
    client, _, _, claims, key, exchange, result, cleanup, _ = browser_recovery
    result["platform_store_records"][0]["platform_store_id"] = "FAKE_WRONG_SHOP"
    assert client.post(ENDPOINT, request_payload(claims, key), format="json").status_code == 410
    exchange.assert_not_called()
    cleanup.assert_not_called()
    assert not MarketplaceStoreAuthorization.objects.exists()


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
def test_store_change_after_receipt_validation_is_rejected_before_exchange(browser_recovery, monkeypatch):
    from apps.integrations import tiktok_browser_bridge as bridge
    client, store, _, claims, key, exchange, result, _, _ = browser_recovery
    original = bridge.validate_browser_receipt
    def change_after_validation(**kwargs):
        validated = original(**kwargs)
        type(store).objects.filter(pk=store.pk).update(external_store_id="FAKE_CHANGED_AFTER_RECEIPT")
        result["platform_store_records"][0]["platform_store_id"] = "FAKE_CHANGED_AFTER_RECEIPT"
        return validated
    monkeypatch.setattr(bridge, "validate_browser_receipt", change_after_validation)
    assert client.post(ENDPOINT, request_payload(claims, key), format="json").status_code == 410
    exchange.assert_not_called()
    assert not MarketplaceStoreAuthorization.objects.exists()


@pytest.mark.parametrize("api_type", ["marketplace", "advertising"])
def test_only_live_tiktok_shop_readiness_checks_real_callback_blockers(monkeypatch, api_type):
    from types import SimpleNamespace
    from apps.integrations import subject_access_service
    cfg = SimpleNamespace(id=1, platform="tiktok", account_alias="Synthetic", environment="production",
        status="verified", regions=["PH"], callback_url="", scopes=[], network_enabled=False,
        sync_read_enabled=False, sync_write_enabled=False, credential_id="", credential_status="",
        platform_config={})
    blocker = Mock(return_value=["callback_missing"])
    monkeypatch.setattr(subject_access_service, "integration_config_oauth_blockers", blocker)
    result = subject_access_service._config_payload(cfg, api_type)
    assert result["oauth_ready"] is (api_type == "advertising")
    assert blocker.call_count == (1 if api_type == "marketplace" else 0)


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
def test_start_builds_signed_fixed_relay_url_only_with_key_and_known_target(browser_recovery, monkeypatch):
    from apps.integrations.tiktok_browser_bridge import prepare_browser_bridge
    _, store, _, claims, key, _, _, _, provider = browser_recovery
    session = OAuthStateSession.objects.get()
    url = prepare_browser_bridge(provider=provider, session=session, state=claims["state"], authorization_url=claims["authorization_url"])
    parts = urlsplit(url)
    assert not parts.query and url.startswith(protocol.START_URI + "#ticket=")
    token = dict(parse_qsl(parts.fragment))["ticket"]
    assert protocol.verify_token(token, key, "start")["platform_store_id"] == store.external_store_id
    monkeypatch.delenv("TIKTOK_BROWSER_BRIDGE_KEY_FILE")
    assert prepare_browser_bridge(provider=provider, session=session, state=claims["state"], authorization_url=claims["authorization_url"]) is None


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
def test_blank_shop_id_start_signs_explicit_confirmation_mode(browser_recovery):
    from apps.integrations.tiktok_browser_bridge import prepare_browser_bridge
    _, store, _, claims, key, _, _, _, provider = browser_recovery
    store.external_store_id = ""
    store.save(update_fields=["external_store_id"])
    session = OAuthStateSession.objects.get()
    url = prepare_browser_bridge(provider=provider, session=session, state=claims["state"], authorization_url=claims["authorization_url"])
    token = dict(parse_qsl(urlsplit(url).fragment))["ticket"]
    flow = protocol.validate_flow(protocol.verify_token(token, key, "start"))
    assert flow["platform_store_id"] == ""
    assert flow["shop_binding_mode"] == protocol.DISCOVERY_MODE
    assert protocol.flow_payload(flow)["shop_binding_mode"] == protocol.DISCOVERY_MODE


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
@pytest.mark.parametrize("mode", [None, False, [], {}, "automatic", "bound"])
def test_invalid_or_downgraded_empty_identity_receipt_never_exchanges(browser_recovery, mode):
    client, _, _, claims, key, exchange, _, _, _ = browser_recovery
    claims["platform_store_id"] = ""
    claims["shop_binding_mode"] = mode
    response = client.post(ENDPOINT, request_payload(claims, key), format="json")
    assert response.status_code == 410
    exchange.assert_not_called()
    assert OAuthStateSession.objects.get().status == "pending"


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
def test_discovery_receipt_cannot_replace_a_prebound_shop(browser_recovery):
    client, _, _, claims, key, exchange, _, _, _ = browser_recovery
    claims.update(platform_store_id="", shop_binding_mode=protocol.DISCOVERY_MODE)
    assert client.post(ENDPOINT, request_payload(claims, key), format="json").status_code == 410
    exchange.assert_not_called()


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
def test_unauthenticated_actor_never_exchanges(browser_recovery):
    client, _, _, claims, key, exchange, _, _, _ = browser_recovery
    client.force_authenticate(None)
    assert client.post(ENDPOINT, request_payload(claims, key), format="json").status_code in {401, 403}
    exchange.assert_not_called()


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
@pytest.mark.parametrize("field", ["tiktok_manual_confirm", "tiktok_pending_token", "callback_url", "state"])
def test_signed_receipt_rejects_unexpected_manual_inputs(browser_recovery, field):
    client, _, _, claims, key, exchange, _, _, _ = browser_recovery
    payload = {**request_payload(claims, key), field: "FAKE_EXTRA_INPUT"}
    assert client.post(ENDPOINT, payload, format="json").status_code == 410
    exchange.assert_not_called()
    assert not MarketplaceStoreAuthorization.objects.exists()
    assert OAuthStateSession.objects.get().status == "pending"
