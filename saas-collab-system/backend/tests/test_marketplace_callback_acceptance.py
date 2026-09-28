"""Shopee/TikTok callback acceptance with synthetic providers, never live OAuth."""
from urllib.parse import urlencode

import pytest
from rest_framework.test import APIClient

from apps.integrations.models import MarketplaceStoreAuthorization, OAuthStateSession, PlatformIntegrationConfig
from tests.test_lazada_store_authorization import lazada_context


pytestmark = pytest.mark.django_db
START = "/api/internal/integrations/store-authorizations/oauth/start/"
MANUAL = "/api/internal/integrations/store-authorizations/oauth/manual-callback/"


@pytest.fixture(params=["shopee", "tiktok"])
def marketplace_callback(request, lazada_context):
    client, store, config = lazada_context
    provider = request.param
    platform = store.platform
    platform.platform_type = provider
    platform.code = provider
    platform.name = provider
    platform.save()
    config.platform = provider
    config.callback_url = (
        "https://example.test/"
        if provider == "shopee"
        else f"https://example.test/api/internal/integrations/store-authorizations/oauth/callback/{provider}/"
    )
    config.contract_version = "v2" if provider == "shopee" else "v202309"
    config.platform_config = {"api_type": "marketplace"}
    config.save()
    response = client.post(START, {
        "platform": provider, "integration_config_id": config.pk,
        "store_id": store.pk, "region": store.country_code,
        "redirect_uri": config.callback_url, "scopes": [],
    }, format="json")
    assert response.status_code == 201, response.data
    params = response.data["data"]["simulation_callback"]
    payload = {
        "store_id": store.pk, "integration_config_id": config.pk,
        "callback_url": config.callback_url + "?" + urlencode(params),
    }
    return client, store, config, params, payload


def test_manual_completion_and_replay_preserve_single_authorization(marketplace_callback):
    client, store, config, _, payload = marketplace_callback
    response = client.post(MANUAL, payload, format="json")
    assert response.status_code == 200, response.data
    authorization = MarketplaceStoreAuthorization.objects.get(store=store)
    assert authorization.platform == config.platform
    assert authorization.status == "active"
    assert payload["callback_url"] not in str(response.data)
    token_reference = authorization.token_id
    replay = client.post(MANUAL, payload, format="json")
    assert replay.status_code == 409
    assert replay.data['data']['reason_code'] == 'OAUTH_STATE_CONSUMED'
    authorization.refresh_from_db()
    assert authorization.token_id == token_reference
    assert MarketplaceStoreAuthorization.objects.filter(store=store).count() == 1


def test_unauthenticated_attempt_does_not_consume_state(marketplace_callback):
    client, store, _, _, payload = marketplace_callback
    rejected = APIClient().post(MANUAL, payload, format="json")
    assert rejected.status_code in (401, 403)
    assert OAuthStateSession.objects.get().status == "pending"
    assert not MarketplaceStoreAuthorization.objects.filter(store=store).exists()
    assert client.post(MANUAL, payload, format="json").status_code == 200


def test_automatic_completion_then_manual_replay_is_non_destructive(marketplace_callback):
    client, store, config, params, payload = marketplace_callback
    automatic = APIClient().get(
        f"/api/internal/integrations/store-authorizations/oauth/callback/{config.platform}/", params,
    )
    assert automatic.status_code == 200, automatic.data
    before = MarketplaceStoreAuthorization.objects.get(store=store)
    assert client.post(MANUAL, payload, format="json").status_code == 409
    after = MarketplaceStoreAuthorization.objects.get(store=store)
    assert (after.pk, after.token_id, after.status) == (before.pk, before.token_id, "active")


def test_shopee_root_registration_is_preserved_for_internal_callback(marketplace_callback):
    _, _, config, _, _ = marketplace_callback
    if config.platform != "shopee":
        pytest.skip("Shopee-only root callback contract")
    session = OAuthStateSession.objects.get()
    assert config.callback_url == "https://example.test/"
    assert session.redirect_uri == "https://example.test/"


