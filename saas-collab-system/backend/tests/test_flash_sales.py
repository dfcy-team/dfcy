from datetime import timedelta
from decimal import Decimal
import time

import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.flash_sales.domain import retry_delay, validate_items
from apps.flash_sales.engine import run_step
from apps.flash_sales.models import Batch, Intent, StoreConfig, StoreTask, WriteOperation
from apps.flash_sales.provider import UnknownWrite
from apps.flash_sales.services import save_config, save_plan, submit
from apps.integrations.models import (
    MarketplaceStoreAuthorization, PlatformIntegrationConfig, authorization_service_write,
    marketplace_identity_key, marketplace_store_binding_key,
)
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.accounts.models import CustomUser
from apps.tenants.models import Tenant
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db


def _admin(code="platform-connector-admin"):
    tenant = Tenant.objects.create(name="Platform connector tenant", code=code)
    user = CustomUser.objects.create_user(
        username=code,
        password="not-a-real-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
        is_superuser=True,
    )
    client = APIClient()
    client.force_authenticate(user)
    return tenant, user, client


@pytest.fixture
def shop():
    tenant, user, client = _admin("flash-test")
    platform = PlatformMaster.objects.create(tenant=tenant, code="SP", name="Shopee", platform_type="shopee")
    store = StoreMaster.objects.create(tenant=tenant, platform=platform, code="SP1", name="Test Shopee",
        country_code="PH", currency="PHP", timezone="Asia/Manila", operator=user)
    config = PlatformIntegrationConfig.objects.create(tenant=tenant, platform="shopee", account_alias="Test Shopee",
        status="verified", environment="pilot", regions=["PH"], platform_config={"api_type": "marketplace"}, created_by=user)
    with authorization_service_write():
        identity = marketplace_identity_key("shopee", "PH", "10001")
        MarketplaceStoreAuthorization.objects.create(tenant=tenant, store=store, integration_config=config,
            platform="shopee", region="PH", platform_store_id="10001", platform_identity_key=identity,
            active_platform_identity_key=identity, active_store_binding_key=marketplace_store_binding_key(tenant.id, "shopee", store.id),
            merchant_subject_id="test-merchant", credential_id="test-reference", token_id="test-token-reference",
            status="active", expires_at=timezone.now()+timedelta(days=1), created_by=user, updated_by=user)
    return user, store, client


class FakeShopee:
    def __init__(self, *, lose_create=False, reject_all=False):
        self.lose_create, self.reject_all = lose_create, reject_all
        self.calls = []
        self.source = [{"item_id": "100", "model_id": "200", "price": "10.25", "stock": 3,
                        "available_stock": 5, "purchase_limit": 0, "status": 0}]
        self.created = {}
        self.products = {}
        self.target = {"timeslot_id": 999, "start_time": int(time.time()) + 3600, "end_time": int(time.time()) + 7200}

    def activities(self):
        return [{"flash_sale_id": 10, "timeslot_id": 100, "start_time": int(time.time())-7200,
                 "end_time": int(time.time())-3600, "status": 1, "item_count": 1}] + list(self.created.values())

    def items(self, activity_id):
        return self.source if str(activity_id) == "10" else self.products.get(str(activity_id), [])

    def slots(self):
        return [self.target]

    def detail(self, activity_id):
        return self.created.get(str(activity_id))

    def call(self, endpoint, *, body):
        self.calls.append((endpoint, body))
        if endpoint == "create_shop_flash_sale":
            self.created["20"] = {**self.target, "flash_sale_id": 20, "status": 1, "item_count": 0}
            if self.lose_create:
                self.lose_create = False
                raise UnknownWrite("response lost")
            return {"flash_sale_id": 20, "status": 1}
        if endpoint in {"add_shop_flash_sale_items", "update_shop_flash_sale_items"}:
            if self.reject_all:
                return {"failed_items": [{"item_id": 100, "model_id": 200, "err_msg": "price rejected",
                                           "unqualified_conditions": [{"unqualified_code": 10014}]}]}
            model = body["items"][0]["models"][0]
            self.products["20"] = [{**self.source[0], "price": str(model["input_promo_price"]), "stock": model["stock"], "status": 1}]
            return {}
        if endpoint == "delete_shop_flash_sale":
            self.created.pop(str(body["flash_sale_id"]), None)
            return {"flash_sale_id": body["flash_sale_id"], "status": 0}
        raise AssertionError(endpoint)


