from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.integrations.models import SyncRun, SyncScheduleDispatch
from apps.integrations.sync_delivery import DeliverySnapshot
from apps.integrations.sync_run_maintenance import archive_invalid_runs, preview_invalid_runs, visible_runs
from apps.integrations.tasks import dispatch_due_readonly_sync_jobs, run_readonly_sync_job
from tests.test_history_sync_batches import ctx, create
from tests.test_phase2_sync_framework import authenticated_client

pytestmark = pytest.mark.django_db


def empty_queue(job, key="invalid-empty"):
    then = timezone.now() - timedelta(days=3)
    return SyncRun.objects.create(tenant=job.tenant, sync_job=job, run_id=key, idempotency_key=key,
                                  status="queued", enqueued_at=then, finished_at=then)


def test_history_get_task_filter_does_not_authorize_controls_on_multi_job_batch(ctx):
    user, job, _ = ctx
    from apps.integrations.models import SyncJob
    other = SyncJob.objects.create(tenant=job.tenant, integration_config=job.integration_config,
        store_authorization=job.store_authorization, resource_type="refund_return", is_enabled=True)
    batch = create(user, [job, other])
    response = authenticated_client(user).get(f"/api/internal/integrations/history-batches/?sync_job_id={job.pk}")
    assert response.status_code == 200
    rows = response.data["data"]["batches"]
    assert len(rows) == 1 and rows[0]["id"] == batch.pk
    assert [shop["job_id"] for shop in rows[0]["shops"]] == [job.pk]
    assert rows[0]["task_action_allowed"] is False


def test_history_task_filter_rejects_bad_ids_and_does_not_leak_other_task(ctx):
    user, job, _ = ctx
    create(user, [job])
    client = authenticated_client(user)
    assert client.get("/api/internal/integrations/history-batches/?sync_job_id=bad").status_code == 400
    response = client.get("/api/internal/integrations/history-batches/?sync_job_id=99999999")
    assert response.status_code == 200
    assert response.data["data"]["batches"] == []


def test_legacy_message_is_relayed_without_provider_work_or_new_run(ctx):
    user, job, _ = ctx
    batch = create(user, [job])
    segment = batch.segments.first()
    key = f"history:{segment.pk}:{segment.attempt}"
    SyncRun.objects.create(tenant=job.tenant, sync_job=job, history_segment=segment,
                          run_id="legacy-route", idempotency_key=key, status="queued")
    with patch.object(run_readonly_sync_job, "apply_async") as relay, patch("apps.integrations.tasks.run_sync_job") as provider:
        run_readonly_sync_job.push_request(delivery_info={"routing_key": "sync"})
        try:
            result = run_readonly_sync_job.run(job.pk, key)
        finally:
            run_readonly_sync_job.pop_request()
    assert result["status"] == "rerouted" and result["queue"] == "sync-history"
    assert relay.call_args.kwargs["queue"] == "sync-history"
    assert relay.call_args.kwargs["kwargs"]["idempotency_key"] == key
    provider.assert_not_called()
    assert SyncRun.objects.count() == 1


def test_history_receives_own_tick_budget_after_daily_budget_is_spent():
    with patch("apps.integrations.tasks.dispatch_due_jobs", return_value={"dispatched": 20, "failed": 0, "skipped": 0}), \
         patch("apps.integrations.sync_delivery.read_delivery_snapshot", return_value=DeliverySnapshot(complete=True)), \
         patch("apps.integrations.history_sync.dispatch_history_segments", return_value=1) as history:
        result = dispatch_due_readonly_sync_jobs(limit=20)
    assert history.call_args.kwargs["limit"] == 2
    assert history.call_args.kwargs["admission"].remaining == 2
    assert result["history_submitted"] == 1


def test_empty_finished_queue_preview_and_archive_preserve_audit_and_idempotency(ctx):
    _, job, _ = ctx
    row = empty_queue(job)
    cutoff = timezone.now() - timedelta(days=1)
    snapshot = DeliverySnapshot(complete=True)
    plan = preview_invalid_runs(job.tenant_id, cutoff, snapshot)
    assert plan["candidate_count"] == 1 and plan["deleted_count"] == 0
    with patch("apps.integrations.sync_run_maintenance.read_delivery_snapshot", return_value=snapshot):
        result = archive_invalid_runs(job.tenant_id, cutoff, plan["plan_sha256"])
    row.refresh_from_db()
    assert result["archived_count"] == 1 and result["deleted_count"] == 0
    assert row.status == "cancelled" and row.idempotency_key == "invalid-empty"
    assert row.masked_log["invalid_queue_archive"]["original_status"] == "queued"
    assert SyncRun.objects.filter(pk=row.pk).exists()
    assert not visible_runs(SyncRun.objects.all()).exists()


@pytest.mark.parametrize("change", ["started", "has_data", "failure", "ordinary_pending", "continuation", "broker_present", "broker_unknown", "job_running"])
def test_cleanup_never_removes_valid_or_ambiguous_records(ctx, change):
    _, job, _ = ctx
    row = empty_queue(job)
    snapshot = DeliverySnapshot(complete=True)
    if change == "started": row.started_at = row.enqueued_at
    elif change == "has_data": row.fetched_count = 1
    elif change == "failure": row.status = "failed"
    elif change == "ordinary_pending": row.finished_at = None
    elif change == "continuation": row.masked_log = {"runtime_budget": {"pending": True}}
    elif change == "broker_present": snapshot.fences.add((job.pk, row.idempotency_key, 0))
    elif change == "broker_unknown": snapshot.complete = False
    elif change == "job_running": job.status = "running"; job.save()
    row.save()
    result = preview_invalid_runs(job.tenant_id, timezone.now() - timedelta(days=1), snapshot)
    assert result["candidate_count"] == 0
    assert SyncRun.objects.filter(pk=row.pk).exists()


def test_history_and_scheduled_queue_rows_are_never_cleanup_candidates(ctx):
    user, job, _ = ctx
    batch = create(user, [job])
    history = empty_queue(job, "protected-history")
    history.history_segment = batch.segments.first()
    history.save()
    scheduled = empty_queue(job, "protected-scheduled")
    SyncScheduleDispatch.objects.create(tenant=job.tenant, sync_job=job, scheduled_at=scheduled.enqueued_at, sync_run=scheduled)
    result = preview_invalid_runs(job.tenant_id, timezone.now() - timedelta(days=1), DeliverySnapshot(complete=True))
    assert result["candidate_count"] == 0
    assert SyncRun.objects.count() == 2


def test_archive_rejects_drift_and_unknown_broker_without_writes(ctx):
    _, job, _ = ctx
    row = empty_queue(job)
    cutoff = timezone.now() - timedelta(days=1)
    with patch("apps.integrations.sync_run_maintenance.read_delivery_snapshot", return_value=DeliverySnapshot(complete=True)):
        plan = preview_invalid_runs(job.tenant_id, cutoff)
        row.masked_log = {"runtime_budget": {"pending": True}}
        row.save()
        with pytest.raises(ValidationError):
            archive_invalid_runs(job.tenant_id, cutoff, plan["plan_sha256"])
    row.refresh_from_db()
    assert row.status == "queued"
