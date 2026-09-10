from urllib.parse import urlencode

import pytest
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient

from apps.integrations.models import MarketplaceStoreAuthorization, OAuthStateSession, oauth_state_service_write
from tests.test_lazada_store_authorization import lazada_context

pytestmark = pytest.mark.django_db
ENDPOINT = "/api/internal/integrations/store-authorizations/oauth/manual-callback/"


def pending(context):
    client, store, config = context
    response = client.post("/api/internal/integrations/store-authorizations/oauth/start/", {
        "platform": "lazada", "integration_config_id": config.pk, "store_id": store.pk,
        "region": "MY", "redirect_uri": config.callback_url, "scopes": [],
    }, format="json")
    assert response.status_code == 201
    params = response.data["data"]["simulation_callback"]
    return {"store_id": store.pk, "integration_config_id": config.pk,
            "callback_url": config.callback_url + "?" + urlencode(params)}


def test_manual_callback_completes_and_replay_is_rejected(lazada_context):
    client, store, _ = lazada_context
    payload = pending(lazada_context)
    response = client.post(ENDPOINT, payload, format="json")
    assert response.status_code == 200, response.data
    assert MarketplaceStoreAuthorization.objects.get(store=store).status == "active"
    assert payload["callback_url"] not in str(response.data)
    assert client.post(ENDPOINT, payload, format="json").status_code >= 400
    assert MarketplaceStoreAuthorization.objects.count() == 1


@pytest.mark.parametrize("mutation", ["host", "path", "duplicate", "no_state", "store", "config"])
def test_mismatched_callback_does_not_consume_state(lazada_context, mutation):
    client, _, _ = lazada_context
    payload = pending(lazada_context)
    if mutation == "host":
        payload["callback_url"] = payload["callback_url"].replace("example.test", "wrong.example.test")
    elif mutation == "path":
        payload["callback_url"] = payload["callback_url"].replace("/callback/lazada/", "/callback/shopee/")
    elif mutation == "duplicate":
        payload["callback_url"] += "&state=FAKE_DUPLICATE"
    elif mutation == "no_state":
        payload["callback_url"] = "https://example.test/?code=FAKE_CODE"
    else:
        payload[mutation + "_id" if mutation == "store" else "integration_config_id"] += 1000
    response = client.post(ENDPOINT, payload, format="json")
    assert response.status_code == 400
    assert OAuthStateSession.objects.get().status == "pending"
    assert not MarketplaceStoreAuthorization.objects.exists()


def test_expired_callback_and_anonymous_request_are_rejected(lazada_context):
    client, _, _ = lazada_context
    payload = pending(lazada_context)
    assert APIClient().post(ENDPOINT, payload, format="json").status_code in (401, 403)
    with oauth_state_service_write():
        OAuthStateSession.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    assert client.post(ENDPOINT, payload, format="json").status_code >= 400
    assert not MarketplaceStoreAuthorization.objects.exists()


@pytest.mark.parametrize("other_tenant", [False, True])
def test_another_user_cannot_consume_callback_even_as_superuser(lazada_context, other_tenant):
    from apps.accounts.models import CustomUser
    from apps.tenants.models import Tenant
    client, store, _ = lazada_context
    payload = pending(lazada_context)
    tenant = Tenant.objects.create(code="other-callback", name="Other") if other_tenant else store.tenant
    other = CustomUser.objects.create_user(username="another-callback-user", tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL, is_superuser=True)
    client.force_authenticate(other)
    assert client.post(ENDPOINT, payload, format="json").status_code == 400
    assert OAuthStateSession.objects.get().status == "pending"
    assert not MarketplaceStoreAuthorization.objects.exists()