def configured(shop):
    user, store, _client = shop
    config = save_config(user, store.id, {"stock": 7, "runs": 1})
    assert config.enabled is False
    return save_config(user, store.id, {"enabled": True, "version": config.version})


def drain(task, adapter, count=8):
    states = []
    for _ in range(count):
        StoreTask.objects.filter(pk=task.id).update(next_attempt_at=None)
        states.append(run_step(task.id, adapter=adapter))
        task.refresh_from_db()
        if task.status in {"succeeded", "failed", "stopped"}:
            break
    return states


@pytest.mark.parametrize("value", [None, 0, -1, 1.5, True, 1000000])
def test_invalid_stock_does_not_persist(shop, value):
    user, store, _ = shop
    with pytest.raises(ValidationError):
        save_config(user, store.id, {"stock": value})
    assert not StoreConfig.objects.exists()


def test_batch_is_idempotent_and_initial_inventory_is_configured_amount(shop):
    user, store, _ = shop
    configured(shop)
    first = submit(user, request_id="once", store_ids=[store.id])
    assert submit(user, request_id="once", store_ids=[store.id]).id == first.id
    assert Batch.objects.count() == 1
    fake = FakeShopee()
    task = first.tasks.get()
    drain(task, fake)
    assert task.status == "succeeded"
    assert task.completed == 1
    assert fake.products["20"][0]["stock"] == 7
    assert Decimal(fake.products["20"][0]["price"]) == Decimal("10.25")
    assert sum(endpoint == "create_shop_flash_sale" for endpoint, _ in fake.calls) == 1


def test_unknown_create_recovers_without_a_second_creation(shop):
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id="lost-create", store_ids=[store.id]).tasks.get()
    fake = FakeShopee(lose_create=True)
    assert run_step(task.id, adapter=fake) == "confirming"
    assert WriteOperation.objects.get().status == "submitted"
    drain(task, fake)
    assert task.status == "confirming"
    assert not any(endpoint == "add_shop_flash_sale_items" for endpoint, _ in fake.calls)
    assert sum(endpoint == "create_shop_flash_sale" for endpoint, _ in fake.calls) == 1


def test_price_rejection_does_not_lower_price_and_cleans_only_owned_activity(shop):
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id="price-rejection", store_ids=[store.id]).tasks.get()
    fake = FakeShopee(reject_all=True)
    drain(task, fake)
    assert task.status == "failed"
    assert not fake.created
    assert Intent.objects.get().absence_evidence["absent"] is True
    assert sum(endpoint == "add_shop_flash_sale_items" for endpoint, _ in fake.calls) == 1


def test_readonly_and_foreign_store_rejected(shop):
    user, store, _ = shop
    _tenant, foreign, _client = _admin("flash-other")
    with pytest.raises(PermissionDenied):
        submit(foreign, request_id="foreign", store_ids=[store.id])
    user.is_superuser = False
    user.save(update_fields=["is_superuser"])
    with pytest.raises(PermissionDenied):
        save_config(user, store.id, {"stock": 7})


def test_plan_create_and_edit_are_paused(shop):
    user, store, _ = shop
    plan = save_plan(user, {"name": "daily", "kind": "daily", "time": "09:00", "store_ids": [store.id]})
    assert plan.enabled is False
    assert plan.next_due.utcoffset().total_seconds() == 0
    changed = save_plan(user, {"kind": "daily", "time": "10:00", "store_ids": [store.id], "version": plan.version}, plan.pk)
    assert changed.enabled is False
    assert changed.version == 2


