import pytest
from datetime import timedelta
from functools import partial
from django.utils import timezone
from unittest.mock import Mock
from apps.flash_sales import engine
from apps.flash_sales.models import Batch, StoreTask, StoreLock, Intent, WriteOperation
from apps.flash_sales.services import submit
from apps.masterdata.models import StoreMaster
from tests.test_flash_sales import shop, configured, FakeShopee, drain, _admin

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


def test_dispatch_preserves_failed_write_lock_while_delivering_readonly_sync(
        shop, settings, monkeypatch, django_capture_on_commit_callbacks):
    from apps.flash_sales.tasks import dispatch
    old, task = protected_sync(shop)
    settings.FLASH_SALES_WORKERS_ENABLED = True
    settings.FLASH_SALES_NOTIFICATIONS_ENABLED = False
    delivered = []
    monkeypatch.setattr('apps.flash_sales.tasks._publish_delivery',
        lambda task_id, token, is_sync: delivered.append((task_id, token, is_sync)))
    with django_capture_on_commit_callbacks(execute=True):
        assert dispatch() == 'dispatched'
    task.refresh_from_db()
    assert len(delivered) == 1
    assert delivered[0] == (task.pk, task.state['delivery_hold']['token'], True)
    assert StoreLock.objects.get(store=task.store).task_id == old.pk
    assert engine.claim(task.pk, delivery_token=delivered[0][1]) is not None
    assert StoreLock.objects.get(store=task.store).task_id == old.pk


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


def test_celery_dispatch_settles_blocked_writer_and_runs_protected_sync(
        shop, settings, monkeypatch, django_capture_on_commit_callbacks):
    from apps.flash_sales.tasks import dispatch, execute

    old, sync = protected_sync(shop)
    writer = submit(old.batch.actor, request_id="blocked-before-sync", store_ids=[old.store_id]).tasks.get()
    old_writes = list(WriteOperation.objects.values_list("pk", "status"))
    old_intent = old.intents.get()
    adapter = FakeShopee()
    settings.FLASH_SALES_WORKERS_ENABLED = True
    settings.FLASH_SALES_NOTIFICATIONS_ENABLED = False
    publish = Mock()
    monkeypatch.setattr(execute, "apply_async", publish)
    monkeypatch.setattr(engine, "run_step", partial(engine.run_step, adapter=adapter))

    with django_capture_on_commit_callbacks(execute=True):
        assert dispatch() == "dispatched"
    sync.refresh_from_db()
    token = sync.state["delivery_hold"]["token"]
    publish.assert_called_once_with((sync.pk, token), queue="shopee-flash-sync", expires=30)
    assert execute.run(sync.pk, token) == "succeeded"

    writer.refresh_from_db()
    old.refresh_from_db()
    assert writer.status == "failed" and writer.finished_at and writer.batch.finished_at
    assert not writer.intents.exists() and not adapter.calls
    assert old.state["recovery_pending"] and StoreLock.objects.get(store=old.store).task_id == old.pk
    assert old.intents.get().reservation_key == old_intent.reservation_key
    assert list(WriteOperation.objects.values_list("pk", "status")) == old_writes


@pytest.mark.parametrize("protected_sync_slot", ["lease", "delivery"])
def test_reconcile_http_waits_for_same_store_read_slot(
        shop, protected_sync_slot, settings, monkeypatch, django_capture_on_commit_callbacks):
    from apps.flash_sales.tasks import dispatch, execute

    old, sync = protected_sync(shop)
    if protected_sync_slot == "lease":
        assert engine.claim(sync.pk)
    else:
        settings.FLASH_SALES_WORKERS_ENABLED = True
        settings.FLASH_SALES_NOTIFICATIONS_ENABLED = False
        monkeypatch.setattr(execute, "apply_async", Mock())
        with django_capture_on_commit_callbacks(execute=True):
            assert dispatch() == "dispatched"
        sync.refresh_from_db()
        assert sync.state["delivery_hold"]["token"]
    adapter = Mock()
    monkeypatch.setattr(engine, "ShopeeAdapter", adapter)

    response = shop[2].post(f"/api/internal/marketing/flash-sales/batches/{old.batch_id}/",
        {"action": "reconcile", "task_id": old.pk}, format="json")

    assert response.status_code == 400 and "请稍后核对" in str(response.data)
    adapter.assert_not_called()
    old.refresh_from_db()
    assert not old.lease_until and old.state["recovery_pending"]


