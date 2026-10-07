"""Feishu delivery with a durable outbox and current-user authorization."""
import hashlib
import json
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import CustomUser
from apps.permissions.services import check_user_permission
from apps.workflows.models import ApprovalRequest
from apps.workflows.permissions import scope_allows_value
from .feishu_identity_service import FeishuIdentityService
from .models import FeishuConfigRule, FeishuConnection, FeishuDelivery, FeishuIdentity, FeishuOperation
from .security import sanitize_text


SCENES = {"inventory_alert", "business_alert", "sync_failed", "approval_pending", "approval_result"}
MANAGE_CODES = {"notification": "feishu.notification.manage", "report": "feishu.report.manage", "approval": "feishu.approval.manage"}


def active_user(user):
    return bool(user and user.is_active and user.user_type == CustomUser.UserType.INTERNAL)


def config_hash(rule):
    return hashlib.sha256(json.dumps(rule.config, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_rule_config(kind, config, tenant_id):
    if not isinstance(config, dict):
        raise ValidationError({"config": "规则必须为 JSON 对象。"})
    ids = config.get("recipient_user_ids", [])
    if not isinstance(ids, list) or len(ids) > 50 or any(type(v) is not int or v < 1 for v in ids):
        raise ValidationError({"recipient_user_ids": "请选择至多50名系统内部用户。"})
    if CustomUser.objects.filter(tenant_id=tenant_id, pk__in=ids, is_active=True, user_type="internal").count() != len(set(ids)):
        raise ValidationError({"recipient_user_ids": "接收人必须是本租户启用的内部用户。"})
    allowed = {"recipient_user_ids", "format"}
    if kind == "notification":
        allowed |= {"scene", "message"}
        if config.get("scene") not in SCENES:
            raise ValidationError({"scene": "请选择有效的通知场景。"})
        if config.get("format", "card") not in {"text", "card"}:
            raise ValidationError({"format": "消息格式仅支持文本或卡片。"})
        if not isinstance(config.get("message", ""), str) or len(config.get("message", "")) > 2000:
            raise ValidationError({"message": "消息内容不得超过2000字。"})
    elif kind == "report":
        allowed |= {"report_type", "schedule", "hour", "filters"}
        if config.get("report_type") not in {"comprehensive", "sales", "inventory"}:
            raise ValidationError({"report_type": "支持综合、销售和库存报表。"})
        if config.get("schedule", "daily") not in {"daily", "weekly", "monthly"}:
            raise ValidationError({"schedule": "请选择有效的推送周期。"})
        if type(config.get("hour", 9)) is not int or not 0 <= config.get("hour", 9) <= 23:
            raise ValidationError({"hour": "推送小时必须在0至23之间（北京时间）。"})
        if config.get("format", "card") not in {"card", "file"}:
            raise ValidationError({"format": "报表格式仅支持摘要卡片或CSV附件。"})
        if not isinstance(config.get("filters", {}), dict) or set(config.get("filters", {})) - {"date_from", "date_to"}:
            raise ValidationError({"filters": "报表筛选只支持起止日期。"})
        from .feishu_reports import _window
        _window(config)
    elif kind == "approval":
        allowed |= {"approval_type"}
        if config.get("approval_type") not in ApprovalRequest.ApprovalType.values:
            raise ValidationError({"approval_type": "请选择系统支持的审批类型。"})
    if set(config) - allowed:
        raise ValidationError({"config": "规则包含不支持的字段，请按表单更新。"})
    return config


def system_url(path):
    base = str(getattr(settings, "FEISHU_SYSTEM_BASE_URL", "")).rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValidationError({"detail": "请由管理员配置本环境 HTTPS 系统入口 FEISHU_SYSTEM_BASE_URL。"})
    return base + path


def reviewer_allowed(user, approval, *, pending=True):
    codes = ["workflow.approvals.view"] + (["workflow.approvals.review"] if pending else [])
    return active_user(user) and user.tenant_id == approval.tenant_id and (not pending or user.pk != approval.requested_by_id) and all(
        check_user_permission(user, code) and scope_allows_value(user, code, "approval_types", approval.approval_type) for code in codes
    )


def enqueue_rule(rule, *, key, payload=None, user_ids=None, reference_type="rule", reference_id=None):
    if not rule.enabled:
        raise ValidationError({"detail": "规则已停用。"})
    validate_rule_config(rule.kind, rule.config, rule.tenant_id)
    connection = FeishuConnection.objects.filter(tenant_id=rule.tenant_id, enabled=True).first()
    if not connection or not connection.app_id or not connection.app_secret_ref:
        raise ValidationError({"detail": "请先启用并配置飞书应用连接。"})
    recipients = user_ids if user_ids is not None else rule.config.get("recipient_user_ids", [])
    if not recipients:
        raise ValidationError({"detail": "规则没有可投递的接收人，请配置已绑定用户。"})
    result = []
    with transaction.atomic():
        for user_id in sorted(set(recipients)):
            stable_key = hashlib.sha256(f"{rule.pk}:{key}:{user_id}".encode()).hexdigest()
            existing = FeishuDelivery.objects.filter(tenant_id=rule.tenant_id, idempotency_key=stable_key).first()
            if existing:
                result.append(existing.operation_id)
                continue
            identity = FeishuIdentity.objects.filter(tenant_id=rule.tenant_id, user_id=user_id, status="active", user__is_active=True, user__user_type="internal").first()
            operation = FeishuOperation.objects.create(
                tenant_id=rule.tenant_id, operation_type=rule.kind, status="pending" if identity and identity.open_id else "skipped",
                reference_type=reference_type, reference_id=str(reference_id or rule.pk),
                masked_detail={"recipient_user_id": user_id, "rule_id": rule.pk, "attempts": 0},
                error_code="" if identity and identity.open_id else "FEISHU_IDENTITY_UNBOUND",
            )
            # Unbound attempts are also durable/idempotent, never silently dropped.
            delivery, _ = FeishuDelivery.objects.get_or_create(
                tenant_id=rule.tenant_id, idempotency_key=stable_key,
                defaults={"operation": operation, "rule": rule, "user_id": user_id, "app_id": connection.app_id,
                          "open_id": identity.open_id if identity else "", "payload": {**(payload or {}), "rule_hash": config_hash(rule)},
                          "next_attempt_at": timezone.now()},
            )
            if delivery.operation_id != operation.pk:
                operation.delete()
            result.append(delivery.operation_id)
    return {"operation_ids": result, "status": "queued"}


def notify_approval(approval_id):
    approval = ApprovalRequest.objects.select_related("tenant").get(pk=approval_id)
    pending = approval.status == "pending"
    operations = []
    rules = FeishuConfigRule.objects.filter(tenant_id=approval.tenant_id, enabled=True, kind__in=["approval", "notification"])
    for rule in rules:
        if not isinstance(rule.config, dict):
            continue
        if rule.kind == "approval" and rule.config.get("approval_type") != approval.approval_type:
            continue
        if rule.kind == "notification" and rule.config.get("scene") != ("approval_pending" if pending else "approval_result"):
            continue
        ids = rule.config.get("recipient_user_ids", []) if pending or rule.kind == "notification" else [approval.requested_by_id]
        users = CustomUser.objects.filter(tenant_id=approval.tenant_id, pk__in=ids)
        allowed_ids = [u.pk for u in users if reviewer_allowed(u, approval, pending=pending)]
        if not allowed_ids:
            continue
        result = enqueue_rule(rule, key=f"approval:{approval.pk}:{approval.status}", user_ids=allowed_ids,
            reference_type="approval", reference_id=approval.pk, payload={"approval_id": approval.pk, "approval_status": approval.status})
        operations.extend(result["operation_ids"])
    return {"operation_ids": operations, "status": "queued" if operations else "no_matching_rule"}


def emit_notification(tenant_id, scene, reference_type, reference_id):
    for rule in FeishuConfigRule.objects.filter(tenant_id=tenant_id, kind="notification", enabled=True):
        if rule.config.get("scene") == scene:
            enqueue_rule(rule, key=f"{scene}:{reference_type}:{reference_id}", reference_type=reference_type,
                         reference_id=reference_id, payload={"scene": scene})


class FeishuMessageService(FeishuIdentityService):
    def base(self, connection):
        return "https://open.larksuite.com" if connection.domain == "lark" else "https://open.feishu.cn"

    def _tenant_token(self, connection):
        if not connection or not connection.enabled or not connection.app_id or not connection.app_secret_ref:
            raise ValidationError({"detail": "飞书应用未启用或凭据未配置。"})
        secret = self.custody.retrieve_secret(connection.app_secret_ref)
        response = self.http.request("POST", self.base(connection) + "/open-apis/auth/v3/tenant_access_token/internal",
            json_body={"app_id": connection.app_id, "app_secret": secret}, retry=False, diagnostic_platform="feishu")
        token = self._payload(response, "飞书认证失败，请检查凭据。").get("tenant_access_token")
        if not token:
            raise ValidationError({"detail": "飞书认证未返回有效凭证。"})
        return token

    def send(self, connection, open_id, message_type, content, key):
        token = self._tenant_token(connection)
        response = self.http.request("POST", self.base(connection) + "/open-apis/im/v1/messages?receive_id_type=open_id",
            headers={"Authorization": f"Bearer {token}"}, json_body={"receive_id": open_id, "msg_type": message_type,
            "content": json.dumps(content, ensure_ascii=False), "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, key))}, retry=False, diagnostic_platform="feishu")
        message_id = (self._payload(response, "飞书消息投递失败，请检查消息权限及应用可用范围。").get("data") or {}).get("message_id")
        if not message_id:
            raise ValidationError({"detail": "飞书未返回消息ID，不能确认投递成功。"})
        return message_id

    def upload_csv(self, connection, content):
        token = self._tenant_token(connection)
        boundary = "feishu" + uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file_type\"\r\n\r\nstream\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file_name\"\r\n\r\nreport.csv\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"report.csv\"\r\nContent-Type: text/csv\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
        response = self.http.request("POST", self.base(connection) + "/open-apis/im/v1/files",
            raw_body=body, headers={"Authorization": f"Bearer {token}", "Content-Type": f"multipart/form-data; boundary={boundary}"}, retry=False, diagnostic_platform="feishu")
        file_key = (self._payload(response, "飞书附件上传失败，请检查资源权限。").get("data") or {}).get("file_key")
        if not file_key:
            raise ValidationError({"detail": "飞书未返回附件标识。"})
        return file_key


def card(title, text, path):
    return {"config": {"wide_screen_mode": True}, "header": {"title": {"tag": "plain_text", "content": title[:150]}},
            "elements": [{"tag": "div", "text": {"tag": "plain_text", "content": text[:3000]}},
                         {"tag": "action", "actions": [{"tag": "button", "text": {"tag": "plain_text", "content": "打开协同系统"}, "type": "primary", "url": system_url(path)}]}]}


def execute_delivery(pk, *, service=None):
    now = timezone.now()
    with transaction.atomic():
        delivery = FeishuDelivery.objects.select_for_update().select_related("operation", "rule", "user").get(pk=pk)
        operation = delivery.operation
        if operation.status not in {"pending", "failed", "processing"} or delivery.attempts >= 3:
            return operation.status
        if delivery.next_attempt_at and delivery.next_attempt_at > now or delivery.lease_until and delivery.lease_until > now:
            return "processing"
        # Provider message UUID retention is bounded; do not replay uncertain old sends.
        if delivery.attempts and now - delivery.created_at > timedelta(minutes=45):
            operation.status, operation.error_code = "failed", "FEISHU_DELIVERY_UNCERTAIN_EXPIRED"
            operation.save()
            delivery.next_attempt_at = None
            delivery.save()
            return "failed"
        delivery.attempts += 1
        delivery.lease_until = now + timedelta(minutes=10)
        delivery.save()
        operation.status = "processing"
        operation.save()
    try:
        rule, user = delivery.rule, delivery.user
        connection = FeishuConnection.objects.filter(tenant_id=delivery.tenant_id, enabled=True).first()
        mapping = FeishuIdentity.objects.filter(tenant_id=delivery.tenant_id, user=user, status="active", open_id=delivery.open_id).first()
        if not rule or not rule.enabled or delivery.payload.get("rule_hash") != config_hash(rule) or not active_user(user) or not mapping or not connection or connection.app_id != delivery.app_id:
            raise ValidationError("规则、账号、绑定或应用配置已改变，投递已阻止。")
        if not active_user(rule.updated_by) or not check_user_permission(rule.updated_by, MANAGE_CODES[rule.kind]):
            raise ValidationError("规则配置人的权限已失效，投递已阻止。")
        sender = service or FeishuMessageService()
        payload = delivery.payload
        if payload.get("approval_id"):
            approval = ApprovalRequest.objects.get(pk=payload["approval_id"], tenant_id=delivery.tenant_id)
            if approval.status != payload["approval_status"] or not reviewer_allowed(user, approval, pending=approval.status == "pending"):
                raise ValidationError("审批状态或接收人的审批权限已改变。")
            msg_type, content = "interactive", card("审批待办" if approval.status == "pending" else "审批结果",
                f"{approval.title}\n状态：{approval.status}\n请进入系统查看依据并操作，飞书消息不直接处理审批。", f"/workflow/approvals/{approval.pk}")
        elif rule.kind == "report":
            from .feishu_reports import build_report, report_csv
            report = build_report(rule, user)
            if rule.config.get("format", "card") == "file":
                msg_type, content = "file", {"file_key": sender.upload_csv(connection, report_csv(report))}
            else:
                msg_type, content = "interactive", card(report["title"], report["summary"], "/reports/basic")
        else:
            # Automatic prewarnings disclose no source detail, only that the viewer should open the system.
            automatic = payload.get("scene")
            text = "系统产生新的预警/异常，请进入协同系统按现有权限查看。" if automatic else rule.config.get("message", "")
            if not text:
                raise ValidationError("请先填写测试消息内容。")
            msg_type = "text" if rule.config.get("format") == "text" else "interactive"
            content = {"text": text} if msg_type == "text" else card(rule.name, text, "/")
        message_id = sender.send(connection, delivery.open_id, msg_type, content, delivery.idempotency_key)
        status, error_code, error_message = "success", "", ""
    except Exception as exc:
        status, error_code, error_message = "failed", "FEISHU_DELIVERY_FAILED", sanitize_text(str(exc))[:250]
        message_id = ""
    with transaction.atomic():
        current = FeishuDelivery.objects.select_for_update().get(pk=pk)
        current.lease_until = None
        current.next_attempt_at = timezone.now() + timedelta(minutes=1) if status == "failed" and current.attempts < 3 else None
        current.save()
        operation.status, operation.error_code = status, error_code
        operation.masked_detail = {**operation.masked_detail, "attempts": current.attempts, "message_id": message_id, "error_message": error_message}
        operation.save()
    return status


def dispatch_feishu():
    local = timezone.localtime(timezone.now(), timezone.get_fixed_timezone(480))
    for rule in FeishuConfigRule.objects.filter(kind="report", enabled=True).select_related("updated_by").iterator(chunk_size=100):
        try:
            validate_rule_config(rule.kind, rule.config, rule.tenant_id)
            cfg = rule.config
            if local.hour < cfg.get("hour", 9) or cfg.get("schedule") == "weekly" and local.weekday() != 0 or cfg.get("schedule") == "monthly" and local.day != 1:
                continue
            enqueue_rule(rule, key=f"scheduled:{local.date().isoformat()}")
        except Exception:
            from apps.tenants.models import Tenant
            # One visible diagnostic per rule/day; bad legacy config must not starve other outboxes.
            with transaction.atomic():
                Tenant.objects.select_for_update().get(pk=rule.tenant_id)
                FeishuOperation.objects.get_or_create(tenant_id=rule.tenant_id, operation_type="report",
                    reference_type="rule_config", reference_id=f"{rule.pk}:{local.date().isoformat()}",
                    defaults={"status": "failed", "error_code": "FEISHU_RULE_CONFIG_INVALID", "masked_detail": {"rule_id": rule.pk, "error_message": "报表规则无效或连接未就绪，请打开配置更新后重试。"}})
            continue
    now = timezone.now()
    ids = list(FeishuDelivery.objects.filter(operation__status__in=["pending", "failed", "processing"], attempts__lt=3, next_attempt_at__lte=now).filter(Q(lease_until__isnull=True) | Q(lease_until__lte=now)).order_by("pk").values_list("pk", flat=True)[:30])
    return {"processed": len(ids), "statuses": [execute_delivery(pk) for pk in ids]}
