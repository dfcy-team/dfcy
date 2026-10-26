"""Revoked-shop replacement, using synthetic credentials and isolated DB only."""
import pytest

from apps.integrations import marketplace_oauth_service as oauth
from apps.integrations.models import MarketplaceStoreAuthorization, TikTokShopBindingSession, SyncJob
from apps.integrations.store_authorization_service import transition_store_authorization
from tests.test_tiktok_direct_callback import direct, ENDPOINT
from tests.test_tiktok_manual_callback_recovery import recovery
from tests.test_marketplace_callback_acceptance import marketplace_callback
from tests.test_lazada_store_authorization import lazada_context

pytestmark = [pytest.mark.django_db(transaction=True),
              pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)]


@pytest.fixture
def replacement(direct):
    client, store, config, session, payload, exchange, result, _, _ = direct
    actor = client.handler._force_user
    old = oauth._create_authorization_from_exchange(session, result, result["platform_store_records"][0])
    old = transition_store_authorization(old, target_status="revoked", actor=actor)
    result["credential_id"] += "-replacement"
    result["token_id"] += "-replacement"
    result["platform_store_records"][0].update(platform_store_id="NEW_MY_SHOP", name="NAHARA MY Store")
    return client, store, config, payload, exchange, old, actor


def preview(context):
    client, _, _, payload, _, _, _ = context
    response = client.post(ENDPOINT, payload, format="json")
    assert response.status_code == 200, response.data
    assert response.data["data"]["status"] == "pending_confirmation"
    return response.data["data"]


def confirm(client, pending):
    return client.post('/api/internal/integrations/store-authorizations/oauth/tiktok-shop-bindings/'
                       + pending['binding_id'] + '/confirm/', {"platform_store_id": "NEW_MY_SHOP"}, format="json")


def test_revoked_replacement_requires_confirmation_and_keeps_old_history(replacement):
    from apps.listings.models import PlatformProductDetail
    client, store, _, payload, exchange, old, _ = replacement
    previous_id = store.external_store_id
    detail = PlatformProductDetail.objects.create(tenant=store.tenant, store=store,
        platform=store.platform, platform_product_id="OLD_PRODUCT", platform_variant_id="OLD_VARIANT")
    payload["callback_params"].pop("state")
    payload["manual_import_confirmed"] = True
    pending = preview(replacement)
    assert pending["replacement"] and pending["previous_platform_store_id"] == previous_id
    store.refresh_from_db()
    assert store.external_store_id == previous_id
    assert exchange.call_args.args[0]["discover_shop_binding"]
    assert not exchange.call_args.args[0].get("target_shop_id")
    result = confirm(client, pending)
    assert result.status_code == 200, result.data
    store.refresh_from_db(); old.refresh_from_db(); detail.refresh_from_db()
    assert store.external_store_id == "NEW_MY_SHOP"
    assert store.name == store.platform_store_name == "NAHARA MY Store"
    assert old.status == "revoked" and old.platform_store_id == previous_id
    assert detail.platform_product_id == "OLD_PRODUCT" and detail.store_id == store.pk
    assert MarketplaceStoreAuthorization.objects.filter(store=store, status="active").count() == 1
    assert confirm(client, pending).status_code == 200
    assert exchange.call_count == 1
    assert not SyncJob.objects.filter(store_authorization__store=store, is_enabled=True).exists()


@pytest.mark.parametrize('change', ['new_active', 'enabled_job', 'identity', 'admin'])
def test_replacement_confirmation_rechecks_state(replacement, change):
    client, store, config, _, _, old, actor = replacement
    pending = preview(replacement)
    from apps.integrations.models import authorization_service_write
    if change == 'new_active':
        with authorization_service_write():
            from apps.integrations.models import marketplace_active_identity_key, marketplace_store_binding_key
            old.status = 'active'
            old.active_platform_identity_key = marketplace_active_identity_key(old.platform, old.region, old.platform_store_id)
            old.active_store_binding_key = marketplace_store_binding_key(old.tenant_id, old.platform, old.store_id)
            old.save()
    elif change == 'enabled_job':
        SyncJob.objects.create(tenant=store.tenant, integration_config=config, store_authorization=old,
                               resource_type='platform_product', is_enabled=True)
    elif change == 'identity':
        store.external_store_id = 'ANOTHER'; store.save()
    else:
        actor.is_superuser = False; actor.save(update_fields=['is_superuser'])
    assert confirm(client, pending).status_code >= 400
    store.refresh_from_db()
    assert store.external_store_id != 'NEW_MY_SHOP'
    assert TikTokShopBindingSession.objects.get().status == 'pending_confirmation'


def test_replacement_conflict_and_persistence_failure_do_not_change_store(replacement, monkeypatch):
    from apps.masterdata.models import StoreMaster
    client, store, _, _, _, _, _ = replacement
    previous_id = store.external_store_id
    pending = preview(replacement)
    StoreMaster.objects.create(tenant=store.tenant, platform=store.platform, code='other', name='Other',
                               country_code=store.country_code, external_store_id='NEW_MY_SHOP')
    assert confirm(client, pending).status_code >= 400
    store.refresh_from_db()
    assert store.external_store_id == previous_id


def test_replacement_save_failure_rolls_back_identity(replacement, monkeypatch):
    from apps.integrations.tiktok_shop_binding import confirm_shop_binding
    client, store, _, _, _, _, actor = replacement
    previous_id, previous_name = store.external_store_id, store.name
    pending = preview(replacement)
    def fail(*args):
        raise RuntimeError('synthetic persistence failure')
    monkeypatch.setattr(oauth, '_create_authorization_from_exchange', fail)
    with pytest.raises(RuntimeError):
        confirm_shop_binding(actor, pending['binding_id'], 'NEW_MY_SHOP')
    store.refresh_from_db()
    assert (store.external_store_id, store.name) == (previous_id, previous_name)
