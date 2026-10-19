"""Synthetic-only manual recovery; never open callback URLs or use live codes."""
from datetime import timedelta
from unittest.mock import Mock
from urllib.parse import urlencode

import pytest
from django.utils import timezone

from apps.integrations import marketplace_oauth_service as service
from apps.integrations.audit_sanitizer import sanitize_audit_detail
from apps.integrations.live_providers import TikTokLiveOAuthProvider
from apps.integrations.models import MarketplaceStoreAuthorization, OAuthStateSession, oauth_state_service_write
from tests.test_lazada_store_authorization import lazada_context
from tests.test_marketplace_callback_acceptance import marketplace_callback, MANUAL

pytestmark = pytest.mark.django_db


@pytest.fixture
def recovery(marketplace_callback, monkeypatch):
    client, store, config, params, _ = marketplace_callback
    if config.platform != "tiktok":
        pytest.skip("TikTok-only recovery fixture")
    synthetic = service.resolve_oauth_provider("tiktok", config)
    result = synthetic.exchange_authorization_code(synthetic.validate_callback(params,
        {"state": params["state"], "region": store.country_code, "scopes": []}))
    store.external_store_id = result["platform_store_records"][0]["platform_store_id"]
    store.save(update_fields=["external_store_id"])
    cleanup = Mock()
    result["new_reference_revoker"] = cleanup
    provider = TikTokLiveOAuthProvider({"app_id": "FAKE_APP"}, http_client=Mock(), custody=Mock())
    monkeypatch.setattr(provider, "_preflight", lambda *args: None)
    exchange = Mock(return_value=result)
    monkeypatch.setattr(provider, "exchange_authorization_code", exchange)
    monkeypatch.setattr(service, "resolve_oauth_provider", lambda *args: provider)
    metadata = {"code": "FAKE_CODE", "app_key": "FAKE_APP", "locale": "zh-CN", "shop_region": store.country_code}
    payload = {"callback_url": config.callback_url + "?" + urlencode(metadata),
               "store_id": store.pk, "integration_config_id": config.pk,
               "tiktok_pending_token": params["state"], "tiktok_manual_confirmed": True}
    return client, store, config, payload, exchange, result, cleanup, provider


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
def test_bound_pending_recovery_and_replay(recovery):
    client, store, _, payload, exchange, _, _, provider = recovery
    response = client.post(MANUAL, payload, format="json")
    assert response.status_code == 200, response.data
    assert exchange.call_args.args[0]["target_shop_id"] == store.external_store_id
    assert MarketplaceStoreAuthorization.objects.get(store=store).status == "active"
    assert payload["tiktok_pending_token"] not in str(response.data)
    assert "FAKE_CODE" not in str(response.data)
    assert client.post(MANUAL, payload, format="json").status_code >= 400
    assert exchange.call_count == 1
    provider.http.request.assert_not_called()


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
@pytest.mark.parametrize("mutation", ["no_nonce", "no_confirm", "wrong_nonce", "state_empty", "state_present",
                                     "duplicate", "host", "path", "port", "store", "config", "expired", "ads", "no_external"])
