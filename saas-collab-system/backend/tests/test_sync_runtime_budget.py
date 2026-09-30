from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from apps.integrations.adapters import MockPlatformAdapter
from apps.integrations.models import SyncCheckpoint, SyncCursor, SyncRun, SyncScheduleDispatch
from apps.integrations.scheduler import dispatch_due_jobs, resume_due_sync_runs
from apps.integrations.sync_services import run_sync_job
from apps.integrations.tasks import run_readonly_sync_job
from tests.test_mock_sync_isolation import context

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 9, 30, tzinfo=UTC)


class TwoPageAdapter(MockPlatformAdapter):
    """Fixed pages make cursor and persisted-count assertions deterministic."""

    def __init__(self, scope=None):
        self.scope = scope or {"time_from": "frozen-from", "time_to": "frozen-to"}
        self.cursors = []

    def fetch_page(self, sync_job, cursor_value=None):
        self.cursors.append(cursor_value)
        if cursor_value in (None, ""):
            return {"records": [{"external_id": "slice-1", "name": "one"}], "next_cursor": "p1"}
        if cursor_value == "p1":
            return {"records": [{"external_id": "slice-2", "name": "two"}], "next_cursor": "p2"}
        return {"records": [], "next_cursor": "p2"}

    def should_continue(self, page, previous_cursor):
        return page["next_cursor"] != previous_cursor and page["next_cursor"] != "p2"

    def persist_record(self, sync_job, record):
        return {"action": "created", "idempotency_key": record["external_id"]}


def setup_budget_job(context):
    _, job = context
    job.sync_scope = {"schedule": {"execution_budget_seconds": 60}, "query": {"time_from": "initial"}}
    job.save(update_fields=["sync_scope"])
    return job


def test_sliced_run_resumes_same_run_cursor_counts_scope_and_only_finalizes_checkpoint(context):
    job = setup_budget_job(context)
    adapter = TwoPageAdapter()
    with patch("apps.integrations.sync_services.timezone.now", return_value=NOW), patch(
        "apps.integrations.sync_services.monotonic", side_effect=[0, 61]
    ):
        first, created = run_sync_job(job, adapter=adapter, idempotency_key="slice-key")
    assert created and first.status == SyncRun.Status.QUEUED
    first.refresh_from_db()
    cursor = SyncCursor.objects.get(sync_job=job)
    assert first.fetched_count == first.created_count == 1
    assert cursor.cursor_value == "p1"
    assert not SyncCheckpoint.objects.filter(sync_job=job).exists()
    assert first.masked_log["runtime_budget"]["sequence"] == 1
    assert first.masked_log["runtime_budget"]["resolved_scope"] == adapter.scope

    later = NOW + timedelta(days=1, minutes=2)
    resumed_adapter = TwoPageAdapter({"time_from": "changed-after-midnight", "time_to": "changed-window"})
    with patch("apps.integrations.sync_services.timezone.now", return_value=later), patch(
        "apps.integrations.sync_services.monotonic", return_value=0
    ):
        resumed, created = run_sync_job(job, adapter=resumed_adapter, idempotency_key="slice-key", resume_sequence=1)
    resumed.refresh_from_db()
    cursor.refresh_from_db()
    checkpoint = SyncCheckpoint.objects.get(sync_job=job)
    assert resumed.pk == first.pk and resumed.run_id == first.run_id and created
    assert adapter.cursors == [""] and resumed_adapter.cursors == ["p1"]
    assert resumed.fetched_count == resumed.created_count == 2
    assert cursor.cursor_value == "p2"
    assert resumed.status == SyncRun.Status.SUCCESS
    assert resumed.started_at == first.started_at
    assert checkpoint.cursor_json == {"default": "p2"} and checkpoint.last_success_run_id == resumed.id
    assert resumed_adapter.scope == {"time_from": "frozen-from", "time_to": "frozen-to"}


