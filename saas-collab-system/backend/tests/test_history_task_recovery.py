from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.integrations.history_advertising import advertising_history_scopes
from apps.integrations.history_recovery import task_action, task_revision
from apps.integrations.history_schedule import execution_window, history_task_gate, runnable_history_exists, validate_execution_policy
from apps.integrations.history_sync import create_history_batch, dispatch_history_segments, update_batch_status
from apps.integrations.models import IntegrationAuditLog, SyncCursor, SyncJob, SyncRun, SyncCheckpoint
from apps.integrations.scheduler import dispatch_due_jobs
from apps.integrations.sync_delivery import DeliverySnapshot
from apps.integrations.sync_services import enqueue_sync_run
from apps.integrations.tasks import run_readonly_sync_job
from apps.permissions.models import Permission, DataScope
from tests.test_history_sync_batches import ctx, create, execute, payload
from tests.test_phase2_sync_framework import authenticated_client
from tests.test_sync_runtime_budget import empty_delivery_broker, TwoPageAdapter

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 10, 15, 7, 0, tzinfo=UTC)
NIGHT = {"mode": "night", "start_time": "00:30", "end_time": "06:00"}


def act(batch, job, user, action, **fields):
    batch.refresh_from_db()
    job.refresh_from_db()
    return task_action(batch, user, {"action": action, "sync_job_id": job.pk,
        "expected_revision": task_revision(batch, job), **fields})


def other_job(job):
    return SyncJob.objects.create(tenant=job.tenant, integration_config=job.integration_config,
        store_authorization=job.store_authorization, resource_type="refund_return", is_enabled=True)


@pytest.mark.parametrize("utc,allowed,next_time", [
    ("2026-10-14T16:29:59+00:00", False, "2026-10-15T00:30:00+08:00"),
    ("2026-10-14T16:30:00+00:00", True, None),
    ("2026-10-14T21:59:59+00:00", True, None),
    ("2026-10-14T22:00:00+00:00", False, "2026-10-16T00:30:00+08:00"),
])
def test_beijing_window_half_open(utc, allowed, next_time):
    gate = execution_window(NIGHT, datetime.fromisoformat(utc))
    assert gate["allowed"] is allowed and gate["next_eligible_at"] == next_time


@pytest.mark.parametrize("utc,allowed,next_time", [
    ("2026-10-14T10:59:59Z", False, "2026-10-14T19:00:00+08:00"),
    ("2026-10-14T11:00:00Z", True, None),
    ("2026-10-14T15:59:59Z", True, None),
    ("2026-10-14T16:00:00Z", True, None),  # midnight is included
    ("2026-10-14T21:59:59Z", True, None),
    ("2026-10-14T22:00:00Z", False, "2026-10-15T19:00:00+08:00"),
    ("2026-10-15T02:00:00Z", False, "2026-10-15T19:00:00+08:00"),  # daytime wait
])
def test_cross_midnight_window_half_open_and_utc_input(utc, allowed, next_time):
    policy = {"mode": "night", "start_time": "19:00", "end_time": "06:00"}
    gate = execution_window(policy, datetime.fromisoformat(utc.replace("Z", "+00:00")))
    assert gate["allowed"] is allowed and gate["next_eligible_at"] == next_time


@pytest.mark.parametrize("policy", [
    {"mode": "night", "start_time": "17:59", "end_time": "06:00"},
    {"mode": "night", "start_time": "19:00", "end_time": "08:01"},
    {"mode": "night", "start_time": "19:00", "end_time": "19:00"},
    {"mode": "night", "start_time": "09:00", "end_time": "17:00"},
    {"mode": "night", "start_time": "1900", "end_time": "06:00"},
])
def test_cross_midnight_policy_rejects_invalid_or_daytime_windows(policy):
    with pytest.raises(ValidationError):
        validate_execution_policy(policy)


@pytest.mark.parametrize("policy", [None, {"mode": []}, {"mode": "cron"}, {"timezone": "UTC"},
    {"mode": "night", "end_time": "09:00"}, {"start_time": "06:00", "end_time": "06:00"},
    {"start_time": "17:59", "end_time": "06:00"}, {"end_time": True}, {"enabled": True}])
