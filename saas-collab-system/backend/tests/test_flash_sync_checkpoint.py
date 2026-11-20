import copy
from types import SimpleNamespace

import pytest

from apps.flash_sales.provider import RateLimited, ShopeeAdapter


@pytest.mark.parametrize("operation", ["activities", "items"])
def test_sync_resumes_pages_after_rate_limit_and_rechecks_first_page(operation):
    adapter = ShopeeAdapter(SimpleNamespace())
    adapter.read_checkpoint = {}
    saved = {}
    def save():
        saved.clear()
        saved.update(copy.deepcopy(adapter.read_checkpoint))
    adapter.save_read_checkpoint = save
    calls = []
    rows = [{"flash_sale_id": i, "item_id": i + 1, "status": 1} for i in range(350)]
    field = "flash_sale_list" if operation == "activities" else "item_info"
    fail = [True]
    def call(endpoint, *, query):
        offset = query["offset"]
        calls.append(offset)
        if offset == 300 and fail[0]:
            fail[0] = False
            raise RateLimited("synthetic rate limit", retry_after=300)
        return {field: copy.deepcopy(rows[offset:offset+100]), "total_count": len(rows)}
    adapter.call = call
    run = lambda: adapter.activities(kinds=(1,)) if operation == "activities" else adapter.items("123")
    with pytest.raises(RateLimited):
        run()
    adapter.read_checkpoint = copy.deepcopy(saved)  # Next worker invocation.
    if operation == "items":
        adapter.read_checkpoint["other-activity"] = {"pages": {"0": {"item_info": []}}, "saved_at": 1}
    result = run()
    assert len(result) == 350
    assert calls == [0, 100, 200, 300, 0, 300]
    if operation == "items":
        assert list(adapter.read_checkpoint) == ["other-activity"]
    else:
        assert adapter.read_checkpoint == {} and saved == {}


def test_changed_first_page_invalidates_cached_sync_pages():
    adapter = ShopeeAdapter(SimpleNamespace())
    adapter.read_checkpoint = {}
    adapter.save_read_checkpoint = lambda: None
    rows = [{"flash_sale_id": i} for i in range(250)]
    calls, failed = [], [False]
    def call(endpoint, *, query):
        offset = query["offset"]
        calls.append(offset)
        if offset == 200 and not failed[0]:
            failed[0] = True
            raise RateLimited("synthetic")
        return {"flash_sale_list": copy.deepcopy(rows[offset:offset+100]), "total_count": len(rows)}
    adapter.call = call
    with pytest.raises(RateLimited):
        adapter.activities(kinds=(1,))
    rows[0]["flash_sale_id"] = 1000
    result = adapter.activities(kinds=(1,))
    assert len(result) == 250 and result[0]["flash_sale_id"] == 1000
    assert calls == [0, 100, 200, 0, 100, 200]


def test_write_verification_adapter_never_reuses_sync_pages():
    adapter = ShopeeAdapter(SimpleNamespace())
    calls = []
    adapter.call = lambda endpoint, query: calls.append(query["offset"]) or {"item_info": [], "total_count": 0}
    adapter.items("123")
    adapter.items("123")
    assert calls == [0, 0]


from datetime import timedelta
from django.utils import timezone
from apps.flash_sales import engine
from apps.flash_sales.models import Activity
from apps.flash_sales.services import submit
from tests.test_flash_sales import shop


@pytest.mark.django_db
@pytest.mark.parametrize("complete", [True, False])
def test_only_complete_active_sync_retires_missing_current_cache(shop, complete):
    user, store, _ = shop
    now = timezone.now()
    row = Activity.objects.create(tenant=user.tenant, store=store, platform_id="stale", slot_id="old-slot",
        starts_at=now-timedelta(hours=1), ends_at=now+timedelta(hours=1), platform_status=1,
        item_count=31, enabled_count=31, synced_at=now-timedelta(days=1))
    expired = Activity.objects.create(tenant=user.tenant, store=store, platform_id="history", slot_id="history-slot",
        starts_at=now-timedelta(days=2), ends_at=now-timedelta(days=1), platform_status=1,
        item_count=1, enabled_count=1, synced_at=now-timedelta(days=1))
    class Adapter:
        def activities(self, *, window, kinds):
            assert kinds == (1, 2)
            if not complete:
                raise RateLimited("synthetic")
            return []
    task = submit(user, request_id="stale-cache",store_ids=[store.id],operation="sync").tasks.get()
    engine.run_step(task.id,adapter=Adapter())
    row.refresh_from_db()
    expired.refresh_from_db()
    assert row.platform_status == (0 if complete else 1)
    assert expired.platform_status == 1
    assert not task.intents.exists()
