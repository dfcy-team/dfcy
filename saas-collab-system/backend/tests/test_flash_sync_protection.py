import pytest
from datetime import timedelta
from django.utils import timezone
from apps.flash_sales import engine
from apps.flash_sales.models import Batch, StoreTask, StoreLock, Intent, WriteOperation
from apps.flash_sales.services import submit
from tests.test_flash_sales import shop, configured, FakeShopee, drain

pytestmark = pytest.mark.django_db


def protected_sync(shop):
    user, store, _ = shop
    configured(shop)
    old = submit(user, request_id='protected-write', store_ids=[store.id]).tasks.get()
    drain(old, FakeShopee(lose_create=True), 30)
    batch = Batch.objects.create(tenant=user.tenant, actor=user, request_id='readonly-protected', operation='sync', payload_hash='test')
    task = StoreTask.objects.create(tenant=user.tenant, store=store, batch=batch, snapshot={'sync_scope': 'active'})
    return old, task


def test_readonly_sync_finishes_without_changing_failed_write_protection(shop):
    old, task = protected_sync(shop)
    intent = old.intents.get()
    before = (intent.reservation_key, intent.status, intent.absence_evidence)
    writes = list(WriteOperation.objects.values_list('id', 'status'))
    adapter = FakeShopee()
    assert engine.run_step(task.id, adapter=adapter) == 'succeeded'
    task.refresh_from_db(); intent.refresh_from_db(); old.refresh_from_db()
    assert task.finished_at and old.state['recovery_pending'] and old.status == 'failed'
    assert StoreLock.objects.get(store=task.store).task_id == old.id
    assert (intent.reservation_key, intent.status, intent.absence_evidence) == before
    assert list(WriteOperation.objects.values_list('id', 'status')) == writes
    assert not adapter.calls


def test_protected_sync_still_serializes_same_shop(shop):
    old, first = protected_sync(shop)
    batch = Batch.objects.create(tenant=first.tenant, actor=first.batch.actor, request_id="second-sync", operation="sync", payload_hash="test")
    second = StoreTask.objects.create(tenant=first.tenant, store=first.store, batch=batch)
    assert engine.claim(first.id)
    assert engine.claim(second.id) is None
    assert StoreLock.objects.get(store=first.store).task_id == old.id
    StoreTask.objects.filter(pk=first.id).update(lease_until=timezone.now()-timedelta(seconds=1))
    assert engine.claim(second.id)


def test_sync_cannot_use_write_journal_even_with_a_valid_lease(shop):
    from rest_framework.exceptions import PermissionDenied
    old, task = protected_sync(shop)
    task = engine.claim(task.id)
    assert task is not None
    intent = Intent.objects.create(tenant=task.tenant, task=task, store=task.store, slot_id='synthetic')
    with pytest.raises(PermissionDenied):
        engine.write_once(task, intent, 'forbidden', 'create_shop_flash_sale', {'timeslot_id': 1}, FakeShopee())
    assert not intent.writes.exists()
    assert StoreLock.objects.get(store=task.store).task_id == old.id

def test_releasing_protection_does_not_allow_writes_during_active_sync(shop):
    old, sync = protected_sync(shop)
    assert engine.claim(sync.id)
    StoreLock.objects.filter(task=old).update(task=None)
    writer = submit(old.batch.actor, request_id='after-readonly-release', store_ids=[old.store_id]).tasks.get()
    assert engine.claim(writer.id) is None
    StoreTask.objects.filter(pk=sync.id).update(lease_until=timezone.now()-timedelta(seconds=1))
    assert engine.claim(writer.id)
