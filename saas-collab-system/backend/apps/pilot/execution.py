"""Durable pilot executions and their controlled-runner state machine."""

import hashlib
import json
import re
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import write_operation_log
from apps.common.error_codes import ErrorCode
from apps.common.exceptions import BusinessRuleViolation, StateConflict

from .models import (
    PerformanceRun,
    PilotAuditEvent,
    PilotExecution,
    RecoveryDrill,
    RecoveryPlan,
    ReleasePlan,
)
from .runner import ControlledRunnerClient, RunnerError
from .services import key_hash, readiness_passed


TERMINAL_EXECUTION_STATUSES = {
    PilotExecution.Status.SUCCEEDED,
    PilotExecution.Status.FAILED,
    PilotExecution.Status.MANUAL_REQUIRED,
}
ACTIVE_EXECUTION_STATUSES = {
    PilotExecution.Status.QUEUED,
    PilotExecution.Status.RUNNING,
}


def _raise(message, code=ErrorCode.STATE_CONFLICT):
    error = StateConflict(message)
    error.error_code = code
    raise error


def _safe_reason(value):
    value = str(value or "").strip()
    if not value or len(value) > 500 or any(ord(char) < 32 for char in value):
        _raise("Execution reason is invalid.", ErrorCode.FIELD_VALIDATION_FAILED)
    blocked_markers = (
        "http://",
        "https://",
        "token" + "=",
        "api_" + "key=",
        "pass" + "word=",
    )
    if any(marker in value.lower() for marker in blocked_markers):
        _raise("Execution reason cannot contain endpoints or secrets.", ErrorCode.FIELD_VALIDATION_FAILED)
    return value


def _save_source(instance, fields):
    instance._pilot_state_service_write = True
    try:
        instance.save(update_fields=[*fields, "updated_at"])
    finally:
        instance._pilot_state_service_write = False


def _save_execution(instance, fields):
    instance._execution_service_write = True
    try:
        instance.save(update_fields=[*fields, "updated_at"])
    finally:
        instance._execution_service_write = False


def _source_object(execution):
    if execution.execution_type == PilotExecution.ExecutionType.PERFORMANCE:
        return execution.performance_run, "performance_run"
    if execution.execution_type == PilotExecution.ExecutionType.RECOVERY:
        return execution.recovery_plan, "recovery_plan"
    return execution.release_plan, "release_plan"


def _source_payload(execution):
    """Build the fixed runner_release payload from an approved source."""

    source, source_type = _source_object(execution)
    payload = {"environment": source.environment.code, "operation": execution.execution_type}
    # runner_release resolves the target and all command details from its own
    # approved configuration.  Deploy receives only the two approved-candidate
    # binding values below; they are equality checks, never shell arguments.
    if execution.execution_type == PilotExecution.ExecutionType.PERFORMANCE:
        # These are server-side mappings from the persisted, approved P8
        # profile; execute requests cannot override either value.
        profile = {"demo": "demo", "synthetic": "synthetic"}.get(source.workload_profile)
        if not profile:
            raise RunnerError("RUNNER_PROFILE_INVALID", "Approved performance profile is invalid.")
        payload["profile"] = profile
        payload["target_alias"] = source.target_alias
    elif execution.execution_type == PilotExecution.ExecutionType.DEPLOY:
        # ReleasePlan has no separate public plan-ref column.  Its approved
        # approval_ref is the immutable reference shared with the staged
        # candidate manifest; never derive runner arguments from tag, commit
        # input, or an API-provided command.
        expected_sha = str(source.commit_sha or "")
        release_plan_ref = str(source.approval_ref or "")
        if not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
            raise RunnerError("RUNNER_RELEASE_BINDING_INVALID", "Approved release SHA is not a production candidate.")
        if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", release_plan_ref):
            raise RunnerError("RUNNER_RELEASE_BINDING_MISSING", "Approved release plan reference is missing.")
        payload["expected_release_sha"] = expected_sha
        payload["release_plan_ref"] = release_plan_ref
    return payload