def test_reconcile_http_waits_for_global_execution_capacity(shop, monkeypatch):
    old, _ = protected_sync(shop)
    user, original_store, client = shop
    active = Batch.objects.create(tenant=user.tenant, actor=user, request_id="three-active", operation="run")
    for index in range(3):
        store = StoreMaster.objects.create(tenant=user.tenant, platform=original_store.platform,
            code=f"BUSY{index}", name=f"Busy {index}", country_code="PH", currency="PHP", timezone="Asia/Manila")
        task = StoreTask.objects.create(tenant=user.tenant, store=store, batch=active)
        assert engine.claim(task.pk)
    adapter = Mock()
    monkeypatch.setattr(engine, "ShopeeAdapter", adapter)

    response = client.post(f"/api/internal/marketing/flash-sales/batches/{old.batch_id}/",
        {"action": "reconcile", "task_id": old.pk}, format="json")

    assert response.status_code == 400 and "执行队列已满" in str(response.data)
    adapter.assert_not_called()
    assert StoreTask.objects.filter(lease_until__gt=timezone.now()).count() == 3


def test_protected_sync_claim_ignores_writer_that_cannot_acquire_store(shop):
    old, sync = protected_sync(shop)
    writer = submit(old.batch.actor, request_id="undispatched-other-writer", store_ids=[old.store_id]).tasks.get()
    assert engine.claim(sync.pk)
    writer.refresh_from_db()
    assert writer.status == "queued" and not writer.intents.exists()


def test_recover_reports_actual_protection_owner_after_blocked_task(shop):
    old, _ = protected_sync(shop)
    user, store, client = shop
    writer = submit(user, request_id="recover-original-owner", store_ids=[store.id]).tasks.get()
    assert engine.run_step(writer.pk, adapter=Mock()) == "not_claimed"

    response = client.post(f"/api/internal/marketing/flash-sales/batches/{writer.batch_id}/",
        {"action": "recover", "task_id": writer.pk}, format="json")

    assert response.status_code == 200
    assert response.data["data"] == {"id": str(old.batch_id), "task_id": old.pk}
    assert StoreLock.objects.get(store=store).task_id == old.pk


@pytest.mark.parametrize("broken_owner_scope", ["store", "tenant"])
def test_recover_rejects_protection_pointer_outside_selected_store_or_tenant(shop, broken_owner_scope):
    old, _ = protected_sync(shop)
    user, selected_store, client = shop
    other_store = selected_store
    other_user = user
    if broken_owner_scope == "store":
        other_store = StoreMaster.objects.create(tenant=user.tenant, platform=selected_store.platform,
            code="OTHER", name="Other store", country_code="PH", currency="PHP", timezone="Asia/Manila")
    else:
        _, other_user, _ = _admin("other-tenant-recovery")
    batch = Batch.objects.create(tenant=other_user.tenant, actor=other_user, request_id="other-owner", operation="run")
    foreign = StoreTask.objects.create(tenant=other_user.tenant, store=other_store, batch=batch,
        status="failed", state={"recovery_pending": True})
    StoreLock.objects.filter(store=selected_store).update(task=foreign)

    response = client.post(f"/api/internal/marketing/flash-sales/batches/{old.batch_id}/",
        {"action": "recover", "task_id": old.pk}, format="json")

    assert response.status_code == 400
    old.refresh_from_db()
    foreign.refresh_from_db()
    assert old.status == foreign.status == "failed"
    assert old.state["recovery_pending"] and foreign.state["recovery_pending"]
    assert StoreLock.objects.get(store=selected_store).task_id == foreign.pk
