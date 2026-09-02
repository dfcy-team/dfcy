import hashlib
import re
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import BusinessRuleViolation, StateConflict

from .models import (
    ReleaseApproval,
    ReleaseArtifact,
    ReleaseAuditEvent,
    ReleaseContract,
    ReleaseGateResult,
)


REQUIRED_GATE_CODES = (
    "engineering-quality",
    "miniapp-special",
    "backend-compatibility",
    "end-to-end",
    "release-readiness",
    "evidence-integrity",
)
MINIAPP_FILING_GATE_CODE = "miniapp-filing-approved"
RECORDABLE_GATE_CODES = (*REQUIRED_GATE_CODES, MINIAPP_FILING_GATE_CODE)
REQUIRED_APPROVAL_TYPES = (
    ReleaseApproval.ApprovalType.BUSINESS,
    ReleaseApproval.ApprovalType.TECHNICAL,
    ReleaseApproval.ApprovalType.SECURITY,
)


def required_gate_codes(contract):
    """Return the gates required for the contract's target environment."""

    if contract.environment == ReleaseContract.Environment.PRODUCTION:
        return RECORDABLE_GATE_CODES
    return REQUIRED_GATE_CODES


def key_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def coded_business_error(message, code):
    error = BusinessRuleViolation(message)
    error.error_code = code
    raise error


def _save_contract(contract, update_fields):
    contract._release_service_write = True
    try:
        contract.save(update_fields=[*update_fields, "updated_at"])
    finally:
        contract._release_service_write = False


def _check_version(contract, version):
    if contract.version != version:
        error = StateConflict("The release contract version changed; refresh before retrying.")
        error.error_code = ErrorCode.VERSION_CONFLICT
        raise error


def _replay(tenant, idempotency_key, *, contract_id, action):
    event = ReleaseAuditEvent.objects.filter(
        tenant=tenant,
        idempotency_key_hash=key_hash(idempotency_key),
    ).first()
    if not event:
        return False
    if event.contract_id != contract_id or event.action != action:
        error = StateConflict("The idempotency key is already used by another release action.")
        error.error_code = ErrorCode.IDEMPOTENCY_CONFLICT
        raise error
    return True


def _audit(contract, *, actor, action, before, reason, idempotency_key, evidence_refs=None):
    return ReleaseAuditEvent.objects.create(
        tenant=contract.tenant,
        contract=contract,
        actor=actor,
        action=action,
        from_status=before,
        to_status=contract.status,
        outcome="success",
        reason=reason[:500],
        evidence_refs=evidence_refs or [],
        idempotency_key_hash=key_hash(idempotency_key),
        request_id=str(uuid.uuid4()),
        contract_version=contract.version,
    )


def _generate_contract_no():
    return f"RC-{timezone.now():%Y%m%d}-{uuid.uuid4().hex[:10].upper()}"


def _validate_commit_sha(value):
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", value):
        raise ValidationError({"commit_sha": "Commit SHA must contain 7 to 64 hexadecimal characters."})


def _comparable_create_fields(contract):
    return {
        "application_code": contract.application_code,
        "environment": contract.environment,
        "commit_sha": contract.commit_sha,
        "api_contract_version": contract.api_contract_version,
        "scope": contract.scope,
        "risk_level": contract.risk_level,
        "rollback_version": contract.rollback_version,
        "rollback_point": contract.rollback_point,
        "stop_conditions": contract.stop_conditions,
        "observation_minutes": contract.observation_minutes,
    }


@transaction.atomic
def create_release_contract(*, actor, payload, idempotency_key):
    digest = key_hash(idempotency_key)
    existing = ReleaseContract.objects.filter(
        tenant=actor.tenant,
        idempotency_key_hash=digest,
    ).first()
    if existing:
        if _comparable_create_fields(existing) != payload:
            error = StateConflict("The create idempotency key belongs to a different release contract.")
            error.error_code = ErrorCode.IDEMPOTENCY_CONFLICT
            raise error
        return existing, True

    _validate_commit_sha(payload["commit_sha"])
    contract = ReleaseContract(
        tenant=actor.tenant,
        contract_no=_generate_contract_no(),
        created_by=actor,
        idempotency_key_hash=digest,
        **payload,
    )
    contract.full_clean()
    contract._release_service_write = True
    try:
        contract.save()
    finally:
        contract._release_service_write = False
    _audit(
        contract,
        actor=actor,
        action="create",
        before="",
        reason="Release contract created.",
        idempotency_key=idempotency_key,
    )
    return contract, False


