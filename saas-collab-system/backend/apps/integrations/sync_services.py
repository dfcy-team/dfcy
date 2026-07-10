import hashlib
import json
import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .adapters import MockPlatformAdapter, get_adapter_for_config
from .models import SyncCursor, SyncJob, SyncRun, WebhookEvent
from .security import sanitize_payload, sanitize_text


def calculate_backoff_seconds(retry_count, base_seconds=1, max_seconds=300):
    return min(max_seconds, base_seconds * (2**retry_count))


def _run_id():
    return uuid.uuid4().hex


def run_sync_job(sync_job, adapter=None, idempotency_key=None):
    if not sync_job.is_enabled or sync_job.status == SyncJob.Status.DISABLED:
        raise ValidationError("Sync job is disabled.")

    adapter = adapter or get_adapter_for_config(sync_job.integration_config)
    if not isinstance(adapter, MockPlatformAdapter):
        raise ValidationError("Only mock synchronization can be executed by this endpoint in phase 2.")

    cursor, _created = SyncCursor.objects.get_or_create(
        tenant=sync_job.tenant,
        sync_job=sync_job,
        cursor_key="default",
        defaults={"cursor_value": ""},
    )
    idempotency_key = idempotency_key or f"{sync_job.id}:{cursor.cursor_value or 'initial'}"
    existing = SyncRun.objects.filter(tenant=sync_job.tenant, idempotency_key=idempotency_key).first()
    if existing:
        return existing, False

    now = timezone.now()
    with transaction.atomic():
        run = SyncRun.objects.create(
            tenant=sync_job.tenant,
            sync_job=sync_job,
            run_id=_run_id(),
            idempotency_key=idempotency_key,
            status=SyncRun.Status.RUNNING,
            started_at=now,
        )
        sync_job.status = SyncJob.Status.RUNNING
        sync_job.last_run_at = now
        sync_job.save(update_fields=["status", "last_run_at", "updated_at"])

        try:
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
            run.masked_log = sanitize_payload({"fetched": run.fetched_count, "sample": records[:1]})
            sync_job.status = SyncJob.Status.IDLE
            sync_job.save(update_fields=["status", "updated_at"])
            run.save()
            return run, True
        except Exception as exc:
            run.retry_count += 1
            run.error_code = exc.__class__.__name__
            run.masked_error_message = sanitize_text(str(exc))
            run.status = SyncRun.Status.FAILED if run.retry_count >= sync_job.max_retry_count else SyncRun.Status.FAILED
            run.finished_at = timezone.now()
            run.masked_log = sanitize_payload({"error": run.masked_error_message})
            sync_job.status = SyncJob.Status.FAILED
            sync_job.save(update_fields=["status", "updated_at"])
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
