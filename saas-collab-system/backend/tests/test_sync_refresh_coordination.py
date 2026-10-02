from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.db import OperationalError
from django.utils import timezone

from apps.integrations import automatic_refresh
from apps.integrations.credential_coordination import WAIT_CODE, WAIT_TIMEOUT_SECONDS, wait_metadata
from apps.integrations.models import SyncCheckpoint, SyncCursor, SyncJob, SyncRun
from apps.integrations.sync_services import run_sync_job
from apps.integrations.tasks import run_readonly_sync_job
from tests.test_automatic_credential_refresh import due_warehouse
from tests.test_mock_sync_isolation import context
from tests.test_sync_runtime_budget import TwoPageAdapter

pytestmark = pytest.mark.django_db


def test_expired_queued_run_waits_without_rotating_or_fetching_and_resumes_same_key(monkeypatch):
    _, authorization = due_warehouse(monkeypatch)
    authorization.oauth_expires_at = timezone.now() - timedelta(minutes=1)
    authorization.save(update_fields=["oauth_expires_at"])
    job = SyncJob.objects.create(tenant=authorization.tenant, integration_config=authorization.integration_config,
                                warehouse_authorization=authorization, resource_type="inventory_snapshot")
    run = SyncRun.objects.create(tenant=authorization.tenant, sync_job=job, run_id="waiting-run",
                                idempotency_key="waiting-key", status="queued")
    with patch("apps.integrations.tasks.validate_manual_sync_job") as validation, patch(
        "apps.integrations.tasks.run_sync_job"
    ) as execution, patch("apps.integrations.warehouse_credential_service.refresh_warehouse_authorization") as rotation:
        result = run_readonly_sync_job.run(job.pk, "waiting-key")
        assert result["waiting_for_refresh"] is True
        validation.assert_not_called()
        execution.assert_not_called()
        rotation.assert_not_called()
    run.refresh_from_db()
    job.refresh_from_db()
    assert run.status == "queued" and run.error_code == WAIT_CODE and run.failed_count == 0
    assert run.masked_log["runtime_budget"]["sequence"] == 0 and job.status == "idle"

    authorization.oauth_expires_at = timezone.now() + timedelta(hours=24)
    authorization.save(update_fields=["oauth_expires_at"])
    run.status = "success"
    with patch("apps.integrations.tasks.validate_manual_sync_job") as validation, patch(
        "apps.integrations.tasks.run_sync_job", return_value=(run, True)
    ) as execution:
        result = run_readonly_sync_job.run(job.pk, "waiting-key", resume_sequence=0)
    assert result["status"] == "success"
    assert execution.call_args.kwargs["idempotency_key"] == "waiting-key"
    validation.assert_called_once()
    assert SyncRun.objects.filter(sync_job=job).count() == 1


def test_page_boundary_releases_lease_without_losing_committed_cursor(context):
    _, job = context
    job.sync_scope = {"schedule": {"execution_budget_seconds": 60}}
    job.save(update_fields=["sync_scope"])
    adapter = TwoPageAdapter()
    with patch("apps.integrations.credential_coordination.job_refresh_wait", side_effect=[None, {"state": "due"}]), patch(
        "apps.integrations.sync_services.monotonic", return_value=0
    ):
        run, _ = run_sync_job(job, adapter=adapter, idempotency_key="boundary-renewal")
    job.refresh_from_db()
    assert adapter.cursors == [""]
    assert run.status == "queued" and run.error_code == WAIT_CODE and run.fetched_count == 1
    assert run.masked_log["renewal_wait"]["active"] is True
    assert SyncCursor.objects.get(sync_job=job).cursor_value == "p1"
    assert job.status == "idle" and not job.lock_token and job.lock_expires_at is None
    assert not SyncCheckpoint.objects.filter(sync_job=job).exists()

    resumed_adapter = TwoPageAdapter()
    with patch("apps.integrations.credential_coordination.job_refresh_wait", return_value=None):
        completed, _ = run_sync_job(job, adapter=resumed_adapter, idempotency_key="boundary-renewal", resume_sequence=1)
    assert completed.pk == run.pk and completed.status == "success" and completed.fetched_count == 2
    assert resumed_adapter.cursors == ["p1"]
    assert completed.masked_log["renewal_wait"]["active"] is False
    assert SyncCheckpoint.objects.get(sync_job=job).version == 1


def test_wait_timeout_is_bounded_and_never_resets_active_wait():
    now = timezone.now()
    prior = {"active": True, "started_at": (now - timedelta(seconds=WAIT_TIMEOUT_SECONDS)).isoformat()}
    with patch("apps.integrations.credential_coordination.timezone.now", return_value=now):
        assert wait_metadata(prior) is None
        recent = {"active": True, "started_at": (now - timedelta(seconds=60)).isoformat()}
        assert wait_metadata(recent)["started_at"] == recent["started_at"]


