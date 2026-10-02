from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.integrations.history_sync import batch_action, create_history_batch, dispatch_history_segments, batch_data
from apps.integrations.models import HistorySyncBatch, HistorySyncSegment, SyncJob, SyncRun, SyncCursor, SyncCheckpoint
from apps.integrations.scheduler import dispatch_due_jobs, resume_due_sync_runs
from apps.integrations.sync_services import enqueue_sync_run, run_sync_job
from apps.integrations.tasks import run_readonly_sync_job
from apps.permissions.models import Permission, Role, UserRole, DataScope
from tests.test_phase2_sync_framework import authenticated_client
from tests.test_shopee_tiktok_finance_ingestion import _finance_scope
from tests.test_sync_runtime_budget import TwoPageAdapter

pytestmark = pytest.mark.django_db


def test_history_permission_migration_matches_runtime_catalog():
    from importlib import import_module
    from django.apps import apps
    from apps.permissions.catalog import permission_defaults, runtime_permission_definitions

    migration = import_module("apps.permissions.migrations.0050_register_history_sync_permissions")
    migration.register(apps, None)
    definitions = {row["code"]: row for row in runtime_permission_definitions()}
    for code in ["integrations.history.view", "integrations.history.manage"]:
        permission = Permission.objects.get(code=code)
        for field, expected in permission_defaults(definitions[code]).items():
            assert getattr(permission, field) == expected, (code, field)


@pytest.fixture
def ctx():
    tenant, store, config, auth, job, run = _finance_scope("shopee")
    run.delete()
    user = config.created_by
    role = Role.objects.create(tenant=tenant, code="history-admin", name="history-admin")
    role.permissions.add(*Permission.objects.filter(code__in=["integrations.history.view", "integrations.history.manage", "integrations.run_live_readonly"]))
    UserRole.objects.create(tenant=tenant, role=role, user=user)
    DataScope.objects.create(tenant=tenant, role=role, scope_type="all", config={})
    job.sync_scope = {"schedule": {"execution_budget_seconds": 480}, "query": {"mode": "incremental", "lookback_days": 1}}
    job.save()
    return user, job, role


def payload(jobs, key="history-create"):
    return {"name": "History", "job_ids": [job.pk for job in jobs], "start_date": "2025-10-01", "end_date": "2026-01-31", "idempotency_key": key}


def create(user, jobs, key="history-create"):
    with patch("apps.integrations.history_sync.validate_manual_sync_job"):
        return create_history_batch(user, payload(jobs, key))


def execute(job, segment, adapter=None, sequence=0):
    key = f"history:{segment.pk}:{segment.attempt}"
    with patch("apps.integrations.sync_services.require_sync_read_capability"), patch("apps.integrations.sync_services.record_sync_source_decision"):
        return run_sync_job(job, adapter=adapter or TwoPageAdapter(), idempotency_key=key, history_segment=segment, resume_sequence=sequence)


def test_batch_wait_metadata_is_not_a_historical_failure_and_clears_after_renewal(ctx):
    user, job, _ = ctx
    batch = create(user, [job], "waiting-metadata")
    segment = batch.segments.order_by("sequence").first()
    SyncRun.objects.create(tenant=job.tenant, sync_job=job, history_segment=segment, run_id="waiting-history-run",
                          idempotency_key="waiting-history-key", status="queued", error_code="WAITING_CREDENTIAL_REFRESH",
                          masked_error_message="等待自动续期；已保留采集断点。")
    refresh = {"state": "due", "expired": False, "requires_manual_recovery": False}
    with patch("apps.integrations.automatic_refresh.credential_refresh_state", return_value=refresh):
        waiting = batch_data(batch, [job.pk])["shops"][0]
        assert waiting["waiting_for_refresh"] == 1 and waiting["last_error"] == ""
        refresh["state"] = "not_due"
        resumed = batch_data(batch, [job.pk])["shops"][0]
        assert resumed["waiting_for_refresh"] == 0 and resumed["last_error"] == ""