def test_invalid_policy_rejected(policy):
    with pytest.raises(ValidationError):
        validate_execution_policy(policy)


def test_window_gates_dispatch_and_queued_worker_without_blocking_daytime(ctx):
    user, job, _ = ctx
    batch = create(user, [job])
    act(batch, job, user, "set_schedule", execution_policy=NIGHT)
    assert dispatch_history_segments(Mock(), now=NOW) == 0
    assert not job.runs.exists()
    assert dispatch_history_segments(Mock(), now=datetime(2026, 10, 14, 17, tzinfo=UTC)) == 1
    segment = batch.segments.get(sequence=1)
    with patch("apps.integrations.history_schedule.timezone.now", return_value=NOW), patch("apps.integrations.tasks.run_sync_job") as work:
        result = run_readonly_sync_job.run(job.pk, f"history:{segment.pk}:1")
        assert result["status"] == "waiting_window"
        work.assert_not_called()
        run, created = enqueue_sync_run(job, "ordinary-manual")
    assert created and run.history_segment_id is None
    run.delete()
    job.runs.update(status="running")
    with patch("apps.integrations.history_schedule.timezone.now", return_value=NOW), pytest.raises(ValidationError, match="排队或运行"):
        enqueue_sync_run(job, "must-block")


def test_night_history_does_not_starve_daily_scheduler(ctx):
    user, job, _ = ctx
    batch = create(user, [job])
    act(batch, job, user, "set_schedule", execution_policy=NIGHT)
    dispatch_history_segments(Mock(), now=datetime(2026, 10, 14, 17, tzinfo=UTC))
    job.schedule_type, job.next_run_at = "interval", NOW
    job.sync_scope["schedule"]["interval_minutes"] = 60
    job.save()
    enqueue = Mock()
    dispatch_due_jobs(enqueue, now=NOW)
    enqueue.assert_called_once()
    assert str(enqueue.call_args.args[1]).startswith("scheduled:")


@pytest.mark.parametrize("gate", ["pause", "night"])
@pytest.mark.parametrize("queued_before_gate", [False, True])
def test_gated_recovered_older_batch_does_not_starve_new_runnable_batch(ctx, gate, queued_before_gate):
    user, job, _ = ctx
    older = create(user, [job], "older-failed-batch")
    older.segments.update(status="failed")
    update_batch_status(older.pk)
    newer = create(user, [job], "newer-runnable-batch")
    with patch("apps.integrations.sync_services.validate_manual_sync_job"):
        act(older, job, user, "retry_failed")
    older_run = None
    if queued_before_gate:
        assert dispatch_history_segments(Mock(), now=NOW) == 1
        older_run = job.runs.get(history_segment__batch=older)
    if gate == "pause":
        act(older, job, user, "pause")
    else:
        act(older, job, user, "set_schedule", execution_policy=NIGHT)
    assert not history_task_gate(older, job.pk, NOW)["allowed"]
    assert history_task_gate(newer, job.pk, NOW)["allowed"]
    assert runnable_history_exists(job, NOW)
    before_older_segments = list(older.segments.order_by("pk").values("pk", "status", "attempt", "scope"))
    enqueue = Mock()
    assert dispatch_history_segments(enqueue, now=NOW) == 1
    newer_run = job.runs.get(history_segment__batch=newer)
    assert enqueue.call_args.args == (job.pk, newer_run.idempotency_key, 0)
    assert newer_run.history_segment.sequence == 1
    assert list(older.segments.order_by("pk").values("pk", "status", "attempt", "scope")) == before_older_segments
    if older_run:
        older_run.refresh_from_db()
        assert older_run.status == "queued"


@pytest.mark.parametrize("gate", ["pause", "night"])
def test_gated_recovered_batch_with_running_run_still_blocks_other_batch(ctx, gate):
    user, job, _ = ctx
    older = create(user, [job], "older-running-batch")
    older.segments.update(status="failed")
    update_batch_status(older.pk)
    newer = create(user, [job], "newer-waiting-batch")
    with patch("apps.integrations.sync_services.validate_manual_sync_job"):
        act(older, job, user, "retry_failed")
    assert dispatch_history_segments(Mock(), now=NOW) == 1
    older_run = job.runs.get(history_segment__batch=older)
    older_run.status = "running"
    older_run.save(update_fields=["status"])
    if gate == "pause":
        act(older, job, user, "pause")
    else:
        act(older, job, user, "set_schedule", execution_policy=NIGHT)
    enqueue = Mock()
    assert dispatch_history_segments(enqueue, now=NOW) == 0
    enqueue.assert_not_called()
    assert not job.runs.filter(history_segment__batch=newer).exists()