def test_retry_wait_and_manual_item_values():
    assert [retry_delay(i) for i in range(6)] == [30, 60, 120, 300, 300, 300]
    assert retry_delay(0, 450) == 450
    assert validate_items([{"item_id": "99", "model_id": "1", "stock": 3, "price": "8.23", "purchase_limit": 0}])[0]["stock"] == 3


@pytest.mark.parametrize("available,expected", [(3, None), (4, 2), (5, 2)])
def test_only_explicit_stock_rejection_adjusts_inventory(shop, available, expected):
    configured(shop)
    user, store, _ = shop

    class StockRejected(FakeShopee):
        rejected = False

        def call(self, endpoint, *, body):
            if endpoint == "add_shop_flash_sale_items" and not self.rejected:
                self.rejected = True
                self.calls.append((endpoint, body))
                return {"failed_items": [{"item_id": 100, "model_id": 200, "err_msg": "insufficient stock"}]}
            return super().call(endpoint, body=body)

    fake = StockRejected()
    fake.source[0]["available_stock"] = available
    task = submit(user, request_id="stock", store_ids=[store.id]).tasks.get()
    drain(task, fake)
    assert task.status == ("succeeded" if expected else "failed")
    assert fake.products.get("20", [{}])[0].get("stock") == expected
    assert sum(endpoint == "add_shop_flash_sale_items" for endpoint, _ in fake.calls) == (2 if expected else 1)


def test_lost_delete_response_confirms_absence_without_repeating_delete(shop):
    configured(shop)
    user, store, _ = shop

    class LostDelete(FakeShopee):
        def call(self, endpoint, *, body):
            result = super().call(endpoint, body=body)
            if endpoint == "delete_shop_flash_sale":
                raise UnknownWrite("lost response")
            return result

    fake = LostDelete(reject_all=True)
    task = submit(user, request_id="lost-delete", store_ids=[store.id]).tasks.get()
    drain(task, fake)
    assert task.status == "failed"
    assert sum(endpoint == "delete_shop_flash_sale" for endpoint, _ in fake.calls) == 1
    assert Intent.objects.get().absence_evidence["absent"]


def test_safe_stop_before_and_after_owned_creation(shop):
    configured(shop)
    user, store, _ = shop
    batch = submit(user, request_id="stop-before", store_ids=[store.id])
    batch.stop_requested = True
    batch.save()
    fake = FakeShopee()
    task = batch.tasks.get()
    drain(task, fake)
    assert task.status == "stopped"
    assert not fake.calls
    batch = submit(user, request_id="stop-after", store_ids=[store.id])
    task = batch.tasks.get()
    assert run_step(task.id, adapter=fake) == "queued"
    batch.stop_requested = True
    batch.save()
    drain(task, fake)
    assert task.status == "stopped"
    assert not fake.created
    assert not any(endpoint == "add_shop_flash_sale_items" for endpoint, _ in fake.calls)


def test_permissions_are_rechecked_after_enqueue(shop):
    configured(shop)
    user, store, _ = shop
    task = submit(user, request_id="revoked-access", store_ids=[store.id]).tasks.get()
    user.is_superuser = False
    user.save()
    fake = FakeShopee()
    drain(task, fake)
    assert task.status == "failed"
    assert not fake.calls


def test_global_pool_and_fencing_prevent_parallel_or_stale_writes(shop):
    from apps.flash_sales.engine import claim, fence, LeaseLost
    user, store, _ = shop
    configured(shop)
    first = submit(user, request_id="pool1", store_ids=[store.id]).tasks.get()
    second = submit(user, request_id="pool2", store_ids=[store.id]).tasks.get()
    held = claim(first.id)
    assert claim(first.id) is None and claim(second.id) is None
    for index in range(2, 7):
        other = StoreMaster.objects.create(tenant=user.tenant, platform=store.platform, code=f"S{index}", name=f"Shop {index}", country_code="PH", currency="PHP", timezone="Asia/Manila")
        task = StoreTask.objects.create(tenant=user.tenant, batch=first.batch, store=other)
        assert bool(claim(task.id)) is (index <= 3)
    StoreTask.objects.filter(pk=first.pk).update(lease_until=timezone.now()-timedelta(seconds=1))
    replacement = claim(first.id)
    assert replacement.fence != held.fence
    with pytest.raises(LeaseLost):
        fence(held)


