import pytest
from django.utils import timezone

from apps.flash_sales import engine
from apps.flash_sales.domain import reconcile
from apps.flash_sales.models import StoreLock, StoreTask
from apps.flash_sales.provider import UnknownWrite
from apps.flash_sales.services import submit
from tests.test_flash_sales import shop, configured, FakeShopee, drain


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("status,expected", [(0, "rejected"), (None, "unknown"), (9, "unknown"), (1, "mismatch")])
def test_readback_distinguishes_disabled_unknown_and_changed_enabled_values(status, expected):
    planned = [{"item_id": "1", "model_id": "2", "price": "3", "stock": 7}]
    actual = [{**planned[0], "status": status, "price": "4", "reject_reason": "平台不允许"}]
    row = reconcile(planned, actual, [])[0]
    assert row["state"] == expected
    if status == 0:
        assert "平台不允许" in row["reason"]
    assert reconcile(planned, [], [])[0]["state"] == "unknown"


def test_explicit_rejection_is_preserved_over_disabled_fallback():
    planned = [{"item_id": "1", "model_id": "0", "price": "3", "stock": 7}]
    actual = [{**planned[0], "status": 0}]
    assert "未返回原因" in reconcile(planned, actual, [])[0]["reason"]
    assert reconcile(planned, actual, [{"item_id": "1", "reason": "库存不足"}])[0]["reason"] == "库存不足"


def retry(task, adapter=None):
    StoreTask.objects.filter(pk=task.pk).update(next_attempt_at=timezone.now())
    result = engine.run_step(task.id, adapter=adapter or object())
    task.refresh_from_db()
    return result


def test_three_unchanged_failures_pause_persistently_and_require_explicit_resume(shop, monkeypatch, settings):
    user, store, client = shop
    configured(shop)
    batch = submit(user, request_id="pause-before-intent", store_ids=[store.id])
    task = batch.tasks.get()
    def unavailable(*args):
        raise UnknownWrite("等待原结果")
    monkeypatch.setattr(engine, "step", unavailable)
    for count in range(1, 4):
        retry(task)
        assert task.state["no_progress_count"] == count
    assert task.state["retry_paused"] and task.next_attempt_at is None
    assert task.retry_count == 3 and task.finished_at is None
    assert StoreLock.objects.get(store=store).task_id == task.id
    batch.refresh_from_db()
    assert batch.finished_at is None
    assert engine.run_step(task.id, adapter=object()) == "not_claimed"
    from apps.flash_sales import tasks
    settings.FLASH_SALES_WORKERS_ENABLED = True
    queued = []
    monkeypatch.setattr(tasks.execute, "apply_async", lambda *args, **kwargs: queued.append(args))
    tasks.dispatch()
    assert queued == []
    endpoint = f"/api/internal/marketing/flash-sales/batches/{batch.id}/"
    payload = client.get(endpoint).data["data"]["tasks"][0]
    assert payload["retry_paused"] and payload["no_progress_count"] == 3
    assert client.post(endpoint, {"action": "reconcile"}, format="json").status_code == 200
    assert engine.run_step(task.id, adapter=object()) == "not_claimed"
    assert client.post(endpoint, {"action": "resume", "task_id": task.id}, format="json").status_code == 400
    StoreTask.objects.filter(pk=task.pk).update(state={**task.state, "migration_hold": True})
    assert client.post(endpoint, {"action": "resume", "task_id": task.id, "confirmed": True}, format="json").status_code == 400
    StoreTask.objects.filter(pk=task.pk).update(state=task.state)
    response = client.post(endpoint, {"action": "resume", "task_id": task.id, "confirmed": True}, format="json")
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.retry_count == 3 and task.state["no_progress_count"] == 0 and not task.state["retry_paused"]
    retry(task)
    assert task.retry_count == 4 and task.state["no_progress_count"] == 1


def test_resume_rejects_another_tenant_and_missing_store_lock(shop):
    from tests.test_flash_sales import _admin
    user, store, client = shop
    configured(shop)
    batch = submit(user, request_id="resume-tenant", store_ids=[store.id])
    task = batch.tasks.get()
    StoreTask.objects.filter(pk=task.id).update(status="confirming", state={"retry_paused": True, "no_progress_count": 3})
    _, _, other_client = _admin("retry-other-tenant")
    endpoint = f"/api/internal/marketing/flash-sales/batches/{batch.id}/"
    body = {"action": "resume", "task_id": task.id, "confirmed": True}
    assert other_client.post(endpoint, body, format="json").status_code == 404
    assert client.post(endpoint, body, format="json").status_code == 400
    task.refresh_from_db()
    assert task.state["retry_paused"]


