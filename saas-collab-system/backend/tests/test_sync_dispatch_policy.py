from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.utils import timezone

from apps.integrations.models import (
    HistorySyncBatch,
    HistorySyncSegment,
    SyncJob,
    SyncRun,
    SyncSchedulerHeartbeat,
)
from apps.integrations.scheduler import dispatch_due_jobs
from apps.integrations.sync_dispatch_policy import (
    DispatchAdmission,
    execution_lane,
    fair_job_ids,
    queue_for_run,
)
from apps.integrations.sync_delivery import DeliverySnapshot
from tests.test_shopee_tiktok_finance_ingestion import _finance_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def context():
    tenant, _store, config, authorization, job, run = _finance_scope("shopee")
    run.delete()
    job.resource_type = SyncJob.ResourceType.SALES_ORDER
    job.save(update_fields=["resource_type"])
    return tenant, config, authorization, job


def another_job(context, resource, *, store_authorization=True, **kwargs):
    tenant, config, authorization, _ = context
    return SyncJob.objects.create(
        tenant=tenant,
        integration_config=config,
        store_authorization=authorization if store_authorization else None,
        resource_type=resource,
        **kwargs,
    )


def test_resource_rotation_serves_finance_before_low_id_backlog(context):
    _tenant, _config, _authorization, oldest_sales_job = context
    sales_jobs = [oldest_sales_job] + [
        another_job(context, SyncJob.ResourceType.SALES_ORDER, store_authorization=False) for _ in range(4)
    ]
    finance_job = another_job(context, SyncJob.ResourceType.SETTLEMENT_BILL)
    now = timezone.now()
    SyncSchedulerHeartbeat.objects.create(key="fair:daily:sales_order", last_seen_at=now)
    SyncSchedulerHeartbeat.objects.create(
        key="fair:daily:settlement_bill", last_seen_at=now - timedelta(minutes=1)
    )

    ordered = fair_job_ids(SyncJob.objects.filter(pk__in=[j.pk for j in sales_jobs + [finance_job]]), "daily", 1)

    assert ordered[0] == finance_job.pk
    assert oldest_sales_job.pk in ordered


def test_fair_rotation_uses_resource_fifo(context):
    first = context[3]
    second = another_job(context, SyncJob.ResourceType.SALES_ORDER, store_authorization=False)
    other = another_job(context, SyncJob.ResourceType.REFUND_RETURN)
    queryset = SyncJob.objects.filter(pk__in=[first.pk, second.pk, other.pk])

    ordered = fair_job_ids(queryset, "history", 2)

    assert ordered.index(first.pk) < ordered.index(second.pk)
    assert set(ordered) == {first.pk, second.pk, other.pk}


def test_admission_enforces_lane_capacity_tick_budget_and_subject(context):
    first = context[3]
    same_store = another_job(context, SyncJob.ResourceType.REFUND_RETURN)
    second_store = another_job(context, SyncJob.ResourceType.SETTLEMENT_BILL)
    admission = DispatchAdmission(DeliverySnapshot(complete=True), timezone.now(), limit=2)

    assert admission.claim(first, "daily")
    assert not admission.claim(same_store, "daily")
    assert admission.claim(first, "history")
    assert not admission.claim(second_store, "history")  # per-lane cap is two, global budget is spent
    assert admission.summary()["remaining_tick_budget"] == 0


def test_admission_treats_present_broker_run_as_occupied(context):
    job = context[3]
    key = "queued-on-broker"
    SyncRun.objects.create(
        tenant=job.tenant,
        sync_job=job,
        run_id="present-run",
        idempotency_key=key,
        status="queued",
        enqueued_at=timezone.now() - timedelta(hours=1),
    )
    snapshot = DeliverySnapshot(fences={(job.pk, key, 0)}, complete=True)

    admission = DispatchAdmission(snapshot, timezone.now(), limit=10)

    assert admission.summary()["daily_slots_occupied"] == 1
    assert not admission.claim(job, "daily")


def test_admission_enforces_two_inflight_slots_per_lane(context):
    first = context[3]
    second = another_job(context, SyncJob.ResourceType.REFUND_RETURN)
    third = another_job(context, SyncJob.ResourceType.SETTLEMENT_BILL)
    second.store_authorization = None
    second.save(update_fields=["store_authorization"])
    third.store_authorization = None
    third.save(update_fields=["store_authorization"])
    admission = DispatchAdmission(DeliverySnapshot(complete=True), timezone.now(), limit=10)

    assert admission.claim(first, "daily")
    assert admission.claim(second, "daily")
    assert not admission.claim(third, "daily")
    assert admission.claim(third, "history")


