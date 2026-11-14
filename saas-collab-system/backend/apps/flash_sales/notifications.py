"""Recipient snapshots are fixed when a batch is submitted, never rebuilt on retry."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.integrations.feishu_delivery import DELIVERY_IDEMPOTENCY_WINDOW, FeishuMessageService
from apps.integrations.models import FeishuConnection, FeishuIdentity
from .domain import TERMINAL
from .models import Batch, Notification, TenantControl


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


@transaction.atomic
def prepare_notifications(batch_id):
    batch = Batch.objects.select_for_update().get(pk=batch_id)
    if batch.request_id.startswith("import:") or batch.source == "post_sync":
        return
    if batch.tasks.exclude(status__in=TERMINAL).exists():
        return
    groups = {}
    for task in batch.tasks.select_related("store"):
        routing = task.snapshot.get("recipients", {})
        for person in routing.get("users", []):
            group = groups.setdefault(person["user_id"], {**person, "stores": []})
            group["stores"].append({"store_id": task.store_id, "name": task.store.name,
                "status": task.status, "completed": task.completed, "requested": task.requested,
                "message": task.message, "fallback_reason": routing.get("reason", "")})
    for user_id, snapshot in groups.items():
        Notification.objects.get_or_create(tenant_id=batch.tenant_id, batch=batch, recipient_id=user_id,
                                            defaults={"snapshot": snapshot})


def deliver(pk, service=None):
    with transaction.atomic():
        row = Notification.objects.select_for_update().get(pk=pk)
        now = timezone.now()
        if row.status == "accepted" or (row.lease_until and row.lease_until > now):
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
        lines = [f"{store['name']}：已完成 {store['completed']}/{store['requested']}；{store['message']}"
                 for store in row.snapshot["stores"]]
        message_id = (service or FeishuMessageService()).send(connection, row.snapshot["open_id"], "text",
            {"text": "店内闪购执行结果\n" + "\n".join(lines)}, f"flash:{row.batch_id}:{row.recipient_id}")
    except Exception:
        Notification.objects.filter(pk=pk).update(status="failed_or_unknown", message="飞书发送未确认，可单独重试通知", lease_until=None)
        return "failed_or_unknown"
    Notification.objects.filter(pk=pk).update(status="accepted", message="飞书已接收", message_id=message_id, lease_until=None)
    return "accepted"
