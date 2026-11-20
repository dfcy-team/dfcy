import pytest
from apps.flash_sales import engine
from apps.flash_sales.models import StoreTask, StoreLock
from apps.flash_sales.services import submit, request_stop
from tests.test_flash_sales import shop, configured, FakeShopee, drain

pytestmark = pytest.mark.django_db


class LostAdd(FakeShopee):
    def call(self, endpoint, *, body):
        if endpoint == 'add_shop_flash_sale_items':
            from apps.flash_sales.provider import UnknownWrite
            self.calls.append((endpoint, body))
            raise UnknownWrite('synthetic unknown add')
        return super().call(endpoint, body=body)


def test_unknown_owned_add_cleans_before_three_rebuilds_and_finishes(shop):
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id='unknown-add-bounded', store_ids=[store.id]).tasks.get()
    adapter = LostAdd()
    drain(task, adapter, 80)
    assert task.status == 'failed' and task.finished_at
    assert not task.state.get('retry_paused')
    assert task.intents.count() == 4
    assert all(i.absence_evidence.get('absent') for i in task.intents.all())
    assert sum(e == 'create_shop_flash_sale' for e, _ in adapter.calls) == 4
    assert sum(e == 'delete_shop_flash_sale' for e, _ in adapter.calls) == 4
    task.batch.refresh_from_db()
    assert task.batch.finished_at


def test_unowned_unknown_create_finishes_without_delete_or_duplicate(shop):
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id='unknown-create-bounded', store_ids=[store.id]).tasks.get()
    adapter = FakeShopee(lose_create=True)
    drain(task, adapter, 30)
    assert task.status == 'failed' and task.finished_at and task.state['recovery_pending']
    assert not task.state.get('retry_paused')
    intent = task.intents.get()
    assert intent.reservation_key and not intent.absence_evidence.get('absent')
    assert StoreLock.objects.get(store=store).task_id == task.pk
    assert sum(e == 'create_shop_flash_sale' for e, _ in adapter.calls) == 1
    assert not any(e == 'delete_shop_flash_sale' for e, _ in adapter.calls)


def test_stop_unpauses_original_task_without_releasing_protection(shop):
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id='stop-paused-original', store_ids=[store.id]).tasks.get()
    adapter = FakeShopee()
    engine.run_step(task.id, adapter=adapter)
    StoreTask.objects.filter(pk=task.pk).update(status='confirming', state={'retry_paused': True, 'no_progress_count': 3}, next_attempt_at=None)
    request_stop(task.batch)
    task.refresh_from_db()
    assert not task.state.get('retry_paused')
    assert StoreLock.objects.get(store=store).task_id == task.pk
    drain(task, adapter)
    assert task.status == 'stopped' and task.intents.get().absence_evidence.get('absent')


def test_final_summary_includes_unknown_cleanup_and_pending_specs(shop):
    from apps.flash_sales.notifications import task_result
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id='unknown-create-summary', store_ids=[store.id]).tasks.get()
    drain(task, FakeShopee(lose_create=True), 30)
    result = task_result(task)
    assert '未确认' in result['cleanup']
    assert result['unconfirmed_specifications'] > 0
    assert result['verification_retries'] >= 3


def test_terminal_readonly_followup_keeps_active_protection_and_releases_verified_absence(shop):
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id='followup-protection', store_ids=[store.id]).tasks.get()
    adapter = FakeShopee(lose_create=True)
    drain(task, adapter, 30)
    calls = list(adapter.calls)
    engine.reconcile_failed(task.id, adapter=adapter)
    task.refresh_from_db()
    assert task.state['recovery_pending'] and StoreLock.objects.get(store=store).task_id == task.id
    adapter.created.clear()  # An independent, confirmed platform deletion.
    engine.reconcile_failed(task.id, adapter=adapter)
    task.refresh_from_db()
    assert task.status == 'failed' and task.finished_at and not task.state['recovery_pending']
    assert StoreLock.objects.get(store=store).task_id is None
    assert task.intents.get().absence_evidence['absent']
    assert adapter.calls == calls


def test_next_batch_fails_explicitly_when_previous_uncertain_write_still_protected(shop):
    user, store, _ = shop
    configured(shop)
    old = submit(user, request_id='protected-old', store_ids=[store.id]).tasks.get()
    drain(old, FakeShopee(lose_create=True), 30)
    new = submit(user, request_id='protected-new', store_ids=[store.id]).tasks.get()
    engine.run_step(new.id, adapter=object())
    new.refresh_from_db()
    new.batch.refresh_from_db()
    assert new.status == 'failed' and new.batch.finished_at
    assert StoreLock.objects.get(store=store).task_id == old.id


def test_cleanup_mismatching_slot_never_deletes(shop):
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id='cleanup-slot-mismatch', store_ids=[store.id]).tasks.get()
    adapter = FakeShopee(reject_all=True)
    engine.run_step(task.id, adapter=adapter)
    adapter.created['20']['timeslot_id'] = 123456
    drain(task, adapter, 30)
    assert task.status == 'failed' and task.state['recovery_pending']
    assert not any(e == 'delete_shop_flash_sale' for e, _ in adapter.calls)


