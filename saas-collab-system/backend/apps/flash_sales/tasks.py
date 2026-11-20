from datetime import timedelta
from itertools import chain
import uuid

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .domain import TERMINAL, digest
from .models import Batch, ExecutionPool, Plan, StoreLock, StoreTask, TenantControl
from .services import submit


@shared_task
def execute(task_id, delivery_token=None):

    if not getattr(settings, "FLASH_SALES_WORKERS_ENABLED", False):

        return "disabled"

    from .engine import run_step

    return run_step(task_id, delivery_token=delivery_token)


@shared_task
def send_notification(notification_id):
    from .notifications import deliver
    return deliver(notification_id)


def prepare_post_sync(batch_id):
    ExecutionPool.objects.get_or_create(key="shopee")
    return _prepare_post_sync(batch_id)


@transaction.atomic
def _prepare_post_sync(batch_id):
    ExecutionPool.objects.select_for_update().get(key="shopee")
    # Recovery and worker finalization can hold a task while waiting for its batch.
    tasks = list(StoreTask.objects.select_for_update().filter(batch_id=batch_id).order_by("pk"))
    parent = Batch.objects.select_for_update().get(pk=batch_id)
    if not parent.finished_at or parent.operation == "sync" or parent.request_id.startswith("import:"):
        return
    recovery_round = max((task.state.get("exception_recovery_round", 0) for task in tasks), default=0)
    request_id = f"post-sync:{parent.id}" + (f":recovery:{recovery_round}" if recovery_round else "")
    child, created = Batch.objects.get_or_create(tenant_id=parent.tenant_id, request_id=request_id,
        defaults={"actor": parent.actor, "source": "post_sync", "operation": "sync", "payload_hash": digest({"parent": str(parent.id)})})
    if not created:
        return
    for task in tasks:
        if recovery_round and task.state.get("post_sync_task_id"):
            continue
        affected = list(task.intents.exclude(platform_id="").values_list("platform_id", flat=True).distinct())
        sync = StoreTask.objects.create(tenant_id=parent.tenant_id, batch=child, store_id=task.store_id,
            snapshot={"activity_ids": affected, "sync_scope": "affected", "recipients": {"users": []}},
            status="queued" if affected else "succeeded", finished_at=None if affected else timezone.now(),
            message="" if affected else "未涉及平台活动，无需同步")
        task.state = {**task.state, "post_sync_task_id": sync.id}
        task.save(update_fields=["state", "updated_at"])
    if not child.tasks.exclude(status__in=TERMINAL).exists():
        child.finished_at = timezone.now()
        child.save(update_fields=["finished_at", "updated_at"])


def dispatch_plans(*, now=None, scheduler_owner="saas"):
    if scheduler_owner not in {"saas", "sync_tasks"}:
        raise ValueError("Unsupported flash sales scheduler owner.")
    now = now or timezone.now()
    dispatched = 0
    for control_id in TenantControl.objects.filter(scheduler_owner=scheduler_owner).values_list("id", flat=True):
        with transaction.atomic():
            control = TenantControl.objects.select_for_update().get(pk=control_id)
            if control.scheduler_owner != scheduler_owner:
                continue
            recovering = not control.last_dispatch_at or (now - control.last_dispatch_at).total_seconds() > 30
            for plan in Plan.objects.select_for_update().filter(tenant_id=control.tenant_id, enabled=True, deleted_at__isnull=True, next_due__lte=now).select_related("actor"):
                dispatch_plan(plan, now, recovering)
                dispatched += 1
            control.last_dispatch_at = now
            control.save(update_fields=["last_dispatch_at", "updated_at"])
    return dispatched


def dispatch_plan(plan, now, recovering):
    due = plan.next_due
    request_id = f"plan:{plan.id}:{due.isoformat()}"
    ids = list(plan.stores.values_list("id", flat=True))
    if not Batch.objects.filter(tenant_id=plan.tenant_id, request_id=request_id).exists():
        if recovering or (now - due).total_seconds() >= 60:
            batch = Batch.objects.create(tenant_id=plan.tenant_id, actor=plan.actor, request_id=request_id,
                payload_hash=digest({"stores": ids}), source="scheduled", operation="run", plan=plan,
                plan_version=plan.version, scheduled_at=due, finished_at=now)
            for store_id in ids:
                StoreTask.objects.create(tenant_id=plan.tenant_id, batch=batch, store_id=store_id,
                    status="missed", message="错过执行时间，未补跑", finished_at=now)
        else:
            try:
                submit(plan.actor, request_id=request_id, store_ids=ids, plan=plan, due=due)
            except (PermissionDenied, ValidationError):
                batch = Batch.objects.create(tenant_id=plan.tenant_id, actor=plan.actor, request_id=request_id,
                    payload_hash=digest({"stores": ids}), source="scheduled", operation="run", plan=plan,
                    plan_version=plan.version, scheduled_at=due, finished_at=now)
                for store_id in ids:
                    StoreTask.objects.create(tenant_id=plan.tenant_id, batch=batch, store_id=store_id,
                        status="failed", message="计划权限、授权或店铺配置已变化；未调用平台，计划已暂停", finished_at=now)
                plan.enabled = False
    if plan.kind == "once":
        plan.enabled, plan.next_due = False, None
    else:
        while plan.next_due <= now:
            plan.next_due += timedelta(days=1)
    plan.save(update_fields=["enabled", "next_due", "updated_at"])


