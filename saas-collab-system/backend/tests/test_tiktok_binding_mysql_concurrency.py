"""Real row-lock probes, exclusively for a disposable MySQL test database."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

import pytest
from django.db import close_old_connections, connection

from apps.integrations import tiktok_shop_binding as binding
from apps.integrations.models import MarketplaceStoreAuthorization, TikTokShopBindingSession
from apps.integrations.oauth_state_service import create_oauth_state
from apps.masterdata.models import StoreMaster
from tests.test_lazada_store_authorization import lazada_context
from tests.test_marketplace_callback_acceptance import marketplace_callback
from tests.test_tiktok_manual_callback_recovery import recovery
from tests.test_tiktok_shop_binding import context, start

pytestmark = [pytest.mark.django_db(transaction=True),
              pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True),
              pytest.mark.skipif(connection.vendor != "mysql", reason="Disposable MySQL row locks required")]


def together(*operations):
    barrier = Barrier(len(operations))
    def run(operation):
        close_old_connections()
        try:
            barrier.wait(timeout=20)
            try:
                return "ok", operation()
            except Exception as exc:
                return "error", type(exc).__name__
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        return list(pool.map(run, operations))


def test_same_confirmation_serializes_to_one_authorization(context):
    actor, store, *_ = context
    pending = start(context)
    sid = pending["candidates"][0]["platform_store_id"]
    outcomes = together(*[lambda: binding.confirm_shop_binding(actor, pending["binding_id"], sid)] * 2)
    assert [outcome[0] for outcome in outcomes] == ["ok", "ok"], outcomes
    assert outcomes[0][1]["authorization_id"] == outcomes[1][1]["authorization_id"]
    assert MarketplaceStoreAuthorization.objects.filter(store=store).count() == 1


def test_two_stores_cannot_claim_the_same_platform_shop(context):
    actor, store, config, params, exchange, result, _ = context
    first = start(context)
    other = StoreMaster.objects.create(tenant=store.tenant, platform=store.platform, code="SYNTHETIC-SECOND",
        name="Synthetic second store", country_code=store.country_code, currency=store.currency, timezone=store.timezone)
    state, _ = create_oauth_state(tenant=actor.tenant, platform="tiktok", actor=actor,
        integration_config=config, store=other, region=store.country_code, redirect_uri=config.callback_url, scopes=[])
    fresh = deepcopy(result)
    fresh["credential_id"] += ".second"
    fresh["token_id"] += ".second"
    exchange.return_value = fresh
    second = binding.start_shop_binding(actor, {**params, "state": state}, callback_state_verified=True)
    sid = first["candidates"][0]["platform_store_id"]
    outcomes = together(lambda: binding.confirm_shop_binding(actor, first["binding_id"], sid),
                        lambda: binding.confirm_shop_binding(actor, second["binding_id"], sid))
    assert sorted(outcome[0] for outcome in outcomes) == ["error", "ok"], outcomes
    assert MarketplaceStoreAuthorization.objects.count() == 1
    assert StoreMaster.objects.filter(pk__in=[store.pk, other.pk], external_store_id=sid).count() == 1
    assert StoreMaster.objects.filter(pk__in=[store.pk, other.pk], external_store_id="").count() == 1


def test_cancel_and_confirm_have_a_single_owner(context):
    actor, _, _, _, _, _, provider = context
    pending = start(context)
    sid = pending["candidates"][0]["platform_store_id"]
    outcomes = together(lambda: binding.confirm_shop_binding(actor, pending["binding_id"], sid),
                        lambda: binding.cancel_shop_binding(actor, pending["binding_id"]))
    row = TikTokShopBindingSession.objects.get(pk=pending["binding_id"])
    assert sorted(outcome[0] for outcome in outcomes) == ["error", "ok"], outcomes
    if row.status == "bound":
        assert MarketplaceStoreAuthorization.objects.count() == 1
        assert binding.cleanup_shop_bindings()["claimed"] == 0
        provider.custody.revoke.assert_not_called()
    else:
        assert row.status == "cancelled" and not MarketplaceStoreAuthorization.objects.exists()
        assert binding.cleanup_shop_bindings()["cleaned"] == 1
        provider.custody.revoke.assert_called_once()
