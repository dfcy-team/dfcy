from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.services import write_operation_log
from apps.integrations.models import MarketplaceStoreAuthorization
from .domain import TERMINAL, digest, identifier, integer
from .models import Activity, Batch, Plan, Preview, StoreConfig, StoreLock, StoreTask, TenantControl
from .permissions import require_stores, visible_stores


def authorized_store(store):
    if store.status != "active":
        raise ValidationError("店铺已停用。")
    rows = list(MarketplaceStoreAuthorization.objects.filter(
        tenant_id=store.tenant_id, store=store, platform="shopee", status="active",
    ).select_related("integration_config"))
    rows = [row for row in rows if (row.integration_config.platform_config or {}).get("api_type", "marketplace") == "marketplace"]
    if len(rows) != 1:
        raise ValidationError("店铺须有唯一有效的 Shopee 商城授权。")
    return rows[0]


def audit(user, action, record, detail=None):
    write_operation_log(tenant=user.tenant, user=user, module="marketing", action=action,
                        object_type="flash_sales", object_id=str(record.pk), after_data=detail or {})


@transaction.atomic
def save_config(user, store_id, values):
    store = require_stores(user, [store_id], "configure")[0]
    authorized_store(store)
    if set(values) - {"stock", "runs", "enabled", "notification_mode", "recipient_ids", "version"}:
        raise ValidationError("店铺配置包含不支持的字段。")
    lock, _ = StoreLock.objects.get_or_create(tenant=user.tenant, store=store)
    lock = StoreLock.objects.select_for_update().get(pk=lock.pk)
    if lock.task_id or StoreTask.objects.filter(store=store).exclude(status__in=TERMINAL).exists():
        raise ValidationError("店铺正在处理任务，请完成或安全停止后再修改。")
    config = StoreConfig.objects.select_for_update().filter(store=store).first()
    if config and values.get("version") != config.version:
        raise ValidationError("配置版本已变化，请刷新后重试。")
    is_new = not config or config.deleted_at is not None
    config = config or StoreConfig(tenant=user.tenant, store=store)
    config.stock = integer(values.get("stock", config.stock), "活动库存")
    config.runs = integer(values.get("runs", config.runs or 1), "时段数")
    if "enabled" in values and type(values["enabled"]) is not bool:
        raise ValidationError("启用状态无效。")
    config.enabled = False if is_new else values.get("enabled", config.enabled)
    mode = values.get("notification_mode", config.notification_mode)
    if mode not in {"owner", "custom", "fallback"}:
        raise ValidationError("通知方式无效。")
    from .notifications import validate_recipients
    recipients = values.get("recipient_ids", list(config.recipients.values_list("id", flat=True)) if config.pk else [])
    if mode == "custom":
        validate_recipients(user.tenant_id, recipients)
    config.notification_mode, config.deleted_at = mode, None
    config.version += 1 if config.pk else 0
    config.save()
    config.recipients.set(recipients if mode == "custom" else [])
    audit(user, "flash_config_save", config, {"version": config.version, "enabled": config.enabled})
    return config


@transaction.atomic
def delete_config(user, store_id, version):
    store = require_stores(user, [store_id], "delete")[0]
    StoreLock.objects.get_or_create(tenant=user.tenant, store=store)
    lock = StoreLock.objects.select_for_update().get(store=store)
    config = StoreConfig.objects.select_for_update().get(tenant=user.tenant, store=store, deleted_at__isnull=True)
    if config.enabled or lock.task_id or StoreTask.objects.filter(store=store).exclude(status__in=TERMINAL).exists():
        raise ValidationError("请先停用店铺并结束正在处理的任务。")
    if version != config.version:
        raise ValidationError("配置版本已变化。")
    config.deleted_at = timezone.now()
    config.version += 1
    config.save(update_fields=["deleted_at", "version", "updated_at"])
    audit(user, "flash_config_delete", config)


