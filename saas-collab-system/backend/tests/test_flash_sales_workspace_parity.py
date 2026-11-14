from datetime import datetime, timedelta, timezone as utc

import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.flash_sales.models import Activity, Batch, Plan, StoreTask
from apps.flash_sales.services import delete_plan, enable_plan, save_plan
from tests.test_flash_sales import shop

pytestmark = pytest.mark.django_db
URL = "/api/internal/marketing/flash-sales/workspace/"


def activity(shop, key, start, end):
    user, store, _ = shop
    return Activity.objects.create(tenant=user.tenant, store=store, platform_id=str(key), slot_id=str(key),
        starts_at=start, ends_at=end, platform_status=1, item_count=2, enabled_count=1, synced_at=timezone.now())


def test_current_activities_do_not_consume_five_future_slots(shop):
    now = timezone.now()
    activity(shop, 1, now - timedelta(hours=1), now + timedelta(hours=1))
    activity(shop, 2, now - timedelta(minutes=30), now + timedelta(hours=1))
    for index in range(3, 10):
        activity(shop, index, now + timedelta(hours=index), now + timedelta(hours=index + 1))
    row = shop[2].get(URL).data["data"]["stores"][0]
    assert [a["platform_id"] for a in row["current"]] == ["1", "2"]
    assert [a["platform_id"] for a in row["upcoming"]] == ["3", "4", "5", "6", "7"]


def test_date_filter_uses_each_store_local_midnight_and_exclusive_end(shop):
    # Manila 2026-11-13 starts at 16:00 UTC on the preceding day.
    start = datetime(2026, 11, 12, 16, tzinfo=utc.utc)
    for index, offset in enumerate([-1, 0, 86399, 86400]):
        stamp = start + timedelta(seconds=offset)
        activity(shop, index + 1, stamp, stamp + timedelta(hours=1))
    data = shop[2].get(URL, {"date_from": "2026-11-13", "date_to": "2026-11-13"}).data["data"]
    assert {a["platform_id"] for a in data["activities"]} == {"2", "3"}
    assert data["activity_counts"]["all"] == 2
    assert data["stores"][0]["activity_count"] == 4


def test_history_filters_match_same_store_task(shop):
    user, store, client = shop
    for source, status in [("manual", "failed"), ("scheduled", "succeeded")]:
        batch = Batch.objects.create(tenant=user.tenant, actor=user, source=source, request_id=source, payload_hash="test")
        StoreTask.objects.create(tenant=user.tenant, store=store, batch=batch, status=status)
    data = client.get(URL, {"history_store_id": store.id, "history_source": "scheduled", "history_status": "succeeded"}).data["data"]
    assert data["batch_total"] == 1
    assert data["batches"][0]["source"] == "scheduled"
    assert client.get(URL, {"history_store_id": store.id + 999}).data["data"]["batch_total"] == 0


def test_time_point_can_be_saved_before_stores_but_cannot_be_enabled(shop):
    user, store, _ = shop
    plan = save_plan(user, {"kind": "daily", "time": "09:00", "store_ids": []})
    assert not plan.enabled and not plan.stores.exists()
    with pytest.raises(PermissionDenied):
        enable_plan(user, plan.pk, plan.version, True)
    changed = save_plan(user, {"kind": "daily", "time": "09:00", "store_ids": [store.pk], "version": plan.version}, plan.pk)
    assert list(changed.stores.values_list("pk", flat=True)) == [store.pk]
    assert not changed.enabled


def test_plan_delete_preserves_history_and_rejects_stale_version(shop):
    user, store, client = shop
    plan = save_plan(user, {"kind": "daily", "time": "09:00", "store_ids": [store.pk]})
    batch = Batch.objects.create(tenant=user.tenant, actor=user, source="scheduled", request_id="history", payload_hash="test", plan=plan)
    with pytest.raises(ValidationError):
        delete_plan(user, plan.pk, plan.version + 1)
    delete_plan(user, plan.pk, plan.version)
    assert Batch.objects.get(pk=batch.pk).plan_id == plan.pk
    assert Plan.objects.get(pk=plan.pk).deleted_at
    assert client.get(URL).data["data"]["plans"] == []
    with pytest.raises(ValidationError):
        save_plan(user, {"kind": "daily", "time": "10:00", "store_ids": [store.pk], "version": plan.version}, plan.pk)