def test_scheduled_slice_resumes_through_task_and_keeps_dispatch_run_link(context):
    job = setup_budget_job(context)
    job.schedule_type = "interval"
    job.sync_scope["schedule"]["interval_minutes"] = 60
    job.next_run_at = NOW
    job.save(update_fields=["schedule_type", "sync_scope", "next_run_at"])
    queued = Mock()
    dispatch_due_jobs(queued, now=NOW)
    key = queued.call_args.args[1]
    dispatch = SyncScheduleDispatch.objects.get(sync_job=job)
    adapters = [
        TwoPageAdapter(),
        TwoPageAdapter({"time_from": "next-day-window", "time_to": "new-end"}),
    ]
    real_run = run_sync_job

    def execute(_job, **kwargs):
        return real_run(_job, adapter=adapters.pop(0), **kwargs)

    with patch("apps.integrations.tasks.validate_manual_sync_job"), patch(
        "apps.integrations.tasks.run_sync_job", side_effect=execute
    ), patch("apps.integrations.sync_services.timezone.now", return_value=NOW), patch(
        "apps.integrations.sync_services.monotonic", side_effect=[0, 61, 0]
    ):
        first = run_readonly_sync_job.run(job.id, key, resume_sequence=0)
        run = SyncRun.objects.get(sync_job=job, idempotency_key=key)
        started_at = run.started_at
        dispatch.refresh_from_db()
        assert first["status"] == SyncRun.Status.QUEUED
        assert dispatch.status == "queued" and dispatch.sync_run_id == run.id

        second = run_readonly_sync_job.run(job.id, key, resume_sequence=1)
        duplicate = run_readonly_sync_job.run(job.id, key, resume_sequence=1)

    run.refresh_from_db()
    dispatch.refresh_from_db()
    assert second["status"] == SyncRun.Status.SUCCESS
    assert duplicate == {"status": "not_executed", "created": False}
    assert run.id == dispatch.sync_run_id and run.started_at == started_at
    assert run.fetched_count == run.created_count == 2
    assert run.status == dispatch.status == "success"
    assert SyncRun.objects.filter(sync_job=job, idempotency_key=key).count() == 1
    assert SyncScheduleDispatch.objects.filter(sync_job=job).count() == 1


def test_outbox_retry_keeps_committed_progress_and_stale_redelivery_is_fenced(context):
    job = setup_budget_job(context)
    adapter = TwoPageAdapter()
    with patch("apps.integrations.sync_services.timezone.now", return_value=NOW), patch(
        "apps.integrations.sync_services.monotonic", side_effect=[0, 61]
    ):
        run, _ = run_sync_job(job, adapter=adapter, idempotency_key="outbox-key")
    run.refresh_from_db()
    assert run.status == SyncRun.Status.QUEUED and run.fetched_count == 1
    assert SyncCursor.objects.get(sync_job=job).cursor_value == "p1"

    enqueue = Mock(side_effect=RuntimeError("broker unavailable"))
    at = NOW + timedelta(minutes=2)
    assert resume_due_sync_runs(enqueue, now=at) == 0
    run.refresh_from_db()
    assert run.masked_log["runtime_budget"]["pending"] is True
    assert run.masked_log["runtime_budget"]["sequence"] == 1
    assert run.fetched_count == 1 and SyncCursor.objects.get(sync_job=job).cursor_value == "p1"

    retry = Mock()
    assert resume_due_sync_runs(retry, now=at + timedelta(minutes=4)) == 1
    assert retry.call_args.args == (job.id, "outbox-key", 1)
    stale = run_readonly_sync_job.run(job.id, "outbox-key", resume_sequence=0)
    assert stale["status"] == "not_executed"
    assert adapter.cursors == [""]
    run.refresh_from_db()
    assert run.fetched_count == 1 and SyncCursor.objects.get(sync_job=job).cursor_value == "p1"


def test_soft_time_limit_fails_without_retry_and_keeps_committed_cursor(context):
    job = setup_budget_job(context)

    class TimedAdapter(TwoPageAdapter):
        def fetch_page(self, sync_job, cursor_value=None):
            if cursor_value == "p1":
                raise SoftTimeLimitExceeded()
            return super().fetch_page(sync_job, cursor_value)

    run, created = run_sync_job(job, adapter=TimedAdapter(), idempotency_key="soft-timeout")
    job.refresh_from_db()
    cursor = SyncCursor.objects.get(sync_job=job)
    assert created and run.status == SyncRun.Status.FAILED
    assert run.retry_count == 0 and run.error_code == "RUN_TIMEOUT"
    assert run.fetched_count == 1 and cursor.cursor_value == "p1"
    assert job.status == "failed" and not job.lock_token and job.lock_expires_at is None

