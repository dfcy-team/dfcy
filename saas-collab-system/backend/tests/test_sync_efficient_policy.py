from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.models import SyncCheckpoint, SyncCursor, SyncRun
from apps.integrations.sync_policy import prepare_policy, recommended_policy, resolve_job_scope
from tests.test_mock_sync_isolation import context

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 10, 8, 4, 0, tzinfo=UTC)


def policy_job(context, resource="sales_order"):
    _, job = context
    job.resource_type = resource
    job.integration_config.platform = "shopee"
    job.integration_config.environment = "production"
    job.integration_config.save(update_fields=["platform", "environment"])
    job.sync_scope = {"strategy_profile": "efficient_v1", "product_full_sync": False,
                      "query": {"mode": "incremental", "incremental_anchor": "checkpoint",
                                "lookback_days": 1, "overlap_minutes": 5}}
    job.save(update_fields=["resource_type", "sync_scope"])
    return job


def successful(job, upper=None, **log_changes):
    with patch("apps.integrations.readonly_clients.timezone.now", return_value=NOW):
        scope = resolve_job_scope(job)
    scope["time_to"] = upper or scope["time_to"]
    log = {"execution_mode": "live_readonly", "runtime_budget": {"resolved_scope": scope},
           "sync_policy": scope["_sync_policy"],
           "decision_source": {"platform": job.integration_config.platform, "resource_type": job.resource_type,
                               "ended_without_cursor": True, "all_records_valid": True}, **log_changes}
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job, status="success", run_id="proof",
                                 idempotency_key="proof", masked_log=log)
    SyncCheckpoint.objects.create(tenant=job.tenant, sync_job=job, last_success_run=run,
                                  watermark_utc=NOW + timedelta(hours=2))
    return run


def test_checkpoint_uses_successful_query_upper_not_finished_wall_clock(context):
    job = policy_job(context)
    upper = int((NOW - timedelta(hours=2)).timestamp())
    successful(job, upper)
    with patch("apps.integrations.readonly_clients.timezone.now", return_value=NOW):
        scope = resolve_job_scope(job)
    assert scope["time_from"] == upper - 300
    assert scope["time_to"] == int(NOW.timestamp())
    assert scope["_sync_policy"]["anchor"] == "checkpoint"


@pytest.mark.parametrize("change", [
    {"execution_mode": "simulation"}, {"sync_policy": {}},
    {"decision_source": {"ended_without_cursor": False, "all_records_valid": True}},
])
def test_unproven_or_simulated_run_falls_back_without_advancing(context, change):
    job = policy_job(context)
    successful(job, **change)
    with patch("apps.integrations.readonly_clients.timezone.now", return_value=NOW):
        scope = resolve_job_scope(job)
    assert scope["_sync_policy"]["anchor"] == "lookback"
    assert "没有可证明" in scope["_sync_policy"]["notice"]


def test_failed_records_and_changed_source_invalidate_proof(context):
    job = policy_job(context)
    run = successful(job)
    run.failed_count = 1
    run.save(update_fields=["failed_count"])
    assert resolve_job_scope(job)["_sync_policy"]["anchor"] == "lookback"
    run.failed_count = 0
    run.save(update_fields=["failed_count"])
    job.sync_scope["query"]["statuses"] = ["READY_TO_SHIP"]
    assert resolve_job_scope(job)["_sync_policy"]["anchor"] == "lookback"


def test_checkpoint_long_gap_is_rejected_not_silently_truncated(context):
    job = policy_job(context)
    successful(job, int((NOW - timedelta(days=32)).timestamp()))
    with patch("apps.integrations.readonly_clients.timezone.now", return_value=NOW), pytest.raises(ValidationError, match="未截断缺口"):
        resolve_job_scope(job)


def test_product_initializes_once_then_incremental_and_keeps_targeted_missing_ids(context):
    job = policy_job(context, "platform_product")
    with patch("apps.integrations.readonly_clients.timezone.now", return_value=NOW):
        first = resolve_job_scope(job)
        successful(job, int((NOW - timedelta(hours=1)).timestamp()))
        following = resolve_job_scope(job)
    assert first["product_full_sync"] and first["_sync_policy"]["bootstrap"]
    assert not following["product_full_sync"] and not following["_sync_policy"]["bootstrap"]
    assert following["_sync_policy"]["anchor"] == "checkpoint"
    assert following["product_order_backfill"] == "catalog_and_order_missing"
    job.refresh_from_db()
    assert not job.sync_scope["product_full_sync"]  # preference never rewritten


