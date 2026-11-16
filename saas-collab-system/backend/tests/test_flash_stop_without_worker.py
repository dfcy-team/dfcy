from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import connection
from django.utils import timezone

from apps.flash_sales.models import Intent, StoreLock
from apps.flash_sales.services import request_stop, submit
from tests.test_flash_sales import _admin, configured, shop


pytestmark = pytest.mark.django_db


def test_stop_unstarted_batch_without_worker(shop, settings):
    settings.FLASH_SALES_WORKERS_ENABLED = False
    user, store, client = shop
    configured(shop)
    batch = submit(user, request_id="stop-without-worker", store_ids=[store.id])
    task = batch.tasks.get()
    StoreLock.objects.filter(store=store).update(task=task)
    with patch("apps.flash_sales.engine.ShopeeAdapter") as adapter:
        for _ in range(2):
            response = client.post(f"/api/internal/marketing/flash-sales/batches/{batch.id}/",
                                   {"action": "stop"}, format="json")
            assert response.status_code == 200
        adapter.assert_not_called()
    task.refresh_from_db()
    batch.refresh_from_db()
    assert task.status == "stopped"
    assert task.started_at is None
    assert task.finished_at is not None
    assert batch.stop_requested and batch.finished_at is not None
    assert not StoreLock.objects.filter(task=task).exists()


@pytest.mark.parametrize("protection", ["started", "lease", "intent", "migration_hold", "retry_paused"])
def test_stop_preserves_tasks_requiring_reconciliation(shop, protection):
    user, store, client = shop
    configured(shop)
    batch = submit(user, request_id=f"stop-protected-{protection}", store_ids=[store.id])
    task = batch.tasks.get()
    StoreLock.objects.filter(store=store).update(task=task)
    if protection == "started":
        task.started_at = timezone.now()
    elif protection == "lease":
        task.lease_until = timezone.now() + timedelta(minutes=3)
    elif protection == "intent":
        Intent.objects.create(tenant=user.tenant, task=task, store=store, slot_id="test-slot")
    else:
        task.state[protection] = True
    task.save()
    response = client.post(f"/api/internal/marketing/flash-sales/batches/{batch.id}/",
                           {"action": "stop"}, format="json")
    assert response.status_code == 200
    task.refresh_from_db()
    batch.refresh_from_db()
    assert task.status == "queued" and task.finished_at is None
    assert batch.stop_requested and batch.finished_at is None
    assert StoreLock.objects.filter(task=task).exists()


def test_stop_does_not_release_another_tasks_store_lock(shop):
    user, store, _ = shop
    configured(shop)
    first = submit(user, request_id="stop-first", store_ids=[store.id])
    other = submit(user, request_id="keep-lock-owner", store_ids=[store.id]).tasks.get()
    StoreLock.objects.filter(store=store).update(task=other)
    request_stop(first)
    assert first.tasks.get().status == "stopped"
    assert StoreLock.objects.get(store=store).task_id == other.pk


def test_stop_rejects_another_tenants_batch(shop):
    user, store, _ = shop
    configured(shop)
    batch = submit(user, request_id="tenant-protected", store_ids=[store.id])
    _, _, other_client = _admin("other-stop-tenant")
    response = other_client.post(f"/api/internal/marketing/flash-sales/batches/{batch.id}/",
                                 {"action": "stop"}, format="json")
    assert response.status_code == 404
    batch.refresh_from_db()
    assert not batch.stop_requested and batch.tasks.get().status == "queued"


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "mysql", reason="Requires real row locks")
@pytest.mark.parametrize("competing_action", ["claim", "stop"])
def test_stop_serializes_with_claim_and_repeated_stop(shop, competing_action):
    from apps.flash_sales.engine import claim
    from apps.flash_sales.models import Batch
    from tests.test_flash_sales_mysql import concurrent

    user, store, _ = shop
    configured(shop)
    batch = submit(user, request_id=f"concurrent-stop-{competing_action}", store_ids=[store.id])
    task = batch.tasks.get()

    def work(index):
        if index == 0 and competing_action == "claim":
            return claim(task.id)
        request_stop(Batch.objects.get(pk=batch.id))

    concurrent(2, work)
    task.refresh_from_db()
    batch.refresh_from_db()
    assert batch.stop_requested
    if task.started_at:
        assert task.status == "running" and task.lease_until is not None
        assert task.finished_at is None and batch.finished_at is None
        assert StoreLock.objects.filter(task=task).exists()
    else:
        assert task.status == "stopped" and task.lease_until is None
        assert task.finished_at is not None and batch.finished_at is not None
        assert not StoreLock.objects.filter(task=task).exists()
