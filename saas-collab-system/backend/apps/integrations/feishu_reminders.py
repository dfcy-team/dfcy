"""Manual business reminders: current organization and business authorization at every step."""
import hashlib
import json
import uuid
from datetime import date
from copy import copy
from time import monotonic
from types import SimpleNamespace
from urllib.parse import urlencode

from django.db import DatabaseError, connection, transaction
from django.db.models import Q, Subquery
from django.http import QueryDict
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.accounts.models import CustomUser
from apps.common.responses import success_response
from apps.permissions.role_catalog import user_is_tenant_administrator
from apps.permissions.services import check_user_permission
from apps.tenants.models import Department
from .models import FeishuBusinessReminder, FeishuConnection, FeishuDelivery, FeishuIdentity, FeishuOperation

SOURCES = {
    "orders": ("sales_management.orders.view", "销售订单", "/sales-management/orders"),
    "returns": ("sales_management.returns.view", "退款退货", "/sales-management/returns"),
}
FILTERS = {"date_from", "date_to", "platform", "platforms", "store_id", "store_ids", "region", "country", "currency",
           "status", "order_status", "refund_status", "case_type", "return_type", "external_order_id", "order_no",
           "sku", "source_sku", "sku_mode", "mapping_as_of", "sku_exact", "order_exact", "exclude_cancelled",
           "unmapped_only", "has_refund_return"}


def active_internal(user):
    return bool(user and user.is_authenticated and user.is_active and user.user_type == "internal" and user.tenant_id)


def managed_departments(actor):
    if not active_internal(actor):
        return set()
    nodes = list(Department.objects.filter(tenant_id=actor.tenant_id, status="active").values("id", "parent_id", "leader_id", "leader_include_descendants"))
    result = {n["id"] for n in nodes if n["leader_id"] == actor.pk}
    frontier = {n["id"] for n in nodes if n["leader_id"] == actor.pk and n["leader_include_descendants"]}
    visited = set(frontier)
    while frontier:
        children = {n["id"] for n in nodes if n["parent_id"] in frontier} - visited
        visited.update(children)
        result.update(children)
        frontier = children
    return result


def is_reminder_admin(actor):
    return active_internal(actor) and (actor.is_superuser or user_is_tenant_administrator(actor, actor.tenant))


def require_sender(actor, source=None):
    if not active_internal(actor) or not (is_reminder_admin(actor) or managed_departments(actor)):
        raise PermissionDenied("仅管理员或已设置的部门负责人可发送业务提醒。")
    if source and (source not in SOURCES or not check_user_permission(actor, SOURCES[source][0])):
        raise PermissionDenied("没有此业务页面的查看权限。")


def recipient_queryset(actor):
    require_sender(actor)
    users = CustomUser.objects.filter(tenant_id=actor.tenant_id, is_active=True, user_type="internal")
    if not is_reminder_admin(actor):
        ids = managed_departments(actor)
        from apps.permissions.models import OrgMembership
        members = OrgMembership.objects.filter(tenant_id=actor.tenant_id, department_id__in=ids, status="active").filter(Q(valid_until__isnull=True) | Q(valid_until__gt=timezone.now())).values("user_id")
        users = users.filter((Q(internal_profile__tenant_id=actor.tenant_id) & (
            Q(internal_profile__department_id__in=ids) | Q(internal_profile__departments__id__in=ids))) | Q(pk__in=Subquery(members)))
    return users.distinct()