def test_shopee_marketplace_and_advertising_authorizations_can_coexist(lazada_context):
    client, store, marketplace_config = lazada_context
    store.platform.platform_type = "shopee"
    store.platform.code = "shopee"
    store.platform.name = "Shopee"
    store.platform.save()
    marketplace_config.platform = "shopee"
    marketplace_config.account_alias = "Shopee marketplace"
    marketplace_config.callback_url = "https://example.test/"
    marketplace_config.contract_version = "v2"
    marketplace_config.platform_config = {"api_type": "marketplace"}
    marketplace_config.save()
    advertising_config = PlatformIntegrationConfig.objects.create(
        tenant=marketplace_config.tenant,
        platform="shopee",
        account_alias="Shopee advertising",
        environment="production",
        status="verified",
        regions=[store.country_code],
        contract_version="v2",
        callback_url="https://example.test/",
        scopes=[],
        platform_config={"api_type": "advertising"},
        created_by=marketplace_config.created_by,
    )

    for config in (marketplace_config, advertising_config):
        start = client.post(START, {
            "platform": "shopee", "integration_config_id": config.pk,
            "store_id": store.pk, "region": store.country_code,
            "redirect_uri": config.callback_url, "scopes": [],
        }, format="json")
        assert start.status_code == 201, start.data
        callback_url = config.callback_url + "?" + urlencode(start.data["data"]["simulation_callback"])
        completed = client.post(MANUAL, {
            "store_id": store.pk,
            "integration_config_id": config.pk,
            "callback_url": callback_url,
        }, format="json")
        assert completed.status_code == 200, completed.data

    authorizations = list(MarketplaceStoreAuthorization.objects.filter(store=store).order_by("integration_config_id"))
    assert len(authorizations) == 2
    assert {item.integration_config_id for item in authorizations} == {marketplace_config.id, advertising_config.id}
    assert {item.status for item in authorizations} == {MarketplaceStoreAuthorization.Status.ACTIVE}
    assert len({item.active_platform_identity_key for item in authorizations}) == 2
    assert len({item.active_store_binding_key for item in authorizations}) == 2

    access = client.get("/api/internal/integrations/subject-api-access/", {
        "subject_type": "store", "subject_id": store.id,
    })
    assert access.status_code == 200, access.data
    assert {item["api_type"] for item in access.data["data"]["bindings"]} == {"marketplace", "advertising"}


def test_wrong_store_does_not_consume_correct_callback(marketplace_callback):
    client, store, _, _, payload = marketplace_callback
    wrong_payload = {**payload, "store_id": store.pk + 10000}
    assert client.post(MANUAL, wrong_payload, format="json").status_code == 400
    assert OAuthStateSession.objects.get().status == "pending"
    assert not MarketplaceStoreAuthorization.objects.exists()
    assert client.post(MANUAL, payload, format="json").status_code == 200


@pytest.mark.parametrize('reason,status', [('OAUTH_AUTH_REJECTED', 401), ('OAUTH_DATABASE_FAILURE', 503)])
def test_callback_error_exposes_only_controlled_reason(marketplace_callback, monkeypatch, reason, status):
    from apps.integrations.oauth_errors import OAuthFlowError
    client, _, _, _, payload = marketplace_callback

    def fail_exchange(**kwargs):
        raise OAuthFlowError(reason, detail='TEST_PROVIDER_SECRET_MUST_NOT_LEAK')

    monkeypatch.setattr('apps.integrations.manual_callback.complete_marketplace_oauth_callback', fail_exchange)
    response = client.post(MANUAL, payload, format='json')
    assert response.status_code == status
    assert response.data['success'] is False
    assert response.data['code'] == 'API_SYNC_FAILED'
    assert response.data['data'] == {'reason_code': reason}
    assert 'TEST_PROVIDER_SECRET_MUST_NOT_LEAK' not in str(response.data)
    assert payload['callback_url'] not in str(response.data)