def test_config_mutations_are_blocked_while_active_and_delete_retains_history(shop):
    from apps.flash_sales.services import delete_config
    configured(shop)
    user, store, _ = shop
    config = StoreConfig.objects.get()
    with pytest.raises(ValidationError):
        delete_config(user, store.id, config.version)
    task = submit(user, request_id="busy-config", store_ids=[store.id]).tasks.get()
    with pytest.raises(ValidationError):
        save_config(user, store.id, {"stock": 4, "version": config.version})
    drain(task, FakeShopee())
    config = save_config(user, store.id, {"enabled": False, "version": config.version})
    delete_config(user, store.id, config.version)
    assert Batch.objects.count() == 1 and Intent.objects.count() == 1
    assert StoreConfig.objects.get().deleted_at


def test_scheduler_idempotency_and_recovery_do_not_catch_up(shop):
    from apps.flash_sales.models import TenantControl
    from apps.flash_sales.tasks import dispatch_plans
    configured(shop)
    user, store, _ = shop
    now = timezone.now()
    control = TenantControl.objects.create(tenant=user.tenant, scheduler_owner="saas", last_dispatch_at=now-timedelta(seconds=5))
    plan = save_plan(user, {"kind": "daily", "time": "09:00", "store_ids": [store.id]})
    plan.enabled, plan.next_due = True, now-timedelta(seconds=1)
    plan.save()
    dispatch_plans(now=now)
    dispatch_plans(now=now)
    assert Batch.objects.count() == 1 and StoreTask.objects.get().status == "queued"
    plan.refresh_from_db()
    plan.next_due = now+timedelta(seconds=10)
    plan.save()
    # Restart 40 seconds later: the occurrence is <60s late but must still be missed.
    dispatch_plans(now=now+timedelta(seconds=40))
    assert Batch.objects.count() == 2
    assert StoreTask.objects.filter(status="missed").count() == 1
    assert StoreTask.objects.filter(status="queued").count() == 1


def test_sync_failure_preserves_cache_and_last_success(shop):
    from apps.flash_sales.models import Activity
    from apps.flash_sales.provider import Deferred
    configured(shop)
    user, store, _ = shop
    original = timezone.now()-timedelta(days=1)
    StoreConfig.objects.filter(store=store).update(last_synced_at=original)
    row = Activity.objects.create(tenant=user.tenant, store=store, platform_id="10", slot_id="100", starts_at=original, ends_at=original+timedelta(hours=1), platform_status=1, synced_at=original)

    class FailedPage(FakeShopee):
        def activities(self):
            raise Deferred("second page failed")

    task = submit(user, request_id="sync-failed", operation="sync", store_ids=[store.id]).tasks.get()
    assert run_step(task.id, adapter=FailedPage()) == "waiting"
    assert StoreConfig.objects.get().last_synced_at == original
    row.refresh_from_db()
    assert row.synced_at == original


def test_api_shapes_and_unknown_fields_fail_cleanly(shop):
    user, store, client = shop
    response = client.get("/api/internal/marketing/flash-sales/workspace/")
    assert response.status_code == 200
    assert response.data["data"]["stores"][0]["id"] == store.id
    assert "open_id" not in str(response.data)
    bad = client.post("/api/internal/marketing/flash-sales/batches/", {"operation": "run"}, format="json")
    assert bad.status_code == 400
    bad = client.post("/api/internal/marketing/flash-sales/batches/", {"request_id": "bad", "store_ids": [store.id], "tenant_id": 999}, format="json")
    assert bad.status_code == 400