@transaction.atomic
def submit(user, *, request_id, store_ids, operation="run", preview_id=None, activity_id=None, desired_status=None,
           confirmed=False, plan=None, due=None, activity_ids=None):
    if operation not in {"run", "copy", "sync", "toggle", "delete"}:
        raise ValidationError("操作无效。")
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 120:
        raise ValidationError("缺少有效的请求编号。")
    stores = require_stores(user, store_ids, "delete" if operation == "delete" else "execute")
    if operation in {"copy", "toggle", "delete"} and len(stores) != 1:
        raise ValidationError("此操作须选择一家店铺。")
    if operation == "delete" and confirmed is not True:
        raise ValidationError("请明确确认删除所选活动。")
    if operation == "toggle" and desired_status not in (1, 2):
        raise ValidationError("活动状态无效。")
    if operation in {"toggle", "delete"}:
        activity_id = identifier(activity_id)
        if not Activity.objects.filter(tenant=user.tenant, store=stores[0], platform_id=activity_id).exists():
            raise ValidationError("活动不属于所选店铺，请先同步。")
    selected = []
    if activity_ids is not None:
        if operation != "sync" or not isinstance(activity_ids, list) or not activity_ids or len(activity_ids) > 500 or any(type(pk) is not int for pk in activity_ids):
            raise ValidationError("请选择有效的待同步活动。")
        selected = list(Activity.objects.filter(tenant=user.tenant, store_id__in=store_ids, pk__in=activity_ids))
        if len(selected) != len(set(activity_ids)):
            raise ValidationError("活动超出所选店铺范围。")
    payload = {"stores": sorted(set(store_ids)), "operation": operation, "preview": str(preview_id or ""),
               "activity": str(activity_id or ""), "desired_status": desired_status, "activity_ids": sorted(activity_ids or [])}
    previous = Batch.objects.filter(tenant=user.tenant, request_id=request_id).first()
    if previous:
        if previous.payload_hash != digest(payload):
            raise ValidationError("相同请求编号不能用于不同操作。")
        return previous
    preview = None
    if operation == "copy":
        preview = Preview.objects.select_for_update().filter(pk=preview_id, tenant=user.tenant, store=stores[0], actor=user).first()
        if not preview or preview.expires_at <= timezone.now() or preview.batch_id:
            raise ValidationError("复制预览已过期或已发布，请重新预览。")
    snapshots = []
    for store in sorted(stores, key=lambda row: row.pk):
        authorized_store(store)
        StoreLock.objects.get_or_create(tenant=user.tenant, store=store)
        StoreLock.objects.select_for_update().get(store=store)
        config = StoreConfig.objects.filter(tenant=user.tenant, store=store, deleted_at__isnull=True).first()
        if operation == "run" and (not config or not config.enabled):
            raise ValidationError("自动补建须先配置并启用店铺。")
        from .notifications import recipient_snapshot
        snapshots.append((store, {
            "stock": config.stock if config else None, "runs": config.runs if operation == "run" else 1,
            "config_version": config.version if config else None, "preview_id": str(preview_id or ""),
            "activity_id": str(activity_id or ""), "desired_status": desired_status,
            "activity_ids": [row.platform_id for row in selected if row.store_id == store.id],
            "recipients": recipient_snapshot(store, config),
        }))
    # A competing request may have committed while this transaction waited for a store lock.
    previous = Batch.objects.filter(tenant=user.tenant, request_id=request_id).first()
    if previous:
        if previous.payload_hash != digest(payload):
            raise ValidationError("相同请求编号不能用于不同操作。")
        return previous
    batch = Batch.objects.create(tenant=user.tenant, actor=user, request_id=request_id, payload_hash=digest(payload),
        operation=operation, source="scheduled" if plan else "copy" if operation == "copy" else "manual",
        plan=plan, plan_version=plan.version if plan else None, scheduled_at=due)
    for store, snapshot in snapshots:
        StoreTask.objects.create(tenant=user.tenant, batch=batch, store=store, snapshot=snapshot, requested=snapshot["runs"])
    if preview:
        preview.batch = batch
        preview.save(update_fields=["batch", "updated_at"])
    audit(user, "flash_submit", batch, {"operation": operation, "store_ids": store_ids})
    return batch