def test_three_resources_whole_range_split_contiguous_and_policy_untouched(ctx):
    user, job, _ = ctx
    jobs = [job] + [SyncJob.objects.create(tenant=job.tenant, integration_config=job.integration_config,
        store_authorization=job.store_authorization, resource_type=resource) for resource in ["sales_order", "refund_return"]]
    original = job.sync_scope.copy()
    batch = create(user, jobs)
    assert batch.segments.count() == 27
    for selected in jobs:
        segments = list(batch.segments.filter(sync_job=selected).order_by("sequence"))
        assert len(segments) == 9
        for first, second in zip(segments, segments[1:]):
            assert second.scope["time_from"] == first.scope["time_to"] + 1
        assert all(s.scope["time_to"] - s.scope["time_from"] < 15 * 86400 for s in segments)
    job.refresh_from_db()
    assert job.sync_scope == original and job.schedule_type == "manual"
    assert create(user, jobs).pk == batch.pk
    with pytest.raises(ValidationError, match="幂等键"):
        changed = payload(jobs)
        changed["name"] = "different"
        create_history_batch(user, changed)
    with pytest.raises(ValidationError, match="未结束"):
        create(user, jobs, "other-request")


def test_outbox_resubmits_same_key_and_pause_blocks_worker(ctx):
    user, job, _ = ctx
    batch = create(user, [job])
    now = timezone.now()
    broken = Mock(side_effect=RuntimeError("broker unknown"))
    assert dispatch_history_segments(broken, now=now) == 0
    segment = batch.segments.get(sequence=1)
    assert segment.status == "queued" and segment.runs.count() == 1
    queued = Mock()
    assert dispatch_history_segments(queued, now=now + timedelta(minutes=4)) == 1
    assert queued.call_args.args == (job.pk, f"history:{segment.pk}:1", 0)
    assert segment.runs.count() == 1
    batch_action(batch, user, "pause")
    assert dispatch_history_segments(queued, now=now + timedelta(minutes=8)) == 0
    with patch("apps.integrations.tasks.validate_manual_sync_job") as preflight:
        result = run_readonly_sync_job.run(job.pk, f"history:{segment.pk}:1")
    assert result["status"] == "paused"
    preflight.assert_not_called()
    batch.refresh_from_db()
    batch_action(batch, user, "resume")
    assert dispatch_history_segments(queued, now=now + timedelta(minutes=12)) == 1


def test_history_budget_resume_scope_and_default_checkpoint_isolation(ctx):
    user, job, _ = ctx
    batch = create(user, [job])
    dispatch_history_segments(Mock())
    segment = batch.segments.get(sequence=1)
    default = SyncCursor.objects.create(tenant=job.tenant, sync_job=job, cursor_key="default", cursor_value="daily-cursor")
    watermark = timezone.now()
    checkpoint = SyncCheckpoint.objects.create(tenant=job.tenant, sync_job=job, cursor_json={"default": "daily-cursor"}, watermark_utc=watermark, version=7)
    with patch("apps.integrations.sync_services.monotonic", side_effect=[0, 241]):
        run, _ = execute(job, segment)
    assert run.status == "queued"
    assert run.history_segment_id == segment.pk
    assert run.masked_log["runtime_budget"]["resolved_scope"] == segment.scope
    batch_action(batch, user, "pause")
    assert resume_due_sync_runs(Mock(), now=timezone.now() + timedelta(minutes=4)) == 0
    batch.refresh_from_db()
    batch_action(batch, user, "resume")
    adapter = TwoPageAdapter({"time_from": 999, "time_to": 1000})
    with patch("apps.integrations.sync_services.monotonic", return_value=0):
        resumed, _ = execute(job, segment, adapter, sequence=1)
    assert resumed.pk == run.pk and resumed.status == "success"
    assert adapter.cursors == ["p1"] and adapter.scope == segment.scope
    default.refresh_from_db()
    checkpoint.refresh_from_db()
    assert default.cursor_value == "daily-cursor"
    assert checkpoint.version == 7 and checkpoint.watermark_utc == watermark
    assert checkpoint.cursor_json == {"default": "daily-cursor"} and checkpoint.last_success_run_id is None
    assert resumed.masked_log["checkpoint"]["advanced"] is False
    dispatch_history_segments(Mock(), now=timezone.now() + timedelta(minutes=4))
    segment.refresh_from_db()
    assert segment.status == "success"
    assert batch.segments.get(sequence=2).status == "queued"


