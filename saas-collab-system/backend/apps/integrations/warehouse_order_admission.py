"""Serialize scheduled and manual admission to the single warehouse consumer."""
from django.utils import timezone

from .models import SyncRun, SyncScheduleDispatch, SyncSchedulerHeartbeat


def warehouse_slot_available(job, *, idempotency_key=None, dispatch_id=None):
    """Caller must hold its transaction until its queued/run row is committed."""
    SyncSchedulerHeartbeat.objects.get_or_create(key='admission:warehouse',
                                                 defaults={'last_seen_at': timezone.now()})
    SyncSchedulerHeartbeat.objects.select_for_update().get(key='admission:warehouse')
    active = SyncRun.objects.filter(sync_job__resource_type='warehouse_order_lookup',
        sync_job__is_enabled=True, status__in=['queued', 'running'])
    if idempotency_key:
        active = active.exclude(sync_job_id=job.pk, idempotency_key=idempotency_key)
    if active.exists():
        return False
    dispatches = SyncScheduleDispatch.objects.filter(sync_job__resource_type='warehouse_order_lookup',
        sync_job__is_enabled=True, status__in=['queued', 'running'], sync_run__isnull=True)
    if dispatch_id:
        dispatches = dispatches.exclude(pk=dispatch_id)
    return not dispatches.exists()
