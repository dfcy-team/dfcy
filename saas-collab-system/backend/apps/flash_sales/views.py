from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError as ModelValidationError
from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.responses import error_response, success_response
from apps.integrations.models import FeishuIdentity
from apps.permissions.services import check_user_permission
from .domain import digest, identifier, validate_items
from .models import Activity, Batch, Intent, Notification, Plan, Preview, StoreConfig, StoreLock, StoreTask, TenantControl
from .permissions import PREFIX, require_global, require_stores, visible_stores
from .provider import Deferred, Rejected, ShopeeAdapter
from .services import audit, delete_config, delete_plan, enable_plan, save_config, save_plan, submit


def plan_data(plan):
    return {"id": plan.id, "name": plan.name, "kind": plan.kind, "date": plan.local_date,
            "time": plan.local_time.strftime("%H:%M"), "store_ids": list(plan.stores.values_list("id", flat=True)),
            "enabled": plan.enabled, "next_due": plan.next_due, "version": plan.version}


def activity_data(row):
    return {"id": row.pk, "store_id": row.store_id, "store_name": row.store.name, "timezone": row.store.timezone,
            "platform_id": row.platform_id, "slot_id": row.slot_id, "starts_at": row.starts_at,
            "ends_at": row.ends_at, "status": row.platform_status, "item_count": row.item_count,
            "enabled_count": row.enabled_count, "synced_at": row.synced_at}