def test_legacy_global_pause_resumes_only_requested_task(ctx):
    user, job, _ = ctx
    other = other_job(job)
    batch = create(user, [job, other])
    batch.task_controls.all().delete()
    batch.status = "paused"
    batch.save()
    saved = list(batch.segments.values("id", "scope", "attempt", "status"))
    act(batch, job, user, "resume")
    batch.refresh_from_db()
    assert batch.status == "running" and history_task_gate(batch, job.pk, NOW)["allowed"]
    assert history_task_gate(batch, other.pk, NOW)["state"] == "paused"
    assert saved == list(batch.segments.values("id", "scope", "attempt", "status"))
    act(batch, job, user, "set_schedule", execution_policy=NIGHT)
    assert batch.task_controls.get(sync_job=other).is_paused
    assert job.sync_scope["query"]["mode"] == "incremental"


def test_selected_retry_preserves_other_segments_cursor_and_pause(ctx):
    user, job, _ = ctx
    other = other_job(job)
    batch = create(user, [job, other])
    batch.segments.update(status="success")
    target = batch.segments.filter(sync_job=job).first()
    foreign = batch.segments.filter(sync_job=other).first()
    batch.segments.filter(pk__in=[target.pk, foreign.pk]).update(status="failed")
    cursor = SyncCursor.objects.create(tenant=job.tenant, sync_job=job, cursor_key=f"history:{target.pk}",
        cursor_value="saved-detail", detail_state={"next_index": 4})
    act(batch, job, user, "pause")
    with patch("apps.integrations.sync_services.validate_manual_sync_job"):
        with pytest.raises(ValidationError, match="不属于"):
            act(batch, job, user, "retry_failed", segment_ids=[foreign.pk])
        _, detail = act(batch, job, user, "retry_failed", segment_ids=[target.pk])
    assert detail["retried_segments"] == 1 and detail["kept_paused"]
    target.refresh_from_db(); foreign.refresh_from_db(); cursor.refresh_from_db()
    assert (target.status, target.attempt) == ("pending", 2)
    assert (foreign.status, foreign.attempt) == ("failed", 1)
    assert cursor.cursor_value == "saved-detail" and cursor.detail_state == {"next_index": 4}
    assert batch.segments.filter(status="success").count() == 16
    assert IntegrationAuditLog.objects.filter(action="history_sync_task_retry_failed").count() == 1


def test_stale_revision_and_revoked_scope_block_actions(ctx):
    user, job, role = ctx
    batch = create(user, [job])
    revision = task_revision(batch, job)
    act(batch, job, user, "set_schedule", execution_policy=NIGHT)
    with pytest.raises(ValidationError, match="状态已变化"):
        task_action(batch, user, {"action": "pause", "sync_job_id": job.pk, "expected_revision": revision})
    scope = DataScope.objects.get(role=role)
    scope.scope_type, scope.config = "custom", {"store_ids": [999999]}
    scope.save()
    with pytest.raises(PermissionDenied):
        act(batch, job, user, "pause")