def gate_status(contract):
    now = timezone.now()
    rows = {gate.code: gate for gate in contract.gate_results.all()}
    blockers = []
    required_codes = required_gate_codes(contract)
    for code in required_codes:
        gate = rows.get(code)
        if gate is None:
            blockers.append({"code": code, "reason": "missing"})
        elif gate.status != ReleaseGateResult.Status.PASSED:
            blockers.append({"code": code, "reason": "failed"})
        elif gate.expires_at <= now:
            blockers.append({"code": code, "reason": "expired"})
    return {
        "passed": not blockers,
        "required": len(required_codes),
        "passed_count": len(required_codes) - len(blockers),
        "blockers": blockers,
    }


@transaction.atomic
def record_gate_result(*, contract, actor, payload, idempotency_key):
    contract = ReleaseContract.objects.select_for_update().get(pk=contract.pk, tenant=actor.tenant)
    action = f"gate:{payload['code']}"
    if _replay(contract.tenant, idempotency_key, contract_id=contract.id, action=action):
        return contract.gate_results.get(code=payload["code"]), True
    _check_version(contract, payload["version"])
    if contract.status not in {
        ReleaseContract.Status.DRAFT,
        ReleaseContract.Status.REVIEW_PENDING,
        ReleaseContract.Status.APPROVED,
    }:
        raise StateConflict("Gate evidence cannot change after the build is confirmed.")
    if payload["expires_at"] <= payload["evaluated_at"] or payload["expires_at"] <= timezone.now():
        coded_business_error("Gate evidence must be unexpired.", ErrorCode.GATE_FAILED)

    gate = contract.gate_results.filter(code=payload["code"]).first()
    if gate:
        gate.category = payload["category"]
        gate.status = payload["status"]
        gate.evidence_ref = payload["evidence_ref"]
        gate.evaluated_at = payload["evaluated_at"]
        gate.expires_at = payload["expires_at"]
        gate.recorded_by = actor
        gate.version += 1
        gate.save(
            update_fields=[
                "category",
                "status",
                "evidence_ref",
                "evaluated_at",
                "expires_at",
                "recorded_by",
                "version",
                "updated_at",
            ]
        )
    else:
        gate = ReleaseGateResult.objects.create(
            contract=contract,
            recorded_by=actor,
            code=payload["code"],
            category=payload["category"],
            status=payload["status"],
            evidence_ref=payload["evidence_ref"],
            evaluated_at=payload["evaluated_at"],
            expires_at=payload["expires_at"],
        )
    contract.version += 1
    _save_contract(contract, ["version"])
    _audit(
        contract,
        actor=actor,
        action=action,
        before=contract.status,
        reason=f"Gate {payload['code']} recorded as {payload['status']}.",
        idempotency_key=idempotency_key,
        evidence_refs=[payload["evidence_ref"]],
    )
    return gate, False


@transaction.atomic
def submit_release_contract(*, contract, actor, version, reason, idempotency_key):
    contract = ReleaseContract.objects.select_for_update().get(pk=contract.pk, tenant=actor.tenant)
    if _replay(contract.tenant, idempotency_key, contract_id=contract.id, action="submit-review"):
        return contract, True
    _check_version(contract, version)
    if contract.status != ReleaseContract.Status.DRAFT:
        raise StateConflict("Only draft release contracts can be submitted.")
    current_gates = gate_status(contract)
    if not current_gates["passed"]:
        coded_business_error("All required release gates must pass before review.", ErrorCode.GATE_FAILED)
    before = contract.status
    contract.status = ReleaseContract.Status.REVIEW_PENDING
    contract.version += 1
    _save_contract(contract, ["status", "version"])
    _audit(
        contract,
        actor=actor,
        action="submit-review",
        before=before,
        reason=reason,
        idempotency_key=idempotency_key,
    )
    return contract, False


