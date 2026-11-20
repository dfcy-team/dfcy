from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest
from django.db import connection, connections, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.flash_sales import engine
from apps.flash_sales.models import Batch, Intent, Notification, StoreLock, StoreTask
from apps.flash_sales.notifications import prepare_notifications
from apps.flash_sales.tasks import prepare_post_sync
from apps.masterdata.models import StoreMaster
from tests.test_flash_sales import shop
from tests.test_flash_sales_mysql import concurrent
from tests.test_flash_sync_protection import protected_sync

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "mysql", reason="Requires real MySQL row locks"),
]


def _thread_job(work):
    try:
        return work()
    finally:
        connections.close_all()


def test_reconcile_and_worker_claims_share_global_capacity(shop):
    old, _ = protected_sync(shop)
    user, original_store, _ = shop
    batch = Batch.objects.create(tenant=user.tenant, actor=user, request_id="shared-capacity", operation="run")
    tasks = []
    for index in range(5):
        store = StoreMaster.objects.create(tenant=user.tenant, platform=original_store.platform,
            code=f"LEASE{index}", name=f"Lease {index}", country_code="PH", currency="PHP", timezone="Asia/Manila")
        tasks.append(StoreTask.objects.create(tenant=user.tenant, store=store, batch=batch))

    compare_finished = Event()
    read_started = Event()

    def inspect(result):
        read_started.set()
        assert compare_finished.wait(timeout=12)
        return result

    # The protected fixture may already know the platform ID. Gate either
    # read-only path so capacity is measured while reconciliation is in flight.
    present = {"status": 1, "timeslot_id": "still-present", "end_time": 4102444800}
    adapter = Mock(activities=Mock(side_effect=lambda **kwargs: inspect([
                       {**present, "timeslot_id": old.intents.get().slot_id}])),
                   detail=Mock(side_effect=lambda *args: inspect(present)))
    with ThreadPoolExecutor(max_workers=1) as pool:
        check = pool.submit(_thread_job, lambda: engine.reconcile_failed(old.pk, adapter=adapter))
        try:
            assert read_started.wait(timeout=12)
            claims = concurrent(len(tasks), lambda index: bool(engine.claim(tasks[index].pk)))
            assert sum(claims) == 2
            assert StoreTask.objects.filter(lease_until__gt=timezone.now()).count() == 3
        finally:
            compare_finished.set()
        check.result(timeout=15)

    assert adapter.activities.call_count + adapter.detail.call_count >= 1
    assert StoreTask.objects.filter(lease_until__gt=timezone.now()).count() == 2
    assert StoreLock.objects.get(store=old.store).task_id == old.id

    assert sum(concurrent(len(tasks), lambda index: bool(engine.claim(tasks[index].pk)))) == 1
    rejected_adapter = Mock()
    with pytest.raises(ValidationError, match="执行队列已满"):
        engine.reconcile_failed(old.pk, adapter=rejected_adapter)
    assert not rejected_adapter.mock_calls
    assert StoreTask.objects.filter(lease_until__gt=timezone.now()).count() == 3


def test_reconcile_finalization_and_recover_lock_task_before_store(shop):
    old, _ = protected_sync(shop)
    Intent.objects.filter(task=old).update(platform_id="synthetic-missing")
    finalizing = Event()
    recovery_task_query = Event()
    adapter = Mock(detail=Mock(return_value=None))

    def reconcile():
        locked_reads = 0

        def wait_after_final_task_lock(execute, sql, params, many, context):
            nonlocal locked_reads
            result = execute(sql, params, many, context)
            if "flash_sales_storetask" in sql and "FOR UPDATE" in sql:
                locked_reads += 1
                if locked_reads == 2:
                    finalizing.set()
                    assert recovery_task_query.wait(timeout=12)
            return result

        with connection.execute_wrapper(wait_after_final_task_lock):
            engine.reconcile_failed(old.pk, adapter=adapter)

    def recover():
        def signal_before_task_lock(execute, sql, params, many, context):
            if "flash_sales_storetask" in sql and "FOR UPDATE" in sql:
                recovery_task_query.set()
            return execute(sql, params, many, context)

        with connection.execute_wrapper(signal_before_task_lock):
            with pytest.raises(ValidationError, match="店铺保护已变化"):
                engine.recover_failed(old.pk)

    with ThreadPoolExecutor(max_workers=2) as pool:
        check = pool.submit(_thread_job, reconcile)
        assert finalizing.wait(timeout=12)
        recovery = pool.submit(_thread_job, recover)
        check.result(timeout=15)
        recovery.result(timeout=15)

    old.refresh_from_db()
    assert old.status == "failed" and not old.state["recovery_pending"] and not old.lease_until
    assert StoreLock.objects.get(store=old.store).task_id is None
    assert old.intents.get().absence_evidence["absent"]