class ReminderInput(serializers.Serializer):
    source = serializers.ChoiceField(choices=list(SOURCES))
    mode = serializers.ChoiceField(choices=["selected", "filtered"])
    record_ids = serializers.ListField(child=serializers.IntegerField(min_value=1, max_value=9223372036854775807), max_length=100, default=list)
    filters = serializers.DictField(child=serializers.CharField(max_length=500, allow_blank=True), default=dict)
    recipient_user_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=1, max_length=50)
    title = serializers.CharField(max_length=100, trim_whitespace=True)
    message = serializers.CharField(max_length=1000, allow_blank=True, default="", trim_whitespace=True)
    due_date = serializers.DateField(allow_null=True, default=None)

    def validate(self, data):
        if set(data["filters"]) - FILTERS:
            raise ValidationError({"filters": "存在不支持的筛选条件，请重新查询后再发送。"})
        if data["mode"] == "filtered":
            try:
                start = date.fromisoformat(data["filters"].get("date_from", ""))
                end = date.fromisoformat(data["filters"].get("date_to", ""))
            except ValueError:
                raise ValidationError({"filters": "筛选范围提醒须提供起止日期。"})
            if not 0 <= (end - start).days <= 30:
                raise ValidationError({"filters": "为保证查询性能，单次提醒范围最多31天。"})
        ids = data["record_ids"]
        if data["mode"] == "selected" and not ids:
            raise ValidationError({"record_ids": "请至少选择一条业务记录。"})
        if data["mode"] == "filtered" and ids:
            raise ValidationError({"record_ids": "筛选范围模式不能同时提交所选记录。"})
        data["record_ids"] = sorted(set(ids))
        data["recipient_user_ids"] = sorted(set(data["recipient_user_ids"]))
        return data


def input_data(payload):
    if not isinstance(payload, dict):
        raise ValidationError("请求须为对象。")
    unknown = set(payload) - set(ReminderInput().fields) - {"idempotency_key", "preview_token"}
    if unknown:
        raise ValidationError("请求包含不支持的字段。")
    serializer = ReminderInput(data=payload)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def records(user, data):
    code = SOURCES[data["source"]][0]
    if not active_internal(user) or not check_user_permission(user, code):
        raise PermissionDenied("收件人没有对应业务数据的查看权限。")
    from apps.sales_management.views import filtered_order_records, filtered_refund_records
    params = QueryDict("", mutable=True)
    params.update(data["filters"])
    request = SimpleNamespace(user=user, query_params=params)
    selector = filtered_order_records if data["source"] == "orders" else filtered_refund_records
    queryset = selector(request).order_by()
    if data["mode"] == "selected":
        queryset = queryset.filter(pk__in=data["record_ids"])
    return queryset


def bounded_count(queryset):
    # Count a bounded subquery, never materialize facts or count an unrestricted result set.
    def time_limit(execute, sql, params, many, context):
        if connection.vendor == "mysql" and not getattr(connection, "mysql_is_mariadb", False) and sql.lstrip().upper().startswith("SELECT "):
            sql = sql.replace("SELECT ", "SELECT /*+ MAX_EXECUTION_TIME(1000) */ ", 1)
        return execute(sql, params, many, context)
    try:
        with connection.execute_wrapper(time_limit):
            count = queryset.values("pk")[:10001].count()
    except DatabaseError as exc:
        raise ValidationError("提醒统计暂不可用或超过查询时限，请缩小日期或门店范围后重试。") from exc
    if count > 10000:
        raise ValidationError("提醒范围超过10000条，请缩小日期、门店或选择具体记录。")
    return count


def recipient_summary(actor, recipient, data, *, own=None, scope_checked=False):
    if not scope_checked:
        require_sender(actor, data["source"])
    if not scope_checked and not recipient_queryset(actor).filter(pk=recipient.pk).exists():
        raise PermissionDenied("收件人已不在当前可管理部门范围内。")
    own = records(actor, data) if own is None else own
    if not scope_checked and data["mode"] == "selected" and bounded_count(own) != len(data["record_ids"]):
        raise PermissionDenied("所选记录不存在或超出发送人的业务权限。")
    shared = records(recipient, data).filter(pk__in=Subquery(own.values("pk")))
    count = bounded_count(shared)
    if not count or data["mode"] == "selected" and count != len(data["record_ids"]):
        raise PermissionDenied("收件人无法查看全部所选记录，或当前筛选下没有共同可见数据。")
    # Counts only: no order numbers, amounts, customer identities or row details are copied into messages.
    path = SOURCES[data["source"]][2]
    query = dict(data["filters"])
    if data["mode"] == "selected":
        query["reminder_record_ids"] = ",".join(map(str, data["record_ids"]))
    text = f"{SOURCES[data['source']][1]} · {'所选记录' if data['mode'] == 'selected' else '筛选范围'}\n当前共同授权范围内 {count} 条记录，请打开系统核查。"
    if data.get("message"):
        text += "\n负责人留言：" + data["message"]
    if data.get("due_date"):
        text += "\n截止日期：" + str(data["due_date"])
    text += "\n数据按发送时权限重新核对，来源完整性请以业务页面为准。"
    return {"recipient_membership_id": getattr(recipient, "_active_membership_id", None), "count": count, "summary": text, "path": path + ("?" + urlencode(query) if query else "")}


