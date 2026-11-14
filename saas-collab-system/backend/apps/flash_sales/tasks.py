from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .domain import TERMINAL, digest
from .models import Batch, Plan, StoreTask, TenantControl
from .services import submit


@shared_task
def execute(task_id):
    if not getattr(settings, "FLASH_SALES_WORKERS_ENABLED", False):
        return "disabled"
    from .engine import run_step
    return run_step(task_id)


@shared_task
def send_notification(notification_id):
    from .notifications import deliver
    return deliver(notification_id)


@transaction.atomic
def prepare_post_sync(batch_id):
    parent = Batch.objects.select_for_update().get(pk=batch_id)
    if not parent.finished_at or parent.operation == "sync" or parent.request_id.startswith("import:"):
        return
    tasks = list(parent.tasks.select_related("store"))
    child, created = Batch.objects.get_or_create(tenant_id=parent.tenant_id, request_id=f"post-sync:{parent.id}",
        defaults={"actor": parent.actor, "source": "post_sync", "operation": "sync", "payload_hash": digest({"parent": str(parent.id)})})
    if not created:
        return
    for task in tasks:
        sync = StoreTask.objects.create(tenant_id=parent.tenant_id, batch=child, store=task.store,
            snapshot={"activity_ids": [], "recipients": {"users": []}})
        task.state = {**task.state, "post_sync_task_id": sync.id}
        task.save(update_fields=["state", "updated_at"])


def dispatch_plans(*, now=None):
    now = now or timezone.now()
    for control_id in TenantControl.objects.filter(scheduler_owner="saas").values_list("id", flat=True):
        with transaction.atomic():
            control = TenantControl.objects.select_for_update().get(pk=control_id)
            if control.scheduler_owner != "saas":
                continue
            recovering = not control.last_dispatch_at or (now - control.last_dispatch_at).total_seconds() > 30
            for plan in Plan.objects.select_for_update().filter(tenant_id=control.tenant_id, enabled=True, deleted_at__isnull=True, next_due__lte=now).select_related("actor"):
                dispatch_plan(plan, now, recovering)
            control.last_dispatch_at = now
            control.save(update_fields=["last_dispatch_at", "updated_at"])


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
    now = timezone.now()
    tasks = StoreTask.objects.exclude(status__in=TERMINAL).filter(
        Q(state__migration_hold=False) | Q(state__migration_hold__isnull=True),
        Q(state__retry_paused=False) | Q(state__retry_paused__isnull=True),
        Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now),
        Q(lease_until__isnull=True) | Q(lease_until__lte=now),
    ).order_by("created_at", "id")[:60]
    for task in tasks:
        execute.apply_async((task.id,), queue="shopee-flash-sync" if task.batch.operation == "sync" else "shopee-flash", expires=30)
    from .notifications import prepare_notifications
    from .models import Notification
    for batch_id in Batch.objects.filter(finished_at__isnull=False).exclude(operation="sync").exclude(request_id__startswith="import:").filter(tasks__state__post_sync_task_id__isnull=True).distinct().values_list("id", flat=True)[:100]:
        prepare_post_sync(batch_id)
    for batch_id in Batch.objects.filter(finished_at__isnull=False, notifications__isnull=True).values_list("id", flat=True)[:100]:
        prepare_notifications(batch_id)
    if getattr(settings, "FLASH_SALES_NOTIFICATIONS_ENABLED", False):
        Notification.objects.filter(status="sending", lease_until__lte=now).update(
            status="failed_or_unknown", lease_until=None, message="发送进程中断，结果未确认；可单独重试通知")
        for pk in Notification.objects.filter(status="pending").values_list("pk", flat=True)[:100]:
            send_notification.apply_async((pk,), queue="shopee-flash-notify", expires=60)
    return "dispatched"