@transaction.atomic
def decide_release_approval(*, contract, actor, payload, idempotency_key):
    contract = ReleaseContract.objects.select_for_update().get(pk=contract.pk, tenant=actor.tenant)
    approval_type = payload["approval_type"]
    action = f"approval:{approval_type}"
    if _replay(contract.tenant, idempotency_key, contract_id=contract.id, action=action):
        return contract.approvals.get(approval_type=approval_type), contract, True
    _check_version(contract, payload["version"])
    rollback = approval_type == ReleaseApproval.ApprovalType.ROLLBACK
    expected_status = (
        ReleaseContract.Status.ROLLBACK_REQUIRED
        if rollback
        else ReleaseContract.Status.REVIEW_PENDING
    )
    if contract.status != expected_status:
        raise StateConflict("The approval is not valid for the current release status.")
    if contract.created_by_id == actor.id:
        coded_business_error("The contract creator cannot approve this release.", ErrorCode.SEPARATION_OF_DUTIES)
    if contract.approvals.filter(decided_by=actor).exists():
        coded_business_error(
            "One person cannot satisfy multiple release approval roles.",
            ErrorCode.SEPARATION_OF_DUTIES,
        )
    if contract.approvals.filter(approval_type=approval_type).exists():
        raise StateConflict("This approval type already has a decision.")

    approval = ReleaseApproval.objects.create(
        contract=contract,
        approval_type=approval_type,
        decision=payload["decision"],
        reason=payload["reason"],
        decided_by=actor,
    )
    before = contract.status
    if payload["decision"] == ReleaseApproval.Decision.REJECTED:
        contract.status = (
            ReleaseContract.Status.ROLLBACK_REQUIRED
            if rollback
            else ReleaseContract.Status.REJECTED
        )
    elif not rollback:
        approved_types = set(
            contract.approvals.filter(decision=ReleaseApproval.Decision.APPROVED)
            .values_list("approval_type", flat=True)
        )
        if set(REQUIRED_APPROVAL_TYPES).issubset(approved_types):
            contract.status = ReleaseContract.Status.APPROVED
    contract.version += 1
    _save_contract(contract, ["status", "version"])
    _audit(
        contract,
        actor=actor,
        action=action,
        before=before,
        reason=payload["reason"],
        idempotency_key=idempotency_key,
    )
    return approval, contract, False


@transaction.atomic
def confirm_release_build(*, contract, actor, payload, idempotency_key):
    contract = ReleaseContract.objects.select_for_update().get(pk=contract.pk, tenant=actor.tenant)
    if _replay(contract.tenant, idempotency_key, contract_id=contract.id, action="confirm-build"):
        return contract.artifact, contract, True
    _check_version(contract, payload["version"])
    if contract.status != ReleaseContract.Status.APPROVED:
        raise StateConflict("Only approved release contracts can confirm a build.")
    if contract.commit_sha.lower() != payload["commit_sha"].lower():
        coded_business_error("Artifact commit does not match the release candidate.", ErrorCode.POLICY_VIOLATION)
    if not re.fullmatch(r"[0-9a-fA-F]{64}", payload["artifact_hash"]):
        raise ValidationError({"artifact_hash": "Artifact hash must be a SHA-256 hexadecimal digest."})

    artifact = ReleaseArtifact.objects.create(
        contract=contract,
        build_no=payload["build_no"],
        commit_sha=payload["commit_sha"],
        artifact_hash=payload["artifact_hash"].lower(),
        config_version=payload["config_version"],
        manifest=payload.get("manifest", {}),
        recorded_by=actor,
    )
    before = contract.status
    contract.status = ReleaseContract.Status.BUILT
    contract.version += 1
    _save_contract(contract, ["status", "version"])
    _audit(
        contract,
        actor=actor,
        action="confirm-build",
        before=before,
        reason=payload["reason"],
        idempotency_key=idempotency_key,
        evidence_refs=[artifact.artifact_hash],
    )
    return artifact, contract, False