def test_diagnostics_readonly_scoped_api_keeps_old_whole_batch_flag(ctx):
    user, job, _ = ctx
    batch = create(user, [job, other_job(job)])
    segment = batch.segments.filter(sync_job=job).first()
    segment.status = "failed"; segment.save()
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job, history_segment=segment,
        run_id="timeout", idempotency_key=f"history:{segment.pk}:1", status="failed", error_code="RUN_TIMEOUT")
    client = authenticated_client(user)
    with patch("apps.integrations.sync_services.validate_manual_sync_job"), patch("apps.integrations.sync_delivery.read_delivery_snapshot") as broker:
        response = client.get(f"/api/internal/integrations/history-batches/?sync_job_id={job.pk}&batch_id={batch.pk}")
        assert response.status_code == 200, response.data
        data = response.data["data"]
        assert data["segments"][0]["category"] == "execution_timeout"
        assert data["segments"][0]["can_retry"] and data["segments"][0]["run_id"] == run.pk
        broker.assert_not_called()
    segment.refresh_from_db()
    assert segment.status == "failed" and segment.attempt == 1
    row = client.get(f"/api/internal/integrations/history-batches/?sync_job_id={job.pk}").data["data"]["batches"][0]
    assert row["task_action_allowed"] is False and row["task_control"]["can_manage"]
    response = client.post(f"/api/internal/integrations/history-batches/{batch.pk}/action/",
        {"action": "set_schedule", "sync_job_id": job.pk, "expected_revision": row["task_control"]["revision"], "execution_policy": NIGHT}, format="json")
    assert response.status_code == 200, response.data


def test_reconcile_requires_complete_absence_and_preserves_cursor(ctx):
    user, job, _ = ctx
    batch = create(user, [job])
    segment = batch.segments.first()
    segment.status = "running"; segment.save()
    key = f"history:{segment.pk}:1"
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job, history_segment=segment,
        run_id="orphan", idempotency_key=key, status="running")
    job.status, job.lock_token, job.lock_expires_at = "running", run.run_id, NOW - timedelta(hours=1)
    job.save()
    cursor = SyncCursor.objects.create(tenant=job.tenant, sync_job=job, cursor_key=f"history:{segment.pk}", cursor_value="kept")
    with patch("apps.integrations.sync_delivery.read_delivery_snapshot", return_value=DeliverySnapshot()):
        with pytest.raises(ValidationError, match="证据不完整"):
            act(batch, job, user, "reconcile")
    present = DeliverySnapshot(complete=True, fences={(job.pk, key, 0)})
    with patch("apps.integrations.sync_delivery.read_delivery_snapshot", return_value=present):
        assert act(batch, job, user, "reconcile")[1]["reconciled_segments"] == 0
    with patch("apps.integrations.sync_delivery.read_delivery_snapshot", return_value=DeliverySnapshot(complete=True)):
        assert act(batch, job, user, "reconcile")[1]["reconciled_segments"] == 1
    run.refresh_from_db(); segment.refresh_from_db(); cursor.refresh_from_db(); job.refresh_from_db()
    assert run.status == segment.status == "failed"
    assert run.error_code == "RUN_INTERRUPTED" and not job.lock_token
    assert cursor.cursor_value == "kept" and segment.attempt == 1


def test_revoke_between_preflight_and_claim_blocks_fetch(ctx):
    user, job, role = ctx
    batch = create(user, [job])
    dispatch_history_segments(Mock())
    segment = batch.segments.get(sequence=1)
    adapter = TwoPageAdapter()
    role.permissions.remove(Permission.objects.get(code="integrations.run_live_readonly"))
    run, executed = execute(job, segment, adapter)
    assert executed is False and run.status == "queued" and not adapter.cursors
    assert batch.task_controls.get(sync_job=job).is_paused
    assert not SyncCursor.objects.filter(sync_job=job).exists()


@pytest.mark.parametrize("days,lengths", [(31, [29, 2]), (61, [30, 29, 2]), (30, [30]), (2, [2])])
def test_advertising_splits_store_dates_without_one_day_tail(ctx, days, lengths):
    _, job, _ = ctx
    end = date(2026, 10, 14)
    data = {"start_date": str(end - timedelta(days=days - 1)), "end_date": str(end)}
    with patch("apps.integrations.shopee_advertising.timezone.now", return_value=NOW):
        scopes = advertising_history_scopes(job, data, NOW)
    assert [((date.fromisoformat(s["history_query"]["end_at"]) - date.fromisoformat(s["history_query"]["start_at"])).days + 1) for s in scopes] == lengths
    assert all(s["report_timezone"] == "Asia/Manila" and s["advertising_datasets"] == ["campaign_daily", "shop_daily"] for s in scopes)
    assert all(a["time_to"] + 1 == b["time_from"] for a, b in zip(scopes, scopes[1:]))


