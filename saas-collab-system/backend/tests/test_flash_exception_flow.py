from unittest.mock import patch
import pytest
from apps.flash_sales import engine
from apps.flash_sales.models import StoreTask, StoreLock
from apps.flash_sales.services import submit
from apps.flash_sales.provider import UnknownWrite
from tests.test_flash_sales import shop, configured, FakeShopee, drain

pytestmark = pytest.mark.django_db


class MissingCreate(FakeShopee):
    def call(self, endpoint, *, body):
        if endpoint == "create_shop_flash_sale" and not self.calls:
            self.calls.append((endpoint, body))
            raise UnknownWrite("synthetic lost response without creation")
        return super().call(endpoint, body=body)


def test_absent_unknown_create_retries_original_slot_after_separated_readbacks(shop):
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id="missing-create-original", store_ids=[store.id]).tasks.get()
    adapter = MissingCreate()
    engine.run_step(task.id, adapter=adapter)
    original = task.intents.get()
    now = engine.time.time()
    for offset in (10, 20, 30):
        StoreTask.objects.filter(pk=task.id).update(next_attempt_at=None)
        with patch("apps.flash_sales.engine.time.time", return_value=now + offset):
            engine.run_step(task.id, adapter=adapter)
    drain(task, adapter)
    assert task.status == "succeeded"
    intents = list(task.intents.order_by("id"))
    assert len(intents) == 2
    assert all(i.slot_id == original.slot_id and i.target == original.target for i in intents)
    assert intents[0].absence_evidence["absent"]
    assert intents[1].result["execution_attempt"] == 1
    assert not any(endpoint == "delete_shop_flash_sale" for endpoint, _ in adapter.calls)


def test_existing_unknown_activity_is_never_deleted_or_recreated(shop):
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id="unknown-existing-stays", store_ids=[store.id]).tasks.get()
    adapter = FakeShopee(lose_create=True)
    drain(task, adapter, 30)
    assert task.status == "failed" and task.state["recovery_pending"]
    assert len(adapter.calls) == 1
    assert StoreLock.objects.get(store=store).task_id == task.id


def test_recovery_from_blocked_batch_resumes_original_and_preserves_budget(shop):
    user, store, client = shop
    configured(shop)
    old = submit(user, request_id="old-exception", store_ids=[store.id]).tasks.get()
    adapter = MissingCreate()
    drain(old, adapter, 30)
    assert old.status == "failed" and old.state["recovery_pending"]
    intent = old.intents.get()
    intent.result["execution_attempt"] = 2
    intent.save()
    new = submit(user, request_id="blocked-exception", store_ids=[store.id]).tasks.get()
    engine.run_step(new.id, adapter=adapter)
    response = client.post(f"/api/internal/marketing/flash-sales/batches/{new.batch_id}/",
        {"action": "recover", "task_id": new.id}, format="json")
    assert response.status_code == 200, response.data
    old.refresh_from_db()
    old.batch.refresh_from_db()
    assert old.status == "queued" and old.batch.finished_at is None
    assert old.intents.get().result["execution_attempt"] == 2
    assert StoreLock.objects.get(store=store).task_id == old.id
    now = engine.time.time()
    for offset in (10, 20, 30):
        StoreTask.objects.filter(pk=old.id).update(next_attempt_at=None)
        with patch("apps.flash_sales.engine.time.time", return_value=now + offset):
            engine.run_step(old.id, adapter=adapter)
    drain(old, adapter)
    assert old.status == "succeeded"
    assert old.intents.latest("id").result["execution_attempt"] == 3
    new.refresh_from_db()
    assert new.status == "failed" and new.intents.count() == 0


def test_exhausted_recovery_never_resets_three_rebuild_budget(shop):
    from rest_framework.exceptions import ValidationError
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id="exhausted-exception", store_ids=[store.id]).tasks.get()
    drain(task, FakeShopee(lose_create=True), 30)
    intent = task.intents.get()
    intent.result["execution_attempt"] = 3
    intent.save()
    with pytest.raises(ValidationError, match="3"):
        engine.recover_failed(task.id)
    task.refresh_from_db()
    assert task.status == "failed" and task.intents.count() == 1


