from types import SimpleNamespace
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.pilot.execution import _performance_result, run_pilot_execution
from apps.pilot.tasks import dispatch_stale_executions
from apps.pilot.models import (
    PerformanceRun,
    PilotEnvironment,
    PilotExecution,
    PilotTargetAlias,
    ReadinessGate,
    RecoveryDrill,
    RecoveryPlan,
    ReleasePlan,
)
from apps.common.exceptions import StateConflict
from apps.pilot.execution import _source_payload
from apps.pilot.runner import ControlledRunnerClient, _clean_metrics
from apps.tenants.models import Tenant


def user_for(tenant, username):
    return CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def grant(user, codes, *, scope_type=DataScope.ScopeType.ALL, config=None):
    role, _ = Role.objects.get_or_create(
        tenant=user.tenant,
        code=f"{user.username}-role",
        defaults={"name": "Pilot execution role"},
    )
    permissions = [
        Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": code.split(".", 1)[0], "action": code.rsplit(".", 1)[-1]},
        )[0]
        for code in codes
    ]
    role.permissions.add(*permissions)
    UserRole.objects.get_or_create(tenant=user.tenant, user=user, role=role)
    scope, _ = DataScope.objects.get_or_create(
        tenant=user.tenant,
        role=role,
        defaults={"scope_type": scope_type, "config": config or {}},
    )
    return scope


def environment(tenant):
    env, _ = PilotEnvironment.objects.get_or_create(code="pilot", defaults={"name": "Controlled pilot"})
    PilotTargetAlias.objects.get_or_create(tenant=tenant, environment=env, alias="demo-app")
    return env


def controlled_create(model, **kwargs):
    instance = model(**kwargs)
    instance._pilot_state_service_write = True
    instance.save(force_insert=True)
    instance._pilot_state_service_write = False
    return instance


def performance_run(tenant, creator, reviewer, env, *, status=PerformanceRun.Status.APPROVED, error_limit=100):
    return controlled_create(
        PerformanceRun,
        tenant=tenant,
        environment=env,
        code=f"PERF-{PerformanceRun.objects.count() + 1}",
        scenario="Synthetic API workload",
        target_alias="demo-app",
        workload_profile="synthetic",
        max_rps=10,
        concurrency=2,
        duration_seconds=30,
        thresholds={
            "p95_ms_max": 800,
            "error_rate_max": error_limit,
            "cpu_percent_max": 80,
            "memory_percent_max": 80,
        },
        evidence_refs=["synthetic-plan"],
        status=status,
        creator=creator,
        owner=creator,
        reviewer=reviewer,
        idempotency_key_hash=(str(PerformanceRun.objects.count() + 1) * 64)[:64],
    )


def release_plan(tenant, creator, approver, env, *, status=ReleasePlan.Status.RUNNING, scheduled_at=None, expires_at=None):
    return controlled_create(
        ReleasePlan,
        tenant=tenant,
        environment=env,
        release_channel="controlled_pilot",
        commit_sha="a" * 40,
        tag="v2.44.59",
        demo_tenant_refs=["demo-tenant"],
        observation_minutes=15,
        stop_conditions=["error_rate"],
        rollback_point="previous-approved",
        database_compatibility="verified",
        approval_ref="release/system-v2.44.59",
        rollback_approval_ref=None,
        rollback_approved_by=None,
        rollback_approved_at=None,
        rollback_approval_expires_at=expires_at,
        status=status,
        manual_context="",
        scheduled_at=scheduled_at,
        created_by=creator,
        approved_by=approver,
        version=1,
        idempotency_key_hash=(str(ReleasePlan.objects.count() + 1) * 64)[:64],
        reason="Approved production pilot release",
    )