def test_advertising_create_freezes_scope_not_daily_query(ctx):
    user, job, _ = ctx
    job.resource_type = "advertising_report"; job.save()
    original = deepcopy(job.sync_scope)
    data = {**payload([job]), "start_date": "2026-08-01", "end_date": "2026-09-30", "execution_policy": NIGHT,
        "advertising_datasets": ["shop_daily", "campaign_daily"]}
    with patch("apps.integrations.history_sync.validate_manual_sync_job"), patch("apps.integrations.history_sync.timezone.now", return_value=NOW):
        batch = create_history_batch(user, data)
        assert create_history_batch(user, data).pk == batch.pk
    assert batch.segments.count() == 3 and batch.task_controls.get().execution_policy["mode"] == "night"
    job.refresh_from_db()
    assert job.sync_scope == original and not SyncCheckpoint.objects.filter(sync_job=job).exists()
    assert all(s.scope["history_query"]["mode"] == "range" for s in batch.segments.all())


@pytest.mark.parametrize("change", [{"start_date": "2025-10-01"}, {"end_date": "2026-10-16"},
    {"start_date": "2026-10-14"}, {"advertising_datasets": ["balance"]}, {"advertising_datasets": ["campaign"]}])
def test_advertising_rejects_unsupported_date_or_snapshot(ctx, change):
    _, job, _ = ctx
    with patch("apps.integrations.shopee_advertising.timezone.now", return_value=NOW), pytest.raises(ValidationError):
        advertising_history_scopes(job, {"start_date": "2026-10-01", "end_date": "2026-10-14", **change}, NOW)


def test_policy_change_releases_old_window_timestamp_without_replacing_run(ctx):
    user, job, _ = ctx
    batch = create(user, [job])
    segment = batch.segments.first()
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job, history_segment=segment,
        run_id="waiting-window", idempotency_key=f"history:{segment.pk}:1", status="queued",
        masked_log={"runtime_budget": {"pending": True, "sequence": 7, "wait_reason": "waiting_window", "ready_at": "2099-01-01T00:30:00+08:00"}})
    act(batch, job, user, "set_schedule", execution_policy={"mode": "anytime"})
    run.refresh_from_db()
    budget = run.masked_log["runtime_budget"]
    assert budget["sequence"] == 7 and budget["pending"]
    assert "wait_reason" not in budget and not budget["ready_at"].startswith("2099")
    assert job.runs.count() == 1


def test_set_schedule_recalculates_queued_ready_at_for_cross_midnight_window(ctx):
    user, job, _ = ctx
    batch = create(user, [job])
    segment = batch.segments.first()
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job, history_segment=segment,
        run_id="waiting-overnight-window", idempotency_key=f"history:{segment.pk}:1", status="queued",
        masked_log={"runtime_budget": {"pending": True, "sequence": 7, "wait_reason": "waiting_window", "ready_at": "2099-01-01T00:30:00+08:00"}})
    policy = {"mode": "night", "timezone": "Asia/Shanghai", "start_time": "19:00", "end_time": "06:00"}
    with patch("apps.integrations.history_recovery.timezone.now", return_value=NOW):
        act(batch, job, user, "set_schedule", execution_policy=policy)
    run.refresh_from_db()
    budget = run.masked_log["runtime_budget"]
    assert budget["ready_at"] == "2026-10-15T19:00:00+08:00"
    assert budget["wait_reason"] == "waiting_window" and budget["sequence"] == 7 and budget["pending"]
    assert job.runs.count() == 1


