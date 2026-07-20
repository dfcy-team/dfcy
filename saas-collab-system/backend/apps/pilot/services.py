import hashlib
import re
import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from apps.common.error_codes import ErrorCode
from apps.common.exceptions import BusinessRuleViolation, StateConflict

from .models import PilotAuditEvent, ReadinessGate, RecoveryDrill, RecoveryPlan, ReleasePlan


def key_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def coded_business_error(message, code):
    error = BusinessRuleViolation(message)
    error.error_code = code
    raise error


def _save_state(instance, update_fields):
    instance._pilot_state_service_write = True
    try:
        instance.save(update_fields=[*update_fields, "updated_at"])
    finally:
        instance._pilot_state_service_write = False


def _check_version(instance, version):
    if instance.version != version:
        raise StateConflict("The workflow version changed; refresh before retrying.")


def _replay(tenant, idempotency_key, *, object_type, object_id, action):
    event = PilotAuditEvent.objects.filter(tenant=tenant, idempotency_key_hash=key_hash(idempotency_key)).first()
    if not event:
        return False
    if event.object_type != object_type or event.object_id != str(object_id) or event.action != action:
        error = StateConflict("The idempotency key is already used by another pilot action.")
        error.error_code = ErrorCode.IDEMPOTENCY_CONFLICT
        raise error
    if event.outcome == PilotAuditEvent.Outcome.FAILED:
        error = StateConflict("The idempotency key belongs to a previously rejected pilot action.")
        error.error_code = ErrorCode.IDEMPOTENCY_CONFLICT
        raise error
    return True


def _audit(instance, *, actor, action, permission_code, before, reason, idempotency_key, evidence_refs=None):
    return PilotAuditEvent.objects.create(
        tenant=actor.tenant,
        actor=actor,
        recovery_plan=instance if isinstance(instance, RecoveryPlan) else None,
        release_plan=instance if isinstance(instance, ReleasePlan) else None,
        object_type="recovery_plan" if isinstance(instance, RecoveryPlan) else "release_plan",
        object_id=str(instance.id),
        action=action,
        outcome=PilotAuditEvent.Outcome.SUCCESS,
        error_code="",
        permission_code=permission_code,
        from_status=before,
        to_status=instance.status,
        reason=reason,
        approval_ref=getattr(instance, "approval_ref", ""),
        rollback_approval_ref=getattr(instance, "rollback_approval_ref", "") or "",
        idempotency_key_hash=key_hash(idempotency_key),
        request_id=str(uuid.uuid4()),
        version=instance.version,
        evidence_refs=evidence_refs or [],
    )


def audit_action_failure(instance, *, actor, action, permission_code, payload, idempotency_key, exc):
    digest = key_hash(idempotency_key)
    existing = PilotAuditEvent.objects.filter(tenant=actor.tenant, idempotency_key_hash=digest).first()
    if existing:
        return existing
    error_code = getattr(exc, "error_code", None) or getattr(exc, "default_code", None) or ErrorCode.INTERNAL_ERROR
    reason = payload.get("reason") if hasattr(payload, "get") else None
    if not isinstance(reason, str) or not reason.strip():
        reason = "Rejected pilot action"
    evidence_refs = payload.get("evidence_refs") if hasattr(payload, "get") else None
    if not isinstance(evidence_refs, list) or any(not isinstance(item, str) for item in evidence_refs):
        evidence_refs = []
    return PilotAuditEvent.objects.create(
        tenant=actor.tenant,
        actor=actor,
        recovery_plan=instance if isinstance(instance, RecoveryPlan) else None,
        release_plan=instance if isinstance(instance, ReleasePlan) else None,
        object_type="recovery_plan" if isinstance(instance, RecoveryPlan) else "release_plan",
        object_id=str(instance.id),
        action=action,
        outcome=PilotAuditEvent.Outcome.FAILED,
        error_code=str(error_code),
        permission_code=permission_code,
        from_status=instance.status,
        to_status=instance.status,
        reason=reason[:500],
        approval_ref=getattr(instance, "approval_ref", ""),
        rollback_approval_ref=getattr(instance, "rollback_approval_ref", "") or "",
        idempotency_key_hash=digest,
        request_id=str(uuid.uuid4()),
        version=instance.version,
        evidence_refs=evidence_refs,
    )