def test_invalid_recovery_never_exchanges(recovery, mutation):
    client, store, config, payload, exchange, _, _, _ = recovery
    if mutation == "no_nonce":
        payload.pop("tiktok_pending_token")
    elif mutation == "no_confirm":
        payload["tiktok_manual_confirmed"] = False
    elif mutation == "wrong_nonce":
        payload["tiktok_pending_token"] = "FAKE_OTHER_STATE"
    elif mutation == "state_empty":
        payload["callback_url"] += "&state="
    elif mutation == "state_present":
        payload["callback_url"] += "&state=" + payload["tiktok_pending_token"]
    elif mutation == "duplicate":
        payload["callback_url"] += "&code=FAKE_SECOND_CODE"
    elif mutation == "host":
        payload["callback_url"] = payload["callback_url"].replace("example.test", "wrong.example.test")
    elif mutation == "path":
        payload["callback_url"] = payload["callback_url"].replace("/callback/tiktok/", "/callback/shopee/")
    elif mutation == "port":
        payload["callback_url"] = payload["callback_url"].replace("example.test", "example.test:444")
    elif mutation == "store":
        payload["store_id"] += 9999
    elif mutation == "config":
        payload["integration_config_id"] += 9999
    elif mutation == "expired":
        with oauth_state_service_write():
            OAuthStateSession.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    elif mutation == "ads":
        config.platform_config = {"api_type": "advertising"}
        config.save()
    elif mutation == "no_external":
        store.external_store_id = ""
        store.save(update_fields=["external_store_id"])
    response = client.post(MANUAL, payload, format="json")
    assert response.status_code >= 400
    exchange.assert_not_called()
    assert not MarketplaceStoreAuthorization.objects.exists()
    assert OAuthStateSession.objects.get().status == "pending"


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
@pytest.mark.parametrize("during_exchange", [False, True])
def test_wrong_or_concurrently_changed_store_cleans_new_references(recovery, during_exchange):
    client, store, _, payload, exchange, result, cleanup, _ = recovery
    if during_exchange:
        def change_target(_payload):
            type(store).objects.filter(pk=store.pk).update(external_store_id="FAKE_CHANGED_TARGET")
            return result
        exchange.side_effect = change_target
    else:
        result["platform_store_records"][0]["platform_store_id"] = "FAKE_OTHER_SHOP"
    response = client.post(MANUAL, payload, format="json")
    assert response.status_code == 409
    cleanup.assert_called_once_with(result["credential_id"], result["token_id"])
    assert not MarketplaceStoreAuthorization.objects.exists()
    assert OAuthStateSession.objects.get().status == "failed"


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
@pytest.mark.parametrize("other_tenant", [False, True])
def test_recovery_nonce_is_not_transferable_between_users(recovery, other_tenant):
    from apps.accounts.models import CustomUser
    from apps.tenants.models import Tenant
    client, store, _, payload, exchange, _, _, _ = recovery
    tenant = Tenant.objects.create(name="Other", code="other-recovery") if other_tenant else store.tenant
    actor = CustomUser.objects.create_user(username="other-recovery", tenant=tenant, is_superuser=True, user_type="internal")
    client.force_authenticate(actor)
    assert client.post(MANUAL, payload, format="json").status_code >= 400
    exchange.assert_not_called()
    assert OAuthStateSession.objects.get().status == "pending"


@pytest.mark.parametrize("marketplace_callback", ["shopee"], indirect=True)
def test_shopee_cannot_use_tiktok_recovery(marketplace_callback):
    client, _, _, params, payload = marketplace_callback
    payload["callback_url"] = payload["callback_url"].replace("state=" + params["state"], "removed_state=" + params["state"])
    payload.update(tiktok_pending_token=params["state"], tiktok_manual_confirmed=True)
    assert client.post(MANUAL, payload, format="json").status_code == 400
    assert OAuthStateSession.objects.get().status == "pending"


@pytest.mark.parametrize("marketplace_callback", ["shopee"], indirect=True)
def test_shopee_rejects_even_false_tiktok_confirmation_field(marketplace_callback):
    client, _, _, _, payload = marketplace_callback
    payload["tiktok_manual_confirmed"] = False
    assert client.post(MANUAL, payload, format="json").status_code == 400
    assert OAuthStateSession.objects.get().status == "pending"


def test_pending_token_is_masked_by_existing_audit_policy():
    assert sanitize_audit_detail({"tiktok_pending_token": "FAKE_NONCE", "tiktok_manual_confirmed": True}) == {"tiktok_manual_confirmed": True}


