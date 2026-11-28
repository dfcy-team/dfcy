from datetime import timedelta
from unittest.mock import patch
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.flash_sales import engine
from apps.flash_sales.models import StoreTask
from apps.flash_sales.provider import Deferred, ShopeeAdapter
from apps.flash_sales.services import submit
from tests.test_flash_sales import shop, configured

pytestmark = pytest.mark.django_db


def test_live_lease_renews_during_long_pagination(shop):
    configured(shop)
    user, store, _ = shop
    task = submit(user, request_id="long-pagination", store_ids=[store.pk]).tasks.get()
    start = timezone.now()
    task = engine.claim(task.pk, now=start)
    with patch("apps.flash_sales.engine.timezone.now", return_value=start + timedelta(seconds=150)):
        engine.fence(task)
    with patch("apps.flash_sales.engine.timezone.now", return_value=start + timedelta(seconds=240)):
        engine.fence(task)
    task.refresh_from_db()
    assert task.lease_until > start + timedelta(seconds=300)


def test_expired_lease_cannot_be_revived(shop):
    configured(shop)
    user, store, _ = shop
    task = engine.claim(submit(user, request_id="expired", store_ids=[store.pk]).tasks.get().pk)
    expired = timezone.now() - timedelta(seconds=1)
    StoreTask.objects.filter(pk=task.pk).update(lease_until=expired)
    with pytest.raises(engine.LeaseLost):
        engine.fence(task)
    task.refresh_from_db()
    assert task.lease_until == expired


def test_platform_cooldown_blocks_other_adapter_but_not_other_partner(shop):
    _, store, _ = shop
    first, second = ShopeeAdapter(store), ShopeeAdapter(store)
    first._cooldown("synthetic-partner", 450)
    with pytest.raises(Deferred) as blocked:
        second._pace("synthetic-partner")
    assert blocked.value.retry_after >= 449
    second._pace("another-synthetic-partner")


def test_shorter_cooldown_cannot_shorten_existing_wait(shop):
    _, store, _ = shop
    adapter = ShopeeAdapter(store)
    adapter._cooldown("synthetic-partner", 600)
    adapter._cooldown("synthetic-partner", 30)
    with pytest.raises(Deferred) as blocked:
        adapter._pace("synthetic-partner")
    assert blocked.value.retry_after >= 599


def test_shared_cooldown_does_not_pause_task_as_failed(shop, monkeypatch):
    from apps.flash_sales.provider import SharedCooldown
    configured(shop)
    user, store, _ = shop
    task = submit(user, request_id="cooldown", store_ids=[store.pk]).tasks.get()
    def waiting(*args):
        raise SharedCooldown("应用共享限流等待", retry_after=300)
    monkeypatch.setattr(engine, "step", waiting)
    for _ in range(4):
        StoreTask.objects.filter(pk=task.pk).update(next_attempt_at=timezone.now())
        assert engine.run_step(task.pk, adapter=object()) == "waiting"
    task.refresh_from_db()
    assert not task.state.get("retry_paused")
    assert task.retry_count == 0
    assert task.next_attempt_at > timezone.now() + timedelta(seconds=290)


@pytest.mark.parametrize("http_error", [True, False])
def test_rate_response_stops_same_shop_endpoint_before_transport(shop, settings, http_error):
    from apps.flash_sales.provider import SharedCooldown
    from apps.integrations.oauth_errors import OAuthFlowError, OAUTH_RATE_LIMITED
    settings.FLASH_SALES_LIVE_ENABLED = True
    _, store, _ = shop
    auth = SimpleNamespace(expires_at=timezone.now() + timedelta(days=1), platform_store_id="123",
        token_id="synthetic-token-ref", integration_config=SimpleNamespace(network_enabled=True,
        status="verified", credential_id="synthetic-secret-ref", platform_config={"partner_id": "test-partner"}))
    custody = SimpleNamespace(retrieve_secret=lambda _: "synthetic-secret", retrieve_access_token=lambda _: "synthetic-token")
    limited = OAuthFlowError(OAUTH_RATE_LIMITED, "synthetic limit")
    limited.retry_after = 450
    response = SimpleNamespace(status_code=200, json=lambda: {"error": "error_rate_limit"})
    with patch("apps.flash_sales.provider.authorized_store", return_value=auth), \
         patch("apps.flash_sales.provider.get_runtime_platform_config", return_value={"api_host": "https://partner.shopeemobile.com"}), \
         patch("apps.flash_sales.provider.checked_custody_backend", return_value=custody), \
         patch("apps.flash_sales.provider.PlatformHttpClient.request", side_effect=limited if http_error else None, return_value=response) as send:
        with pytest.raises(Deferred) as first:
            ShopeeAdapter(store).call("get_shop_flash_sale_list")
        assert first.value.retry_after == (450 if http_error else 300)
        with pytest.raises(SharedCooldown):
            ShopeeAdapter(store).call("get_shop_flash_sale_list")
        assert send.call_count == 1


def test_replaced_fence_cannot_renew_new_workers_lease(shop):
    import uuid
    configured(shop)
    user, store, _ = shop
    task = engine.claim(submit(user, request_id="replaced", store_ids=[store.pk]).tasks.get().pk)
    new_fence = uuid.uuid4()
    until = timezone.now() + timedelta(seconds=30)
    StoreTask.objects.filter(pk=task.pk).update(fence=new_fence, lease_until=until)
    with pytest.raises(engine.LeaseLost):
        engine.fence(task)
    task.refresh_from_db()
    assert task.fence == new_fence and task.lease_until == until
