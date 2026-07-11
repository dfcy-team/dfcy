import hashlib
import json
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.common.security import mask_sensitive_text

from .models import RPAAccountLock, RPAEvidence, RPAPageSignature, RPATask, RPATaskAttempt


ACTIVE_TASK_STATUSES = {RPATask.Status.CLAIMED, RPATask.Status.RUNNING}
TERMINAL_TASK_STATUSES = {
    RPATask.Status.SUCCESS,
    RPATask.Status.FAILED,
    RPATask.Status.MANUAL_REQUIRED,
    RPATask.Status.CANCELLED,
}
ALLOWED_TRANSITIONS = {
    RPATask.Status.PENDING: {RPATask.Status.CLAIMED, RPATask.Status.CANCELLED},
    RPATask.Status.RETRYING: {RPATask.Status.CLAIMED, RPATask.Status.MANUAL_REQUIRED, RPATask.Status.CANCELLED},
    RPATask.Status.CLAIMED: {
        RPATask.Status.RUNNING,
        RPATask.Status.FAILED,
        RPATask.Status.RETRYING,
        RPATask.Status.MANUAL_REQUIRED,
        RPATask.Status.CANCELLED,
    },
    RPATask.Status.RUNNING: {
        RPATask.Status.SUCCESS,
        RPATask.Status.FAILED,
        RPATask.Status.RETRYING,
        RPATask.Status.MANUAL_REQUIRED,
        RPATask.Status.CANCELLED,
    },
}


class AccountLockConflict(Exception):
    pass


def transition_task(task, next_status):
    if next_status not in ALLOWED_TRANSITIONS.get(task.status, set()):
        raise ValidationError({"status": f"Illegal RPA task transition: {task.status} -> {next_status}."})
    task.status = next_status


def create_attempt(task, agent, now=None):
    now = now or timezone.now()
    attempt_no = (task.attempts.aggregate(value=Max("attempt_no"))["value"] or 0) + 1
    return RPATaskAttempt.objects.create(
        tenant=task.tenant,
        task=task,
        attempt_no=attempt_no,
        agent=agent,
        started_at=now,
        heartbeat_at=now,
    )


def current_attempt(task, agent, create_if_missing=False):
    attempt = task.attempts.filter(agent=agent, finished_at__isnull=True).order_by("-attempt_no").first()
    if attempt is None and create_if_missing:
        attempt = create_attempt(task, agent)
    return attempt


def release_expired_account_locks(now=None, tenant=None):
    now = now or timezone.now()
    locks = RPAAccountLock.objects.filter(
        lock_status=RPAAccountLock.LockStatus.HELD,
        expires_at__lte=now,
    )
    if tenant is not None:
        locks = locks.filter(tenant=tenant)
    return locks.update(lock_status=RPAAccountLock.LockStatus.EXPIRED, released_at=now)


def acquire_account_lock(task, now=None, lease_seconds=300):
    platform = task.payload.get("platform")
    account_alias = task.payload.get("account_alias")
    if not platform or not account_alias:
        return None

    now = now or timezone.now()
    release_expired_account_locks(now, tenant=task.tenant)
    existing = RPAAccountLock.objects.select_for_update().filter(
        tenant=task.tenant,
        platform=platform,
        account_alias=account_alias,
        lock_status=RPAAccountLock.LockStatus.HELD,
    ).first()
    if existing:
        if existing.task_id == task.id:
            return existing
        raise AccountLockConflict(f"Account {platform}/{account_alias} is already locked.")

    try:
        with transaction.atomic():
            return RPAAccountLock.objects.create(
                tenant=task.tenant,
                platform=platform,
                account_alias=account_alias,
                task=task,
                acquired_at=now,
                expires_at=now + timedelta(seconds=lease_seconds),
            )
    except IntegrityError as exc:
        raise AccountLockConflict(f"Account {platform}/{account_alias} is already locked.") from exc


