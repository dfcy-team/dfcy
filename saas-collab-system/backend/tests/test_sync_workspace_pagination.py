from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.integrations.capability_gate import sync_source_health, sync_source_health_for_jobs
from apps.integrations.models import ConnectionCapability, SyncJob, SyncRun, SyncScheduleDispatch
from apps.integrations.workspace_service import _matches, _run_rows, _workspace_rows, integration_workspace
from apps.permissions.models import DataScope
from tests.test_sync_capability_gate import grant_workspace_view, make_job

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 9, 20, 12, tzinfo=dt_timezone.utc)


@pytest.fixture
def workspace():
    job, auth = make_job()
    user = auth.created_by
    grant_workspace_view(user)
    return user, job


def add_run(job, number, **kwargs):
    fields = {"tenant": job.tenant, "sync_job": job, "run_id": f"real-test-{number}",
              "idempotency_key": f"test-key-{number}", "status": "success",
              "enqueued_at": NOW + timedelta(minutes=number),
              "started_at": NOW + timedelta(minutes=number),
              "finished_at": NOW + timedelta(minutes=number, seconds=5),
              "masked_log": {"execution_mode": "live_readonly", "trigger_type": "manual", "fetched": 0}}
    fields.update(kwargs)
    return SyncRun.objects.create(**fields)


def test_sql_page_preserves_summary_and_only_serializes_current_page(workspace):
    user, job = workspace
    for number in range(13):
        add_run(job, number, status="failed" if number == 1 else "success")
    with patch("apps.integrations.workspace_service._run_rows", wraps=_run_rows) as serialize:
        page = integration_workspace(user, "sync-runs", {"page": 2, "page_size": 5})
        assert len(serialize.call_args.args[0]) == 5
    assert page["pagination"] == {"page": 2, "page_size": 5, "total": 13, "page_count": 3}
    assert [row["run_id"] for row in page["results"]] == [f"real-test-{n}" for n in range(7, 2, -1)]
    assert page["summary"]["run_count"] == 13 and page["summary"]["failed_run_count"] == 1
    assert page["summary"]["successful_run_count"] == 12
    assert page["options"]["statuses"] == ["failed", "success"]
    filtered = integration_workspace(user, "sync-runs", {"status": "failed", "page": 99})
    assert filtered["pagination"]["page"] == 1 and filtered["pagination"]["total"] == 1
    assert filtered["summary"]["run_count"] == 13
    assert filtered["options"]["statuses"] == ["failed", "success"]


def test_real_runs_and_unexecuted_plans_share_stable_sql_pagination(workspace):
    user, job = workspace
    first = add_run(job, 1)
    second = add_run(job, 3, started_at=None, status="queued")
    linked = SyncScheduleDispatch.objects.create(tenant=job.tenant, sync_job=job,
        scheduled_at=NOW, status="success", sync_run=first, schedule_snapshot={"schedule_type": "daily"})
    plan = SyncScheduleDispatch.objects.create(tenant=job.tenant, sync_job=job,
        scheduled_at=NOW + timedelta(minutes=2), status="skipped", reason="test skip")
    page = integration_workspace(user, "sync-runs", {"page_size": 2})
    assert page["pagination"]["total"] == 3
    assert [str(row["id"]) for row in page["results"]] == [str(second.pk), f"plan-{plan.pk}"]
    assert page["summary"]["run_count"] == 2
    tail = integration_workspace(user, "sync-runs", {"page_size": 2, "page": 2})
    assert tail["results"][0]["id"] == first.pk
    assert tail["results"][0]["scheduled_at"] == linked.scheduled_at.isoformat(timespec="seconds")
    only_plan = integration_workspace(user, "sync-runs", {"run_pk": f"plan-{plan.pk}"})
    assert only_plan["results"][0]["is_plan_only"]
    no_match = integration_workspace(user, "sync-runs", {"run_pk": "nonnumeric"})
    assert no_match["results"] == [] and no_match["pagination"]["total"] == 0


@pytest.mark.parametrize("params", [
    {"platform": "SHOPEE"}, {"platform": "tiktok"}, {"api_type": "marketplace"},
    {"environment": "mock"}, {"subject": "shop"}, {"subject": "not-present"},
    {"status": "success,failed"}, {"status": "queued"}, {"resource_type": "sales_order"},
    {"trigger_type": "retry"}, {"trigger_type": "scheduled"}, {"trigger_type": "manual"},
    {"run_id": "REAL-TEST-1"}, {"run_id": "计划 #"},
    {"subject": "gate-shop"},
    {"started_from": "2026-09-21"}, {"started_to": "2026-09-19"},
    {"started_from": "2026-09-20", "started_to": "2026-09-20"},
    {"schedule_type": "daily"}, {"health_state": "healthy"},
])
def test_sql_filters_match_existing_row_contract(workspace, params):
    user, job = workspace
    add_run(job, 1)
    add_run(job, 2, status="failed", masked_log={"execution_mode": "simulation", "retry_of": "prior"})
    add_run(job, 3, status="queued", started_at=None, masked_log={})
    add_run(job, 4, started_at=None, enqueued_at=None, masked_log={"trigger_type": "scheduled", "scheduled_at": NOW.isoformat()})
    plan = SyncScheduleDispatch.objects.create(tenant=job.tenant, sync_job=job,
        scheduled_at=NOW, status="skipped")
    from apps.integrations.workspace_service import _unexecuted_plan_rows
    _, _, _, jobs, runs, _ = _workspace_rows(user)
    old_rows = _run_rows(runs, jobs) + _unexecuted_plan_rows(user, jobs)
    expected = {str(row["id"]) for row in old_rows if _matches(row, params, "sync-runs")}
    actual = integration_workspace(user, "sync-runs", params)
    assert {str(row["id"]) for row in actual["results"]} == expected
    assert actual["pagination"]["total"] == len(expected)
    assert actual["summary"]["run_count"] == 4