def audit_plan_creation_failure(*, actor, object_type, permission_code, payload, idempotency_key, exc):
    digest = key_hash(idempotency_key)
    existing = PilotAuditEvent.objects.filter(tenant=actor.tenant, idempotency_key_hash=digest).first()
    if existing:
        return existing
    error_code = getattr(exc, "error_code", None) or getattr(exc, "default_code", None) or ErrorCode.INTERNAL_ERROR
    reason = payload.get("reason") if hasattr(payload, "get") else None
    if not isinstance(reason, str) or not reason.strip():
        reason = "Rejected pilot plan creation"
    return PilotAuditEvent.objects.create(
        tenant=actor.tenant,
        actor=actor,
        object_type=object_type,
        object_id=f"uncreated:{digest[:16]}",
        action="create",
        outcome=PilotAuditEvent.Outcome.FAILED,
        error_code=str(error_code),
        permission_code=permission_code,
        from_status="",
        to_status="",
        reason=reason[:500],
        idempotency_key_hash=digest,
        request_id=str(uuid.uuid4()),
        version=0,
        evidence_refs=[],
    )


def audit_plan_creation(instance, *, actor, permission_code, idempotency_key):
    return _audit(
        instance,
        actor=actor,
        action="create",
        permission_code=permission_code,
        before="",
        reason=instance.reason,
        idempotency_key=idempotency_key,
    )


def readiness_passed(environment):
    now = timezone.now()
    gates = list(ReadinessGate.objects.filter(environment=environment))
    return bool(gates) and all(
        gate.status == ReadinessGate.Status.PASSED and gate.expires_at and gate.expires_at > now
        for gate in gates
    )


@transaction.atomic
def transition_recovery(*, plan, actor, action, payload, idempotency_key, permission_code):
    plan = RecoveryPlan.objects.select_for_update().get(pk=plan.pk, tenant=actor.tenant)
    if _replay(plan.tenant, idempotency_key, object_type="recovery_plan", object_id=plan.id, action=action):
        return plan, plan.drills.order_by("-id").first(), True
    _check_version(plan, payload["version"])
    before = plan.status
    reason = payload["reason"]
    drill = None

    if action == "submit-review":
        if before != RecoveryPlan.Status.DRAFT:
            raise StateConflict("Only draft recovery plans can be submitted.")
        plan.status = RecoveryPlan.Status.REVIEW_PENDING
        plan.approval_ref = payload["approval_ref"]
        fields = ["status", "approval_ref"]
    elif action in {"approve", "reject"}:
        if before != RecoveryPlan.Status.REVIEW_PENDING:
            raise StateConflict("Only review-pending recovery plans can be reviewed.")
        if plan.created_by_id == actor.id:
            coded_business_error("The creator cannot review their own recovery plan.", "SEPARATION_OF_DUTIES")
        if action == "approve":
            plan.status = RecoveryPlan.Status.APPROVED
            plan.approval_ref = payload["approval_ref"]
            plan.approved_by = actor
            fields = ["status", "approval_ref", "approved_by"]
        else:
            plan.status = RecoveryPlan.Status.REJECTED
            fields = ["status"]
    elif action == "schedule":
        if before != RecoveryPlan.Status.APPROVED:
            raise StateConflict("Only approved recovery plans can be scheduled.")
        if payload["scheduled_at"] <= timezone.now():
            coded_business_error("Schedule must be in the future.", ErrorCode.FIELD_VALIDATION_FAILED)
        plan.status = RecoveryPlan.Status.SCHEDULED
        plan.scheduled_at = payload["scheduled_at"]
        fields = ["status", "scheduled_at"]
    elif action == "start":
        if before != RecoveryPlan.Status.SCHEDULED:
            raise StateConflict("Only scheduled recovery plans can start recording.")
        if plan.scheduled_at and plan.scheduled_at > timezone.now() + timedelta(minutes=15):
            coded_business_error("The recovery window has not started.", "GATE_FAILED")
        if plan.drills.filter(status=RecoveryPlan.Status.RUNNING).exists():
            raise StateConflict("A recovery drill is already running.")
        plan.status = RecoveryPlan.Status.RUNNING
        fields = ["status"]
        drill = RecoveryDrill.objects.create(
            tenant=plan.tenant,
            recovery_plan=plan,
            status=RecoveryPlan.Status.RUNNING,
            started_at=timezone.now(),
        )
    elif action == "resume":
        if before != RecoveryPlan.Status.MANUAL_REQUIRED:
            raise StateConflict("Only manual-required recovery plans can resume.")
        drill = plan.drills.filter(status=RecoveryPlan.Status.MANUAL_REQUIRED).order_by("-id").first()
        if not drill:
            raise StateConflict("No manual-required drill exists.")
        plan.status = RecoveryPlan.Status.RUNNING
        fields = ["status"]
        drill.status = RecoveryPlan.Status.RUNNING
        drill.version += 1
        _save_state(drill, ["status", "version"])
    elif action == "cancel":
        if before not in {
            RecoveryPlan.Status.DRAFT,
            RecoveryPlan.Status.REVIEW_PENDING,
            RecoveryPlan.Status.APPROVED,
            RecoveryPlan.Status.SCHEDULED,
            RecoveryPlan.Status.MANUAL_REQUIRED,
        }:
            raise StateConflict("The recovery plan cannot be cancelled from its current state.")
        plan.status = RecoveryPlan.Status.CANCELLED
        fields = ["status"]
    else:
        coded_business_error("Unsupported recovery action.", ErrorCode.POLICY_VIOLATION)

    plan.reason = reason
    plan.version += 1
    _save_state(plan, [*fields, "reason", "version"])
    _audit(plan, actor=actor, action=action, permission_code=permission_code, before=before, reason=reason, idempotency_key=idempotency_key)
    return plan, drill, False