@pytest.mark.parametrize("resource,query", [
    ("sales_order", {"mode": "range", "time_basis": "created"}),
    ("sales_order", {"time_basis": "created"}),
    ("refund_return", {}), ("settlement_bill", {}),
    ("platform_product", {"product_order_backfill": "order_missing_only"}),
])
def test_checkpoint_rejects_unsupported_time_semantics(context, resource, query):
    job = policy_job(context, resource)
    job.sync_scope["query"].update(query)
    with pytest.raises(ValidationError, match="成功上界仅用于"):
        resolve_job_scope(job)


def test_recommendations_do_not_enable_reschedule_or_change_execution_mode(context):
    job = policy_job(context)
    values = prepare_policy(job, {"strategy_profile": "efficient_v1", "lookback_days": 2})
    assert values["lookback_days"] == 2 and values["execution_budget_seconds"] == 120
    assert not {"is_enabled", "execution_mode", "schedule_type", "interval_minutes"}.intersection(values)
    job.resource_type = "settlement_bill"
    assert recommended_policy(job)["values"]["incremental_anchor"] == "lookback"
    assert recommended_policy(job)["values"]["lookback_days"] == 7


def test_frozen_continuation_does_not_recalculate_or_fail_long_gap(context):
    job = policy_job(context)
    job._frozen_sync_scope = {"time_from": 1, "time_to": 2, "page_size": 100}
    assert resolve_job_scope(job) == job._frozen_sync_scope


def test_preview_then_save_preserves_enablement_and_history_cursor(context):
    client, job = context
    job = policy_job(context)
    job.is_enabled = False
    job.status = "disabled"
    job.save(update_fields=["is_enabled", "status"])
    SyncCursor.objects.create(tenant=job.tenant, sync_job=job, cursor_key="history:fixture", cursor_value="protected")
    url = f"/api/internal/integrations/sync-jobs/{job.pk}/"
    payload = {"strategy_profile": "efficient_v1"}
    preview = client.post(url + "schedule-preview/", payload, format="json")
    assert preview.status_code == 200, preview.data
    job.refresh_from_db()
    assert "execution_budget_seconds" not in job.sync_scope.get("schedule", {})
    response = client.patch(url, payload, format="json")
    assert response.status_code == 200, response.data
    job.refresh_from_db()
    assert not job.is_enabled and job.status == "disabled"
    assert response.data["data"]["strategy_profile"] == "efficient_v1"
    assert response.data["data"]["incremental_anchor"] == "checkpoint"
    assert response.data["data"]["recommended_policy"]["available"]
    assert job.sync_scope["schedule"]["execution_budget_seconds"] == 120
    assert job.cursors.get(cursor_key="history:fixture").cursor_value == "protected"


def test_view_only_cannot_apply_policy(context):
    from apps.permissions.models import Role
    client, job = context
    role = Role.objects.get(tenant=job.tenant)
    role.permissions.remove(*role.permissions.exclude(code="integrations.view"))
    url = f"/api/internal/integrations/sync-jobs/{job.pk}/"
    assert client.patch(url, {"strategy_profile": "efficient_v1"}, format="json").status_code == 403
    assert client.post(url + "schedule-preview/", {"strategy_profile": "efficient_v1"}, format="json").status_code == 403


def test_scheduled_continuation_preflight_retains_frozen_window_after_locked_reload(context):
    from apps.integrations.models import SyncScheduleDispatch
    from apps.integrations.tasks import run_readonly_sync_job
    _, job = context
    dispatch = SyncScheduleDispatch.objects.create(tenant=job.tenant, sync_job=job, scheduled_at=NOW, status="queued")
    key = f"scheduled:{job.pk}:{dispatch.pk}"
    frozen = {"time_from": 1, "time_to": 2, "page_size": 100}
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job, status="queued", run_id="scheduled-frozen",
        idempotency_key=key, masked_log={"runtime_budget": {"sequence": 2, "pending": True, "resolved_scope": frozen}})
    dispatch.sync_run = run
    dispatch.save(update_fields=["sync_run"])
    def validate(candidate, **kwargs):
        assert candidate._frozen_sync_scope == frozen
    with patch("apps.integrations.tasks.validate_manual_sync_job", side_effect=validate), \
            patch("apps.integrations.tasks.run_sync_job", return_value=(run, True)):
        result = run_readonly_sync_job.run(job.pk, key, resume_sequence=2)
    assert result["status"] == "queued"


def test_platform_config_status_filter_change_invalidates_previous_time_bound(context):
    job = policy_job(context)
    successful(job, int((NOW - timedelta(hours=2)).timestamp()))
    job.integration_config.platform_config = {"sync_scope": {"statuses": ["READY_TO_SHIP"]}}
    assert resolve_job_scope(job)["_sync_policy"]["anchor"] == "lookback"
