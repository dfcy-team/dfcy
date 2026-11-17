"""Recipient snapshots are fixed when a batch is submitted, never rebuilt on retry."""
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.integrations.feishu_delivery import DELIVERY_IDEMPOTENCY_WINDOW, FeishuMessageService
from apps.integrations.models import FeishuConnection, FeishuIdentity
from .domain import TERMINAL
from .models import Batch, Intent, Notification, TenantControl


def valid_identities(tenant_id, ids):
    return FeishuIdentity.objects.filter(tenant_id=tenant_id, user_id__in=ids, user__tenant_id=tenant_id,
        user__is_active=True, user__user_type="internal", status="active").exclude(open_id="").select_related("user")


def validate_recipients(tenant_id, ids):
    if not isinstance(ids, list) or not ids or len(ids) > 50 or any(type(value) is not int or value < 1 for value in ids):
        raise ValidationError("请选择 1～50 名有效接收人。")
    if len(ids) != len(set(ids)) or valid_identities(tenant_id, ids).count() != len(ids):
        raise ValidationError("接收人须为当前租户启用并已绑定飞书的内部人员。")


def recipient_snapshot(store, config):
    mode = config.notification_mode if config else "owner"
    if mode == "disabled":
        return {"mode": mode, "reason": "已关闭推送", "error": "", "users": []}
    control = TenantControl.objects.filter(tenant_id=store.tenant_id).first()
    fallback = list(control.fallback_users.values_list("id", flat=True)) if control else []
    primary = list(config.recipients.values_list("id", flat=True)) if mode == "custom" else [store.operator_id] if store.operator_id else []
    ids = fallback if mode == "fallback" else primary
    records = list(valid_identities(store.tenant_id, ids))
    reason = "明确使用全局兜底" if mode == "fallback" else ""
    if mode != "fallback" and (not ids or len(records) != len(set(ids))):
        records = list(valid_identities(store.tenant_id, fallback))
        reason = "主接收人缺失、停用或未绑定飞书，使用兜底"
    return {"mode": mode, "reason": reason, "error": "没有有效接收人或兜底人员" if not records else "",
            "users": [{"user_id": row.user_id, "name": row.user.full_name or row.user.username,
                       "open_id": row.open_id} for row in records]}


def task_result(task):
    intents = sorted(task.intents.all(), key=lambda intent: intent.id)
    attempts = {}
    for intent in intents:
        attempts[intent.slot_id] = max(attempts.get(intent.slot_id, 0), intent.result.get("execution_attempt", 0))
    failed_activities = [i for i in intents if i.platform_id and i.status != "succeeded"]
    cleanup = ("失败活动已全部清理" if all(i.absence_evidence.get("absent") for i in failed_activities) else
               "失败活动清理尚未确认，需人工核对") if failed_activities else "无待清理的失败活动"
    succeeded = [i for i in intents if i.status == "succeeded"]
    specifications = [row for i in succeeded for row in i.result.get("specifications", [])]
    latest_failed = {i.slot_id: i for i in intents if i.status == "failed"}
    reasons = list(dict.fromkeys(row["reason"] for i in latest_failed.values()
        for row in i.result.get("specifications", []) if row.get("state") == "rejected" and row.get("reason")))
    return {"store_id": task.store_id, "name": task.store.name, "status": task.status,
            "completed": task.completed, "requested": task.requested, "message": task.message,
            "retries": sum(attempts.values()), "cleanup": cleanup,
            "failure_details": reasons[:3],
            "enabled_specifications": sum(row.get("state") == "enabled" for row in specifications),
            "rejected_specifications": sum(row.get("state") == "rejected" for row in specifications),
            "activities": [{"id": i.platform_id, "start": i.target.get("start_time"),
                            "end": i.target.get("end_time")} for i in succeeded]}


def notification_text(batch, snapshot):
    def stamp(value):
        if not value:
            return "未记录"
        if isinstance(value, (int, float)):
            value = datetime.fromtimestamp(value, dt_timezone.utc)
        return value.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")

    stores = snapshot["stores"]
    succeeded = sum(store["status"] == "succeeded" for store in stores)
    attention = snapshot.get("phase") == "attention"
    operation = {"run": "补建闪购", "copy": "复制闪购", "sync": "同步活动", "toggle": "调整活动状态", "delete": "删除活动"}.get(batch.operation, "闪购操作")
    lines = [f"店内闪购｜{operation}{'异常待核对提醒' if attention else '批次执行结果'}", f"批次：{batch.id}",
             f"执行：{stamp(batch.created_at)} → {stamp(batch.finished_at)}（北京时间）",
             f"本通知店铺：{len(stores)} 家｜成功 {succeeded} 家｜失败 {len(stores) - succeeded} 家"]
    if attention:
        lines[3] = f"本通知店铺：{len(stores)} 家；批次尚未结束，以下为需要核对的异常。"
    for store in stores:
        success = store["status"] == "succeeded"
        lines.extend(["", f"{'待核对' if attention else '成功' if success else '失败'}｜{store['name']}"])
        if batch.operation in {"run", "copy"}:
            lines.append(f"时段完成：{store['completed']}/{store['requested']}")
        retries = store.get("retries")
        if retries is not None:
            lines.append(f"重建重试：{retries} 次（不含限流等待）")
            if success and retries and store["requested"] == 1:
                lines.append(f"第 {retries} 次重试成功")
        lines.append(f"{'结果' if success else '失败原因'}：{store['message']}")
        if not success and store.get("failure_details"):
            lines.append("平台原因：" + "；".join(store["failure_details"]))
        if store.get("cleanup"):
            lines.append(f"清理结果：{store['cleanup']}")
        for activity in store.get("activities", []):
            if activity.get("start") and activity.get("end"):
                lines.append(f"活动时段：{stamp(activity['start'])} ～ {stamp(activity['end'])}（北京）")
        if store.get("enabled_specifications") or store.get("rejected_specifications"):
            lines.append(f"规格结果：已参加 {store['enabled_specifications']}，平台拒绝 {store['rejected_specifications']}")
    base = settings.SUPPLY_NOTIFICATION_PUBLIC_BASE_URL.rstrip("/")
    lines.extend(["", f"查看运行详情：{base}/marketing/campaigns?activity=flash&tab=history&batch={batch.id}"])
    return "\n".join(lines)