@pytest.mark.parametrize("enabled,state,expired,health,schedule,reason", [
    (True, "due", False, "authorization", "queued", "等待自动续期"),
    (True, "not_due", False, "healthy", "queued", "授权已更新"),
    (True, "manual_recovery", True, "authorization", "blocked", "需人工处理"),
    (False, "manual_recovery", True, "disabled", "disabled", "授权已过期"),
])
def test_workspace_renewal_wait_separates_current_state_and_schedule(monkeypatch, enabled, state, expired, health, schedule, reason):
    from apps.integrations.workspace_service import _job_row

    _, authorization = due_warehouse(monkeypatch)
    config = authorization.integration_config
    config.status, config.credential_status = "verified", "verified"
    job = SyncJob.objects.create(tenant=authorization.tenant, integration_config=config,
                                warehouse_authorization=authorization, resource_type="inventory_snapshot", is_enabled=enabled)
    run = SyncRun.objects.create(tenant=authorization.tenant, sync_job=job, run_id="metadata-run",
                                idempotency_key="metadata-key", status="queued", error_code=WAIT_CODE)
    refresh = {"state": state, "expired": expired, "requires_manual_recovery": state == "manual_recovery"}
    with patch("apps.integrations.workspace_service.credential_refresh_state", return_value=refresh), patch(
        "apps.integrations.workspace_service.get_runtime_setting", return_value=True
    ), patch("apps.integrations.workspace_service.sync_source_health", return_value={"state": "not_required"}):
        row = _job_row(job, {}, {"authorization_status": "active", "subject_type": "warehouse"}, run)
    assert row["health_state"] == health
    assert row["schedule_state"] == schedule
    assert reason in row["blocked_reason"]


@pytest.mark.parametrize("errno", [1205, 1213])
def test_mysql_lock_retry_uses_cached_page_and_rolls_back_raw_counts_cursor_checkpoint(context, monkeypatch, errno):
    _, job = context
    job.max_retry_count = 0  # DB lock retries have their own bounded page policy
    job.save(update_fields=["max_retry_count"])
    adapter = TwoPageAdapter()
    original_save = SyncRun.save
    failed = False

    def fail_after_cursor_saved(record, *args, **kwargs):
        nonlocal failed
        if record.status == "success" and not failed:
            failed = True
            raise OperationalError(errno, "SYNTHETIC_SECRET_MUST_NOT_BE_LOGGED")
        return original_save(record, *args, **kwargs)

    monkeypatch.setattr(SyncRun, "save", fail_after_cursor_saved)
    run, _ = run_sync_job(job, adapter=adapter, idempotency_key=f"db-lock-{errno}", retry_wait=lambda _delay: None)
    assert run.status == "success" and run.retry_count == 1
    assert adapter.cursors == ["", "p1"]  # no second provider request for rollback
    assert run.fetched_count == run.created_count == 2
    assert run.raw_envelopes.count() == 2
    assert list(run.raw_envelopes.order_by("sequence").values_list("cursor", flat=True)) == ["", "p1"]
    assert SyncCursor.objects.get(sync_job=job).cursor_value == "p2"
    assert SyncCheckpoint.objects.get(sync_job=job).version == 1
    assert "SYNTHETIC_SECRET" not in str(run.masked_log)


def test_mysql_lock_exhaustion_is_bounded_without_cursor_or_raw_commit(context):
    _, job = context
    adapter = TwoPageAdapter()
    persist = Mock(side_effect=OperationalError(1213, "synthetic deadlock"))
    adapter.persist_record = persist
    run, _ = run_sync_job(job, adapter=adapter, idempotency_key="db-lock-exhausted", retry_wait=lambda _delay: None)
    assert run.status == "failed" and run.error_code == "MYSQL_LOCK_RETRY_EXHAUSTED"
    assert run.retry_count == 3 and persist.call_count == 4 and adapter.cursors == [""]
    assert run.fetched_count == 0 and run.raw_envelopes.count() == 0
    assert SyncCursor.objects.get(sync_job=job).cursor_value == ""
    assert not SyncCheckpoint.objects.filter(sync_job=job).exists()


def test_sync_still_fences_rotation_while_a_page_is_running(monkeypatch):
    _, record = due_warehouse(monkeypatch)
    job = SyncJob.objects.create(tenant=record.tenant, integration_config=record.integration_config,
                                warehouse_authorization=record, resource_type="inventory_snapshot")
    SyncRun.objects.create(tenant=record.tenant, sync_job=job, status="running")
    assert not automatic_refresh.automatic_refresh_allowed(record)
    assert automatic_refresh.automatic_refresh_allowed(record, ignore_running=True)