def test_post_sync_creation_uses_same_lock_order_as_task_finalization(shop):
    old, _ = protected_sync(shop)
    Intent.objects.filter(task=old).update(platform_id="synthetic-affected")
    task_locked = Event()
    post_sync_task_query = Event()

    def finalize():
        with transaction.atomic():
            StoreTask.objects.select_for_update().get(pk=old.pk)
            task_locked.set()
            assert post_sync_task_query.wait(timeout=12)
            Batch.objects.select_for_update().get(pk=old.batch_id)

    def post_sync():
        def signal_before_task_lock(execute, sql, params, many, context):
            if "flash_sales_storetask" in sql and ("FOR UPDATE" in sql or sql.startswith("UPDATE")):
                post_sync_task_query.set()
            return execute(sql, params, many, context)

        with connection.execute_wrapper(signal_before_task_lock):
            prepare_post_sync(old.batch_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        finalize_task = pool.submit(_thread_job, finalize)
        assert task_locked.wait(timeout=12)
        schedule_sync = pool.submit(_thread_job, post_sync)
        finalize_task.result(timeout=15)
        schedule_sync.result(timeout=15)

    old.refresh_from_db()
    post_sync_task = StoreTask.objects.get(pk=old.state["post_sync_task_id"])
    assert post_sync_task.batch.source == "post_sync"
    assert post_sync_task.snapshot["activity_ids"] == ["synthetic-affected"]
    assert StoreLock.objects.get(store=old.store).task_id == old.id


def test_notification_preparation_serializes_with_recovery_revision(shop):
    old, _ = protected_sync(shop)
    user = shop[0]
    old.snapshot["recipients"] = {"users": [{"user_id": user.id, "open_id": "synthetic", "name": "Test"}]}
    old.save(update_fields=["snapshot"])
    notification = Notification.objects.create(tenant=user.tenant, batch=old.batch, recipient=user,
        status="accepted", message_id="synthetic-receipt", snapshot={"phase": "attention"})
    recovered_batch = Event()
    notification_prepare_started = Event()

    def recover():
        def hold_batch_before_notification(execute, sql, params, many, context):
            if "flash_sales_notification" in sql and "FOR UPDATE" in sql:
                recovered_batch.set()
                assert notification_prepare_started.wait(timeout=12)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(hold_batch_before_notification):
            assert engine.recover_failed(old.pk).pk == old.pk

    def prepare():
        def signal_before_batch_lock(execute, sql, params, many, context):
            if "flash_sales_batch" in sql and "FOR UPDATE" in sql:
                notification_prepare_started.set()
            return execute(sql, params, many, context)

        with connection.execute_wrapper(signal_before_batch_lock):
            prepare_notifications(old.batch_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        recovery = pool.submit(_thread_job, recover)
        assert recovered_batch.wait(timeout=12)
        preparation = pool.submit(_thread_job, prepare)
        recovery.result(timeout=15)
        preparation.result(timeout=15)

    old.refresh_from_db()
    notification.refresh_from_db()
    assert old.status == "queued" and old.state["exception_recovery_round"] == 1
    assert notification.status == "pending"
    assert notification.snapshot["phase"] == "recovery_pending"
    assert notification.snapshot["previous_receipt"]["message_id"] == "synthetic-receipt"
