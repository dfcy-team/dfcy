import base64
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.influencers.models import Influencer, InfluencerProfile, TikTokCreatorProfileSnapshot
from apps.influencers.tiktok_creator_lookup import lookup_tiktok_creator
from apps.integrations import automatic_refresh
from apps.integrations.models import (
    InternalAPIClient, MarketplaceStoreAuthorization, TikTokTokenLeaseAudit,
    authorization_service_write,
)
from apps.integrations.production_settings import validate_runtime_config
from apps.integrations.readonly_clients import TikTokReadonlyClient
from apps.integrations.serializers import InternalAPIClientSerializer
from apps.masterdata.models import StoreMaster
from tests.test_lazada_store_authorization import lazada_context
from tests.test_marketplace_callback_acceptance import MANUAL, marketplace_callback


pytestmark = pytest.mark.django_db


def _tiktok_context(marketplace_callback):
    client, store, config, _, payload = marketplace_callback
    if config.platform != "tiktok":
        pytest.skip("TikTok-only pilot")
    assert client.post(MANUAL, payload, format="json").status_code == 200
    store.code = "TK1PH"
    store.save(update_fields=["code"])
    config.network_enabled = True
    config.sync_read_enabled = True
    config.save(update_fields=["network_enabled", "sync_read_enabled"])
    record = MarketplaceStoreAuthorization.objects.get(store=store)
    record.expires_at = timezone.now() + timedelta(hours=2)
    with authorization_service_write():
        record.save(update_fields=["expires_at", "updated_at"])
    binding = {
        "tenant_id": record.tenant_id, "store_code": store.code,
        "region": record.region, "platform_store_id": record.platform_store_id,
    }
    return client, store, config, record, binding


def test_tiktok_pilot_binding_validation_is_exact():
    binding = {"tenant_id": 1, "store_code": "TK1PH", "region": "PH", "platform_store_id": "shop-1"}
    config = validate_runtime_config({"platforms": {"tiktok": {"auto_refresh_bindings": [binding]}}})
    assert config["platforms"]["tiktok"]["auto_refresh_bindings"] == [binding]
    with pytest.raises(Exception):
        validate_runtime_config({"platforms": {"tiktok": {"auto_refresh_bindings": [{**binding, "tenant_id": True}]}}})


def test_only_exact_tiktok_binding_can_refresh_when_global_switch_is_off(monkeypatch):
    binding = {"tenant_id": 1, "store_code": "TK1PH", "region": "PH", "platform_store_id": "shop-1"}
    monkeypatch.setattr(automatic_refresh, "get_runtime_platform_config", lambda platform: {
        "auto_refresh_enabled": False, "auto_refresh_bindings": [binding],
    })
    record = MarketplaceStoreAuthorization(platform="tiktok", tenant_id=1, store=StoreMaster(code="TK1PH"),
                                           region="PH", platform_store_id="shop-1")
    assert automatic_refresh._refresh_enabled_for_record(record)
    record.platform_store_id = "other-shop"
    assert not automatic_refresh._refresh_enabled_for_record(record)
    record.platform_store_id = "shop-1"
    record.tenant_id = 2
    assert not automatic_refresh._refresh_enabled_for_record(record)


def test_creator_client_needs_saved_scope_before_network(monkeypatch):
    client = object.__new__(TikTokReadonlyClient)
    client.authorization = SimpleNamespace(scopes=[], shop_cipher="cipher")
    client._request = Mock()
    monkeypatch.setattr("apps.integrations.readonly_clients.get_runtime_platform_config", lambda platform: {
        "affiliate_seller_creator_scope": "seller.affiliate_collaboration.read",
    })
    with pytest.raises(ValidationError, match="scope"):
        client.fetch_marketplace_creator("123456789")
    client._request.assert_not_called()
    client.authorization.scopes = ["seller.affiliate_collaboration.read"]
    client._request.return_value = {"data": {"creator": {"username": "creator.one", "follower_count": 42}}}
    result = client.fetch_marketplace_creator("123456789")
    assert result["follower_count"] == 42
    assert client._request.call_args.args[0] == "/affiliate_seller/202406/marketplace_creators/123456789"


def test_missing_creator_id_is_candidate_without_network(marketplace_callback, monkeypatch):
    _, _, _, record, _ = _tiktok_context(marketplace_callback)
    creator = Influencer.objects.create(tenant=record.tenant, code="missing-id", name="Missing", platform="TikTok")
    InfluencerProfile.objects.create(tenant=record.tenant, influencer=creator, external_influencer_id="")
    fetch = Mock()
    monkeypatch.setattr(TikTokReadonlyClient, "fetch_marketplace_creator", fetch)
    result = lookup_tiktok_creator(actor=record.updated_by, influencer_id=creator.pk, store_id=record.store_id)
    assert result["reason"] == "external_id_missing"
    assert not TikTokCreatorProfileSnapshot.objects.exists()
    fetch.assert_not_called()


def test_conflicting_creator_id_is_candidate_without_network(marketplace_callback, monkeypatch):
    _, _, _, record, _ = _tiktok_context(marketplace_callback)
    creators = [
        Influencer.objects.create(tenant=record.tenant, code=f"duplicate-{index}", name=f"Creator {index}", platform="TikTok")
        for index in range(2)
    ]
    for creator in creators:
        InfluencerProfile.objects.create(
            tenant=record.tenant, influencer=creator, external_influencer_id="123456789",
        )
    fetch = Mock()
    monkeypatch.setattr(TikTokReadonlyClient, "fetch_marketplace_creator", fetch)

    result = lookup_tiktok_creator(actor=record.updated_by, influencer_id=creators[0].pk, store_id=record.store_id)
    assert result["reason"] == "external_id_conflict"
    assert not TikTokCreatorProfileSnapshot.objects.exists()
    fetch.assert_not_called()