def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def request_hash(data):
    return hashlib.sha256(canonical(data).encode()).hexdigest()


def preview(actor, data):
    started = monotonic()
    require_sender(actor, data["source"])
    users = list(recipient_queryset(actor).filter(pk__in=data["recipient_user_ids"]).order_by("pk"))
    if len(users) != len(data["recipient_user_ids"]):
        raise PermissionDenied("接收人超出可管理范围或账号已停用。")
    # Validate the source even when every recipient is unbound.
    own = records(actor, data)
    own_count = bounded_count(own)
    if not own_count or data["mode"] == "selected" and own_count != len(data["record_ids"]):
        raise ValidationError("没有可提醒的记录，或所选记录已不可见。")
    bound = set(FeishuIdentity.objects.filter(tenant_id=actor.tenant_id, user_id__in=data["recipient_user_ids"], status="active").exclude(open_id="").values_list("user_id", flat=True))
    from apps.permissions.models import OrgMembership
    memberships = OrgMembership.objects.filter(tenant_id=actor.tenant_id, user_id__in=data["recipient_user_ids"], status="active", department__status="active").filter(Q(valid_until__isnull=True) | Q(valid_until__gt=timezone.now())).order_by("id")
    if not is_reminder_admin(actor):
        memberships = memberships.filter(department_id__in=managed_departments(actor))
    contexts = {}
    for membership in memberships.values("id", "user_id"):
        contexts.setdefault(membership["user_id"], []).append(membership["id"])
    items = []
    for user in users:
        if monotonic() - started > 6:
            raise ValidationError("预览超过6秒预算，请减少收件人或缩小数据范围。")
        item = {"user_id": user.pk, "name": user.full_name or user.username, "eligible": False}
        if user.pk not in bound:
            item["reason"] = "尚未绑定飞书"
        else:
            item["reason"] = "收件人无法查看此数据范围"
            for membership_id in [None, *contexts.get(user.pk, [])[:10]]:
                if monotonic() - started > 6:
                    raise ValidationError("预览超过6秒预算，请减少收件人或缩小数据范围。")
                contextual_user = copy(user)
                contextual_user._active_membership_id = membership_id
                try:
                    item.update(recipient_summary(actor, contextual_user, data, own=own, scope_checked=True), eligible=True)
                    item.pop("reason", None)
                    break
                except PermissionDenied:
                    continue
        items.append(item)
    connection_ready = FeishuConnection.objects.filter(tenant_id=actor.tenant_id, enabled=True).exclude(app_id="").exclude(app_secret_ref="").exists()
    from django.core import signing
    digest = request_hash({"request": data, "actor_membership_id": getattr(actor, "_active_membership_id", None), "recipients": items, "connection_ready": connection_ready})
    token = signing.dumps({"actor": actor.pk, "tenant": actor.tenant_id, "digest": digest}, salt="feishu-reminder-preview")
    return {"recipients": items, "connection_ready": connection_ready, "can_send": connection_ready and all(i["eligible"] for i in items), "preview_token": token, "digest": digest}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def options(request):
    try:
        require_sender(request.user)
    except PermissionDenied:
        return success_response({"can_send": False, "sources": [], "recipients": []})
    users = recipient_queryset(request.user).order_by("username", "pk")
    search = request.query_params.get("search", "").strip()[:100]
    if search:
        users = users.filter(Q(username__icontains=search) | Q(full_name__icontains=search))
    users = list(users[:101])
    bound = set(FeishuIdentity.objects.filter(tenant_id=request.user.tenant_id, user_id__in=[u.pk for u in users], status="active").exclude(open_id="").values_list("user_id", flat=True))
    return success_response({"can_send": True, "sources": [key for key, val in SOURCES.items() if check_user_permission(request.user, val[0])],
        "truncated": len(users) > 100, "recipients": [{"id": u.pk, "name": u.full_name or u.username, "bound": u.pk in bound} for u in users[:100]]})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def preview_view(request):
    return success_response(preview(request.user, input_data(request.data)))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def send_view(request):
    from django.core import signing
    data = input_data(request.data)
    require_sender(request.user, data["source"])
    try:
        key = uuid.UUID(str(request.data.get("idempotency_key", "")))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("请提交有效的发送请求编号。")
    digest = request_hash({"request": data, "actor_membership_id": getattr(request.user, "_active_membership_id", None)})
    # Actor row serializes duplicate concurrent sends, including when no reminder row exists yet.
    with transaction.atomic():
        CustomUser.objects.select_for_update().get(pk=request.user.pk)
        existing = FeishuBusinessReminder.objects.filter(tenant_id=request.user.tenant_id, actor=request.user, request_key=key).first()
        if existing:
            if existing.request_hash != digest:
                raise ValidationError("同一发送编号不能用于不同内容。")
            return success_response({"id": existing.pk, "status": "queued", "replayed": True}, status=202)
        current = preview(request.user, data)
        try:
            token = signing.loads(request.data.get("preview_token", ""), salt="feishu-reminder-preview", max_age=600)
        except (signing.BadSignature, TypeError):
            raise ValidationError("发送预览已失效，请重新预览。")
        if token != {"actor": request.user.pk, "tenant": request.user.tenant_id, "digest": current["digest"]}:
            raise ValidationError("内容、绑定或数据范围已变化，请重新预览。")
        if not current["can_send"]:
            raise ValidationError("请配置飞书连接，并移除未绑定或无数据权限的收件人后重新预览。")
        reminder = FeishuBusinessReminder.objects.create(tenant_id=request.user.tenant_id, actor=request.user,
            request_key=key, request_hash=digest, source=data["source"],
            selection={**{k: data[k] for k in ("mode", "record_ids", "filters")}, "actor_membership_id": getattr(request.user, "_active_membership_id", None)}, title=data["title"], message=data["message"], due_date=data["due_date"])
        connection = FeishuConnection.objects.get(tenant_id=request.user.tenant_id)
        preview_by_user = {item["user_id"]: item for item in current["recipients"]}
        for user_id in data["recipient_user_ids"]:
            identity = FeishuIdentity.objects.get(tenant_id=request.user.tenant_id, user_id=user_id, status="active")
            operation = FeishuOperation.objects.create(tenant_id=request.user.tenant_id, operation_type="notification", status="pending",
                reference_type="business_reminder", reference_id=str(reminder.pk), masked_detail={"recipient_user_id": user_id, "attempts": 0})
            FeishuDelivery.objects.create(tenant_id=request.user.tenant_id, operation=operation, user_id=user_id, rule=None, business_reminder=reminder,
                app_id=connection.app_id, open_id=identity.open_id, payload={"business_reminder_id": reminder.pk, "recipient_membership_id": preview_by_user[user_id].get("recipient_membership_id")},
                idempotency_key=hashlib.sha256(f"reminder:{reminder.pk}:{user_id}".encode()).hexdigest(), next_attempt_at=timezone.now())
    return success_response({"id": reminder.pk, "status": "queued"}, status=202)