def recovery_plan(tenant, creator, approver, env, *, status=RecoveryPlan.Status.RUNNING):
    return controlled_create(
        RecoveryPlan,
        tenant=tenant,
        environment=env,
        name=f"REC-{RecoveryPlan.objects.count() + 1}",
        rpo_minutes=15,
        rto_minutes=30,
        backup_summary="Synthetic backup snapshot",
        backup_checksum_masked="sha256:masked",
        approval_ref="recovery/system-v2.44.59",
        status=status,
        scheduled_at=timezone.now() - timedelta(minutes=1),
        created_by=creator,
        approved_by=approver,
        version=1,
        idempotency_key_hash=(str(RecoveryPlan.objects.count() + 1) * 64)[:64],
        reason="Approved recovery drill",
    )


def runner_result(**overrides):
    value = {
        "status": "succeeded",
        "runner_job_id": "runner-op-1",
        "runner_reference": "evidence/runner-op-1",
        "result_metrics": {
            "p50_ms": 120,
            "p95_ms": 300,
            "error_rate": 0.25,
            "cpu_percent": 40,
            "memory_percent": 50,
        },
        "evidence_refs": ["evidence/runner-op-1"],
        "result_summary": "Synthetic runner completed.",
        "error_code": "",
    }
    value.update(overrides)
    return value