def test_token_client_binding_cannot_cross_tenant_or_share_resources(marketplace_callback):
    _, store, _, record, _ = _tiktok_context(marketplace_callback)
    serializer = InternalAPIClientSerializer(context={"request": SimpleNamespace(user=record.updated_by)})
    valid = {
        "caller_type": InternalAPIClient.CallerType.INTERNAL_SYSTEM,
        "resources": {}, "tiktok_token_store": store, "allow_sso_login": False,
    }
    assert serializer.validate(valid) == valid
    with pytest.raises(ValidationError, match="Token clients cannot also read resources"):
        serializer.validate({**valid, "resources": {"orders": ["id"]}})
    with pytest.raises(ValidationError, match="own-tenant"):
        serializer.validate({**valid, "tiktok_token_store": SimpleNamespace(
            tenant_id=record.tenant_id + 1, code="TK1PH", platform=store.platform,
        )})


def test_creator_lookup_saves_projection_but_does_not_rewrite_identity(marketplace_callback, monkeypatch):
    _, store, _, record, binding = _tiktok_context(marketplace_callback)
    actor = record.updated_by
    creator = Influencer.objects.create(
        tenant=record.tenant, code="trusted-id", name="Old name", platform="TikTok", handle="creator.one",
        follower_count=7,
    )
    profile = InfluencerProfile.objects.create(
        tenant=record.tenant, influencer=creator, external_influencer_id="123456789", display_name="Old name",
    )
    monkeypatch.setattr("apps.influencers.tiktok_creator_lookup.get_runtime_platform_config", lambda platform: {
        "auto_refresh_bindings": [binding],
    })
    monkeypatch.setattr("apps.influencers.tiktok_creator_lookup.check_user_permission", lambda *args: True)
    monkeypatch.setattr("apps.influencers.tiktok_creator_lookup.integration_values_allowed", lambda *args, **kwargs: True)
    fetch = Mock(return_value={"username": "creator.one", "nickname": "Fresh", "selection_region": record.region, "follower_count": 123})
    monkeypatch.setattr(TikTokReadonlyClient, "fetch_marketplace_creator", fetch)
    monkeypatch.setattr("apps.integrations.readonly_clients.get_custody_backend", Mock())
    result = lookup_tiktok_creator(actor=actor, influencer_id=creator.pk, store_id=store.pk)
    assert result["snapshot"]["identity_status"] == "matched"
    assert result["snapshot"]["follower_count"] == 123
    fetch.assert_called_once_with("123456789")
    creator.refresh_from_db()
    profile.refresh_from_db()
    assert (creator.handle, creator.follower_count, profile.display_name) == ("creator.one", 7, "Old name")
    fetch.return_value = {"username": "different", "nickname": "Fresh", "selection_region": record.region, "follower_count": 321}
    result = lookup_tiktok_creator(actor=actor, influencer_id=creator.pk, store_id=store.pk)
    assert result["snapshot"]["identity_status"] == "handle_mismatch"
    assert TikTokCreatorProfileSnapshot.objects.count() == 1


def test_token_handoff_is_single_store_https_and_audited(marketplace_callback, monkeypatch):
    _, store, config, record, binding = _tiktok_context(marketplace_callback)
    actor = record.updated_by
    client_id, secret = "pilot-client", "synthetic-secret"
    InternalAPIClient.objects.create(
        tenant=record.tenant, name="Pilot token reader", caller_type="internal_system",
        client_id=client_id, secret_hash=make_password(secret), secret_prefix="synthetic",
        secret_fingerprint="a" * 64, resources={}, tiktok_token_store=store,
        allowed_cidrs=["127.0.0.1/32"], rate_limit_per_minute=5,
        status="active", approval_status="approved", created_by=actor, updated_by=actor,
    )
    monkeypatch.setattr("apps.integrations.internal_token_broker.get_runtime_platform_config", lambda platform: {
        "access_handoff_approved": True, "contract_approved": True, "auto_refresh_bindings": [binding],
        "app_id": "synthetic-app-key",
    })
    monkeypatch.setattr("apps.integrations.internal_token_broker.get_runtime_setting", lambda *args, **kwargs: True)
    monkeypatch.setattr("apps.integrations.internal_token_broker.is_module_enabled", lambda name: True)
    custody = Mock()
    custody.retrieve_access_token.return_value = "synthetic-access-token"
    monkeypatch.setattr("apps.integrations.internal_token_broker.get_custody_backend", lambda: custody)
    api = APIClient()
    headers = {"HTTP_AUTHORIZATION": "Basic " + base64.b64encode(f"{client_id}:{secret}".encode()).decode()}
    url = "/api/internal-readonly/v1/tiktok-shop-token/"
    assert api.get(url, **headers).status_code == 403
    custody.retrieve_access_token.assert_not_called()
    response = api.get(url, secure=True, **headers)
    assert response.status_code == 200, response.data
    assert response.data["data"]["store_code"] == store.code
    assert response.data["data"]["app_key"] == "synthetic-app-key"
    assert response.data["data"]["shop_cipher"] == record.shop_cipher
    assert response.data["data"]["access_token"] == "synthetic-access-token"
    assert "refresh_token" not in str(response.data)
    assert response["Cache-Control"].startswith("no-store")
    assert TikTokTokenLeaseAudit.objects.count() == 1
    assert "synthetic-access-token" not in str(TikTokTokenLeaseAudit.objects.values().first())