def test_notifications_are_snapshotted_per_person_and_accepted_not_resent(shop):
    from apps.accounts.models import CustomUser
    from apps.flash_sales.models import Notification, TenantControl
    from apps.flash_sales.notifications import deliver, prepare_notifications, recipient_snapshot
    from apps.integrations.models import FeishuConnection, FeishuIdentity
    configured(shop)
    user, store, _ = shop
    backup = CustomUser.objects.create_user(username="flash-fallback", tenant=user.tenant, user_type="internal")
    FeishuIdentity.objects.create(tenant=user.tenant, user=user, open_id="ou_synthetic_owner")
    FeishuIdentity.objects.create(tenant=user.tenant, user=backup, open_id="ou_synthetic_backup")
    FeishuConnection.objects.create(tenant=user.tenant, app_id="synthetic-app", app_secret_ref="synthetic-ref", enabled=True, created_by=user, updated_by=user)
    control = TenantControl.objects.create(tenant=user.tenant)
    control.fallback_users.set([backup])
    config = StoreConfig.objects.get()
    assert recipient_snapshot(store, config)["users"][0]["user_id"] == user.id
    config.notification_mode = "fallback"
    config.save()
    assert recipient_snapshot(store, config)["users"][0]["user_id"] == backup.id
    task = submit(user, request_id="notify", store_ids=[store.id]).tasks.get()
    drain(task, FakeShopee())
    prepare_notifications(task.batch_id)
    record = Notification.objects.get()
    assert record.recipient_id == backup.id
    control.fallback_users.set([user])

    class Sender:
        calls = []

        def send(self, *args):
            self.calls.append(args)
            return "synthetic-message-id"

    sender = Sender()
    assert deliver(record.pk, sender) == "accepted"
    assert deliver(record.pk, sender) == "accepted"
    assert len(sender.calls) == 1
    assert sender.calls[0][1] == "ou_synthetic_backup"
    assert store.name in sender.calls[0][3]["text"]
    Notification.objects.filter(pk=record.pk).update(status="pending", message="原发送未知", created_at=timezone.now()-timedelta(hours=1))
    assert deliver(record.pk, sender) == "uncertain_expired"
    assert len(sender.calls) == 1


def test_cleanup_releases_slot_but_keeps_previous_intent(shop):
    configured(shop)
    user, store, _ = shop
    first = submit(user, request_id="first-rejected", store_ids=[store.id]).tasks.get()
    drain(first, FakeShopee(reject_all=True))
    old = first.intents.get()
    assert old.absence_evidence["absent"] and old.reservation_key is None
    second = submit(user, request_id="second-same-slot", store_ids=[store.id]).tasks.get()
    drain(second, FakeShopee())
    assert second.intents.get().slot_id == old.slot_id
    assert Intent.objects.count() == 2


def test_latest_store_result_is_independent_of_history_page(shop):
    configured(shop)
    user, store, client = shop
    task = submit(user, request_id="latest-store", store_ids=[store.id]).tasks.get()
    drain(task, FakeShopee())
    response = client.get("/api/internal/marketing/flash-sales/workspace/?history_page=20")
    assert response.data["data"]["batches"] == []
    assert response.data["data"]["stores"][0]["latest_task"]["status"] == "succeeded"


def test_post_sync_is_independent_and_idempotent(shop):
    from apps.flash_sales.tasks import prepare_post_sync
    configured(shop)
    user, store, _ = shop
    task = submit(user, request_id="post-sync", store_ids=[store.id]).tasks.get()
    drain(task, FakeShopee())
    prepare_post_sync(task.batch_id)
    prepare_post_sync(task.batch_id)
    child = Batch.objects.get(source="post_sync")
    assert child.tasks.count() == 1 and child.operation == "sync"
    assert child.tasks.get().snapshot["recipients"]["users"] == []
    task.refresh_from_db()
    assert task.status == "succeeded" and task.state["post_sync_task_id"] == child.tasks.get().id