def delivery_content(delivery):
    from .feishu_delivery import card
    reminder = FeishuBusinessReminder.objects.select_related("actor", "actor__tenant").get(pk=delivery.business_reminder_id, tenant_id=delivery.tenant_id)
    data = {**reminder.selection, "source": reminder.source, "message": reminder.message, "due_date": reminder.due_date}
    reminder.actor._active_membership_id = reminder.selection.get("actor_membership_id")
    membership_id = delivery.payload.get("recipient_membership_id")
    if membership_id:
        from apps.permissions.models import OrgMembership
        if not OrgMembership.objects.filter(pk=membership_id, tenant_id=delivery.tenant_id, user=delivery.user, status="active", department__status="active").filter(Q(valid_until__isnull=True) | Q(valid_until__gt=timezone.now())).exists():
            raise PermissionDenied("收件人的组织身份已失效。")
    delivery.user._active_membership_id = membership_id
    result = recipient_summary(reminder.actor, delivery.user, data)
    path = SOURCES[reminder.source][2] + "?" + urlencode({**reminder.selection["filters"], "reminder_id": reminder.pk, "reminder_membership": membership_id or 0})
    return "interactive", card(reminder.title, result["summary"], path)


def apply_reminder_scope(request, queryset, source):
    """Links open the exact source selection, constrained by both parties' live scopes."""
    try:
        pk = int(request.query_params["reminder_id"])
    except (ValueError, TypeError):
        raise ValidationError("提醒编号无效。")
    reminder = FeishuBusinessReminder.objects.select_related("actor", "actor__tenant").filter(pk=pk, tenant_id=request.user.tenant_id, source=source).first()
    if not reminder or not (reminder.actor_id == request.user.pk or FeishuDelivery.objects.filter(
        tenant_id=request.user.tenant_id, user=request.user, business_reminder_id=pk).exists()):
        raise PermissionDenied("没有查看此提醒的权限。")
    reminder.actor._active_membership_id = reminder.selection.get("actor_membership_id")
    require_sender(reminder.actor, source)
    if reminder.actor_id != request.user.pk and not recipient_queryset(reminder.actor).filter(pk=request.user.pk).exists():
        raise PermissionDenied("已不在此提醒的部门范围内。")
    data = {**reminder.selection, "source": source}
    own = records(reminder.actor, data)
    return queryset.filter(pk__in=Subquery(own.values("pk")))


