from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.responses import success_response
from apps.common.security import mask_sensitive_text, sanitize_sensitive_data
from apps.permissions.api_permissions import IsRPAAgent
from apps.rpa.models import RPAAgent, RPATask, RPATaskAttempt, RPATaskStepLog
from apps.rpa.stability_services import (
    ACTIVE_TASK_STATUSES,
    AccountLockConflict,
    acquire_account_lock,
    create_attempt,
    current_attempt,
    evaluate_page_signature,
    finish_attempt,
    record_evidence,
    refresh_account_lock,
    release_account_lock,
    transition_task,
    validate_evidence_references,
)


@api_view(["GET"])
def health(request):
    return success_response({"status": "ok", "service": "rpa"})


def _get_agent_for_user(request):
    agent = RPAAgent.objects.filter(
        tenant=request.user.tenant,
        user=request.user,
        status=RPAAgent.Status.ACTIVE,
    ).first()
    if agent is None:
        raise PermissionDenied("Valid RPA agent binding is required.")
    return agent


def _get_task_for_rpa_agent(request, task_id):
    agent = _get_agent_for_user(request)
    task = get_object_or_404(RPATask, id=task_id, tenant=request.user.tenant)
    if task.claimed_by_id != agent.id:
        raise PermissionDenied("RPA task is not claimed by this agent.")
    return task, agent


def _task_payload(task):
    return {
        "task_id": task.id,
        "task_type": task.task_type,
        "business_type": task.business_type,
        "business_id": task.business_id,
        "payload": sanitize_sensitive_data(task.payload),
        "queue_key": task.payload.get("queue_key"),
        "status": task.status,
    }


@api_view(["POST"])
@permission_classes([IsRPAAgent])
def claim_task(request):
    queue_key = request.data.get("queue_key")
    agent = _get_agent_for_user(request)
    with transaction.atomic():
        tasks = RPATask.objects.select_for_update().filter(
            tenant=request.user.tenant,
            status__in=(RPATask.Status.PENDING, RPATask.Status.RETRYING),
            retry_count__lte=F("max_retry_count"),
        )
        if queue_key:
            tasks = tasks.filter(payload__queue_key=queue_key)
        task = None
        for candidate in tasks.order_by("-priority", "created_at"):
            try:
                acquire_account_lock(candidate)
            except AccountLockConflict:
                continue
            task = candidate
            break

        if task is None:
            return success_response({"task": None, "status": "empty"})

        transition_task(task, RPATask.Status.CLAIMED)
        task.claimed_by = agent
        task.claimed_at = timezone.now()
        task.finished_at = None
        task.save(update_fields=["status", "claimed_by", "claimed_at", "finished_at", "updated_at"])
        create_attempt(task, agent, task.claimed_at)

    return success_response(_task_payload(task))


@api_view(["POST"])
@permission_classes([IsRPAAgent])
def task_heartbeat(request, task_id):
    task, agent = _get_task_for_rpa_agent(request, task_id)
    if task.status not in ACTIVE_TASK_STATUSES:
        raise ValidationError({"status": "Heartbeat is only allowed for claimed or running tasks."})
    now = timezone.now()
    agent.last_heartbeat_at = now
    agent.save(update_fields=["last_heartbeat_at", "updated_at"])
    update_fields = ["updated_at"]
    if task.status == RPATask.Status.CLAIMED:
        transition_task(task, RPATask.Status.RUNNING)
        task.started_at = task.started_at or now
        update_fields.extend(["status", "started_at"])
    task.save(update_fields=update_fields)
    attempt = current_attempt(task, agent, create_if_missing=True)
    attempt.status = RPATaskAttempt.Status.RUNNING
    attempt.heartbeat_at = now
    attempt.save(update_fields=["status", "heartbeat_at"])
    refresh_account_lock(task, now)

    continue_running = True
    signature_hash = request.data.get("page_signature_hash")
    if signature_hash:
        signature = evaluate_page_signature(
            task,
            request.data.get("platform") or task.payload.get("platform", "mock"),
            request.data.get("page_type", "unknown"),
            signature_hash,
            now,
        )
        if signature.detected_status == signature.DetectedStatus.CHANGED:
            finish_attempt(
                attempt,
                RPATaskAttempt.Status.MANUAL_REQUIRED,
                error="Page signature changed; manual inspection required.",
                manual_required=True,
                now=now,
            )
            continue_running = False

    return success_response(
        {
            "task_id": task.id,
            "status": task.status,
            "server_time": now.isoformat(),
            "continue_running": continue_running,
        }
    )