def test_completed_batch_stops_and_failed_retry_keeps_cursor(ctx):
    user, job, _ = ctx
    batch = create(user, [job])
    batch.segments.update(status="success")
    segment = batch.segments.get(sequence=1)
    segment.status = "failed"
    segment.save()
    SyncCursor.objects.create(tenant=job.tenant, sync_job=job, cursor_key=f"history:{segment.pk}", cursor_value="saved-page")
    SyncRun.objects.create(tenant=job.tenant, sync_job=job, history_segment=segment, run_id="failed-history", idempotency_key=f"history:{segment.pk}:1", status="failed")
    batch.status = "failed"
    batch.save()
    # This test isolates retry/cursor mechanics; live admission is verified
    # independently by the selective-recovery tests below.
    with patch("apps.integrations.history_sync.validate_manual_sync_job"):
        batch_action(batch, user, "retry_failed")
    segment.refresh_from_db()
    assert segment.attempt == 2 and segment.status == "pending"
    dispatch_history_segments(Mock())
    assert segment.runs.count() == 2
    assert job.cursors.get(cursor_key=f"history:{segment.pk}").cursor_value == "saved-page"
    segment.runs.filter(status="queued").update(status="success")
    assert dispatch_history_segments(Mock(), now=timezone.now() + timedelta(minutes=4)) == 0
    batch.refresh_from_db()
    assert batch.status == "completed"
    assert dispatch_history_segments(Mock(), now=timezone.now() + timedelta(days=1)) == 0


def test_retry_failed_skips_unrestored_segment_preserves_success_and_audits_counts(ctx):
    from apps.integrations.models import IntegrationAuditLog
    user, job, _ = ctx
    batch = create(user, [job])
    batch.segments.update(status="success")
    first, second = list(batch.segments.order_by("sequence")[:2])
    batch.segments.filter(pk__in=[first.pk, second.pk]).update(status="failed")
    SyncCursor.objects.create(tenant=job.tenant, sync_job=job, cursor_key=f"history:{first.pk}", cursor_value="kept-page")

    def admission(candidate, **kwargs):
        if candidate.sync_scope["query"]["start_at"] == history_validation_job(job, second).sync_scope["query"]["start_at"]:
            raise ValidationError("synthetic blocked configuration")

    from apps.integrations.history_sync import history_validation_job
    with patch("apps.integrations.history_sync.validate_manual_sync_job", side_effect=admission):
        batch_action(batch, user, "retry_failed")
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == "pending" and first.attempt == 2
    assert second.status == "failed" and second.attempt == 1
    assert job.cursors.get(cursor_key=f"history:{first.pk}").cursor_value == "kept-page"
    assert batch.segments.exclude(pk__in=[first.pk, second.pk]).filter(status="success").count() == batch.segments.count() - 2
    detail = IntegrationAuditLog.objects.get(action="history_sync_retry_failed").masked_detail
    assert detail["retried_segments"] == 1 and detail["skipped_segments"] == 1


def test_retry_failed_with_no_ready_segment_makes_no_mutation(ctx):
    user, job, _ = ctx
    batch = create(user, [job])
    segment = batch.segments.first()
    segment.status = "failed"
    segment.save()
    with patch("apps.integrations.history_sync.validate_manual_sync_job", side_effect=ValidationError("synthetic expired")):
        with pytest.raises(ValidationError, match="没有可恢复"):
            batch_action(batch, user, "retry_failed")
    segment.refresh_from_db()
    assert segment.status == "failed" and segment.attempt == 1 and segment.submitted_at is None