def test_disabled_specification_finishes_readback_without_replaying_submission(shop):
    user, store, _ = shop
    configured(shop)
    class MixedReadback(FakeShopee):
        def call(self, endpoint, *, body):
            result = super().call(endpoint, body=body)
            if endpoint == "add_shop_flash_sale_items":
                self.products["20"].append({**self.products["20"][0], "model_id": "201", "status": 0, "reject_reason": ""})
            return result
    adapter = MixedReadback()
    adapter.source.append({**adapter.source[0], "model_id": "201"})
    task = submit(user, request_id="disabled-readback", store_ids=[store.id]).tasks.get()
    drain(task, adapter, 10)
    assert task.status == "succeeded"
    assert [row["state"] for row in task.intents.get().result["specifications"]] == ["enabled", "rejected"]
    assert sum(endpoint == "add_shop_flash_sale_items" for endpoint, _ in adapter.calls) == 1


def test_business_progress_restarts_consecutive_count(shop, monkeypatch):
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id="pause-progress", store_ids=[store.id]).tasks.get()
    def unavailable(task, adapter):
        raise UnknownWrite("等待原结果")
    monkeypatch.setattr(engine, "step", unavailable)
    retry(task); retry(task)
    StoreTask.objects.filter(pk=task.pk).update(completed=1)
    retry(task)
    assert task.state["no_progress_count"] == 1 and not task.state.get("retry_paused")


def test_paused_unknown_creation_never_replays_create_after_resume(shop):
    user, store, client = shop
    configured(shop)
    batch = submit(user, request_id="lost-create-pause", store_ids=[store.id])
    task = batch.tasks.get()
    adapter = FakeShopee(lose_create=True)
    for _ in range(10):
        retry(task, adapter)
        if task.state.get("retry_paused"):
            break
    assert task.state["retry_paused"]
    intent = task.intents.get()
    original = (intent.pk, intent.platform_id, intent.reservation_key)
    assert client.post(f"/api/internal/marketing/flash-sales/batches/{batch.id}/", {
        "action": "resume", "task_id": task.id, "confirmed": True}, format="json").status_code == 200
    retry(task, adapter)
    intent.refresh_from_db()
    assert (intent.pk, intent.platform_id, intent.reservation_key) == original
    assert sum(endpoint == "create_shop_flash_sale" for endpoint, _ in adapter.calls) == 1


@pytest.mark.django_db(transaction=True)
def test_pause_survives_fresh_worker_processes(shop, monkeypatch):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path
    from django.db import connection

    db = connection.settings_dict
    if connection.vendor != "mysql":
        pytest.skip("Process persistence requires isolated MySQL")
    assert str(db["PORT"]) == "3313" and db["NAME"] == "test_flash_acceptance"
    user, store, client = shop
    configured(shop)
    batch = submit(user, request_id="restart-paused-worker", store_ids=[store.id])
    task = batch.tasks.get()

    def unavailable(*args):
        raise UnknownWrite("synthetic unavailable result")

    monkeypatch.setattr(engine, "step", unavailable)
    for _ in range(3):
        retry(task)
    assert task.state["retry_paused"]
    environment = dict(os.environ, DB_ENGINE=db["ENGINE"], DB_HOST=db["HOST"],
                       DB_PORT=str(db["PORT"]), DB_NAME=db["NAME"], DB_USER=db["USER"],
                       DB_PASSWORD=db["PASSWORD"], DJANGO_SETTINGS_MODULE="config.settings.dev")
    script = """
import json, os, sys
import django
django.setup()
from django.db import connection
from apps.flash_sales.engine import claim
from apps.flash_sales.models import StoreTask, StoreLock
assert connection.vendor == 'mysql'
assert str(connection.settings_dict['PORT']) == '3313'
assert connection.settings_dict['NAME'] == 'test_flash_acceptance'
task = StoreTask.objects.get(pk=int(sys.argv[1]))
assert task.state['retry_paused'] and task.state['no_progress_count'] == 3
assert task.retry_count == 3 and task.finished_at is None and task.next_attempt_at is None
assert claim(task.pk) is None
assert StoreLock.objects.get(store_id=task.store_id).task_id == task.pk
print(json.dumps({'pid':os.getpid(),'paused':True,'claim_blocked':True}))
"""
    pids = []
    for _ in range(2):
        result = subprocess.run([sys.executable, "-c", script, str(task.id)],
                                cwd=Path(__file__).resolve().parents[1], env=environment,
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, "Fresh worker persistence check failed"
        evidence = json.loads(result.stdout)
        assert evidence["paused"] and evidence["claim_blocked"]
        pids.append(evidence["pid"])
    assert len(set(pids + [os.getpid()])) == 3
    response = client.post(f"/api/internal/marketing/flash-sales/batches/{batch.id}/", {
        "action": "resume", "task_id": task.id, "confirmed": True}, format="json")
    assert response.status_code == 200
    retry(task)
    assert task.retry_count == 4 and task.state["no_progress_count"] == 1