@pytest.mark.parametrize("case", ["unique", "missing", "duplicate", "region", "cleanup_failure"])
def test_live_provider_exact_target_selection_and_cleanup(monkeypatch, case):
    from apps.integrations.oauth_errors import OAuthFlowError
    custody = Mock()
    provider = TikTokLiveOAuthProvider({"app_id": "FAKE_APP", "market": "ROW", "token_path": "/fake/token"}, custody=custody, http_client=Mock())
    monkeypatch.setattr(provider, "_preflight", lambda *args: None)
    monkeypatch.setattr(provider, "_app_secret", lambda: "FAKE_SECRET")
    monkeypatch.setattr(provider, "_token_request", Mock(return_value=({"access_token": "FAKE_ACCESS", "refresh_token": "FAKE_REFRESH",
        "open_id": "FAKE_SUBJECT", "granted_scopes": [], "access_token_expire_in": 3600}, "FAKE_REQUEST")))
    monkeypatch.setattr(provider, "_store_tokens", lambda **kwargs: {"credential_id": "FAKE_CREDENTIAL", "token_id": "FAKE_TOKEN"})
    target = {"platform_store_id": "FAKE_TARGET", "region": "MY", "shop_cipher": "FAKE_CIPHER"}
    other = {**target, "platform_store_id": "FAKE_OTHER"}
    shops = [other, target]
    if case in {"missing", "cleanup_failure"}:
        shops = [other]
    elif case == "duplicate":
        shops = [target, target]
    elif case == "region":
        shops = [{**target, "region": "PH"}]
    monkeypatch.setattr(provider, "_fetch_authorized_shops_all", lambda _: shops)
    if case == "cleanup_failure":
        custody.revoke.side_effect = RuntimeError("FAKE_SECRET_MUST_NOT_LEAK")
    payload = {"code": "FAKE_CODE", "region": "MY", "scopes": [], "target_shop_id": "FAKE_TARGET"}
    if case == "unique":
        result = provider.exchange_authorization_code(payload)
        assert result["platform_store_records"] == [target]
        custody.revoke.assert_not_called()
    else:
        with pytest.raises(OAuthFlowError) as error:
            provider.exchange_authorization_code(payload)
        assert "FAKE_SECRET" not in str(error.value)
        if case == "cleanup_failure":
            assert error.value.tiktok_cleanup_pending is True
        custody.revoke.assert_called_once_with("FAKE_CREDENTIAL", "FAKE_TOKEN")
    provider.http.request.assert_not_called()


@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
def test_cleanup_failure_is_recorded_without_claiming_success(recovery):
    from apps.integrations.models import IntegrationAuditLog
    client, _, _, payload, _, result, cleanup, _ = recovery
    result["platform_store_records"][0]["platform_store_id"] = "FAKE_OTHER_SHOP"
    cleanup.side_effect = RuntimeError("FAKE_SECRET_MUST_NOT_LEAK")
    response = client.post(MANUAL, payload, format="json")
    assert response.status_code == 409
    assert "FAKE_SECRET" not in str(response.data)
    assert not MarketplaceStoreAuthorization.objects.exists()
    assert IntegrationAuditLog.objects.filter(masked_detail__result_code="TIKTOK_MANUAL_REFERENCE_CLEANUP_PENDING").exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)
def test_mysql_concurrent_recovery_exchanges_exactly_once(recovery, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import connection, close_old_connections
    from rest_framework.test import APIClient
    from apps.accounts.models import CustomUser
    if connection.vendor != "mysql":
        pytest.skip("Concurrent consume requires independent MySQL connections")
    client, _, _, payload, exchange, _, _, _ = recovery
    actor_id = client.handler._force_user.pk
    barrier = Barrier(2)
    original = service.consume_oauth_state
    def simultaneous(*args, **kwargs):
        barrier.wait(timeout=10)
        return original(*args, **kwargs)
    monkeypatch.setattr(service, "consume_oauth_state", simultaneous)
    def submit():
        close_old_connections()
        try:
            worker = APIClient()
            worker.force_authenticate(CustomUser.objects.get(pk=actor_id))
            return worker.post(MANUAL, payload, format="json").status_code
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: submit(), range(2)))
    assert sorted(statuses) == [200, 409]
    assert exchange.call_count == 1
    assert MarketplaceStoreAuthorization.objects.count() == 1