@transaction.atomic
def record_recovery_result(*, drill, actor, payload, idempotency_key, permission_code):
    drill = RecoveryDrill.objects.select_for_update().select_related("recovery_plan").get(pk=drill.pk, tenant=actor.tenant)
    plan = RecoveryPlan.objects.select_for_update().get(pk=drill.recovery_plan_id, tenant=actor.tenant)
    if _replay(plan.tenant, idempotency_key, object_type="recovery_plan", object_id=plan.id, action="record-result"):
        return drill, plan, True
    _check_version(drill, payload["version"])
    if drill.status != RecoveryPlan.Status.RUNNING or plan.status != RecoveryPlan.Status.RUNNING:
        raise StateConflict("Only running recovery drills can record results.")
    target = payload["result_status"]
    before = plan.status
    if target == RecoveryPlan.Status.SUCCESS and (payload.get("actual_rpo_minutes") is None or payload.get("actual_rto_minutes") is None):
        coded_business_error("Successful drills require actual RPO and RTO.", ErrorCode.FIELD_VALIDATION_FAILED)
    drill.status = target
    drill.actual_rpo_minutes = payload.get("actual_rpo_minutes")
    drill.actual_rto_minutes = payload.get("actual_rto_minutes")
    drill.result_summary = payload["result_summary"]
    drill.evidence_refs = payload["evidence_refs"]
    drill.finished_at = None if target == RecoveryPlan.Status.MANUAL_REQUIRED else timezone.now()
    drill.version += 1
    _save_state(drill, ["status", "actual_rpo_minutes", "actual_rto_minutes", "result_summary", "evidence_refs", "finished_at", "version"])
    plan.status = target
    plan.reason = payload["reason"]
    plan.version += 1
    _save_state(plan, ["status", "reason", "version"])
    _audit(plan, actor=actor, action="record-result", permission_code=permission_code, before=before, reason=payload["reason"], idempotency_key=idempotency_key, evidence_refs=payload["evidence_refs"])
    return drill, plan, False


