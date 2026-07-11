import hashlib
import json
import uuid
from datetime import timedelta
from time import sleep as default_retry_wait

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .adapters import MockPlatformAdapter, get_adapter_for_config
from .models import SyncCursor, SyncJob, SyncRun, WebhookEvent
from .security import sanitize_payload, sanitize_text


def calculate_backoff_seconds(retry_count, base_seconds=1, max_seconds=30):
    return min(max_seconds, base_seconds * (2**retry_count))


def _run_id():
    return uuid.uuid4().hex


def _lease_duration():
    return timedelta(seconds=settings.SYNC_JOB_LEASE_SECONDS)


def _has_expired_lease(sync_job, now):
    if sync_job.status != SyncJob.Status.RUNNING:
        return False
    if sync_job.lock_expires_at:
        return sync_job.lock_expires_at <= now
    if sync_job.last_run_at:
        return sync_job.last_run_at <= now - _lease_duration()
    return True


def _recover_expired_lease(sync_job, now):
    SyncRun.objects.filter(sync_job=sync_job, status=SyncRun.Status.RUNNING).update(
        status=SyncRun.Status.FAILED,
        finished_at=now,
        failed_count=F("failed_count") + 1,
        error_code="LEASE_EXPIRED",
        masked_error_message="Sync run lease expired before completion.",
        masked_log={"error": "lease_expired"},
    )
    sync_job.status = SyncJob.Status.FAILED
    sync_job.lock_token = ""
    sync_job.lock_expires_at = None
    sync_job.lock_heartbeat_at = now
    sync_job.save(
        update_fields=[
            "status",
            "lock_token",
            "lock_expires_at",
            "lock_heartbeat_at",
            "updated_at",
        ]
    )


def _renew_lease(sync_job, run, not_before=None):
    now = timezone.now()
    lease_anchor = max(now, not_before) if not_before else now
    expires_at = lease_anchor + _lease_duration()
    renewed = SyncJob.objects.filter(
        pk=sync_job.pk,
        status=SyncJob.Status.RUNNING,
        lock_token=run.run_id,
    ).update(
        lock_expires_at=expires_at,
        lock_heartbeat_at=now,
        updated_at=now,
    )
    if not renewed:
        raise ValidationError("Sync job run lease was lost.")
    sync_job.lock_expires_at = expires_at
    sync_job.lock_heartbeat_at = now


