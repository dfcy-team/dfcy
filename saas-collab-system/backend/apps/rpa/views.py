from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes

from apps.common.responses import success_response
from apps.permissions.api_permissions import IsRPAAgent
from apps.rpa.models import RPAAgent, RPATask, RPATaskStepLog


@api_view(["GET"])
def health(request):
    return success_response({"status": "ok", "service": "rpa"})


def _get_task_for_rpa_user(request, task_id):
    return get_object_or_404(RPATask, id=task_id, tenant=request.user.tenant)


def _get_agent_for_user(request):
    return RPAAgent.objects.filter(
        tenant=request.user.tenant,
        status=RPAAgent.Status.ACTIVE,
    ).first()


def _task_payload(task):
    return {
        "task_id": task.id,
        "task_type": task.task_type,
        "business_type": task.business_type,
        "business_id": task.business_id,
        "payload": task.payload,
        "queue_key": task.payload.get("queue_key"),
        "status": task.status,
    }


@api_view(["POST"])
@permission_classes([IsRPAAgent])
def claim_task(request):
    queue_key = request.data.get("queue_key")
    with transaction.atomic():
        tasks = RPATask.objects.select_for_update().filter(
            tenant=request.user.tenant,
            status=RPATask.Status.PENDING,
        )
        if queue_key:
            tasks = tasks.filter(payload__queue_key=queue_key)
        task = tasks.order_by("-priority", "created_at").first()

        if task is None:
            return success_response({"task": None, "status": "empty"})

        task.status = RPATask.Status.CLAIMED
        task.claimed_by = _get_agent_for_user(request)
        task.claimed_at = timezone.now()
        task.save(update_fields=["status", "claimed_by", "claimed_at", "updated_at"])

    return success_response(_task_payload(task))


@api_view(["POST"])
@permission_classes([IsRPAAgent])
def task_heartbeat(request, task_id):
    task = _get_task_for_rpa_user(request, task_id)
    now = timezone.now()
    update_fields = ["updated_at"]
    if task.status in {RPATask.Status.CLAIMED, RPATask.Status.PENDING}:
        task.status = RPATask.Status.RUNNING
        task.started_at = task.started_at or now
        update_fields.extend(["status", "started_at"])
    task.save(update_fields=update_fields)

    return success_response(
        {
            "task_id": task.id,
            "status": task.status,
            "server_time": now.isoformat(),
            "continue_running": True,
        }
    )


@api_view(["POST"])
@permission_classes([IsRPAAgent])
def append_task_log(request, task_id):
    task = _get_task_for_rpa_user(request, task_id)
    status_value = request.data.get("status") or RPATaskStepLog.Status.RUNNING
    if status_value not in RPATaskStepLog.Status.values:
        status_value = RPATaskStepLog.Status.RUNNING
    log = RPATaskStepLog.objects.create(
        tenant=task.tenant,
        task=task,
        step_name=request.data.get("step_name", "rpa_step"),
        status=status_value,
        message=request.data.get("message", ""),
        screenshot_url=request.data.get("screenshot_url", ""),
    )

    return success_response({"task_id": task.id, "log_id": log.id, "status": task.status})


@api_view(["POST"])
@permission_classes([IsRPAAgent])
def append_task_screenshot(request, task_id):
    task = _get_task_for_rpa_user(request, task_id)
    screenshot_url = request.data.get("screenshot_url") or request.data.get("screenshot_ref", "")
    log = RPATaskStepLog.objects.create(
        tenant=task.tenant,
        task=task,
        step_name=request.data.get("step_name", "screenshot"),
        status=RPATaskStepLog.Status.SUCCESS,
        message=request.data.get("message", "screenshot placeholder recorded"),
        screenshot_url=screenshot_url,
    )
    if screenshot_url.startswith(("http://", "https://")):
        task.screenshot_url = screenshot_url
        task.save(update_fields=["screenshot_url", "updated_at"])

    return success_response(
        {
            "task_id": task.id,
            "screenshot_id": log.id,
            "screenshot_url": screenshot_url,
            "status": task.status,
        }
    )


@api_view(["POST"])
@permission_classes([IsRPAAgent])
def complete_task(request, task_id):
    task = _get_task_for_rpa_user(request, task_id)
    task.status = RPATask.Status.SUCCESS
    task.result = {
        "message": request.data.get("message", ""),
        "result": request.data.get("result", {}),
        "screenshots": request.data.get("screenshots", []),
        "page_url": request.data.get("page_url", ""),
        "page_snapshot": request.data.get("page_snapshot", {}),
    }
    task.error_message = ""
    task.finished_at = timezone.now()
    task.save(update_fields=["status", "result", "error_message", "finished_at", "updated_at"])

    return success_response(
        {
            "task_id": task.id,
            "status": task.status,
            "finished_at": task.finished_at.isoformat(),
        }
    )


@api_view(["POST"])
@permission_classes([IsRPAAgent])
def fail_task(request, task_id):
    task = _get_task_for_rpa_user(request, task_id)
    manual_required = bool(request.data.get("manual_required", False))
    requested_status = request.data.get("status")
    if manual_required:
        next_status = RPATask.Status.MANUAL_REQUIRED
    elif requested_status == RPATask.Status.RETRYING:
        next_status = RPATask.Status.RETRYING
    else:
        next_status = RPATask.Status.FAILED

    task.status = next_status
    task.error_message = request.data.get("error_message") or request.data.get("message", "")
    task.result = {
        "message": request.data.get("message", ""),
        "error_code": request.data.get("error_code", ""),
        "error_message": task.error_message,
        "manual_required": manual_required,
        "manual_reason": request.data.get("manual_reason", ""),
        "failed_step": request.data.get("failed_step", ""),
        "last_success_step": request.data.get("last_success_step", ""),
        "screenshots": request.data.get("screenshots", []),
        "page_url": request.data.get("page_url", ""),
        "page_snapshot": request.data.get("page_snapshot", {}),
    }
    task.finished_at = timezone.now()
    task.save(update_fields=["status", "error_message", "result", "finished_at", "updated_at"])

    return success_response(
        {
            "task_id": task.id,
            "status": task.status,
            "finished_at": task.finished_at.isoformat(),
        }
    )