def local_date_filter(activities, stores, params):
    bounds = {}
    for key in ("date_from", "date_to"):
        if params.get(key):
            try:
                bounds[key] = date.fromisoformat(params[key])
            except ValueError:
                raise ValidationError("日期格式无效。") from None
    if not bounds:
        return activities
    if len(bounds) == 2 and bounds["date_from"] > bounds["date_to"]:
        raise ValidationError("开始日期不能晚于结束日期。")
    predicate = Q(pk__in=[])
    for store in stores:
        try:
            zone = ZoneInfo(store.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationError(f"店铺 {store.code} 的时区无效，请先修正档案。") from None
        condition = Q(store_id=store.id)
        if "date_from" in bounds:
            condition &= Q(starts_at__gte=datetime.combine(bounds["date_from"], time.min, zone))
        if "date_to" in bounds:
            condition &= Q(starts_at__lt=datetime.combine(bounds["date_to"] + timedelta(days=1), time.min, zone))
        predicate |= condition
    return activities.filter(predicate)


def batch_data(batch, store_ids):
    tasks = list(batch.tasks.filter(store_id__in=store_ids).select_related("store").prefetch_related("intents"))
    syncs = {row.id: row for row in StoreTask.objects.filter(tenant_id=batch.tenant_id, store_id__in=store_ids,
        pk__in=[task.state.get("post_sync_task_id") for task in tasks if task.state.get("post_sync_task_id")])}
    return {"id": str(batch.id), "source": batch.source, "operation": batch.operation,
        "created_at": batch.created_at, "finished_at": batch.finished_at, "stop_requested": batch.stop_requested,
        "tasks": [{"id": task.id, "store_id": task.store_id, "store_name": task.store.name,
            "timezone": task.store.timezone,
            "status": task.status, "message": task.message, "requested": task.requested, "completed": task.completed,
            "started_at": task.started_at, "finished_at": task.finished_at, "retry_count": task.retry_count,
            "retry_paused": bool(task.state.get("retry_paused")), "no_progress_count": task.state.get("no_progress_count", 0),
            "retry_pause_reason": task.state.get("retry_pause_reason", ""),
            "next_attempt_at": task.next_attempt_at, "execution_ms": task.execution_ms, "waiting_ms": task.waiting_ms,
            "queue_ms": max(0, int((task.started_at - task.created_at).total_seconds() * 1000)) if task.started_at else None,
            "notification_error": task.snapshot.get("recipients", {}).get("error", ""),
            "sync": {"status": syncs[task.state["post_sync_task_id"]].status, "message": syncs[task.state["post_sync_task_id"]].message}
                if task.state.get("post_sync_task_id") in syncs else None,
            "intents": [{"id": row.id, "platform_id": row.platform_id, "target": row.target,
                "status": row.status, "result": row.result} for row in task.intents.all()]} for task in tasks],
        "notifications": [{"id": row.id, "status": row.status, "message": row.message,
            "name": row.snapshot.get("name", ""), "stores": [item["store_id"] for item in row.snapshot.get("stores", []) if item["store_id"] in store_ids]}
            for row in batch.notifications.all()
            if any(item["store_id"] in store_ids for item in row.snapshot.get("stores", []))]}


class FlashView(APIView):
    permission_classes = [IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.method in {"POST", "PUT", "DELETE"} and not isinstance(request.data, dict):
            raise ValidationError("请提交有效的表单对象。")

    def handle_exception(self, exc):
        if isinstance(exc, ObjectDoesNotExist):
            return error_response("NOT_FOUND", "当前租户下的记录不存在。", status=404)
        if isinstance(exc, ModelValidationError):
            return error_response("VALIDATION_ERROR", "字段格式无效，请刷新后重试。", status=400)
        if isinstance(exc, (Deferred, Rejected)):
            return error_response("FLASH_PLATFORM_UNAVAILABLE", str(exc), status=503)
        return super().handle_exception(exc)


class Workspace(FlashView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        stores = list(visible_stores(request.user).filter(platform__platform_type="shopee").select_related("operator"))
        ids = [row.id for row in stores]
        configs = {row.store_id: row for row in StoreConfig.objects.filter(tenant=request.user.tenant, store_id__in=ids, deleted_at__isnull=True).prefetch_related("recipients")}
        activities = Activity.objects.filter(tenant=request.user.tenant, store_id__in=ids).select_related("store").order_by("-starts_at")
        store_counts = {row["store_id"]: row["total"] for row in activities.order_by().values("store_id").annotate(total=Count("id"))}
        try:
            page = max(1, int(request.query_params.get("page", 1)))
            history_page = max(1, int(request.query_params.get("history_page", 1)))
            page_size = int(request.query_params.get("page_size", 50))
            if page_size not in {25, 50, 100}:
                raise ValueError
        except ValueError:
            raise ValidationError("页码无效。") from None
        if request.query_params.get("store_id"):
            try:
                activities = activities.filter(store_id=int(request.query_params["store_id"]))
            except ValueError:
                raise ValidationError("店铺筛选无效。") from None
        if request.query_params.get("activity_id"):
            activities = activities.filter(platform_id__icontains=request.query_params["activity_id"][:80])
        state = request.query_params.get("activity_state")
        now = timezone.now()
        activities = local_date_filter(activities, stores, request.query_params)
        activity_counts = activities.aggregate(all=Count("id"),
            current=Count("id", filter=Q(starts_at__lte=now, ends_at__gt=now)),
            upcoming=Count("id", filter=Q(starts_at__gt=now)),
            expired=Count("id", filter=Q(ends_at__lte=now)))
        if state == "current":
            activities = activities.filter(starts_at__lte=now, ends_at__gt=now)
        elif state == "upcoming":
            activities = activities.filter(starts_at__gt=now)
        elif state == "expired":
            activities = activities.filter(ends_at__lte=now)
        history_ids = ids
        if request.query_params.get("history_store_id"):
            try:
                history_ids = [int(request.query_params["history_store_id"])]
            except ValueError:
                raise ValidationError("记录店铺筛选无效。") from None
            history_ids = [pk for pk in history_ids if pk in ids]
        history_tasks = StoreTask.objects.filter(tenant=request.user.tenant, store_id__in=history_ids)
        if request.query_params.get("history_status"):
            history_tasks = history_tasks.filter(status=request.query_params["history_status"])
        batches = Batch.objects.filter(tenant=request.user.tenant, pk__in=history_tasks.values("batch_id")).order_by("-created_at")
        source = request.query_params.get("history_source")
        if source == "scheduled":
            batches = batches.filter(source="scheduled")
        elif source == "manual":
            batches = batches.exclude(source="scheduled")
        plans = [plan for plan in Plan.objects.filter(tenant=request.user.tenant, deleted_at__isnull=True).prefetch_related("stores")
                 if set(plan.stores.values_list("id", flat=True)) <= set(ids)]
        control = TenantControl.objects.filter(tenant=request.user.tenant).first()
        latest_ids = StoreTask.objects.filter(tenant=request.user.tenant, store_id=OuterRef("store_id"),
            batch__operation__in={"run", "copy"}).order_by("-created_at", "-id").values("id")[:1]
        latest = {row["store_id"]: row for row in StoreTask.objects.filter(tenant=request.user.tenant,
            store_id__in=ids, id=Subquery(latest_ids)).values("store_id", "status", "message", "finished_at", "batch_id")}
        sync_ids = StoreTask.objects.filter(tenant=request.user.tenant, store_id=OuterRef("store_id"),
            batch__operation="sync").order_by("-created_at", "-id").values("id")[:1]
        latest_sync = {row["store_id"]: row for row in StoreTask.objects.filter(tenant=request.user.tenant,
            store_id__in=ids, id=Subquery(sync_ids)).values("store_id", "status", "message", "finished_at", "batch_id")}
        current = {store_id: [] for store_id in ids}
        upcoming = {store_id: [] for store_id in ids}
        for row in Activity.objects.filter(tenant=request.user.tenant, store_id__in=ids, ends_at__gt=now).exclude(platform_status=0).select_related("store").order_by("starts_at"):
            if row.starts_at <= now:
                current[row.store_id].append(activity_data(row))
            elif len(upcoming[row.store_id]) < 5:
                upcoming[row.store_id].append(activity_data(row))
        people = FeishuIdentity.objects.filter(tenant=request.user.tenant, user__tenant=request.user.tenant,
            user__is_active=True, user__user_type="internal", status="active").exclude(open_id="").select_related("user")
        return success_response({
            "workspace_key": f"{request.user.tenant_id}:{request.user.id}",
            "stores": [{"id": store.id, "code": store.code, "name": store.name, "timezone": store.timezone,
                "owner_id": store.operator_id,
                "owner_name": store.operator.full_name or store.operator.username if store.operator_id else "未设置",
                "configured": store.id in configs,
                "latest_task": latest.get(store.id),
                "latest_sync": latest_sync.get(store.id), "current": current[store.id],
                "activity_count": store_counts.get(store.id, 0),
                "upcoming": upcoming[store.id],
                **({"stock": configs[store.id].stock, "runs": configs[store.id].runs, "enabled": configs[store.id].enabled,
                    "version": configs[store.id].version, "notification_mode": configs[store.id].notification_mode,
                    "recipient_ids": list(configs[store.id].recipients.values_list("id", flat=True)),
                    "last_synced_at": configs[store.id].last_synced_at} if store.id in configs else {})} for store in stores],
            "activities": [activity_data(row) for row in activities[(page - 1) * page_size:page * page_size]],
            "activity_counts": activity_counts,
            "activity_total": activities.count(), "batch_total": batches.count(),
            "batches": [batch_data(batch, history_ids) for batch in batches[(history_page - 1) * 50:history_page * 50]],
            "latest_run_batch": str(Batch.objects.filter(tenant=request.user.tenant, tasks__store_id__in=ids,
                operation__in=["run", "copy"]).order_by("-created_at").values_list("id", flat=True).first() or ""),
            "latest_sync_batch": str(Batch.objects.filter(tenant=request.user.tenant, tasks__store_id__in=ids,
                operation="sync").order_by("-created_at").values_list("id", flat=True).first() or ""),
            "plans": [plan_data(plan) for plan in plans],
            "people": [{"id": row.user_id, "name": row.user.full_name or row.user.username} for row in people],
            "fallback_ids": list(control.fallback_users.values_list("id", flat=True)) if control else [],
            "scheduler_owner": control.scheduler_owner if control else "paused",
            "capabilities": {action: check_user_permission(request.user, PREFIX + action) for action in
                             ("configure", "execute", "delete", "plans", "notifications")},
            "workers_enabled": getattr(settings, "FLASH_SALES_WORKERS_ENABLED", False),
        })


class ConfigDetail(FlashView):
    permission_classes = [IsAuthenticated]

    def put(self, request, store_id):
        row = save_config(request.user, store_id, request.data)
        return success_response({"id": row.id, "version": row.version, "enabled": row.enabled})

    def delete(self, request, store_id):
        delete_config(request.user, store_id, request.data.get("version"))
        return success_response({"deleted": True})


class Batches(FlashView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        allowed = {"request_id", "store_ids", "operation", "preview_id", "activity_id", "desired_status", "confirmed", "activity_ids"}
        if set(request.data) - allowed:
            raise ValidationError("执行请求包含不支持的字段。")
        if not {"request_id", "store_ids"} <= set(request.data):
            raise ValidationError("请选择店铺并提供请求编号。")
        row = submit(request.user, **request.data)
        return success_response({"id": str(row.id)}, status=202)


class BatchDetail(FlashView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        ids = list(visible_stores(request.user).values_list("id", flat=True))
        batch = get_object_or_404(Batch.objects.filter(tenant=request.user.tenant, tasks__store_id__in=ids).distinct(), pk=pk)
        return success_response(batch_data(batch, ids))

    def post(self, request, pk):
        batch = get_object_or_404(Batch, pk=pk, tenant=request.user.tenant)
        require_stores(request.user, list(batch.tasks.values_list("store_id", flat=True)), "execute")
        if request.data.get("action") == "stop":
            Batch.objects.filter(pk=batch.id).update(stop_requested=True)
            audit(request.user, "flash_stop_requested", batch)
        elif request.data.get("action") == "reconcile":
            StoreTask.objects.filter(batch=batch, status__in={"waiting", "confirming"}).update(next_attempt_at=None)
        elif request.data.get("action") == "resume":
            if request.data.get("confirmed") is not True or type(request.data.get("task_id")) is not int:
                raise ValidationError("请明确确认继续核对指定原任务。")
            with transaction.atomic():
                task = get_object_or_404(StoreTask.objects.select_for_update(), pk=request.data["task_id"],
                                         batch=batch, tenant=request.user.tenant)
                if task.state.get("migration_hold") or not task.state.get("retry_paused") or task.finished_at:
                    raise ValidationError("该任务不能通过此入口继续；迁移保护须单独核对。")
                if task.lease_until and task.lease_until > timezone.now():
                    raise ValidationError("原任务仍有有效执行租约。")
                if not StoreLock.objects.filter(tenant=request.user.tenant, store_id=task.store_id, task=task).exists():
                    raise ValidationError("原任务店铺保护不一致，不能继续。")
                task.state.update(retry_paused=False, no_progress_count=0, retry_pause_reason="")
                task.state.pop("retry_progress", None)
                task.next_attempt_at, task.fence = None, None
                task.message = "已确认继续原任务，保留原写入记录及历史重试次数"
                task.save(update_fields=["state", "next_attempt_at", "fence", "message", "updated_at"])
                audit(request.user, "flash_resume_original_task", batch)
        elif request.data.get("action") == "retry_notification":
            Notification.objects.filter(batch=batch, pk=request.data.get("notification_id"), status__in={"failed", "failed_or_unknown"}).update(status="pending", lease_until=None)
        else:
            raise ValidationError("操作无效。")
        return success_response({"id": str(batch.id)})


class CopySource(FlashView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        ids = visible_stores(request.user, "execute").values_list("id", flat=True)
        activity = get_object_or_404(Activity.objects.select_related("store"), pk=pk, tenant=request.user.tenant, store_id__in=ids)
        adapter = ShopeeAdapter(activity.store)
        items = adapter.items(activity.platform_id)
        return success_response({"items": items, "slots": adapter.slots(), "source_id": activity.platform_id, "store_id": activity.store_id})


class ActivityDetail(FlashView):
    def get(self, request, pk):
        ids = visible_stores(request.user).values_list("id", flat=True)
        activity = get_object_or_404(Activity.objects.select_related("store"), pk=pk, tenant=request.user.tenant, store_id__in=ids)
        return success_response({**activity_data(activity), "items": activity.items, "details_synced_at": activity.details_synced_at})


class Previews(FlashView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        store = require_stores(request.user, [request.data.get("store_id")], "execute")[0]
        source_id = identifier(request.data.get("source_id"))
        if not Activity.objects.filter(tenant=request.user.tenant, store=store, platform_id=source_id).exists():
            raise ValidationError("来源活动不属于所选店铺。")
        adapter = ShopeeAdapter(store)
        source = adapter.items(source_id)
        items = validate_items(request.data.get("items"), source)
        targets = [row for row in adapter.slots() if str(row["timeslot_id"]) == str(request.data.get("slot_id"))]
        if len(targets) != 1:
            raise ValidationError("目标时段不再可用，请重新读取。")
        if targets[0]["start_time"] <= timezone.now().timestamp() + 600:
            raise ValidationError("目标时段临近开始，请重新选择。")
        if Intent.objects.filter(tenant=request.user.tenant, store=store, slot_id=str(targets[0]["timeslot_id"]), reservation_key__isnull=False).exists():
            raise ValidationError("目标时段已被占用。")
        row = Preview.objects.create(tenant=request.user.tenant, actor=request.user, store=store,
            source_id=source_id, source_hash=digest(source), items=items, target=targets[0], expires_at=timezone.now()+timedelta(minutes=10))
        return success_response({"id": str(row.id), "expires_at": row.expires_at, "items": items, "target": row.target}, status=201)


class Plans(FlashView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk=None):
        if pk and "enabled" in request.data:
            row = enable_plan(request.user, pk, request.data.get("version"), request.data["enabled"])
        else:
            row = save_plan(request.user, request.data, pk)
        return success_response(plan_data(row))

    def delete(self, request, pk):
        delete_plan(request.user, pk, request.data.get("version"))
        return success_response({"deleted": True})


class NotificationSettings(FlashView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def put(self, request):
        from .notifications import validate_recipients
        if set(request.data) - {"user_ids", "stores"}:
            raise ValidationError("通知设置包含不支持的字段。")
        rows = request.data.get("stores", [])
        if not isinstance(rows, list) or len(rows) > 500 or any(not isinstance(row, dict) or set(row) != {"store_id", "version", "notification_mode", "recipient_ids"} for row in rows):
            raise ValidationError("店铺通知设置格式无效。")
        if "user_ids" not in request.data and not rows:
            raise ValidationError("没有待保存的通知设置。")
        if "user_ids" in request.data:
            require_global(request.user)
            validate_recipients(request.user.tenant_id, request.data["user_ids"])
        if rows:
            require_stores(request.user, [row["store_id"] for row in rows], "configure")
            if len({row["store_id"] for row in rows}) != len(rows):
                raise ValidationError("店铺通知设置不能重复。")
        for row in sorted(rows, key=lambda item: item["store_id"]):
            StoreLock.objects.get_or_create(tenant=request.user.tenant, store_id=row["store_id"])
            StoreLock.objects.select_for_update().get(tenant=request.user.tenant, store_id=row["store_id"])
            config = get_object_or_404(StoreConfig.objects.select_for_update(), tenant=request.user.tenant, store_id=row["store_id"], deleted_at__isnull=True)
            if type(row["version"]) is not int or row["version"] != config.version:
                raise ValidationError("店铺配置版本已变化，请重新打开通知设置。")
            mode = row["notification_mode"]
            if not isinstance(mode, str) or mode not in {"owner", "custom", "fallback"}:
                raise ValidationError("通知方式无效。")
            if mode == "custom":
                validate_recipients(request.user.tenant_id, row["recipient_ids"])
            elif row["recipient_ids"] != []:
                raise ValidationError("仅自定义方式可指定接收人。")
            config.notification_mode = mode
            config.version += 1
            config.save(update_fields=["notification_mode", "version", "updated_at"])
            config.recipients.set(row["recipient_ids"])
            audit(request.user, "flash_notification_save", config, {"version": config.version, "notification_mode": mode})
        if "user_ids" in request.data:
            control, _ = TenantControl.objects.get_or_create(tenant=request.user.tenant)
            control = TenantControl.objects.select_for_update().get(pk=control.pk)
            control.fallback_users.set(request.data["user_ids"])
            audit(request.user, "flash_fallback_save", control, {"user_ids": request.data["user_ids"]})
        return success_response({"saved_stores": len(rows), **({"user_ids": request.data["user_ids"]} if "user_ids" in request.data else {})})