def run_sync_job(sync_job, adapter=None, idempotency_key=None, retry_wait=None):
    retry_wait = retry_wait or default_retry_wait
    adapter = adapter or get_adapter_for_config(sync_job.integration_config)
    if type(adapter) is not MockPlatformAdapter:
        raise ValidationError("Only mock synchronization can be executed by this endpoint in phase 2.")

    now = timezone.now()
    with transaction.atomic():
        locked_job = (
            SyncJob.objects.select_for_update()
            .select_related("integration_config", "tenant")
            .get(pk=sync_job.pk, tenant_id=sync_job.tenant_id)
        )
        if not locked_job.is_enabled or locked_job.status == SyncJob.Status.DISABLED:
            raise ValidationError("Sync job is disabled.")

        if _has_expired_lease(locked_job, now):
            _recover_expired_lease(locked_job, now)

        cursor, _created = SyncCursor.objects.get_or_create(
            tenant=locked_job.tenant,
            sync_job=locked_job,
            cursor_key="default",
            defaults={"cursor_value": ""},
        )
        idempotency_key = idempotency_key or f"{locked_job.id}:{cursor.cursor_value or 'initial'}"
        existing = SyncRun.objects.filter(
            tenant=locked_job.tenant,
            sync_job=locked_job,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            return existing, False

        run_id = _run_id()
        lease_expires_at = now + _lease_duration()
        acquired = SyncJob.objects.filter(
            pk=locked_job.pk,
            is_enabled=True,
            status__in=(SyncJob.Status.IDLE, SyncJob.Status.FAILED),
        ).update(
            status=SyncJob.Status.RUNNING,
            last_run_at=now,
            next_run_at=None,
            lock_token=run_id,
            lock_acquired_at=now,
            lock_expires_at=lease_expires_at,
            lock_heartbeat_at=now,
            updated_at=now,
        )
        if not acquired:
            raise ValidationError("Sync job already has an active run.")

        run = SyncRun.objects.create(
            tenant=locked_job.tenant,
            sync_job=locked_job,
            run_id=run_id,
            idempotency_key=idempotency_key,
            status=SyncRun.Status.RUNNING,
            started_at=now,
        )
        locked_job.refresh_from_db()

    sync_job = locked_job

    last_retry_error = ""
    while True:
        try:
            _renew_lease(sync_job, run)
            with transaction.atomic():
                page = adapter.fetch_page(sync_job, cursor.cursor_value)
                records = page.get("records", [])
                for raw_record in records:
                    run.fetched_count += 1
                    normalized = adapter.normalize_record(raw_record)
                    if not adapter.validate_record(normalized):
                        run.failed_count += 1
                        continue
                    result = adapter.persist_record(sync_job, normalized)
                    if result.get("action") == "created":
                        run.created_count += 1
                    elif result.get("action") == "updated":
                        run.updated_count += 1
                    else:
                        run.skipped_count += 1

                cursor.cursor_value = adapter.get_next_cursor(page)
                cursor.save(update_fields=["cursor_value", "updated_at"])
                run.status = SyncRun.Status.SUCCESS
                run.finished_at = timezone.now()
                run.error_code = ""
                run.masked_error_message = ""
                run.masked_log = sanitize_payload(
                    {
                        "fetched": run.fetched_count,
                        "sample": records[:1],
                        "retry_count": run.retry_count,
                        "last_retry_error": last_retry_error,
                    }
                )
                sync_job.status = SyncJob.Status.IDLE
                sync_job.next_run_at = None
                sync_job.lock_token = ""
                sync_job.lock_expires_at = None
                sync_job.lock_heartbeat_at = timezone.now()
                sync_job.save(
                    update_fields=[
                        "status",
                        "next_run_at",
                        "lock_token",
                        "lock_expires_at",
                        "lock_heartbeat_at",
                        "updated_at",
                    ]
                )
                run.save()
                return run, True
        except Exception as exc:
            cursor.refresh_from_db()
            run.refresh_from_db()
            sync_job.refresh_from_db()
            last_retry_error = sanitize_text(str(exc))
            if run.retry_count < sync_job.max_retry_count:
                with transaction.atomic():
                    delay_seconds = calculate_backoff_seconds(
                        run.retry_count,
                        base_seconds=sync_job.backoff_base_seconds,
                    )
                    run.retry_count += 1
                    run.error_code = "RETRYABLE_ERROR"
                    run.masked_error_message = last_retry_error
                    run.masked_log = sanitize_payload(
                        {
                            "retry_count": run.retry_count,
                            "retry_delay_seconds": delay_seconds,
                            "error": last_retry_error,
                        }
                    )
                    sync_job.next_run_at = timezone.now() + timedelta(seconds=delay_seconds)
                    _renew_lease(sync_job, run, not_before=sync_job.next_run_at)
                    sync_job.save(update_fields=["next_run_at", "updated_at"])
                    run.save(
                        update_fields=[
                            "retry_count",
                            "error_code",
                            "masked_error_message",
                            "masked_log",
                        ]
                    )
                retry_wait(delay_seconds)
                cursor.refresh_from_db()
                run.refresh_from_db()
                sync_job.refresh_from_db()
                continue

            with transaction.atomic():
                run.error_code = "MAX_RETRY_EXCEEDED"
                run.masked_error_message = last_retry_error
                run.status = SyncRun.Status.FAILED
                run.failed_count += 1
                run.finished_at = timezone.now()
                run.masked_log = sanitize_payload(
                    {
                        "retry_count": run.retry_count,
                        "error": last_retry_error,
                    }
                )
                sync_job.status = SyncJob.Status.FAILED
                sync_job.next_run_at = None
                sync_job.lock_token = ""
                sync_job.lock_expires_at = None
                sync_job.lock_heartbeat_at = timezone.now()
                sync_job.save(
                    update_fields=[
                        "status",
                        "next_run_at",
                        "lock_token",
                        "lock_expires_at",
                        "lock_heartbeat_at",
                        "updated_at",
                    ]
                )
                run.save()
            return run, True


def record_retry_failure(sync_job, error_message, retry_count):
    run = SyncRun.objects.create(
        tenant=sync_job.tenant,
        sync_job=sync_job,
        run_id=_run_id(),
        idempotency_key=f"{sync_job.id}:retry:{retry_count}:{uuid.uuid4().hex}",
        status=SyncRun.Status.FAILED,
        started_at=timezone.now(),
        finished_at=timezone.now(),
        retry_count=retry_count,
        error_code="MAX_RETRY_EXCEEDED" if retry_count >= sync_job.max_retry_count else "RETRYABLE_ERROR",
        masked_error_message=sanitize_text(error_message),
        failed_count=1,
    )
    return run


def record_webhook_event(tenant, platform, event_id, event_type, payload, signature_status):
    payload_text = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"))
    payload_hash = hashlib.sha256(payload_text.encode()).hexdigest()
    event, created = WebhookEvent.objects.get_or_create(
        tenant=tenant,
        platform=platform,
        event_id=event_id,
        defaults={
            "event_type": event_type,
            "signature_status": signature_status,
            "payload_hash": payload_hash,
        },
    )
    if not created:
        event.processing_status = WebhookEvent.ProcessingStatus.DUPLICATE
        event.save(update_fields=["processing_status"])
    return event, created