def test_partial_store_permission_allows_own_resume_and_reconcile_only(shop):
    from apps.flash_sales.models import Batch, StoreConfig
    from apps.masterdata.models import StoreMaster
    from tests.test_flash_access_boundaries import scoped_client
    user, store, _ = shop
    configured(shop)
    hidden = StoreMaster.objects.create(tenant=user.tenant, platform=store.platform, code='hidden', name='Hidden')
    StoreConfig.objects.create(tenant=user.tenant, store=hidden, stock=1)
    batch = Batch.objects.create(tenant=user.tenant, actor=user, source='manual', request_id='mixed-recovery', payload_hash='x')
    own = StoreTask.objects.create(tenant=user.tenant, batch=batch, store=store, status='confirming', state={'retry_paused': True})
    other = StoreTask.objects.create(tenant=user.tenant, batch=batch, store=hidden, status='confirming', state={'retry_paused': True})
    StoreLock.objects.update_or_create(store=store, defaults={'tenant': user.tenant, 'task': own})
    _, client = scoped_client(shop, ('view', 'execute'))
    url = f'/api/internal/marketing/flash-sales/batches/{batch.id}/'
    assert client.post(url, {'action': 'resume', 'task_id': own.id, 'confirmed': True}, format='json').status_code == 200
    assert client.post(url, {'action': 'reconcile', 'task_id': own.id}, format='json').status_code == 200
    assert client.post(url, {'action': 'resume', 'task_id': other.id, 'confirmed': True}, format='json').status_code == 403
    assert client.post(url, {'action': 'reconcile', 'task_id': other.id}, format='json').status_code == 403
    assert client.post(url, {'action': 'stop'}, format='json').status_code == 403
    assert client.post(url, {'action': 'reconcile'}, format='json').status_code == 403


def test_store_cooldown_recovery_does_not_slow_application_or_other_shop(shop):
    import hashlib
    from datetime import timedelta
    from unittest.mock import patch
    from django.utils import timezone
    from apps.flash_sales.provider import ShopeeAdapter
    from apps.flash_sales.models import AppPacer
    _, store, _ = shop
    adapter = ShopeeAdapter(store)
    now = timezone.now()
    key = lambda s: hashlib.sha256(s.encode()).hexdigest()
    AppPacer.objects.create(key=key('shopee:cooldown:synthetic:11:items'), next_request_at=now-timedelta(seconds=1))
    with patch('apps.flash_sales.provider.timezone.now', return_value=now), patch('apps.flash_sales.provider.time.sleep'):
        adapter._pace('synthetic', shop='11', endpoint='items')
        assert AppPacer.objects.get(pk=key('shopee:pace:synthetic')).next_request_at == now+timedelta(seconds=4)
        assert AppPacer.objects.get(pk=key('shopee:pace:synthetic:11:items')).next_request_at == now+timedelta(seconds=8)
        adapter._pace('synthetic', shop='22', endpoint='items')
        assert AppPacer.objects.get(pk=key('shopee:pace:synthetic:22:items')).next_request_at == now+timedelta(seconds=8)


def test_incomplete_activity_response_is_not_absence(shop, monkeypatch):
    from apps.flash_sales.provider import ShopeeAdapter, UnknownWrite
    _, store, _ = shop
    adapter = ShopeeAdapter(store)
    monkeypatch.setattr(adapter, 'call', lambda *a, **k: {})
    with pytest.raises(UnknownWrite):
        adapter.detail('123')


def test_readonly_followup_cooldown_returns_actionable_error(shop, monkeypatch):
    from apps.flash_sales.provider import SharedCooldown
    user, store, client = shop
    configured(shop)
    task = submit(user, request_id='followup-cooldown', store_ids=[store.id]).tasks.get()
    drain(task, FakeShopee(lose_create=True), 30)
    def cooldown(*args, **kwargs):
        raise SharedCooldown('synthetic cooldown', retry_after=300)
    monkeypatch.setattr(engine, 'reconcile_failed', cooldown)
    response = client.post(f'/api/internal/marketing/flash-sales/batches/{task.batch_id}/',
        {'action': 'reconcile', 'task_id': task.id}, format='json')
    assert response.status_code == 400 and '原保护保留' in str(response.data)
    assert StoreLock.objects.get(store=store).task_id == task.id

def test_unknown_create_without_id_never_recreates_or_claims_absence_before_slot_end(shop):
    from apps.flash_sales.provider import UnknownWrite
    user, store, _ = shop
    configured(shop)
    class LostCreateNoReadback(FakeShopee):
        def call(self, endpoint, *, body):
            if endpoint == 'create_shop_flash_sale':
                self.calls.append((endpoint, body))
                raise UnknownWrite('synthetic lost create')
            return super().call(endpoint, body=body)
    task = submit(user, request_id='unknown-no-id', store_ids=[store.id]).tasks.get()
    adapter = LostCreateNoReadback()
    drain(task, adapter, 30)
    intent = task.intents.get()
    assert task.status == 'failed' and task.state['recovery_pending'] and not intent.platform_id
    assert intent.reservation_key and not intent.absence_evidence.get('absent')
    calls = list(adapter.calls)
    engine.reconcile_failed(task.id, adapter=adapter)
    task.refresh_from_db()
    assert task.state['recovery_pending'] and StoreLock.objects.get(store=store).task_id == task.id
    assert calls == adapter.calls and len(calls) == 1