def test_real_detail_client_checkpoint_survives_slice_failure_and_retry(ctx, monkeypatch):
    from apps.integrations.adapters import ProductionReadonlyAdapter
    from tests.test_shopee_history_detail_checkpoint import configured
    user, job, _ = ctx
    batch = create(user, [job])
    dispatch_history_segments(Mock())
    segment = batch.segments.get(sequence=1)
    client = configured(monkeypatch)
    queries = []

    def request(path, query):
        queries.append((path, dict(query)))
        if path == client.FINANCE_LIST_PATH:
            return {"response": {"order_income_list": [{"order_sn": f"o{i}", "escrow_release_time": segment.scope["time_from"]} for i in range(6)], "more": False}}
        return {"response": {"order_income": {"escrow_amount": "1.25", "currency": "PHP"}}}

    monkeypatch.setattr(client, "_request", request)
    def adapter(valid=True):
        result = ProductionReadonlyAdapter(job.integration_config, client=client)
        result.validate_configuration = lambda candidate: None
        result.normalize_record = lambda record: record
        result.validate_record = lambda record: valid
        result.persist_record = lambda _, record: {"action": "created", "idempotency_key": record["order_id"]}
        result.resource_type = job.resource_type
        return result

    with patch("apps.integrations.sync_services.monotonic", side_effect=[0, 241]):
        run, _ = execute(job, segment, adapter())
    cursor = SyncCursor.objects.get(sync_job=job, cursor_key=f"history:{segment.pk}")
    saved = (cursor.cursor_value, deepcopy(cursor.detail_state))
    assert run.status == "queued" and run.fetched_count == 4
    assert cursor.detail_state["next_index"] == 4 and cursor.cursor_value.startswith("sd1:")
    with patch("apps.integrations.sync_services.monotonic", return_value=0):
        failed, _ = execute(job, segment, adapter(False), sequence=1)
    cursor.refresh_from_db()
    assert failed.status == "failed" and (cursor.cursor_value, cursor.detail_state) == saved
    assert failed.raw_envelopes.count() == 1  # Uncommitted detail response rolled back.
    batch.segments.filter(pk=segment.pk).update(status="failed")
    with patch("apps.integrations.sync_services.validate_manual_sync_job"):
        act(batch, job, user, "retry_failed", segment_ids=[segment.pk])
    dispatch_history_segments(Mock())
    segment.refresh_from_db()
    with patch("apps.integrations.sync_services.monotonic", return_value=0):
        finished, _ = execute(job, segment, adapter())
    cursor.refresh_from_db()
    assert finished.status == "success" and finished.fetched_count == 2
    assert cursor.detail_state == {} and cursor.cursor_value == ""
    assert sum(path == client.FINANCE_LIST_PATH for path, query in queries) == 1
    assert not SyncCheckpoint.objects.filter(sync_job=job).exists()


def test_window_closes_after_page_commit_then_next_night_resumes(ctx):
    user, job, _ = ctx
    batch = create(user, [job])
    dispatch_history_segments(Mock())
    segment = batch.segments.get(sequence=1)

    class CloseWindow(TwoPageAdapter):
        def fetch_page(self, sync_job, cursor_value=None):
            result = super().fetch_page(sync_job, cursor_value)
            batch.task_controls.filter(sync_job=job).update(execution_policy=NIGHT)
            return result

    with patch("apps.integrations.history_schedule.timezone.now", return_value=NOW):
        run, _ = execute(job, segment, CloseWindow())
    assert run.status == "queued" and run.fetched_count == 1
    assert run.masked_log["runtime_budget"]["wait_reason"] == "waiting_window"
    assert run.masked_log["runtime_budget"]["ready_at"] == "2026-10-16T00:30:00+08:00"
    cursor = SyncCursor.objects.get(sync_job=job)
    assert cursor.cursor_value == "p1"
    next_night = datetime(2026, 10, 15, 17, 0, tzinfo=UTC)
    with patch("apps.integrations.history_schedule.timezone.now", return_value=next_night):
        resumed, _ = execute(job, segment, TwoPageAdapter(), sequence=1)
    assert resumed.pk == run.pk and resumed.status == "success" and resumed.fetched_count == 2


def test_permission_update_does_not_grant_roles_or_scopes(ctx):
    from django.apps import apps
    from importlib import import_module
    _, _, role = ctx
    before_permissions = list(role.permissions.order_by("pk").values_list("pk", flat=True))
    before_scopes = list(DataScope.objects.order_by("pk").values("pk", "scope_type", "config"))
    import_module("apps.permissions.migrations.0052_history_task_recovery_description").update_description(apps, None)
    assert list(role.permissions.order_by("pk").values_list("pk", flat=True)) == before_permissions
    assert list(DataScope.objects.order_by("pk").values("pk", "scope_type", "config")) == before_scopes
    assert "广告补采" in Permission.objects.get(code="integrations.history.manage").description
