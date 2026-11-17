from datetime import timedelta
import hashlib
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.flash_sales import engine
from apps.flash_sales.models import Activity, AppPacer, Batch, StoreLock, StoreTask
from apps.flash_sales.provider import Deferred, ShopeeAdapter
from apps.flash_sales.services import submit
from apps.flash_sales.tasks import prepare_post_sync
from tests.test_flash_activity_pagination import reader, activity
from tests.test_flash_sales import shop, configured, FakeShopee, drain


def test_source_selection_skips_large_history_when_active_source_exists():
    rows = [activity(i) for i in range(2558)] + [dict(activity(3000, kind=1), item_count=1)]
    baseline, old_calls = reader(rows)
    baseline.activities()
    adapter, calls = reader(rows)
    selected = next(adapter.candidate_activities({}, lambda: None))
    assert selected['flash_sale_id'] == 3000
    assert len(old_calls) == 47 and len(calls) == 2
    assert {q['type'] for q in calls} == {1, 2}


def test_source_pagination_resumes_at_failed_page_without_replaying_completed_pages():
    rows = [dict(activity(i), item_count=0 if i < 100 else 1) for i in range(101)]
    adapter, calls = reader(rows)
    original = adapter.call
    failed = False
    def call(endpoint, *, query):
        nonlocal failed
        if query['type'] == 3 and query['offset'] == 100 and not failed:
            failed = True
            calls.append(dict(query))
            raise Deferred('synthetic 429')
        return original(endpoint, query=query)
    adapter.call = call
    checkpoint = {}
    with pytest.raises(Deferred):
        next(adapter.candidate_activities(checkpoint, lambda: None))
    assert checkpoint['offset'] == 100
    assert next(adapter.candidate_activities(checkpoint, lambda: None))['flash_sale_id'] == 100
    assert sum(q['type'] == 3 and q['offset'] == 0 for q in calls) == 1
    assert sum(q['type'] == 3 and q['offset'] == 100 for q in calls) == 2


@pytest.mark.django_db
def test_selected_source_survives_wait_for_slots_without_rereading_items(shop):
    user, store, _ = shop
    configured(shop)
    class WaitingSlots(FakeShopee):
        source_reads = 0
        waiting = True
        def items(self, activity_id):
            if str(activity_id) == '10': self.source_reads += 1
            return super().items(activity_id)
        def slots(self):
            if self.waiting:
                self.waiting = False
                raise Deferred('slot read limited')
            return super().slots()
    adapter = WaitingSlots()
    task = submit(user, request_id='reuse-selected-source', store_ids=[store.pk]).tasks.get()
    assert engine.run_step(task.pk, adapter=adapter) == 'waiting'
    assert task.intents.get().status == 'selecting'
    StoreTask.objects.filter(pk=task.pk).update(next_attempt_at=None)
    assert engine.run_step(task.pk, adapter=adapter) == 'queued'
    assert adapter.source_reads == 1 and task.intents.count() == 1
    assert task.intents.get().platform_id == '20'


@pytest.mark.django_db
def test_post_sync_reads_only_affected_activity_and_populates_cache(shop):
    user, store, _ = shop
    configured(shop)
    adapter = FakeShopee()
    task = submit(user, request_id='affected-sync', store_ids=[store.pk]).tasks.get()
    drain(task, adapter)
    prepare_post_sync(task.batch_id)
    child = Batch.objects.get(source='post_sync').tasks.get()
    assert child.snapshot['activity_ids'] == ['20']
    def forbidden(*args, **kwargs): raise AssertionError('full history must not be read')
    adapter.activities = forbidden
    assert engine.run_step(child.pk, adapter=adapter) == 'succeeded'
    assert Activity.objects.get(store=store, platform_id='20').item_count == 1


@pytest.mark.django_db
def test_post_sync_without_writes_finishes_without_platform_reads(shop):
    user, store, _ = shop
    batch = Batch.objects.create(tenant=user.tenant, actor=user, request_id='no-write-sync', payload_hash='test', source='manual', finished_at=timezone.now())
    StoreTask.objects.create(tenant=user.tenant, batch=batch, store=store, status='failed')
    prepare_post_sync(batch.pk)
    child = Batch.objects.get(source='post_sync')
    assert child.finished_at and child.tasks.get().status == 'succeeded'


@pytest.mark.django_db
def test_sync_yields_to_foreground_but_finishes_when_it_already_owns_store_lock(shop):
    user, store, _ = shop
    configured(shop)
    foreground = submit(user, request_id='foreground-priority', store_ids=[store.pk]).tasks.get()
    batch = Batch.objects.create(tenant=user.tenant, actor=user, request_id='background-sync',
                                 payload_hash='test', source='manual', operation='sync')
    sync = StoreTask.objects.create(tenant=user.tenant, batch=batch, store=store)
    assert engine.claim(sync.pk) is None
    StoreLock.objects.update_or_create(store=store, defaults={'tenant': user.tenant, 'task': sync})
    assert engine.claim(foreground.pk) is None
    assert engine.claim(sync.pk) is not None


@pytest.mark.django_db
def test_pacing_uses_four_seconds_and_eight_after_cooldown(shop):
    _, store, _ = shop
    adapter = ShopeeAdapter(store)
    now = timezone.now()
    key = hashlib.sha256(b'shopee:pace:synthetic').hexdigest()
    scope = hashlib.sha256(b'shopee:cooldown:synthetic:11:get_shop_flash_sale_list').hexdigest()
    with patch('apps.flash_sales.provider.timezone.now', return_value=now), patch('apps.flash_sales.provider.time.sleep'):
        adapter._pace('synthetic', shop='11', endpoint='get_shop_flash_sale_list')
        assert AppPacer.objects.get(pk=key).next_request_at == now + timedelta(seconds=4)
        AppPacer.objects.filter(pk=key).update(next_request_at=now)
        AppPacer.objects.create(key=scope, next_request_at=now-timedelta(seconds=1))
        adapter._pace('synthetic', shop='11', endpoint='get_shop_flash_sale_list')
        assert AppPacer.objects.get(pk=key).next_request_at == now + timedelta(seconds=8)
    later = now + timedelta(seconds=121)
    with patch('apps.flash_sales.provider.timezone.now', return_value=later):
        adapter._pace('synthetic', shop='11', endpoint='get_shop_flash_sale_list')
        assert AppPacer.objects.get(pk=key).next_request_at == later + timedelta(seconds=4)