def refresh_account_lock(task, now=None, lease_seconds=300):
    now = now or timezone.now()
    task.account_locks.filter(lock_status=RPAAccountLock.LockStatus.HELD).update(
        expires_at=now + timedelta(seconds=lease_seconds)
    )


def release_account_lock(task, now=None):
    now = now or timezone.now()
    return task.account_locks.filter(lock_status=RPAAccountLock.LockStatus.HELD).update(
        lock_status=RPAAccountLock.LockStatus.RELEASED,
        released_at=now,
    )


def is_placeholder_reference(value):
    value = str(value or "")
    return value.startswith(("demo", "example", "local-placeholder"))


def record_evidence(task, attempt, placeholder_url, payload):
    if not is_placeholder_reference(placeholder_url):
        raise ValidationError({"screenshot_ref": "Only demo/example placeholder references are allowed."})
    payload_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return RPAEvidence.objects.create(
        tenant=task.tenant,
        task=task,
        attempt=attempt,
        evidence_type=RPAEvidence.EvidenceType.SCREENSHOT,
        placeholder_url=placeholder_url,
        payload_hash=payload_hash,
    )


def validate_evidence_references(values):
    for value in values or []:
        if isinstance(value, dict):
            value = value.get("screenshot_ref") or value.get("placeholder_url") or ""
        if not is_placeholder_reference(value):
            raise ValidationError({"screenshots": "Only demo/example placeholder references are allowed."})


def evaluate_page_signature(task, platform, page_type, signature_hash, now=None):
    previous = RPAPageSignature.objects.filter(
        tenant=task.tenant,
        platform=platform,
        page_type=page_type,
        detected_status=RPAPageSignature.DetectedStatus.STABLE,
    ).first()
    changed = previous is not None and previous.signature_hash != signature_hash
    signature = RPAPageSignature.objects.create(
        tenant=task.tenant,
        platform=platform,
        page_type=page_type,
        signature_hash=signature_hash,
        detected_status=(
            RPAPageSignature.DetectedStatus.CHANGED if changed else RPAPageSignature.DetectedStatus.STABLE
        ),
    )
    if changed and task.status in ACTIVE_TASK_STATUSES:
        transition_task(task, RPATask.Status.MANUAL_REQUIRED)
        task.error_message = "Page signature changed; manual inspection required."
        task.finished_at = now or timezone.now()
        task.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        release_account_lock(task, now)
    return signature


@transaction.atomic
def mark_heartbeat_timeouts(timeout_seconds=300, now=None):
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=timeout_seconds)
    attempts = RPATaskAttempt.objects.select_for_update().select_related("task").filter(
        status__in=(RPATaskAttempt.Status.CLAIMED, RPATaskAttempt.Status.RUNNING),
        heartbeat_at__lt=cutoff,
        finished_at__isnull=True,
        task__status__in=ACTIVE_TASK_STATUSES,
    )
    count = 0
    for attempt in attempts:
        task = attempt.task
        transition_task(task, RPATask.Status.MANUAL_REQUIRED)
        task.error_message = "Heartbeat timeout; manual inspection required."
        task.finished_at = now
        task.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        attempt.status = RPATaskAttempt.Status.MANUAL_REQUIRED
        attempt.masked_error = task.error_message
        attempt.manual_required = True
        attempt.finished_at = now
        attempt.save(
            update_fields=["status", "masked_error", "manual_required", "finished_at"]
        )
        release_account_lock(task, now)
        count += 1
    return count


def finish_attempt(attempt, status, *, error="", failed_step="", last_success_step="", manual_required=False, now=None):
    if attempt is None:
        return
    attempt.status = status
    attempt.masked_error = mask_sensitive_text(error)
    attempt.failed_step = failed_step
    attempt.last_success_step = last_success_step
    attempt.manual_required = manual_required
    attempt.finished_at = now or timezone.now()
    attempt.save(
        update_fields=[
            "status",
            "masked_error",
            "failed_step",
            "last_success_step",
            "manual_required",
            "finished_at",
        ]
    )