def test_workspace_reads_do_not_mutate_and_query_count_does_not_grow_with_history(workspace):
    user, job = workspace
    add_run(job, 1)
    for mode in ("sync-runs", "sync-jobs"):
        with CaptureQueriesContext(connection) as baseline:
            integration_workspace(user, mode, {"page_size": 20})
        SyncRun.objects.bulk_create([SyncRun(
            tenant=job.tenant, sync_job=job, run_id=f"large-{mode}-{n}", idempotency_key=f"large-{mode}-{n}",
            started_at=NOW + timedelta(days=1, seconds=n), status="success",
            masked_log={"execution_mode": "live_readonly", "payload": "x" * 8192},
        ) for n in range(700)])
        before_job = SyncJob.objects.values().get(pk=job.pk)
        with CaptureQueriesContext(connection) as expanded:
            result = integration_workspace(user, mode, {"page_size": 20})
        assert len(expanded) <= len(baseline) + 1
        # This non-superuser fixture also exercises permission/scope reads.
        assert len(expanded) < 100
        assert not any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in expanded)
        assert SyncJob.objects.values().get(pk=job.pk) == before_job
        assert result["summary"]["run_count"] == SyncRun.objects.filter(sync_job=job).count()
    rows = integration_workspace(user, "sync-jobs", {})["results"]
    assert rows[0]["last_success_at"] is not None


def test_all_counts_options_plans_and_results_obey_store_data_scope(workspace):
    user, job = workspace
    add_run(job, 1)
    SyncScheduleDispatch.objects.create(tenant=job.tenant, sync_job=job, scheduled_at=NOW, status="blocked")
    scope = DataScope.objects.get(role__user_roles__user=user)
    scope.scope_type, scope.config = "custom", {"platforms": ["shopee"], "store_ids": [job.store_authorization.store_id + 1]}
    scope.save()
    result = integration_workspace(user, "sync-runs", {})
    assert result["results"] == [] and result["options"]["subjects"] == []
    assert result["summary"]["job_count"] == 0 and result["summary"]["run_count"] == 0
    assert result["pagination"]["total"] == 0


def test_batched_source_health_matches_single_job_rule(workspace):
    _, job = workspace
    other = SyncJob.objects.create(tenant=job.tenant, integration_config=job.integration_config,
        store_authorization=job.store_authorization, resource_type="refund_return")
    ConnectionCapability.objects.create(authorization=job.store_authorization, capability_code="ORDER",
        read_enabled=True, write_enabled=False, status="active", source_priority=7)
    expected = {row.pk: sync_source_health(row) for row in (job, other)}
    with CaptureQueriesContext(connection) as queries:
        actual = sync_source_health_for_jobs([job, other])
    assert actual == expected and len(queries) == 1


@pytest.mark.parametrize("retry_of", ["null", "false", "0", "[]", "{}", "", None, False, 0, 0.0, [], {}, "prior"])
def test_retry_filter_preserves_json_value_truthiness(workspace, retry_of):
    user, job = workspace
    run = add_run(job, 1, masked_log={"retry_of": retry_of, "trigger_type": "manual"})
    retry = integration_workspace(user, "sync-runs", {"trigger_type": "retry"})
    manual = integration_workspace(user, "sync-runs", {"trigger_type": "manual"})
    assert [row["id"] for row in retry["results"]] == ([run.pk] if retry_of else [])
    assert [row["id"] for row in manual["results"]] == ([] if retry_of else [run.pk])


def test_queued_run_sort_uses_linked_dispatch_enqueue_time(workspace):
    user, job = workspace
    queued = add_run(job, 1, status="queued", started_at=None, enqueued_at=None)
    SyncScheduleDispatch.objects.create(tenant=job.tenant, sync_job=job, sync_run=queued,
        scheduled_at=NOW, enqueued_at=NOW + timedelta(days=5))
    add_run(job, 2, started_at=NOW + timedelta(days=2))
    result = integration_workspace(user, "sync-runs", {"page_size": 1})
    assert result["results"][0]["id"] == queued.pk


@pytest.mark.parametrize("key,value", [("started_from", "invalid"), ("started_to", "2026-02-30")])
def test_invalid_dates_are_controlled_validation_errors(workspace, key, value):
    user, job = workspace
    add_run(job, 1)
    with pytest.raises(ValueError, match="valid YYYY-MM-DD"):
        integration_workspace(user, "sync-runs", {key: value})