def test_preflight_rejection_does_not_become_unknown_outbound_write(shop):
    configured(shop)
    user, store, _ = shop
    class PreflightRejected(FakeShopee):
        def call(self, endpoint, *, body):
            raise ValidationError("Connection is not enabled")
    task = submit(user, request_id="preflight-rejected", store_ids=[store.id]).tasks.get()
    assert run_step(task.id, adapter=PreflightRejected()) == "failed"
    assert not WriteOperation.objects.filter(status="submitted").exists()


@pytest.mark.parametrize("header,expected", [("450", 450), ("NaN", 300), ("Fri, 13 Nov 2026 00:10:00 GMT", 600)])
def test_rate_limit_preserves_full_retry_after_without_sleep(monkeypatch, header, expected):
    from apps.integrations.net_guard import HttpResponse, PlatformHttpClient
    from apps.integrations.oauth_errors import OAuthFlowError, OAUTH_RATE_LIMITED
    monkeypatch.setattr("apps.integrations.net_guard.assert_host_allowed", lambda url: None)
    monkeypatch.setattr("apps.integrations.net_guard.time.time", lambda: 1794528000)
    calls, sleeps = [], []
    def transport(*args, **kwargs):
        calls.append(1)
        return HttpResponse(status_code=429, headers={"Retry-After": header}, text="{}")
    with pytest.raises(OAuthFlowError) as error:
        PlatformHttpClient(transport=transport, max_retries=0, sleeper=sleeps.append).request("POST", "https://synthetic.invalid", json_body={}, retry=False)
    assert error.value.controlled_code == OAUTH_RATE_LIMITED
    assert error.value.retry_after == expected and calls == [1] and sleeps == []


def test_single_owner_cutover_and_rollback_require_reconciliation(shop, tmp_path):
    import hashlib
    import json
    from io import StringIO
    from django.core.management import call_command, CommandError
    from apps.flash_sales.models import TenantControl
    user, store, _ = shop
    plan = save_plan(user, {"kind": "daily", "time": "09:00", "store_ids": [store.id]})
    common = {"tenant_code": user.tenant.code, "actor": user.username, "stdout": StringIO()}
    call_command("flash_sales_owner", owner="paused", **common)
    with pytest.raises(CommandError):
        call_command("flash_sales_owner", owner="saas", **common)
    evidence_path = tmp_path/"synthetic-cutover.json"
    def evidence(owner):
        raw = json.dumps({"tenant_code": user.tenant.code, "target_owner": owner,
            "previous_source_stopped": True, "writes_reconciled": True, "verified_by": "isolated-test",
            "verified_at": timezone.now().isoformat(), "imported_record_count": 0}).encode()
        evidence_path.write_bytes(raw)
        return {"evidence": str(evidence_path), "sha256": hashlib.sha256(raw).hexdigest()}
    call_command("flash_sales_owner", owner="saas", **evidence("saas"), **common)
    assert TenantControl.objects.get().scheduler_owner == "saas"
    plan.refresh_from_db()
    assert not plan.enabled
    with pytest.raises(CommandError):
        call_command("flash_sales_owner", owner="legacy", **evidence("legacy"), **common)
    call_command("flash_sales_owner", owner="paused", **common)
    batch = Batch.objects.create(tenant=user.tenant, actor=user, request_id="unreconciled", payload_hash="test", source="manual")
    task = StoreTask.objects.create(tenant=user.tenant, batch=batch, store=store, status="confirming")
    with pytest.raises(CommandError):
        call_command("flash_sales_owner", owner="legacy", **evidence("legacy"), **common)
    task.status, task.finished_at = "stopped", timezone.now()
    task.save()
    call_command("flash_sales_owner", owner="legacy", **evidence("legacy"), **common)
    assert TenantControl.objects.get().scheduler_owner == "legacy"