def test_recovery_notification_waits_and_refreshes_final_summary(shop):
    from apps.flash_sales.models import Notification
    from apps.flash_sales.notifications import prepare_notifications, deliver
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id="recover-summary", store_ids=[store.id]).tasks.get()
    task.snapshot["recipients"] = {"users": [{"user_id": user.id, "open_id": "synthetic", "name": "Test"}]}
    task.save()
    adapter = MissingCreate()
    drain(task, adapter, 30)
    prepare_notifications(task.batch_id)
    notification = Notification.objects.get(batch=task.batch)
    notification.status, notification.message_id = "accepted", "synthetic-receipt"
    notification.save()
    engine.recover_failed(task.id)
    assert deliver(notification.id, service=object()) == "pending"
    now = engine.time.time()
    for offset in (10, 20, 30):
        StoreTask.objects.filter(pk=task.id).update(next_attempt_at=None)
        with patch("apps.flash_sales.engine.time.time", return_value=now + offset):
            engine.run_step(task.id, adapter=adapter)
    drain(task, adapter)
    prepare_notifications(task.batch_id)
    notification.refresh_from_db()
    assert notification.snapshot["phase"] == "final"
    assert notification.snapshot["recovery_revision"] == 1
    assert notification.snapshot["stores"][0]["status"] == "succeeded"
    assert notification.snapshot["previous_receipt"]["message_id"] == "synthetic-receipt"


def test_fast_repeated_reads_do_not_release_unknown_create(shop):
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id="same-instant-empty", store_ids=[store.id]).tasks.get()
    adapter = MissingCreate()
    with patch("apps.flash_sales.engine.time.time", return_value=engine.time.time()):
        drain(task, adapter, 30)
    assert task.status == "failed" and task.state["recovery_pending"]
    assert len(adapter.calls) == 1 and task.intents.count() == 1
    assert StoreLock.objects.get(store=store).task_id == task.id


def test_repeated_absent_creates_finish_after_initial_plus_three_attempts(shop):
    class AlwaysMissing(FakeShopee):
        def call(self, endpoint, *, body):
            self.calls.append((endpoint, body))
            raise UnknownWrite("synthetic lost create")
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id="all-creates-absent", store_ids=[store.id]).tasks.get()
    adapter = AlwaysMissing()
    now = engine.time.time()
    for index in range(40):
        StoreTask.objects.filter(pk=task.id).update(next_attempt_at=None)
        with patch("apps.flash_sales.engine.time.time", return_value=now + 10 * index):
            engine.run_step(task.id, adapter=adapter)
        task.refresh_from_db()
        if task.status == "failed":
            break
    assert task.status == "failed" and task.intents.count() == 4
    assert len(adapter.calls) == 4
    assert all(body["timeslot_id"] == adapter.target["timeslot_id"] for _, body in adapter.calls)
    assert all(intent.absence_evidence["absent"] for intent in task.intents.all())
    assert StoreLock.objects.get(store=store).task_id is None


def test_recovery_pacing_waits_for_next_page_without_restarting_read(shop):
    import hashlib
    from datetime import timedelta
    from django.utils import timezone
    from apps.flash_sales.provider import ShopeeAdapter
    from apps.flash_sales.models import AppPacer
    _, store, _ = shop
    adapter = ShopeeAdapter(store)
    now = [timezone.now()]
    key = lambda value: hashlib.sha256(value.encode()).hexdigest()
    AppPacer.objects.create(key=key("shopee:cooldown:synthetic:11:items"),next_request_at=now[0]-timedelta(seconds=1))
    def sleep(seconds):
        now[0] += timedelta(seconds=seconds)
    with patch("apps.flash_sales.provider.timezone.now", side_effect=lambda: now[0]), patch("apps.flash_sales.provider.time.sleep",side_effect=sleep) as waiting:
        adapter._pace("synthetic",shop="11",endpoint="items")
        adapter._pace("synthetic",shop="11",endpoint="items")
    waiting.assert_called_once_with(8)
    assert AppPacer.objects.get(pk=key("shopee:pace:synthetic")).next_request_at == now[0]+timedelta(seconds=4)
    assert AppPacer.objects.get(pk=key("shopee:pace:synthetic:11:items")).next_request_at == now[0]+timedelta(seconds=8)