def test_product_details_preserve_display_dimensions_and_missing_values():
    from apps.flash_sales.domain import normalize_items

    rows = normalize_items([{"item_id": 31, "item_name": "商品"}], [
        {"item_id": 31, "model_id": 52, "model_name": "蓝色", "input_promotion_price": "10.50",
         "original_price": "12.50", "campaign_stock": 0, "stock": 0, "reject_reason": "库存不足"},
    ])
    assert rows[0]["model_name"] == "蓝色"
    assert rows[0]["original_price"] == "12.50"
    assert rows[0]["reject_reason"] == "库存不足"
    assert rows[0]["status"] is None
    assert rows[0]["stock"] == rows[0]["available_stock"] == 0


@pytest.mark.parametrize("image,expected", [("https://images.example.invalid/item.png", "https://images.example.invalid/item.png"), ("javascript:alert(1)", ""), (None, "")])
def test_product_image_is_preserved_only_for_https(image, expected):
    from apps.flash_sales.domain import normalize_items

    rows = normalize_items([{"item_id": 1, "image": image}], [])
    assert rows[0]["image"] == expected


def test_notification_table_updates_are_atomic_and_do_not_change_existing_tasks(shop):
    from apps.flash_sales.models import StoreConfig, TenantControl
    from apps.integrations.models import FeishuIdentity
    from apps.masterdata.models import StoreMaster

    user, store, client = shop
    other = StoreMaster.objects.create(tenant=user.tenant, platform=store.platform, code="SP2", name="第二店")
    configs = [StoreConfig.objects.create(tenant=user.tenant, store=s, stock=7, runs=1) for s in [store, other]]
    FeishuIdentity.objects.create(tenant=user.tenant, user=user, open_id="ou_synthetic_notification_parity")
    batch = Batch.objects.create(tenant=user.tenant, actor=user, request_id="notification-history", payload_hash="test")
    task = StoreTask.objects.create(tenant=user.tenant, store=store, batch=batch, status="running", snapshot={"recipients": {"mode": "owner", "users": []}})
    body = {"user_ids": [user.pk], "stores": [{"store_id": s.pk, "version": config.version, "notification_mode": "fallback", "recipient_ids": []} for s, config in zip([store, other], configs)]}
    body["stores"][1]["version"] += 1
    response = client.put(URL.replace("workspace/", "notifications/"), body, format="json")
    assert response.status_code == 400
    configs[0].refresh_from_db()
    assert configs[0].notification_mode == "owner"
    assert not TenantControl.objects.filter(tenant=user.tenant, fallback_users=user).exists()
    body["stores"][1]["version"] -= 1
    assert client.put(URL.replace("workspace/", "notifications/"), body, format="json").status_code == 200
    assert StoreConfig.objects.filter(tenant=user.tenant, notification_mode="fallback").count() == 2
    task.refresh_from_db()
    assert task.snapshot["recipients"] == {"mode": "owner", "users": []}


def test_notification_table_rejects_foreign_stores_and_preserves_global_fallback(shop):
    from apps.flash_sales.models import StoreConfig, TenantControl
    from apps.integrations.models import FeishuIdentity

    user, store, client = shop
    config = StoreConfig.objects.create(tenant=user.tenant, store=store, stock=7, runs=1)
    FeishuIdentity.objects.create(tenant=user.tenant, user=user, open_id="ou_synthetic_notification_scope")
    control = TenantControl.objects.create(tenant=user.tenant)
    control.fallback_users.add(user)
    body = {"stores": [{"store_id": store.pk, "version": config.version, "notification_mode": "custom", "recipient_ids": [user.pk]}]}
    assert client.put(URL.replace("workspace/", "notifications/"), body, format="json").status_code == 200
    assert list(control.fallback_users.values_list("pk", flat=True)) == [user.pk]
    body["stores"][0]["store_id"] = store.pk + 999
    assert client.put(URL.replace("workspace/", "notifications/"), body, format="json").status_code == 403