def owned_reminder(request, pk):
    require_sender(request.user)
    qs = FeishuBusinessReminder.objects.filter(tenant_id=request.user.tenant_id, pk=pk)
    if not is_reminder_admin(request.user):
        qs = qs.filter(actor=request.user)
    from django.shortcuts import get_object_or_404
    return get_object_or_404(qs)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def history_view(request):
    require_sender(request.user)
    qs = FeishuBusinessReminder.objects.filter(tenant_id=request.user.tenant_id)
    if not is_reminder_admin(request.user):
        qs = qs.filter(actor=request.user)
    return success_response({"items": [{"id": r.pk, "title": r.title, "source": r.source, "created_at": r.created_at} for r in qs[:30]]})


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def status_view(request, pk):
    reminder = owned_reminder(request, pk)
    deliveries = FeishuDelivery.objects.filter(tenant_id=request.user.tenant_id, business_reminder=reminder).select_related("operation", "user")
    if request.method == "POST":
        try:
            operation_id = int(request.data.get("operation_id"))
        except (ValueError, TypeError):
            raise ValidationError("请选择失败的投递记录。")
        with transaction.atomic():
            delivery = deliveries.select_for_update().filter(operation_id=operation_id).first()
            if not delivery or delivery.operation.status != "failed" or delivery.attempts >= 3 or delivery.lease_until and delivery.lease_until > timezone.now():
                raise ValidationError("仅可重试失败且未超过三次上限的记录。")
            delivery_content(delivery)  # Revalidate ownership and business permissions before retry.
            delivery.next_attempt_at = timezone.now()
            delivery.save(update_fields=["next_attempt_at"])
        return success_response({"status": "queued"}, status=202)
    return success_response({"id": reminder.pk, "title": reminder.title, "items": [{"operation_id": d.operation_id,
        "recipient": d.user.full_name or d.user.username, "status": d.operation.status, "attempts": d.attempts,
        "error_code": d.operation.error_code, "can_retry": d.operation.status == "failed" and d.attempts < 3} for d in deliveries]})