@pytest.mark.django_db(transaction=True)
def test_performance_execute_requires_exact_execute_permission_and_is_idempotent(monkeypatch):
    tenant = Tenant.objects.create(name="Pilot tenant", code="pilot-execute-permission")
    creator = user_for(tenant, "pilot-creator")
    reviewer = user_for(tenant, "pilot-reviewer")
    env = environment(tenant)
    run = performance_run(tenant, creator, reviewer, env)
    client = client_for(creator)
    grant(creator, ["pilot.performance.view", "pilot.performance.record"])
    denied = client.post(
        f"/api/internal/pilot/performance-runs/{run.id}/execute/",
        {"version": run.version, "reason": "Execute approved synthetic run"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="pilot-execution-permission-1",
    )
    assert denied.status_code == 403

    grant(creator, ["pilot.performance.execute"])
    queued = []
    monkeypatch.setattr(
        "apps.pilot.execution_views.execute_pilot_execution.apply_async",
        lambda *args, **kwargs: queued.append((args, kwargs)) or SimpleNamespace(id="celery-pilot-1"),
    )
    with TestCase.captureOnCommitCallbacks(execute=True):
        accepted = client.post(
            f"/api/internal/pilot/performance-runs/{run.id}/execute/",
            {"version": run.version, "reason": "Execute approved synthetic run"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="pilot-execution-permission-2",
        )
    assert accepted.status_code == 202, accepted.json()
    execution_id = accepted.json()["data"]["id"]
    assert accepted.json()["data"]["status"] == "queued"
    assert len(queued) == 1
    replay = client.post(
        f"/api/internal/pilot/performance-runs/{run.id}/execute/",
        {"version": run.version, "reason": "Execute approved synthetic run"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="pilot-execution-permission-2",
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["id"] == execution_id


@pytest.mark.django_db
def test_performance_result_writes_metrics_and_fails_closed_when_target_metrics_missing(monkeypatch):
    tenant = Tenant.objects.create(name="Pilot metrics tenant", code="pilot-metrics")
    creator = user_for(tenant, "metrics-creator")
    reviewer = user_for(tenant, "metrics-reviewer")
    env = environment(tenant)
    run = performance_run(tenant, creator, reviewer, env)
    execution = PilotExecution.objects.create(
        tenant=tenant,
        execution_type=PilotExecution.ExecutionType.PERFORMANCE,
        performance_run=run,
        requested_by=creator,
        request_version=run.version,
        request_fingerprint="a" * 64,
        idempotency_key_hash="b" * 64,
        request_id="request-metrics",
        status=PilotExecution.Status.QUEUED,
    )
    monkeypatch.setattr("apps.pilot.execution.ControlledRunnerClient.execute", lambda *args, **kwargs: runner_result())
    finished = run_pilot_execution(execution.id)
    run.refresh_from_db()
    assert finished.status == PilotExecution.Status.SUCCEEDED
    assert run.status == PerformanceRun.Status.PASSED
    assert float(run.p95_ms) == 300
    assert float(run.error_rate) == 0.25
    assert float(run.cpu_percent) == 40
    assert float(run.memory_percent) == 50

    missing_run = performance_run(tenant, creator, reviewer, env)
    missing = PilotExecution.objects.create(
        tenant=tenant,
        execution_type=PilotExecution.ExecutionType.PERFORMANCE,
        performance_run=missing_run,
        requested_by=creator,
        request_version=missing_run.version,
        request_fingerprint="c" * 64,
        idempotency_key_hash="d" * 64,
        request_id="request-metrics-missing",
        status=PilotExecution.Status.QUEUED,
    )
    incomplete = runner_result()
    incomplete["result_metrics"] = {
        "p50_ms": 100,
        "p95_ms": 200,
        "error_rate": 0,
    }
    monkeypatch.setattr("apps.pilot.execution.ControlledRunnerClient.execute", lambda *args, **kwargs: incomplete)
    failed = run_pilot_execution(missing.id)
    missing_run.refresh_from_db()
    assert failed.status == PilotExecution.Status.FAILED
    assert failed.error_code == "METRIC_MISSING"
    assert missing_run.status == PerformanceRun.Status.FAILED


@pytest.mark.parametrize("value", [0, 0.25, 100])
def test_runner_accepts_error_rate_percentage_boundaries(value):
    cleaned = _clean_metrics({"error_rate": value, "cpu_percent": 20, "memory_percent": 30})
    assert cleaned["error_rate"] == value


def test_runner_rejects_error_rate_outside_percentage_contract():
    assert "error_rate" not in _clean_metrics({"error_rate": 100.001})
    assert "error_rate" not in _clean_metrics({"error_rate": -0.01})


def test_runner_marks_host_process_resources_as_non_target_metrics():
    cleaned = _clean_metrics(
        {
            "error_rate": 0,
            "cpu_percent": 20,
            "memory_percent": 30,
            "metrics_source": "app-vm-host-proc",
            "scope": "app_vm_host",
        }
    )
    assert cleaned["metrics_source"] == "app-vm-host-proc"
    assert cleaned["scope"] == "app_vm_host"


@pytest.mark.parametrize(
    ("runner_status", "expected_status", "expected_code"),
    [
        ("rejected", "failed", "RUNNER_REJECTED"),
        ("timed_out", "failed", "RUNNER_TIMED_OUT"),
        ("interrupted", "failed", "RUNNER_INTERRUPTED"),
    ],
)
def test_runner_maps_nonterminal_failure_states_fail_closed(runner_status, expected_status, expected_code):
    normalized = ControlledRunnerClient()._normalize_result({"operation_id": "op-1", "status": runner_status})
    assert normalized["status"] == expected_status
    assert normalized["error_code"] == expected_code


def test_runner_uses_fixed_post_and_poll_contract(monkeypatch):
    calls = []

    def request_json(self, method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "POST":
            return {"operation_id": "runner-op-2", "status": "running"}
        return {
            "operation_id": "runner-op-2",
            "status": "succeeded",
            "metrics": {"p50_ms": 10, "p95_ms": 20, "error_rate": 0, "cpu_percent": 20, "memory_percent": 30},
            "evidence_ref": "evidence/runner-op-2",
            "summary": "completed",
        }

    monkeypatch.setattr(ControlledRunnerClient, "_request_json", request_json)
    with override_settings(
        PILOT_RUNNER_URL="https://runner.internal",
        PILOT_RUNNER_ALLOWED_HOSTS=["runner.internal"],
        PILOT_RUNNER_TOKEN="runner-test-token",
        PILOT_RUNNER_TOKEN_FILE="",
        PILOT_RUNNER_MAX_RETRIES=0,
        PILOT_RUNNER_MAX_POLLS=2,
        PILOT_RUNNER_POLL_INTERVAL=0,
    ):
        first = ControlledRunnerClient().execute(
            "performance",
            {
                "environment": "pilot",
                "operation": "performance",
                "profile": "synthetic",
                "target_alias": "demo-app",
            },
            idempotency_key="runner-contract-1",
        )
        result = ControlledRunnerClient().execute(
            "performance",
            {
                "environment": "pilot",
                "operation": "performance",
                "profile": "synthetic",
                "target_alias": "demo-app",
            },
            idempotency_key="runner-contract-1",
            runner_job_id=first["runner_job_id"],
        )
    assert first["status"] == "running"
    assert result["status"] == "succeeded"
    assert calls[0][0] == "POST"
    assert calls[0][1] == "https://runner.internal/v1/executions"
    assert calls[0][2]["body"] == {
        "environment": "pilot",
        "operation": "performance",
        "profile": "synthetic",
        "target_alias": "demo-app",
    }
    assert calls[0][2]["idempotency_key"] == "runner-contract-1"
    assert calls[1][0] == "GET"
    assert calls[1][1] == "https://runner.internal/v1/executions/runner-op-2"
    assert "idempotency_key" not in calls[1][2]


@pytest.mark.django_db
def test_execution_jobs_are_immutable_and_get_reports_runner_degraded(monkeypatch):
    tenant = Tenant.objects.create(name="Pilot immutable tenant", code="pilot-immutable")
    creator = user_for(tenant, "immutable-creator")
    reviewer = user_for(tenant, "immutable-reviewer")
    env = environment(tenant)
    run = performance_run(tenant, creator, reviewer, env)
    execution = PilotExecution.objects.create(
        tenant=tenant,
        execution_type=PilotExecution.ExecutionType.PERFORMANCE,
        performance_run=run,
        requested_by=creator,
        request_version=run.version,
        request_fingerprint="e" * 64,
        idempotency_key_hash="f" * 64,
        request_id="request-immutable",
    )
    with pytest.raises(ValidationError):
        PilotExecution.objects.filter(pk=execution.pk).update(status=PilotExecution.Status.RUNNING)
    with pytest.raises(ValidationError):
        execution.delete()

    grant(creator, ["pilot.performance.view"])
    response = client_for(creator).get(f"/api/internal/pilot/executions/{execution.id}/")
    assert response.status_code == 200, response.json()
    assert response.json()["data"]["api_status"] in {"blocked", "degraded"}


@pytest.mark.django_db
def test_deploy_binds_approved_release_and_rejects_terminal_mismatch(monkeypatch):
    tenant = Tenant.objects.create(name="Pilot deploy tenant", code="pilot-deploy-binding")
    creator = user_for(tenant, "deploy-creator")
    approver = user_for(tenant, "deploy-approver")
    executor = user_for(tenant, "deploy-executor")
    env = environment(tenant)
    for code in ("release-ready",):
        ReadinessGate.objects.create(
            environment=env,
            code=code,
            name="Release readiness",
            status=ReadinessGate.Status.PASSED,
            evidence_ref="readiness-evidence",
            evaluated_at=timezone.now(),
            expires_at=timezone.now() + timedelta(hours=1),
        )
    plan = release_plan(
        tenant,
        creator,
        approver,
        env,
        status=ReleasePlan.Status.SCHEDULED,
        scheduled_at=timezone.now() - timedelta(minutes=1),
    )
    # The binding is generated from persisted approved fields, not caller
    # payload, and contains no tag/command/shell data.
    execution = PilotExecution(
        tenant=tenant,
        execution_type=PilotExecution.ExecutionType.DEPLOY,
        release_plan=plan,
        requested_by=executor,
        request_version=plan.version,
        request_fingerprint="1" * 64,
        idempotency_key_hash="2" * 64,
        request_id="deploy-binding-request",
    )
    execution.save(force_insert=True)
    assert _source_payload(execution) == {
        "environment": env.code,
        "operation": "deploy",
        "expected_release_sha": "a" * 40,
        "release_plan_ref": "release/system-v2.44.59",
    }

    monkeypatch.setattr(
        "apps.pilot.execution.ControlledRunnerClient.execute",
        lambda *args, **kwargs: runner_result(
            target_release_sha="b" * 40,
            target_release_plan_ref="release/system-v2.44.59",
        ),
    )
    finished = run_pilot_execution(execution.id)
    plan.refresh_from_db()
    assert finished.status == PilotExecution.Status.MANUAL_REQUIRED
    assert finished.error_code == "RUNNER_RELEASE_BINDING_MISMATCH"
    assert plan.status == ReleasePlan.Status.MANUAL_REQUIRED


@pytest.mark.django_db
def test_recovery_execution_persists_actual_rpo_and_rto(monkeypatch):
    tenant = Tenant.objects.create(name="Pilot recovery tenant", code="pilot-recovery-execution")
    creator = user_for(tenant, "recovery-creator")
    approver = user_for(tenant, "recovery-approver")
    executor = user_for(tenant, "recovery-executor")
    env = environment(tenant)
    plan = recovery_plan(tenant, creator, approver, env)
    drill = controlled_create(
        RecoveryDrill,
        tenant=tenant,
        recovery_plan=plan,
        status=RecoveryPlan.Status.RUNNING,
        started_at=timezone.now() - timedelta(minutes=2),
        version=1,
    )
    execution = PilotExecution.objects.create(
        tenant=tenant,
        execution_type=PilotExecution.ExecutionType.RECOVERY,
        recovery_plan=plan,
        recovery_drill=drill,
        requested_by=executor,
        request_version=plan.version,
        request_fingerprint="3" * 64,
        idempotency_key_hash="4" * 64,
        request_id="recovery-execution-request",
    )
    monkeypatch.setattr(
        "apps.pilot.execution.ControlledRunnerClient.execute",
        lambda *args, **kwargs: runner_result(
            result_metrics={"actual_rpo_minutes": 4, "actual_rto_minutes": 12},
            result_summary="Recovery reconciliation completed.",
        ),
    )
    finished = run_pilot_execution(execution.id)
    drill.refresh_from_db()
    plan.refresh_from_db()
    assert finished.status == PilotExecution.Status.SUCCEEDED
    assert drill.status == RecoveryPlan.Status.SUCCESS
    assert drill.actual_rpo_minutes == 4
    assert drill.actual_rto_minutes == 12
    assert plan.status == RecoveryPlan.Status.SUCCESS


@pytest.mark.django_db
def test_recovery_and_release_windows_require_due_time_and_rollback_separation():
    tenant = Tenant.objects.create(name="Pilot gate tenant", code="pilot-execution-gates")
    creator = user_for(tenant, "gate-creator")
    approver = user_for(tenant, "gate-approver")
    executor = user_for(tenant, "gate-executor")
    env = environment(tenant)
    ReadinessGate.objects.create(
        environment=env,
        code="gate-ready",
        name="Readiness",
        status=ReadinessGate.Status.PASSED,
        evaluated_at=timezone.now(),
        expires_at=timezone.now() + timedelta(hours=1),
    )

    future_release = release_plan(
        tenant,
        creator,
        approver,
        env,
        status=ReleasePlan.Status.SCHEDULED,
        scheduled_at=timezone.now() + timedelta(minutes=5),
    )
    with pytest.raises(StateConflict) as future_error:
        from apps.pilot.execution import create_pilot_execution

        create_pilot_execution(
            actor=executor,
            source=future_release,
            execution_type=PilotExecution.ExecutionType.DEPLOY,
            payload={"version": future_release.version, "reason": "Run approved release"},
            idempotency_key="future-release-execution-key",
        )
    assert future_error.value.error_code == "GATE_FAILED"

    due_release = release_plan(
        tenant,
        creator,
        approver,
        env,
        status=ReleasePlan.Status.SCHEDULED,
        scheduled_at=timezone.now() - timedelta(seconds=1),
    )
    from apps.pilot.execution import create_pilot_execution

    due_execution, replay = create_pilot_execution(
        actor=executor,
        source=due_release,
        execution_type=PilotExecution.ExecutionType.DEPLOY,
        payload={"version": due_release.version, "reason": "Run approved release"},
        idempotency_key="due-release-execution-key",
    )
    assert due_execution.status == PilotExecution.Status.QUEUED
    assert replay is False
    replayed_execution, replay = create_pilot_execution(
        actor=executor,
        source=due_release,
        execution_type=PilotExecution.ExecutionType.DEPLOY,
        payload={"version": 1, "reason": "Run approved release"},
        idempotency_key="due-release-execution-key",
    )
    assert replay is True
    assert replayed_execution.id == due_execution.id

    rollback_expired = release_plan(
        tenant,
        creator,
        approver,
        env,
        status=ReleasePlan.Status.ROLLBACK_REQUIRED,
        expires_at=timezone.now() - timedelta(minutes=1),
    )
    rollback_expired.rollback_approval_ref = "rollback-expired"
    rollback_expired.rollback_approved_by = approver
    rollback_expired._pilot_state_service_write = True
    rollback_expired.save(update_fields=["rollback_approval_ref", "rollback_approved_by"])
    rollback_expired._pilot_state_service_write = False
    with pytest.raises(StateConflict) as expired_error:
        create_pilot_execution(
            actor=executor,
            source=rollback_expired,
            execution_type=PilotExecution.ExecutionType.ROLLBACK,
            payload={
                "version": rollback_expired.version,
                "reason": "Run approved rollback",
                "rollback_approval_ref": "rollback-expired",
            },
            idempotency_key="expired-rollback-execution-key",
        )
    assert expired_error.value.error_code == "ROLLBACK_APPROVAL_EXPIRED"

    rollback_sod = release_plan(
        tenant,
        creator,
        approver,
        env,
        status=ReleasePlan.Status.ROLLBACK_REQUIRED,
        expires_at=timezone.now() + timedelta(hours=1),
    )
    rollback_sod.rollback_approval_ref = "rollback-sod"
    rollback_sod.rollback_approved_by = executor
    rollback_sod._pilot_state_service_write = True
    rollback_sod.save(update_fields=["rollback_approval_ref", "rollback_approved_by"])
    rollback_sod._pilot_state_service_write = False
    with pytest.raises(StateConflict) as sod_error:
        create_pilot_execution(
            actor=executor,
            source=rollback_sod,
            execution_type=PilotExecution.ExecutionType.ROLLBACK,
            payload={
                "version": rollback_sod.version,
                "reason": "Run approved rollback",
                "rollback_approval_ref": "rollback-sod",
            },
            idempotency_key="sod-rollback-execution-key",
        )
    assert sod_error.value.error_code == "SEPARATION_OF_DUTIES"


@pytest.mark.django_db
def test_running_execution_polls_existing_runner_and_deadline_requires_manual(monkeypatch):
    tenant = Tenant.objects.create(name="Pilot polling tenant", code="pilot-polling")
    creator = user_for(tenant, "polling-creator")
    reviewer = user_for(tenant, "polling-reviewer")
    env = environment(tenant)
    run = performance_run(tenant, creator, reviewer, env)
    execution = PilotExecution.objects.create(
        tenant=tenant,
        execution_type=PilotExecution.ExecutionType.PERFORMANCE,
        performance_run=run,
        requested_by=creator,
        request_version=run.version,
        request_fingerprint="5" * 64,
        idempotency_key_hash="6" * 64,
        request_id="polling-request",
    )
    calls = []

    def execute(*args, **kwargs):
        calls.append(kwargs.get("runner_job_id"))
        if len(calls) == 1:
            return runner_result(status="running", runner_job_id="runner-poll-1")
        return runner_result(runner_job_id="runner-poll-1")

    monkeypatch.setattr("apps.pilot.execution.ControlledRunnerClient.execute", execute)
    first = run_pilot_execution(execution.id)
    second = run_pilot_execution(execution.id)
    assert first.status == PilotExecution.Status.RUNNING
    assert second.status == PilotExecution.Status.SUCCEEDED
    assert calls == [None, "runner-poll-1"]

    deadline_run = performance_run(tenant, creator, reviewer, env)
    deadline_execution = PilotExecution.objects.create(
        tenant=tenant,
        execution_type=PilotExecution.ExecutionType.PERFORMANCE,
        performance_run=deadline_run,
        requested_by=creator,
        request_version=deadline_run.version,
        request_fingerprint="7" * 64,
        idempotency_key_hash="8" * 64,
        request_id="deadline-request",
        status=PilotExecution.Status.RUNNING,
        attempt=2,
        started_at=timezone.now() - timedelta(hours=2),
        runner_job_id="runner-still-running",
        runner_deadline_at=timezone.now() - timedelta(seconds=1),
    )
    monkeypatch.setattr(
        "apps.pilot.execution.ControlledRunnerClient.execute",
        lambda *args, **kwargs: pytest.fail("A runner past its deadline must not be polled again"),
    )
    manual = run_pilot_execution(deadline_execution.id)
    deadline_run.refresh_from_db()
    assert manual.status == PilotExecution.Status.MANUAL_REQUIRED
    assert manual.error_code == "RUNNER_DEADLINE"
    assert deadline_run.status == PerformanceRun.Status.MANUAL_REQUIRED


@pytest.mark.django_db
def test_stale_runner_progress_cannot_overwrite_terminal_execution(monkeypatch):
    tenant = Tenant.objects.create(name="Pilot terminal fence tenant", code="pilot-terminal-fence")
    creator = user_for(tenant, "terminal-fence-creator")
    reviewer = user_for(tenant, "terminal-fence-reviewer")
    env = environment(tenant)
    run = performance_run(tenant, creator, reviewer, env)
    execution = PilotExecution.objects.create(
        tenant=tenant,
        execution_type=PilotExecution.ExecutionType.PERFORMANCE,
        performance_run=run,
        requested_by=creator,
        request_version=run.version,
        request_fingerprint="b" * 64,
        idempotency_key_hash="c" * 64,
        request_id="terminal-fence-request",
    )

    def execute(*args, **kwargs):
        current = PilotExecution.objects.get(pk=execution.id)
        current.status = PilotExecution.Status.SUCCEEDED
        current.runner_job_id = "runner-terminal"
        current._execution_service_write = True
        try:
            current.save(update_fields=["status", "runner_job_id"])
        finally:
            current._execution_service_write = False
        return runner_result(status="running", runner_job_id="runner-stale-progress")

    monkeypatch.setattr("apps.pilot.execution.ControlledRunnerClient.execute", execute)
    result = run_pilot_execution(execution.id)

    assert result.status == PilotExecution.Status.SUCCEEDED
    assert result.runner_job_id == "runner-terminal"


@pytest.mark.django_db
def test_pilot_compensator_republishes_stale_queued_execution(monkeypatch):
    tenant = Tenant.objects.create(name="Pilot compensation tenant", code="pilot-compensation")
    creator = user_for(tenant, "compensation-creator")
    reviewer = user_for(tenant, "compensation-reviewer")
    env = environment(tenant)
    run = performance_run(tenant, creator, reviewer, env)
    execution = PilotExecution.objects.create(
        tenant=tenant,
        execution_type=PilotExecution.ExecutionType.PERFORMANCE,
        performance_run=run,
        requested_by=creator,
        request_version=run.version,
        request_fingerprint="9" * 64,
        idempotency_key_hash="a" * 64,
        request_id="pilot-compensation-request",
    )
    clock = timezone.now()
    monkeypatch.setattr(
        "apps.pilot.tasks.timezone.now",
        lambda: clock + timedelta(minutes=10),
    )
    monkeypatch.setattr(
        "apps.pilot.tasks.execute_pilot_execution.apply_async",
        lambda *args, **kwargs: SimpleNamespace(id="celery-pilot-compensation-1"),
    )
    assert dispatch_stale_executions() == {"dispatched": 1}
    execution.refresh_from_db()
    assert execution.celery_task_id == "celery-pilot-compensation-1"