def _valid_rollback_approval(plan, approval_ref):
    if not plan.rollback_approval_ref or approval_ref != plan.rollback_approval_ref:
        coded_business_error("Rollback approval reference is invalid.", "ROLLBACK_APPROVAL_INVALID")
    if not plan.rollback_approval_expires_at or plan.rollback_approval_expires_at <= timezone.now():
        coded_business_error("Rollback approval has expired.", "ROLLBACK_APPROVAL_EXPIRED")


@transaction.atomic
def transition_release(*, plan, actor, action, payload, idempotency_key, permission_code):
    plan = ReleasePlan.objects.select_for_update().get(pk=plan.pk, tenant=actor.tenant)
    if _replay(plan.tenant, idempotency_key, object_type="release_plan", object_id=plan.id, action=action):
        return plan, True
    _check_version(plan, payload["version"])
    before = plan.status
    reason = payload["reason"]

    if action == "submit-review":
        if before != ReleasePlan.Status.DRAFT:
            raise StateConflict("Only draft release plans can be submitted.")
        plan.status = ReleasePlan.Status.REVIEW_PENDING
        plan.approval_ref = payload["approval_ref"]
        fields = ["status", "approval_ref"]
    elif action in {"approve", "reject"}:
        if before != ReleasePlan.Status.REVIEW_PENDING:
            raise StateConflict("Only review-pending release plans can be reviewed.")
        if plan.created_by_id == actor.id:
            coded_business_error("The creator cannot review their own release plan.", "SEPARATION_OF_DUTIES")
        if action == "approve":
            if plan.database_compatibility == "pending" or not readiness_passed(plan.environment):
                coded_business_error("Release readiness gates are not valid.", "GATE_FAILED")
            plan.status = ReleasePlan.Status.APPROVED
            plan.approval_ref = payload["approval_ref"]
            plan.approved_by = actor
            fields = ["status", "approval_ref", "approved_by"]
        else:
            plan.status = ReleasePlan.Status.REJECTED
            fields = ["status"]
    elif action == "schedule":
        if before != ReleasePlan.Status.APPROVED:
            raise StateConflict("Only approved release plans can be scheduled.")
        if payload["scheduled_at"] <= timezone.now():
            coded_business_error("Schedule must be in the future.", ErrorCode.FIELD_VALIDATION_FAILED)
        plan.status = ReleasePlan.Status.SCHEDULED
        plan.scheduled_at = payload["scheduled_at"]
        fields = ["status", "scheduled_at"]
    elif action == "start":
        if before != ReleasePlan.Status.SCHEDULED:
            raise StateConflict("Only scheduled release plans can start recording.")
        if not readiness_passed(plan.environment):
            coded_business_error("Release readiness gates are not valid.", "GATE_FAILED")
        if plan.scheduled_at and plan.scheduled_at > timezone.now() + timedelta(minutes=15):
            coded_business_error("The release window has not started.", "GATE_FAILED")
        plan.status = ReleasePlan.Status.RUNNING
        fields = ["status"]
    elif action == "resume":
        if before != ReleasePlan.Status.MANUAL_REQUIRED or plan.manual_context != "release":
            raise StateConflict("Only release-context manual work can resume through this endpoint.")
        if not readiness_passed(plan.environment):
            coded_business_error("Release readiness gates are not valid.", "GATE_FAILED")
        plan.status = ReleasePlan.Status.RUNNING
        plan.manual_context = ""
        fields = ["status", "manual_context"]
    elif action == "cancel":
        allowed = {
            ReleasePlan.Status.DRAFT,
            ReleasePlan.Status.REVIEW_PENDING,
            ReleasePlan.Status.APPROVED,
            ReleasePlan.Status.SCHEDULED,
        }
        if before not in allowed and not (before == ReleasePlan.Status.MANUAL_REQUIRED and plan.manual_context == "release"):
            raise StateConflict("The release plan cannot be cancelled from its current state.")
        plan.status = ReleasePlan.Status.CANCELLED
        fields = ["status"]
    elif action == "record-result":
        if before != ReleasePlan.Status.RUNNING:
            raise StateConflict("Only running release plans can record results.")
        target = payload["result_status"]
        plan.status = target
        plan.result_summary = payload["result_summary"]
        plan.evidence_refs = payload["evidence_refs"]
        plan.manual_context = "release" if target == ReleasePlan.Status.MANUAL_REQUIRED else ""
        fields = ["status", "result_summary", "evidence_refs", "manual_context"]
        if target == ReleasePlan.Status.ROLLBACK_REQUIRED:
            plan.rollback_approval_ref = None
            plan.rollback_approved_by = None
            plan.rollback_approved_at = None
            plan.rollback_approval_expires_at = None
            fields += ["rollback_approval_ref", "rollback_approved_by", "rollback_approved_at", "rollback_approval_expires_at"]
    elif action == "approve-rollback":
        if before != ReleasePlan.Status.ROLLBACK_REQUIRED:
            raise StateConflict("Rollback can only be approved from rollback_required.")
        if actor.id in {plan.created_by_id, plan.approved_by_id}:
            coded_business_error("Rollback approver must be separate from creator and release approver.", "SEPARATION_OF_DUTIES")
        if payload["approval_expires_at"] <= timezone.now() or payload["approval_expires_at"] > timezone.now() + timedelta(hours=24):
            coded_business_error("Rollback approval must expire within 24 hours.", ErrorCode.FIELD_VALIDATION_FAILED)
        if ReleasePlan.objects.filter(
            tenant=plan.tenant,
            rollback_approval_ref=payload["rollback_approval_ref"],
        ).exclude(pk=plan.pk).exists():
            coded_business_error("Rollback approval reference must be unique.", "POLICY_VIOLATION")
        plan.rollback_approval_ref = payload["rollback_approval_ref"]
        plan.rollback_approved_by = actor
        plan.rollback_approved_at = timezone.now()
        plan.rollback_approval_expires_at = payload["approval_expires_at"]
        fields = ["rollback_approval_ref", "rollback_approved_by", "rollback_approved_at", "rollback_approval_expires_at"]
    elif action == "resume-rollback":
        if before != ReleasePlan.Status.MANUAL_REQUIRED or plan.manual_context != "rollback":
            raise StateConflict("Only rollback-context manual work can resume through this endpoint.")
        _valid_rollback_approval(plan, payload["rollback_approval_ref"])
        plan.status = ReleasePlan.Status.ROLLBACK_REQUIRED
        plan.manual_context = ""
        fields = ["status", "manual_context"]
    elif action == "record-rollback":
        if before != ReleasePlan.Status.ROLLBACK_REQUIRED:
            raise StateConflict("Rollback results require rollback_required state.")
        _valid_rollback_approval(plan, payload["rollback_approval_ref"])
        if plan.rollback_approved_by_id == actor.id:
            coded_business_error("Rollback approver cannot record rollback results.", "SEPARATION_OF_DUTIES")
        plan.status = payload["rollback_status"]
        plan.result_summary = payload["result_summary"]
        plan.evidence_refs = payload["evidence_refs"]
        plan.manual_context = "rollback" if plan.status == ReleasePlan.Status.MANUAL_REQUIRED else ""
        fields = ["status", "result_summary", "evidence_refs", "manual_context"]
    else:
        coded_business_error("Unsupported release action.", ErrorCode.POLICY_VIOLATION)

    plan.reason = reason
    plan.version += 1
    try:
        _save_state(plan, [*fields, "reason", "version"])
    except IntegrityError as exc:
        if action == "approve-rollback":
            coded_business_error("Rollback approval reference must be unique.", "POLICY_VIOLATION")
        raise exc
    _audit(plan, actor=actor, action=action, permission_code=permission_code, before=before, reason=reason, idempotency_key=idempotency_key, evidence_refs=payload.get("evidence_refs"))
    return plan, False


def validate_release_payload(payload):
    if not re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", payload["commit_sha"]):
        coded_business_error("Commit SHA must contain 40 or 64 hexadecimal characters.", ErrorCode.FIELD_VALIDATION_FAILED)
