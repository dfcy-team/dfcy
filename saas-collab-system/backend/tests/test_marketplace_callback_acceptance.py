"""Shopee/TikTok callback acceptance with synthetic providers, never live OAuth."""
from urllib.parse import urlencode

import pytest
from rest_framework.test import APIClient

from apps.integrations.models import MarketplaceStoreAuthorization, OAuthStateSession
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
    config.callback_url = f"https://example.test/api/internal/integrations/store-authorizations/oauth/callback/{provider}/"
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