def test_history_lane_and_queue_require_actual_segment_relation(context):
    job = context[3]
    now = timezone.now()
    batch = HistorySyncBatch.objects.create(
        tenant=job.tenant,
        created_by=job.integration_config.created_by,
        name="Synthetic history",
        idempotency_key="dispatch-policy-history",
        request_hash="synthetic",
        start_date=now.date(),
        end_date=now.date(),
        status="running",
    )
    segment = HistorySyncSegment.objects.create(
        batch=batch, sync_job=job, sequence=1, scope={}, status="queued", submitted_at=now,
    )
    linked = SyncRun.objects.create(
        tenant=job.tenant, sync_job=job, history_segment=segment, run_id="history-linked",
        idempotency_key="caller-daily-looking-key", status="queued", enqueued_at=now,
    )
    unlinked = SyncRun.objects.create(
        tenant=job.tenant, sync_job=job, run_id="daily-unlinked",
        idempotency_key="history:fake-prefix", status="queued", enqueued_at=now,
    )

    assert execution_lane(linked) == "history"
    assert execution_lane(unlinked) == "daily"
    assert queue_for_run(job.pk, linked.idempotency_key) == "sync-history"
    assert queue_for_run(job.pk, unlinked.idempotency_key) == "sync"


def test_scheduler_capacity_wait_preserves_due_slot_after_misfire(context):
    job = context[3]
    due = timezone.now() - timedelta(minutes=5)
    job.schedule_type = SyncJob.ScheduleType.INTERVAL
    job.sync_scope = {"schedule": {"interval_minutes": 60}}
    job.next_run_at = due
    job.save(update_fields=["schedule_type", "sync_scope", "next_run_at"])
    admission = Mock()
    admission.claim.return_value = False

    first = dispatch_due_jobs(Mock(), now=due + timedelta(minutes=1), admission=admission)

    job.refresh_from_db()
    assert first["dispatched"] == first["skipped"] == 0
    assert job.next_run_at == due
    assert SyncSchedulerHeartbeat.objects.get(key=f"capacity:{job.pk}").last_seen_at == due

    admission.claim.return_value = True
    enqueue = Mock()
    second = dispatch_due_jobs(enqueue, now=due + timedelta(minutes=6), admission=admission)

    job.refresh_from_db()
    assert second["dispatched"] == 1 and second["skipped"] == 0
    assert enqueue.called
    assert job.next_run_at > due


def test_control_tick_finance_due_competes_with_order_continuation(context):
    from apps.integrations.tasks import dispatch_due_readonly_sync_jobs, run_readonly_sync_job
    job = context[3]
    now = timezone.now()
    pending = SyncRun.objects.create(tenant=job.tenant, sync_job=job, run_id="long-order",
        idempotency_key="long-order", status="queued", masked_log={"runtime_budget": {
            "pending": True, "sequence": 3, "ready_at": (now - timedelta(minutes=1)).isoformat(),
            "submitted_at": (now - timedelta(minutes=5)).isoformat(), "resolved_scope": {"time_from": 1, "time_to": 2}}})
    finance = another_job(context, SyncJob.ResourceType.SETTLEMENT_BILL, schedule_type="interval",
                          next_run_at=now, sync_scope={"schedule": {"interval_minutes": 60}})
    SyncSchedulerHeartbeat.objects.create(key="fair:daily:sales_order", last_seen_at=now)
    with patch("apps.integrations.sync_delivery.read_delivery_snapshot", return_value=DeliverySnapshot(complete=True)), \
            patch.object(run_readonly_sync_job, "apply_async") as enqueue:
        result = dispatch_due_readonly_sync_jobs.run(limit=1)
    assert enqueue.call_count == 1
    assert enqueue.call_args.kwargs["args"] == (finance.pk,)
    assert enqueue.call_args.kwargs["queue"] == "sync"
    assert result["dispatched"] == 1 and result["continued"] == result["history_submitted"] == 0
    pending.refresh_from_db()
    assert pending.masked_log["runtime_budget"]["sequence"] == 3


@pytest.mark.parametrize("complete,expected", [(False, 1), (True, 0)])
def test_old_submitted_continuation_requires_confirmed_absence_for_admission(context, complete, expected):
    job = context[3]
    now = timezone.now()
    SyncRun.objects.create(tenant=job.tenant, sync_job=job, run_id="old-submitted",
        idempotency_key="old-submitted", status="queued", masked_log={"runtime_budget": {
            "pending": True, "sequence": 2, "submitted_at": (now - timedelta(hours=1)).isoformat()}})
    admission = DispatchAdmission(DeliverySnapshot(complete=complete), now, limit=2)
    assert admission.summary()["daily_slots_occupied"] == expected
    assert not SyncSchedulerHeartbeat.objects.filter(key=f"capacity:{job.pk}").exists()