@transaction.atomic
def prepare_notifications(batch_id):
    batch = Batch.objects.select_for_update().get(pk=batch_id)
    cutoff = TenantControl.objects.filter(tenant_id=batch.tenant_id).values_list("notifications_not_before", flat=True).first()
    if cutoff and batch.created_at < cutoff:
        return
    if batch.operation == "sync" or batch.request_id.startswith("import:") or batch.source == "post_sync":
        return
    attention = batch.tasks.exclude(status__in=TERMINAL).exists()
    if attention and not batch.tasks.filter(state__retry_paused=True).exists():
        return
    groups = {}
    for task in batch.tasks.select_related("store").prefetch_related(
            Prefetch("intents", queryset=Intent.objects.defer("items").order_by())).order_by("id"):
        routing = task.snapshot.get("recipients", {})
        if attention and not task.state.get("retry_paused"):
            continue
        if routing.get("mode") == "disabled":
            continue
        result = {**task_result(task), "fallback_reason": routing.get("reason", "")}
        for person in routing.get("users", []):
            group = groups.setdefault(person["user_id"], {**person, "stores": []})
            group["stores"].append(result)
    for user_id, snapshot in groups.items():
        snapshot["phase"] = "attention" if attention else "final"
        row, created = Notification.objects.get_or_create(tenant_id=batch.tenant_id, batch=batch, recipient_id=user_id,
                                            defaults={"snapshot": snapshot})
        if not created and not attention and row.snapshot.get("phase") == "attention" and not row.lease_until:
            snapshot["attention_receipt"] = {"status": row.status, "message_id": row.message_id}
            row.snapshot, row.status, row.message, row.message_id = snapshot, "pending", "", ""
            row.save(update_fields=["snapshot", "status", "message", "message_id", "updated_at"])


def deliver(pk, service=None):
    with transaction.atomic():
        row = Notification.objects.select_for_update().get(pk=pk)
        now = timezone.now()
        if row.status == "accepted" or (row.lease_until and row.lease_until > now):
            return row.status
        if row.batch.operation == "sync" or row.batch.source == "post_sync":
            row.status, row.message, row.lease_until = "skipped", "同步任务不推送飞书", None
            row.save(update_fields=["status", "message", "lease_until", "updated_at"])
            return row.status
        if row.snapshot.get("phase") != "attention" and row.batch.tasks.exclude(status__in=TERMINAL).exists():
            return "pending"
        cutoff = TenantControl.objects.filter(tenant_id=row.tenant_id).values_list("notifications_not_before", flat=True).first()
        if cutoff and row.batch.created_at < cutoff:
            row.status, row.message, row.lease_until = "skipped", "启用推送前的历史批次，不补发", None
            row.save(update_fields=["status", "message", "lease_until", "updated_at"])
            return row.status
        if (row.message or row.status == "sending") and now - row.created_at > DELIVERY_IDEMPOTENCY_WINDOW:
            row.status, row.message, row.lease_until = "uncertain_expired", "原发送结果未确认且已超过去重窗口，请核对飞书记录；未重复发送", None
            row.save(update_fields=["status", "message", "lease_until", "updated_at"])
            return row.status
        if not valid_identities(row.tenant_id, [row.recipient_id]).filter(open_id=row.snapshot["open_id"]).exists():
            row.status, row.message = "failed", "批次接收人已失效；保留原接收快照，未发送"
            row.save(update_fields=["status", "message", "updated_at"])
            return row.status
        if service is None and not getattr(settings, "FLASH_SALES_NOTIFICATIONS_ENABLED", False):
            return "pending"
        row.status, row.lease_until = "sending", now + timedelta(minutes=2)
        row.save(update_fields=["status", "lease_until", "updated_at"])
    try:
        connection = FeishuConnection.objects.filter(tenant_id=row.tenant_id, enabled=True).first()
        if not connection:
            raise ValidationError("飞书连接未启用。")
        key = f"flash:{row.batch_id}:{row.recipient_id}" + (":attention" if row.snapshot.get("phase") == "attention" else "")
        message_id = (service or FeishuMessageService()).send(connection, row.snapshot["open_id"], "text",
            {"text": notification_text(row.batch, row.snapshot)}, key)
    except Exception:
        Notification.objects.filter(pk=pk).update(status="failed_or_unknown", message="飞书发送未确认，可单独重试通知", lease_until=None)
        return "failed_or_unknown"
    Notification.objects.filter(pk=pk).update(status="accepted", message="飞书已接收", message_id=message_id, lease_until=None)
    return "accepted"