def _release_binding_matches(source, runner_result):
    """Require the runner's terminal candidate to equal the approved plan."""

    return (
        runner_result.get("target_release_sha") == str(source.commit_sha or "")
        and runner_result.get("target_release_plan_ref") == str(source.approval_ref or "")
    )


def _fingerprint(execution_type, source, request_payload):
    # The request version is the immutable idempotency input.  The source may
    # advance its optimistic-lock version when the first execution is
    # accepted (recovery/deploy), so using ``source.version`` here would make
    # a same-key retry look like a conflicting request after that transition.
    request_version = request_payload.get("version")
    canonical = {
        "execution_type": execution_type,
        "source_type": source.__class__.__name__,
        "source_id": source.pk,
        "source_version": request_version,
        "payload": request_payload,
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _audit_execution(execution, *, action, before, outcome="success", error_code="", reason="", evidence_refs=None):
    source, source_type = _source_object(execution)
    return PilotAuditEvent.objects.create(
        tenant=execution.tenant,
        actor=execution.requested_by,
        actor_type="user",
        recovery_plan=execution.recovery_plan,
        release_plan=execution.release_plan,
        object_type=source_type,
        object_id=str(source.pk if source else execution.id),
        action=action,
        outcome=outcome,
        error_code=error_code,
        permission_code={
            "performance_run": "pilot.performance.execute",
            "recovery_plan": "pilot.recovery.execute",
            "release_plan": "pilot.release.execute" if execution.execution_type == PilotExecution.ExecutionType.DEPLOY else "pilot.release.rollback.execute",
        }[source_type],
        from_status=before,
        to_status=getattr(source, "status", before),
        reason=(reason or "Controlled pilot execution")[:500],
        approval_ref=getattr(source, "approval_ref", "") or "",
        rollback_approval_ref=execution.request_payload.get("rollback_approval_ref", "") or "",
        idempotency_key_hash=key_hash(f"pilot-execution-audit:{execution.id}:{action}:{uuid.uuid4().hex}"),
        request_id=execution.request_id,
        version=getattr(source, "version", execution.request_version),
        evidence_refs=evidence_refs or [],
    )


def _validate_source_and_transition(*, actor, source, execution_type, payload):
    """Validate approval/version fences and enter the runner-owned state."""

    _safe_reason(payload.get("reason"))
    requested_version = payload["version"]
    if source.version != requested_version:
        _raise("The workflow version changed; refresh before execution.", ErrorCode.VERSION_CONFLICT)

    if execution_type == PilotExecution.ExecutionType.PERFORMANCE:
        if source.status != PerformanceRun.Status.APPROVED:
            _raise("Only approved performance runs can execute.")
        if not source.reviewer_id:
            _raise("Performance approval is incomplete.", ErrorCode.POLICY_VIOLATION)
        if source.reviewer_id == actor.id:
            _raise("The performance reviewer cannot execute its result.", ErrorCode.SEPARATION_OF_DUTIES)
        return None

    if execution_type == PilotExecution.ExecutionType.RECOVERY:
        if source.status != RecoveryPlan.Status.SCHEDULED:
            _raise("Only scheduled, approved recovery plans can execute.")
        if not source.approved_by_id or not source.approval_ref:
            _raise("Recovery approval is incomplete.", ErrorCode.POLICY_VIOLATION)
        if source.approved_by_id == actor.id:
            _raise("The recovery approver cannot execute the recovery drill.", ErrorCode.SEPARATION_OF_DUTIES)
        if source.scheduled_at and source.scheduled_at > timezone.now():
            _raise("The approved recovery window has not started.", ErrorCode.GATE_FAILED)
        if source.drills.filter(status=RecoveryPlan.Status.RUNNING).exists():
            _raise("A recovery drill is already running.")
        source.status = RecoveryPlan.Status.RUNNING
        source.reason = payload["reason"]
        source.version += 1
        _save_source(source, ["status", "reason", "version"])
        return RecoveryDrill.objects.create(
            tenant=source.tenant,
            recovery_plan=source,
            status=RecoveryPlan.Status.RUNNING,
            started_at=timezone.now(),
        )

    if execution_type == PilotExecution.ExecutionType.DEPLOY:
        if source.status != ReleasePlan.Status.SCHEDULED:
            _raise("Only scheduled, approved release plans can deploy.")
        if not source.approved_by_id or not source.approval_ref:
            _raise("Release approval is incomplete.", ErrorCode.POLICY_VIOLATION)
        if source.approved_by_id == actor.id:
            _raise("The release approver cannot execute the deployment.", ErrorCode.SEPARATION_OF_DUTIES)
        if source.scheduled_at and source.scheduled_at > timezone.now():
            _raise("The approved release window has not started.", ErrorCode.GATE_FAILED)
        if not readiness_passed(source.environment):
            _raise("Release readiness gates are not valid.", ErrorCode.GATE_FAILED)
        source.status = ReleasePlan.Status.RUNNING
        source.reason = payload["reason"]
        source.version += 1
        _save_source(source, ["status", "reason", "version"])
        return None

    if execution_type == PilotExecution.ExecutionType.ROLLBACK:
        approval_ref = payload.get("rollback_approval_ref", "")
        if source.status != ReleasePlan.Status.ROLLBACK_REQUIRED:
            _raise("Only rollback-required releases can roll back.")
        if not source.rollback_approved_by_id:
            _raise("Rollback approval is incomplete.", ErrorCode.ROLLBACK_APPROVAL_INVALID)
        if not source.rollback_approval_ref or approval_ref != source.rollback_approval_ref:
            _raise("Rollback approval reference is invalid.", ErrorCode.ROLLBACK_APPROVAL_INVALID)
        if not source.rollback_approval_expires_at or source.rollback_approval_expires_at <= timezone.now():
            _raise("Rollback approval has expired.", ErrorCode.ROLLBACK_APPROVAL_EXPIRED)
        if source.rollback_approved_by_id == actor.id:
            _raise("The rollback approver cannot execute rollback.", ErrorCode.SEPARATION_OF_DUTIES)
        return None

    _raise("Unsupported pilot execution type.", ErrorCode.POLICY_VIOLATION)


@transaction.atomic
def create_pilot_execution(*, actor, source, execution_type, payload, idempotency_key):
    """Create exactly one immutable execution for an approved source object."""

    payload = dict(payload)
    request_payload = {}
    if execution_type == PilotExecution.ExecutionType.ROLLBACK:
        request_payload["rollback_approval_ref"] = payload["rollback_approval_ref"]
    fingerprint = _fingerprint(execution_type, source, {**request_payload, "version": payload["version"]})
    digest = key_hash(idempotency_key)
    existing = PilotExecution.objects.select_for_update().filter(
        tenant=actor.tenant,
        idempotency_key_hash=digest,
    ).first()
    if existing:
        if existing.request_fingerprint != fingerprint:
            _raise("Execution idempotency key was reused with different data.", ErrorCode.IDEMPOTENCY_CONFLICT)
        return existing, True
    if PilotExecution.objects.filter(
        tenant=actor.tenant,
        execution_type=execution_type,
        status__in=ACTIVE_EXECUTION_STATUSES,
        **({"performance_run": source} if execution_type == PilotExecution.ExecutionType.PERFORMANCE else
           {"recovery_plan": source} if execution_type == PilotExecution.ExecutionType.RECOVERY else
           {"release_plan": source}),
    ).exists():
        _raise("An execution for this source object is already running.")

    before = source.status
    drill = _validate_source_and_transition(actor=actor, source=source, execution_type=execution_type, payload=payload)
    kwargs = {
        "tenant": actor.tenant,
        "execution_type": execution_type,
        "requested_by": actor,
        "request_version": payload["version"],
        "request_fingerprint": fingerprint,
        "idempotency_key_hash": digest,
        "request_id": str(uuid.uuid4()),
        "request_payload": request_payload,
    }
    if execution_type == PilotExecution.ExecutionType.PERFORMANCE:
        kwargs["performance_run"] = source
    elif execution_type == PilotExecution.ExecutionType.RECOVERY:
        kwargs["recovery_plan"] = source
        kwargs["recovery_drill"] = drill
    else:
        kwargs["release_plan"] = source
    try:
        execution = PilotExecution.objects.create(**kwargs)
    except IntegrityError as exc:
        raise StateConflict("Execution idempotency conflict.") from exc
    _audit_execution(
        execution,
        action="execute",
        before=before,
        reason=payload["reason"],
    )
    write_operation_log(
        tenant=actor.tenant,
        user=actor,
        module="pilot",
        action="pilot_execution_queued",
        object_type="pilot_execution",
        object_id=execution.id,
        after_data={
            "execution_type": execution.execution_type,
            "status": execution.status,
            "source_id": source.id,
            "source_version": execution.request_version,
        },
    )
    return execution, False


def _decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _performance_result(run, runner_result):
    metrics = runner_result.get("result_metrics") or {}
    keys = ("p50_ms", "p95_ms", "error_rate", "cpu_percent", "memory_percent")
    if metrics.get("metrics_source") in {"app-vm-host-proc", "app_vm_host", "runner-process", "process"} or metrics.get("scope") in {"app_vm_host", "runner_process"}:
        return "failed", "METRIC_MISSING", "Runner returned host or process resource metrics instead of target workload metrics."
    if runner_result.get("status") == "succeeded":
        missing = [key for key in keys if key not in metrics or metrics.get(key) is None]
        if missing:
            # CPU and memory must describe the approved target workload.  A
            # runner process self-observation is not a substitute; absent or
            # malformed target metrics fail closed instead of skipping a
            # configured threshold and reporting PASSED.
            return "failed", "METRIC_MISSING", f"Runner did not return required target metrics: {', '.join(missing)}."
    if runner_result.get("status") != "succeeded":
        return runner_result.get("status", "failed"), "RUNNER_EXECUTION_FAILED", "Performance runner failed."
    checks = {
        "p95_ms": (metrics.get("p95_ms"), run.thresholds.get("p95_ms_max")),
        "error_rate": (metrics.get("error_rate"), run.thresholds.get("error_rate_max")),
        "cpu_percent": (metrics.get("cpu_percent"), run.thresholds.get("cpu_percent_max")),
        "memory_percent": (metrics.get("memory_percent"), run.thresholds.get("memory_percent_max")),
    }
    if any(_decimal(actual) is None or _decimal(limit) is None or _decimal(actual) > _decimal(limit) for actual, limit in checks.values()):
        return "failed", "THRESHOLD_FAILED", "Performance metrics exceeded an approved threshold."
    return "succeeded", "", runner_result.get("result_summary") or "Performance thresholds passed."


def _update_performance(source, execution, runner_result):
    target, error_code, summary = _performance_result(source, runner_result)
    source.status = {
        "succeeded": PerformanceRun.Status.PASSED,
        "failed": PerformanceRun.Status.FAILED,
        "manual_required": PerformanceRun.Status.MANUAL_REQUIRED,
        "running": PerformanceRun.Status.MANUAL_REQUIRED,
        "queued": PerformanceRun.Status.MANUAL_REQUIRED,
    }.get(target, PerformanceRun.Status.FAILED)
    metrics = runner_result.get("result_metrics") or {}
    for field in ("p50_ms", "p95_ms", "error_rate", "cpu_percent", "memory_percent"):
        setattr(source, field, metrics.get(field))
    source.result_summary = summary[:1000]
    source.evidence_refs = runner_result.get("evidence_refs") or []
    source.recorder = execution.requested_by
    source.version += 1
    _save_source(source, ["status", "p50_ms", "p95_ms", "error_rate", "cpu_percent", "memory_percent", "result_summary", "evidence_refs", "recorder", "version"])
    return target, error_code, summary


def _update_recovery(source, execution, runner_result):
    target = runner_result.get("status", "failed")
    metrics = runner_result.get("result_metrics") or {}
    if target == "succeeded" and not {"actual_rpo_minutes", "actual_rto_minutes"} <= set(metrics):
        target = "failed"
        error_code = "RUNNER_METRICS_MISSING"
        summary = "Runner did not return actual RPO and RTO."
    else:
        error_code = "" if target == "succeeded" else "RUNNER_EXECUTION_FAILED"
        summary = runner_result.get("result_summary") or "Recovery execution completed."
    plan_status = {
        "succeeded": RecoveryPlan.Status.SUCCESS,
        "failed": RecoveryPlan.Status.FAILED,
        "manual_required": RecoveryPlan.Status.MANUAL_REQUIRED,
    }.get(target, RecoveryPlan.Status.MANUAL_REQUIRED)
    drill = execution.recovery_drill
    drill.status = plan_status
    drill.actual_rpo_minutes = metrics.get("actual_rpo_minutes")
    drill.actual_rto_minutes = metrics.get("actual_rto_minutes")
    drill.result_summary = summary[:1000]
    drill.evidence_refs = runner_result.get("evidence_refs") or []
    drill.finished_at = timezone.now()
    drill.version += 1
    _save_source(drill, ["status", "actual_rpo_minutes", "actual_rto_minutes", "result_summary", "evidence_refs", "finished_at", "version"])
    source.status = plan_status
    source.reason = summary[:500]
    source.version += 1
    _save_source(source, ["status", "reason", "version"])
    return target, error_code, summary


def _update_release(source, execution, runner_result):
    target = runner_result.get("status", "failed")
    summary = runner_result.get("result_summary") or "Release execution completed."
    if execution.execution_type == PilotExecution.ExecutionType.DEPLOY:
        source_status = {
            "succeeded": ReleasePlan.Status.SUCCESS,
            "failed": ReleasePlan.Status.MANUAL_REQUIRED,
            "manual_required": ReleasePlan.Status.MANUAL_REQUIRED,
        }.get(target, ReleasePlan.Status.MANUAL_REQUIRED)
        source.manual_context = "release" if source_status == ReleasePlan.Status.MANUAL_REQUIRED else ""
    else:
        source_status = {
            "succeeded": ReleasePlan.Status.ROLLED_BACK,
            "failed": ReleasePlan.Status.MANUAL_REQUIRED,
            "manual_required": ReleasePlan.Status.MANUAL_REQUIRED,
        }.get(target, ReleasePlan.Status.MANUAL_REQUIRED)
        source.manual_context = "rollback" if source_status == ReleasePlan.Status.MANUAL_REQUIRED else ""
    source.status = source_status
    source.result_summary = summary[:1000]
    source.evidence_refs = runner_result.get("evidence_refs") or []
    source.version += 1
    _save_source(source, ["status", "manual_context", "result_summary", "evidence_refs", "version"])
    return target, "" if target == "succeeded" else "RUNNER_EXECUTION_FAILED", summary


def _save_runner_progress(execution, runner_result):
    """Persist a non-terminal runner observation without changing source state."""

    # Runner I/O happens outside the database lock. Reacquire the execution
    # row for this progress write so a concurrent delivery that already
    # finished it cannot be resurrected as RUNNING by a stale response.
    with transaction.atomic():
        current = PilotExecution.objects.select_for_update().get(pk=execution.pk)
        if current.status not in ACTIVE_EXECUTION_STATUSES:
            return current
        current.runner_job_id = str(runner_result.get("runner_job_id") or current.runner_job_id or "")[:160]
        current.runner_reference = str(runner_result.get("runner_reference") or current.runner_reference or "")[:240]
        current.result_metrics = runner_result.get("result_metrics") or {}
        current.evidence_refs = runner_result.get("evidence_refs") or []
        current.result_summary = str(runner_result.get("result_summary") or "Runner execution is still in progress.")[:1000]
        current.error_code = str(runner_result.get("error_code") or "")[:80]
        current.error_message = ""
        current.status = PilotExecution.Status.RUNNING
        _save_execution(
            current,
            [
                "status", "runner_job_id", "runner_reference", "result_metrics",
                "evidence_refs", "result_summary", "error_code", "error_message",
            ],
        )
        return current


def _mark_runner_manual_required(execution_id, *, error_code, summary):
    return _finish_execution(
        execution_id,
        {
            "status": "manual_required",
            "runner_job_id": "",
            "runner_reference": "",
            "result_metrics": {},
            "evidence_refs": [],
            "result_summary": summary,
            "error_code": error_code,
        },
        error_code_override=error_code,
    )


@transaction.atomic
def _finish_execution(execution_id, runner_result, *, error_code_override=""):
    execution = PilotExecution.objects.select_for_update().select_related(
        "tenant", "requested_by", "performance_run", "recovery_plan", "recovery_drill", "release_plan",
    ).get(pk=execution_id)
    if execution.status in TERMINAL_EXECUTION_STATUSES:
        return execution
    source, source_type = _source_object(execution)
    before = getattr(source, "status", "")
    if (
        execution.execution_type == PilotExecution.ExecutionType.DEPLOY
        and runner_result.get("status") == "succeeded"
        and not _release_binding_matches(source, runner_result)
    ):
        # A successful HTTP response without the exact approved candidate
        # binding is never a deployment success. Convert it to an explicit
        # manual-required result so the state machine cannot imply production
        # safety while retaining the runner evidence for investigation.
        runner_result = {
            **runner_result,
            "status": "manual_required",
            "error_code": "RUNNER_RELEASE_BINDING_MISMATCH",
            "result_summary": "Runner candidate did not match the approved release plan.",
        }
    if source_type == "performance_run":
        target, error_code, summary = _update_performance(source, execution, runner_result)
    elif source_type == "recovery_plan":
        target, error_code, summary = _update_recovery(source, execution, runner_result)
    else:
        target, error_code, summary = _update_release(source, execution, runner_result)
    execution.status = {
        "succeeded": PilotExecution.Status.SUCCEEDED,
        "failed": PilotExecution.Status.FAILED,
        "manual_required": PilotExecution.Status.MANUAL_REQUIRED,
        "running": PilotExecution.Status.RUNNING,
        "queued": PilotExecution.Status.RUNNING,
    }.get(target, PilotExecution.Status.FAILED)
    execution.runner_job_id = str(runner_result.get("runner_job_id") or execution.runner_job_id or "")[:160]
    execution.runner_reference = str(runner_result.get("runner_reference") or execution.runner_reference or "")[:240]
    execution.result_metrics = runner_result.get("result_metrics") or execution.result_metrics or {}
    execution.evidence_refs = runner_result.get("evidence_refs") or execution.evidence_refs or []
    execution.result_summary = summary[:1000]
    execution.error_code = error_code_override or runner_result.get("error_code") or error_code
    execution.error_message = {
        "": "",
        "METRIC_MISSING": "Runner did not return all required target metrics.",
        "THRESHOLD_FAILED": "Performance thresholds were not met.",
        "RUNNER_EXECUTION_FAILED": "Runner execution failed; manual intervention may be required.",
    }.get(error_code, "Execution failed; manual intervention may be required." if error_code else "")
    execution.finished_at = None if execution.status == PilotExecution.Status.RUNNING else timezone.now()
    fields = [
        "status", "runner_job_id", "runner_reference", "result_metrics", "evidence_refs",
        "result_summary", "error_code", "error_message", "finished_at",
    ]
    _save_execution(execution, fields)
    _audit_execution(
        execution,
        action="execution-result",
        before=before,
        outcome="success" if execution.status == PilotExecution.Status.SUCCEEDED else "failed",
        error_code=execution.error_code,
        reason=summary,
        evidence_refs=execution.evidence_refs,
    )
    write_operation_log(
        tenant=execution.tenant,
        user=execution.requested_by,
        module="pilot",
        action="pilot_execution_finished",
        object_type="pilot_execution",
        object_id=execution.id,
        after_data={"status": execution.status, "attempt": execution.attempt, "error_code": execution.error_code},
    )
    return execution


def run_pilot_execution(execution_id):
    now = timezone.now()
    deadline_reached = False
    with transaction.atomic():
        execution = PilotExecution.objects.select_for_update().get(pk=execution_id)
        # A duplicate delivery must never submit a second operation. A queued
        # row is claimed for its first POST; a running row with a persisted
        # runner id is a bounded GET poll from a later Celery delivery.
        if execution.status in TERMINAL_EXECUTION_STATUSES:
            return execution
        if execution.status == PilotExecution.Status.QUEUED:
            execution.status = PilotExecution.Status.RUNNING
            execution.attempt += 1
            execution.started_at = execution.started_at or now
            execution.runner_deadline_at = execution.runner_deadline_at or (
                now + timedelta(seconds=max(60, min(int(getattr(settings, "PILOT_RUNNER_EXECUTION_DEADLINE_SECONDS", 3600)), 86400)))
            )
            _save_execution(execution, ["status", "attempt", "started_at", "runner_deadline_at"])
        elif execution.status == PilotExecution.Status.RUNNING:
            if execution.runner_deadline_at and execution.runner_deadline_at <= now:
                deadline_reached = True
            else:
                deadline_reached = False
            if not deadline_reached:
                execution.attempt += 1
                _save_execution(execution, ["attempt"])
        else:
            return execution
    if deadline_reached:
        return _mark_runner_manual_required(
            execution_id,
            error_code="RUNNER_DEADLINE",
            summary="Runner execution exceeded the service deadline; manual intervention is required.",
        )
    try:
        execution = PilotExecution.objects.select_related(
            "performance_run", "recovery_plan", "release_plan",
        ).get(pk=execution_id)
        runner_result = ControlledRunnerClient().execute(
            execution.execution_type,
            _source_payload(execution),
            idempotency_key=execution.request_id,
            runner_job_id=execution.runner_job_id or None,
        )
    except RunnerError as exc:
        # A retryable error may have happened after the runner accepted the
        # idempotent POST. Keep the execution open so the next delivery can
        # retry the POST (same Idempotency-Key) or poll the known operation.
        if exc.retryable and execution.runner_deadline_at and execution.runner_deadline_at > timezone.now():
            _save_runner_progress(
                execution,
                {
                    "status": "running",
                    "runner_job_id": execution.runner_job_id,
                    "runner_reference": execution.runner_reference,
                    "result_metrics": execution.result_metrics,
                    "evidence_refs": execution.evidence_refs,
                    "result_summary": "Runner request will be retried.",
                    "error_code": exc.code,
                },
            )
            return execution
        runner_result = {
            "status": "manual_required" if execution.runner_job_id else "failed",
            "runner_job_id": execution.runner_job_id,
            "runner_reference": execution.runner_reference,
            "result_metrics": execution.result_metrics,
            "evidence_refs": execution.evidence_refs,
            "result_summary": "Runner request failed; manual intervention may be required.",
            "error_code": exc.code,
        }
        return _finish_execution(execution_id, runner_result, error_code_override=exc.code)
    if runner_result.get("status") in {"queued", "running"}:
        return _save_runner_progress(execution, runner_result)
    return _finish_execution(execution_id, runner_result)