def test_pause_allows_daily_schedule_without_changing_next_due(ctx):
    user, job, _ = ctx
    now = timezone.now()
    job.schedule_type, job.next_run_at = "interval", now
    job.sync_scope["schedule"] = {"interval_minutes": 60}
    job.save()
    batch = create(user, [job])
    dispatch_history_segments(Mock())
    assert dispatch_due_jobs(Mock(), now=now)["dispatched"] == 0
    job.refresh_from_db()
    assert job.next_run_at == now
    batch_action(batch, user, "pause")
    enqueue = Mock()
    assert dispatch_due_jobs(enqueue, now=now)["dispatched"] == 1


def test_paused_history_allows_manual_daily_queue(ctx):
    user, job, _ = ctx
    batch = create(user, [job])
    dispatch_history_segments(Mock())
    batch_action(batch, user, "pause")
    run, created = enqueue_sync_run(job, "normal-daily-manual")
    assert created and run.history_segment_id is None
    assert job.runs.filter(status="queued").count() == 2


def test_paused_history_preserves_cursor_when_editing_or_disabling_daily_job(ctx):
    user, job, role = ctx
    role.permissions.add(Permission.objects.get(code="integrations.manage"))
    batch = create(user, [job])
    dispatch_history_segments(Mock())
    segment = batch.segments.get(sequence=1)
    history_cursor = SyncCursor.objects.create(tenant=job.tenant, sync_job=job, cursor_key=f"history:{segment.pk}", cursor_value="history-page")
    batch_action(batch, user, "pause")
    client = authenticated_client(user)
    response = client.patch(f"/api/internal/integrations/sync-jobs/{job.pk}/", {"query_mode": "incremental", "lookback_days": 2}, format="json")
    assert response.status_code == 200, response.data
    history_cursor.refresh_from_db()
    assert history_cursor.cursor_value == "history-page"
    assert client.post(f"/api/internal/integrations/sync-jobs/{job.pk}/toggle/", {"enabled": False}, format="json").status_code == 200


def test_disabled_module_blocks_history_creation_and_dispatch(ctx):
    user, job, _ = ctx
    with patch("apps.integrations.history_sync.is_module_enabled", return_value=False):
        with pytest.raises(ValidationError, match="模块已停用"):
            create(user, [job])
        assert dispatch_history_segments(Mock()) == 0


def test_permissions_and_scopes_api_atomic(ctx):
    user, job, role = ctx
    client = authenticated_client(user)
    with patch("apps.integrations.history_sync.validate_manual_sync_job"):
        response = client.post("/api/internal/integrations/history-batches/", payload([job]), format="json")
    assert response.status_code == 200
    assert client.get("/api/internal/integrations/history-batches/").data["data"]["batches"][0]["total_segments"] == 9
    role.permissions.remove(Permission.objects.get(code="integrations.run_live_readonly"))
    assert client.post(f"/api/internal/integrations/history-batches/{response.data['data']['id']}/action/", {"action": "pause"}, format="json").status_code == 403
    assert client.get("/api/internal/integrations/history-batches/").status_code == 200
    scope = role.data_scopes.first() if hasattr(role, "data_scopes") else DataScope.objects.get(role=role)
    scope.scope_type, scope.config = "custom", {"store_ids": [job.store_authorization.store_id + 1000]}
    scope.save()
    assert client.get("/api/internal/integrations/history-batches/").data["data"]["batches"] == []


def test_permission_revocation_blocks_queued_background_execution(ctx):
    user, job, role = ctx
    batch = create(user, [job])
    dispatch_history_segments(Mock())
    segment = batch.segments.get(sequence=1)
    role.permissions.remove(Permission.objects.get(code="integrations.run_live_readonly"))
    with patch("apps.integrations.tasks.run_sync_job") as run:
        result = run_readonly_sync_job.run(job.pk, f"history:{segment.pk}:1")
    assert result["status"] == "paused"
    run.assert_not_called()
    batch.refresh_from_db()
    assert batch.status == "paused"


@pytest.mark.parametrize("field,value", [("job_ids", [True]), ("end_date", "2099-01-01"), ("start_date", "invalid")])
def test_invalid_requests_never_create_batch(ctx, field, value):
    user, job, _ = ctx
    data = payload([job])
    data[field] = value
    with pytest.raises(ValidationError):
        create_history_batch(user, data)
    assert not HistorySyncBatch.objects.exists()