@api_view(["POST"])
@permission_classes([IsRPAAgent])
def append_task_log(request, task_id):
    task, agent = _get_task_for_rpa_agent(request, task_id)
    if task.status not in ACTIVE_TASK_STATUSES:
        raise ValidationError({"status": "Logs are only accepted for active task attempts."})
    status_value = request.data.get("status") or RPATaskStepLog.Status.RUNNING
    if status_value not in RPATaskStepLog.Status.values:
        status_value = RPATaskStepLog.Status.RUNNING
    screenshot_url = request.data.get("screenshot_url", "")
    if screenshot_url:
        validate_evidence_references([screenshot_url])
    log = RPATaskStepLog.objects.create(
        tenant=task.tenant,
        task=task,
        step_name=request.data.get("step_name", "rpa_step"),
        status=status_value,
        message=mask_sensitive_text(request.data.get("message", "")),
        screenshot_url=screenshot_url,
    )
    attempt = current_attempt(task, agent, create_if_missing=True)
    if status_value == RPATaskStepLog.Status.SUCCESS:
        attempt.last_success_step = log.step_name
        attempt.save(update_fields=["last_success_step"])

    return success_response({"task_id": task.id, "log_id": log.id, "status": task.status})


@api_view(["POST"])
@permission_classes([IsRPAAgent])
def append_task_screenshot(request, task_id):
    task, agent = _get_task_for_rpa_agent(request, task_id)
    if task.status not in ACTIVE_TASK_STATUSES:
        raise ValidationError({"status": "Evidence is only accepted for active task attempts."})
    screenshot_url = request.data.get("screenshot_url") or request.data.get("screenshot_ref", "")
    if screenshot_url.startswith(("http://", "https://")):
        raise ValidationError({"screenshot_ref": "External screenshot URLs are not allowed."})
    attempt = current_attempt(task, agent, create_if_missing=True)
    evidence = record_evidence(task, attempt, screenshot_url, request.data)
    log = RPATaskStepLog.objects.create(
        tenant=task.tenant,
        task=task,
        step_name=request.data.get("step_name", "screenshot"),
        status=RPATaskStepLog.Status.SUCCESS,
        message=mask_sensitive_text(request.data.get("message", "screenshot placeholder recorded")),
        screenshot_url=screenshot_url,
    )
    return success_response(
        {
            "task_id": task.id,
            "screenshot_id": evidence.id,
            "log_id": log.id,
            "screenshot_url": screenshot_url,
            "status": task.status,
        }
    )


@api_view(["POST"])
@permission_classes([IsRPAAgent])
def complete_task(request, task_id):
    task, agent = _get_task_for_rpa_agent(request, task_id)
    transition_task(task, RPATask.Status.SUCCESS)
    validate_evidence_references(request.data.get("screenshots", []))
    task.result = sanitize_sensitive_data({
        "message": request.data.get("message", ""),
        "result": request.data.get("result", {}),
        "screenshots": request.data.get("screenshots", []),
        "page_url": request.data.get("page_url", ""),
        "page_snapshot": request.data.get("page_snapshot", {}),
    })
    task.error_message = ""
    task.finished_at = timezone.now()
    task.save(update_fields=["status", "result", "error_message", "finished_at", "updated_at"])
    finish_attempt(
        current_attempt(task, agent, create_if_missing=True),
        RPATaskAttempt.Status.SUCCESS,
        now=task.finished_at,
    )
    release_account_lock(task, task.finished_at)

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
    task, agent = _get_task_for_rpa_agent(request, task_id)
    validate_evidence_references(request.data.get("screenshots", []))
    manual_required = bool(request.data.get("manual_required", False))
    requested_status = request.data.get("status")
    if manual_required:
        next_status = RPATask.Status.MANUAL_REQUIRED
    elif requested_status == RPATask.Status.RETRYING:
        if task.retry_count >= task.max_retry_count:
            next_status = RPATask.Status.MANUAL_REQUIRED
            manual_required = True
        else:
            next_status = RPATask.Status.RETRYING
            task.retry_count += 1
    else:
        next_status = RPATask.Status.FAILED

    transition_task(task, next_status)
    task.error_message = mask_sensitive_text(
        request.data.get("error_message") or request.data.get("message", "")
    )
    task.result = sanitize_sensitive_data({
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
    })
    task.result["error_message"] = task.error_message
    task.finished_at = timezone.now()
    task.save(
        update_fields=["status", "retry_count", "error_message", "result", "finished_at", "updated_at"]
    )
    attempt_status = {
        RPATask.Status.RETRYING: RPATaskAttempt.Status.RETRYING,
        RPATask.Status.MANUAL_REQUIRED: RPATaskAttempt.Status.MANUAL_REQUIRED,
        RPATask.Status.FAILED: RPATaskAttempt.Status.FAILED,
    }[next_status]
    finish_attempt(
        current_attempt(task, agent, create_if_missing=True),
        attempt_status,
        error=task.error_message,
        failed_step=request.data.get("failed_step", ""),
        last_success_step=request.data.get("last_success_step", ""),
        manual_required=manual_required,
        now=task.finished_at,
    )
    release_account_lock(task, task.finished_at)

    return success_response(
        {
            "task_id": task.id,
            "status": task.status,
            "finished_at": task.finished_at.isoformat(),
        }
    )