def next_due(kind, local_date, local_time, *, now=None):
    now = now or timezone.now()
    zone = ZoneInfo("Asia/Shanghai")
    today = now.astimezone(zone).date()
    candidate = datetime.combine(local_date if kind == "once" else today, local_time, tzinfo=zone)
    if kind == "daily" and candidate <= now:
        candidate += timedelta(days=1)
    if candidate <= now:
        raise ValidationError("单次计划须选择未来时间。")
    return candidate.astimezone(dt_timezone.utc)


@transaction.atomic
def save_plan(user, values, pk=None):
    if set(values) - {"name", "kind", "date", "time", "store_ids", "version"}:
        raise ValidationError("计划包含不支持的字段。")
    visible_stores(user, "plans")
    ids = values.get("store_ids")
    stores = [] if ids == [] else require_stores(user, ids, "plans")
    if ids:
        require_stores(user, ids, "execute")
    kind = values.get("kind")
    if kind not in {"once", "daily"}:
        raise ValidationError("请选择单次或每日计划。")
    try:
        clock = datetime.strptime(values.get("time", ""), "%H:%M").time()
        date = datetime.strptime(values.get("date", ""), "%Y-%m-%d").date() if kind == "once" else None
    except (ValueError, TypeError):
        raise ValidationError("请填写北京时间，单次计划还需填写日期。") from None
    due = next_due(kind, date, clock)
    plan = Plan.objects.select_for_update().filter(tenant=user.tenant, pk=pk, deleted_at__isnull=True).first() if pk else None
    if pk and not plan:
        raise ValidationError("计划不存在。")
    if plan:
        old_ids = list(plan.stores.values_list("id", flat=True))
        if old_ids:
            require_stores(user, old_ids, "plans")
        if values.get("version") != plan.version:
            raise ValidationError("计划版本已变化。")
    plan = plan or Plan(tenant=user.tenant, actor=user)
    plan.name = str(values.get("name") or "闪购计划")[:120]
    plan.kind, plan.local_date, plan.local_time = kind, date, clock
    plan.next_due, plan.enabled = due, False
    plan.version += 1 if plan.pk else 0
    plan.actor = user
    plan.save()
    plan.stores.set(stores)
    audit(user, "flash_plan_save_paused", plan, {"version": plan.version})
    return plan


@transaction.atomic
def enable_plan(user, pk, version, enabled):
    plan = Plan.objects.select_for_update().get(pk=pk, tenant=user.tenant, deleted_at__isnull=True)
    ids = list(plan.stores.values_list("id", flat=True))
    require_stores(user, ids, "plans")
    require_stores(user, ids, "execute")
    if type(enabled) is not bool or version != plan.version:
        raise ValidationError("计划状态或版本无效。")
    if enabled:
        control = TenantControl.objects.filter(tenant=user.tenant).first()
        if not control or control.scheduler_owner != "saas":
            raise ValidationError("尚未完成旧调度停止和单边接管，计划保持暂停。")
        plan.next_due = next_due(plan.kind, plan.local_date, plan.local_time)
    plan.enabled, plan.actor, plan.version = enabled, user, plan.version + 1
    plan.save()
    audit(user, "flash_plan_enable" if enabled else "flash_plan_pause", plan)
    return plan


@transaction.atomic
def delete_plan(user, pk, version):
    visible_stores(user, "plans")
    plan = Plan.objects.select_for_update().get(pk=pk, tenant=user.tenant, deleted_at__isnull=True)
    ids = list(plan.stores.values_list("id", flat=True))
    if ids:
        require_stores(user, ids, "plans")
    if plan.enabled or version != plan.version:
        raise ValidationError("请先暂停计划，并刷新核对版本后删除。")
    plan.deleted_at, plan.next_due = timezone.now(), None
    plan.version += 1
    plan.save(update_fields=["deleted_at", "next_due", "version", "updated_at"])
    audit(user, "flash_plan_delete", plan)