@transaction.atomic
def transition_release(*, contract, actor, action, payload, idempotency_key):
    contract = ReleaseContract.objects.select_for_update().get(pk=contract.pk, tenant=actor.tenant)
    if _replay(contract.tenant, idempotency_key, contract_id=contract.id, action=action):
        return contract, True
    _check_version(contract, payload["version"])
    before = contract.status
    fields = ["status"]

    if action == "upload":
        if before != ReleaseContract.Status.BUILT:
            raise StateConflict("Only built candidates can be marked uploaded.")
        contract.status = ReleaseContract.Status.UPLOADED
    elif action == "submit-platform-review":
        if before != ReleaseContract.Status.UPLOADED:
            raise StateConflict("Only uploaded candidates can enter platform review.")
        contract.status = ReleaseContract.Status.PLATFORM_REVIEW
    elif action == "record-platform-review":
        if before != ReleaseContract.Status.PLATFORM_REVIEW:
            raise StateConflict("Only platform-review contracts can record the review result.")
        if payload.get("result_status") == "approved":
            scheduled_at = payload.get("scheduled_at")
            if not scheduled_at or scheduled_at <= timezone.now():
                coded_business_error("An approved platform review requires a future release window.", ErrorCode.FIELD_VALIDATION_FAILED)
            contract.status = ReleaseContract.Status.SCHEDULED
            contract.scheduled_at = scheduled_at
            fields.append("scheduled_at")
        elif payload.get("result_status") == "rejected":
            contract.status = ReleaseContract.Status.REVIEW_FAILED
        else:
            raise ValidationError({"result_status": "Expected approved or rejected."})
    elif action == "start-release":
        if before != ReleaseContract.Status.SCHEDULED:
            raise StateConflict("Only scheduled release contracts can start.")
        if contract.scheduled_at and contract.scheduled_at > timezone.now() + timedelta(minutes=15):
            coded_business_error("The approved release window has not started.", ErrorCode.GATE_FAILED)
        if not gate_status(contract)["passed"]:
            coded_business_error("Release gate evidence is missing or expired.", ErrorCode.GATE_FAILED)
        contract.status = ReleaseContract.Status.RELEASING
    elif action == "record-release-result":
        if before != ReleaseContract.Status.RELEASING:
            raise StateConflict("Only releasing contracts can record a release result.")
        result_status = payload.get("result_status")
        if result_status == "released":
            contract.status = ReleaseContract.Status.RELEASED
        elif result_status == "failed":
            contract.status = ReleaseContract.Status.RELEASE_FAILED
        else:
            raise ValidationError({"result_status": "Expected released or failed."})
    elif action == "start-observation":
        if before != ReleaseContract.Status.RELEASED:
            raise StateConflict("Only released contracts can enter observation.")
        contract.status = ReleaseContract.Status.OBSERVING
    elif action == "complete":
        if before != ReleaseContract.Status.OBSERVING:
            raise StateConflict("Only observing contracts can complete.")
        contract.status = ReleaseContract.Status.COMPLETED
        contract.completed_at = timezone.now()
        fields.append("completed_at")
    elif action == "request-rollback":
        if before not in {
            ReleaseContract.Status.RELEASED,
            ReleaseContract.Status.RELEASE_FAILED,
            ReleaseContract.Status.OBSERVING,
        }:
            raise StateConflict("Rollback cannot be requested from the current status.")
        contract.status = ReleaseContract.Status.ROLLBACK_REQUIRED
    elif action == "execute-rollback":
        if before != ReleaseContract.Status.ROLLBACK_REQUIRED:
            raise StateConflict("Only rollback-required contracts can record rollback execution.")
        rollback_approval = contract.approvals.filter(
            approval_type=ReleaseApproval.ApprovalType.ROLLBACK,
            decision=ReleaseApproval.Decision.APPROVED,
        ).first()
        if not rollback_approval:
            coded_business_error("Rollback requires an independent approval.", ErrorCode.ROLLBACK_APPROVAL_INVALID)
        contract.status = ReleaseContract.Status.ROLLED_BACK
        contract.completed_at = timezone.now()
        fields.append("completed_at")
    elif action == "cancel":
        if before not in {
            ReleaseContract.Status.DRAFT,
            ReleaseContract.Status.REVIEW_PENDING,
            ReleaseContract.Status.APPROVED,
            ReleaseContract.Status.BUILT,
            ReleaseContract.Status.UPLOADED,
            ReleaseContract.Status.SCHEDULED,
        }:
            raise StateConflict("The release contract cannot be cancelled from the current status.")
        contract.status = ReleaseContract.Status.CANCELLED
    else:
        coded_business_error("Unsupported release action.", ErrorCode.POLICY_VIOLATION)

    contract.version += 1
    _save_contract(contract, [*fields, "version"])
    _audit(
        contract,
        actor=actor,
        action=action,
        before=before,
        reason=payload["reason"],
        idempotency_key=idempotency_key,
        evidence_refs=payload.get("evidence_refs", []),
    )
    return contract, False