@shared_task
def dispatch():
    if not getattr(settings, "FLASH_SALES_WORKERS_ENABLED", False):
        return "disabled"
    dispatch_plans()
    from .engine import (
        EXECUTION_CAPACITY, delivery_candidates, fail_recovery_blocked_writer,
        has_delivery_hold, occupied_execution_slots, ready_for_delivery,
    )

    # Settle blocked writes independently so no transaction holds a batch lock
    # while reserving delivery for another task. Dispatch and claim can proceed
    # with protected reads even if more blocked writes remain in the next scan.
    blocked_ids = list(delivery_candidates(timezone.now()).exclude(batch__operation="sync")
        .filter(status="queued", started_at__isnull=True, fence__isnull=True, recovery_blocked=True)
        .order_by("created_at", "id").values_list("id", flat=True)[:100])
    for task_id in blocked_ids:
        fail_recovery_blocked_writer(task_id)

    deliveries = []
    ExecutionPool.objects.get_or_create(key="shopee")
    with transaction.atomic():
        ExecutionPool.objects.select_for_update().get(key="shopee")
        now = timezone.now()
        occupied = list(occupied_execution_slots(now).values_list("store_id", flat=True))
        served = set(occupied)
        capacity = max(0, EXECUTION_CAPACITY - len(occupied))
        candidates = delivery_candidates(now).exclude(store_id__in=served)
        foreground = candidates.exclude(batch__operation="sync").filter(store_blocked=False)
        background = candidates.filter(batch__operation="sync").filter(
            Q(store_blocked=False) | Q(recovery_blocked=True))
        if foreground.exists():
            background = background.filter(pk__in=StoreLock.objects.values("task_id"))
        ordered = chain(foreground.order_by("created_at", "id").iterator(chunk_size=100),
                        background.order_by("created_at", "id").iterator(chunk_size=100))
        for task in ordered:
            if len(deliveries) >= capacity:
                break
            if task.store_id in served:
                continue
            task = StoreTask.objects.select_for_update().get(pk=task.pk)
            if not ready_for_delivery(task, now) or has_delivery_hold(task, now):
                continue
            token = str(uuid.uuid4())
            state = dict(task.state or {})
            state["delivery_hold"] = {"token": token, "expires_at": now.timestamp() + 120}
            StoreTask.objects.filter(pk=task.pk).update(state=state)
            deliveries.append((task.id, token, task.batch.operation == "sync"))
            served.add(task.store_id)
        for task_id, token, is_sync in deliveries:
            transaction.on_commit(lambda task_id=task_id, token=token, is_sync=is_sync:
                                  _publish_delivery(task_id, token, is_sync), robust=True)
    from .notifications import prepare_notifications
    from .models import Notification
    for batch_id in Batch.objects.filter(finished_at__isnull=False).exclude(operation="sync").exclude(request_id__startswith="import:").filter(tasks__state__post_sync_task_id__isnull=True).distinct().values_list("id", flat=True)[:100]:
        prepare_post_sync(batch_id)
    for batch_id in Batch.objects.filter(
        Q(finished_at__isnull=False, notifications__isnull=True)
        | Q(finished_at__isnull=False, notifications__snapshot__phase="attention")
        | Q(finished_at__isnull=False, notifications__snapshot__phase="recovery_pending")
        | Q(finished_at__isnull=True, tasks__state__retry_paused=True, notifications__isnull=True)
    ).exclude(operation="sync").distinct().values_list("id", flat=True)[:100]:
        prepare_notifications(batch_id)
    if getattr(settings, "FLASH_SALES_NOTIFICATIONS_ENABLED", False):
        Notification.objects.filter(status="sending", lease_until__lte=now).update(
            status="failed_or_unknown", lease_until=None, message="发送进程中断，结果未确认；可单独重试通知")
        for pk in Notification.objects.filter(status="pending").values_list("pk", flat=True)[:100]:
            send_notification.apply_async((pk,), queue="shopee-flash-notify", expires=60)
    return "dispatched"


def _publish_delivery(task_id, token, is_sync):
    try:
        execute.apply_async((task_id, token), queue="shopee-flash-sync" if is_sync else "shopee-flash", expires=30)
    except Exception:
        with transaction.atomic():
            task = StoreTask.objects.select_for_update().filter(pk=task_id).first()
            if task and (task.state or {}).get("delivery_hold", {}).get("token") == token:
                task.state.pop("delivery_hold", None)
                task.save(update_fields=["state", "updated_at"])
