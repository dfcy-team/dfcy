import hashlib
import json
import uuid
from decimal import Decimal
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import ContractViolation, DataScopeDenied, StateConflict
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p7_scopes import filter_plan_queryset
from apps.permissions.ui_p8_scopes import finance_values_allowed, filter_resource_queryset

from .models import (
    EntryDecision,
    PerformanceRun,
    PilotAuditEvent,
    PilotEvidenceReference,
    PilotTargetAlias,
    RecoveryPlan,
    ReleasePlan,
    SecurityReview,
    VerificationRun,
)
from .services import key_hash


CONTRACT_VERSION = "UI-P8-R3"
RESOURCE_META = {
    SecurityReview: ("security_review", "security_review_ids"),
    VerificationRun: ("verification_run", "verification_run_ids"),
    PerformanceRun: ("performance_run", "performance_run_ids"),
    EntryDecision: ("entry_decision", "entry_decision_ids"),
}


def save_controlled(instance, fields):
    instance._pilot_state_service_write = True
    try:
        instance.save(update_fields=[*fields, "updated_at"])
    finally:
        instance._pilot_state_service_write = False


def _audit(instance, *, actor, actor_type="user", action, permission, before, reason, idempotency_key, outcome="success", error_code="", evidence_refs=None):
    object_type, _ = RESOURCE_META[type(instance)]
    return PilotAuditEvent.objects.create(
        tenant=instance.tenant,
        actor=actor,
        actor_type=actor_type,
        object_type=object_type,
        object_id=str(instance.id),
        action=action,
        outcome=outcome,
        error_code=error_code,
        permission_code=permission,
        from_status=before,
        to_status=instance.status,
        reason=reason[:500],
        idempotency_key_hash=key_hash(idempotency_key),
        request_id=str(uuid.uuid4()),
        version=instance.version,
        evidence_refs=evidence_refs or [],
    )


def _check_version(instance, version):
    if instance.version != version:
        error = StateConflict("The workflow version changed; refresh before retrying.")
        error.error_code = ErrorCode.VERSION_CONFLICT
        raise error


def _check_replay(instance, action, idempotency_key):
    object_type, _ = RESOURCE_META[type(instance)]
    event = PilotAuditEvent.objects.filter(tenant=instance.tenant, idempotency_key_hash=key_hash(idempotency_key)).first()
    if not event:
        return False
    if event.object_type != object_type or event.object_id != str(instance.id) or event.action != action:
        error = StateConflict("Idempotency key belongs to another request.")
        error.error_code = ErrorCode.IDEMPOTENCY_CONFLICT
        raise error
    return event.outcome == PilotAuditEvent.Outcome.SUCCESS


@transaction.atomic
def expire_if_needed(instance):
    if not isinstance(instance, (SecurityReview, EntryDecision)):
        return instance, False
    instance = type(instance).objects.select_for_update().get(pk=instance.pk)
    active = {"draft", "submitted", "approved"}
    if instance.status not in active or timezone.now() < instance.expires_at:
        return instance, False
    before = instance.status
    instance.status = "expired"
    instance.expired_at = timezone.now()
    instance.version += 1
    save_controlled(instance, ["status", "expired_at", "version"])
    _audit(
        instance,
        actor=None,
        actor_type="system",
        action="expire",
        permission="system",
        before=before,
        reason="Resource reached its frozen expires_at boundary.",
        idempotency_key=f"expire:{RESOURCE_META[type(instance)][0]}:{instance.id}:{instance.version}",
    )
    return instance, True


def expire_queryset(queryset):
    if queryset.model not in (SecurityReview, EntryDecision):
        return queryset
    for item in list(queryset.filter(status__in=("draft", "submitted", "approved"), expires_at__lte=timezone.now())):
        expire_if_needed(item)
    return queryset


def _finance_boundary(user, data):
    is_finance = data.get("review_type") == SecurityReview.ReviewType.FINANCE_BOUNDARY
    finance_scope = data.get("finance_scope")
    if is_finance and not finance_scope:
        raise ContractViolation(
            "Finance boundary review requires finance_scope.",
            error_code=ErrorCode.VALIDATION_ERROR,
            status_code=422,
        )
    if not is_finance and finance_scope is not None:
        raise ContractViolation(
            "Non-finance review requires finance_scope=null.",
            error_code=ErrorCode.VALIDATION_ERROR,
            status_code=422,
        )
    if is_finance:
        finance_values_allowed(user, finance_scope)


def _validate_controlled_references(actor, environment, evidence_refs, *, target_alias=None):
    references = set(evidence_refs or [])
    registered = set(PilotEvidenceReference.objects.filter(
        tenant=actor.tenant,
        environment=environment,
        status="controlled",
        reference__in=references,
    ).values_list("reference", flat=True))
    if registered != references:
        raise ContractViolation(
            "Evidence references must be registered for the current tenant and environment.",
            error_code=ErrorCode.VALIDATION_ERROR,
            status_code=422,
        )
    if target_alias and not PilotTargetAlias.objects.filter(
        tenant=actor.tenant,
        environment=environment,
        status="controlled",
        alias=target_alias,
    ).exists():
        raise ContractViolation(
            "Verification target_alias is not registered for the current tenant and environment.",
            error_code=ErrorCode.VALIDATION_ERROR,
            status_code=422,
        )


@transaction.atomic
def create_resource(model, *, actor, environment, data, idempotency_key, permission):
    digest = key_hash(idempotency_key)
    existing = model.objects.filter(tenant=actor.tenant, idempotency_key_hash=digest).first()
    if existing:
        comparable = {field: value for field, value in data.items() if hasattr(existing, field)}
        if existing.environment_id != environment.id or any(getattr(existing, field) != value for field, value in comparable.items()):
            error = StateConflict("Idempotency key was reused with a different UI-P8 request.")
            error.error_code = ErrorCode.IDEMPOTENCY_CONFLICT
            raise error
        return existing, True
    if model is SecurityReview:
        _finance_boundary(actor, data)
    if model in (SecurityReview, VerificationRun, PerformanceRun):
        _validate_controlled_references(
            actor,
            environment,
            data.get("evidence_refs"),
            target_alias=data.get("target_alias") if model is VerificationRun else None,
        )
    code_prefix = {
        SecurityReview: "SEC",
        VerificationRun: "VER",
        PerformanceRun: "PERF",
        EntryDecision: "ENTRY",
    }[model]
    instance = model(
        tenant=actor.tenant,
        environment=environment,
        code=f"{code_prefix}-{uuid.uuid4().hex[:12].upper()}",
        creator=actor,
        owner=actor,
        idempotency_key_hash=digest,
        **data,
    )
    instance._pilot_state_service_write = True
    try:
        instance.save(force_insert=True)
    finally:
        instance._pilot_state_service_write = False
    if model is EntryDecision:
        _authorized_references(actor, instance)
    _audit(instance, actor=actor, action="create", permission=permission, before="", reason="Create controlled UI-P8 draft.", idempotency_key=idempotency_key)
    return instance, False


@transaction.atomic
def patch_resource(instance, *, actor, data, permission):
    instance = type(instance).objects.select_for_update().get(pk=instance.pk, tenant=actor.tenant)
    instance, expired = expire_if_needed(instance)
    if expired or instance.status != "draft":
        raise StateConflict("Only an unexpired draft can be patched.")
    _check_version(instance, data.pop("version"))
    if isinstance(instance, SecurityReview):
        target_review_type = data.get("review_type", instance.review_type)
        if (
            instance.review_type == SecurityReview.ReviewType.FINANCE_BOUNDARY
            and target_review_type != SecurityReview.ReviewType.FINANCE_BOUNDARY
            and "finance_scope" not in data
        ):
            raise ContractViolation(
                "Leaving finance_boundary requires explicit finance_scope=null.",
                error_code=ErrorCode.VALIDATION_ERROR,
                status_code=422,
            )
        merged = {
            "review_type": target_review_type,
            "finance_scope": data.get("finance_scope", instance.finance_scope),
        }
        _finance_boundary(actor, merged)
        expires_at = data.get("expires_at", instance.expires_at)
        if not timezone.now() < expires_at <= timezone.now() + timedelta(days=180):
            raise ContractViolation("expires_at must be within the next 180 days.", error_code=ErrorCode.VALIDATION_ERROR, status_code=422)
    if isinstance(instance, VerificationRun):
        planned_start = data.get("planned_start_at", instance.planned_start_at)
        planned_end = data.get("planned_end_at", instance.planned_end_at)
        if planned_end <= planned_start:
            raise ContractViolation("planned_end_at must be later than planned_start_at.", error_code=ErrorCode.VALIDATION_ERROR, status_code=422)
    if isinstance(instance, EntryDecision):
        expires_at = data.get("expires_at", instance.expires_at)
        if not timezone.now() < expires_at <= timezone.now() + timedelta(days=30):
            raise ContractViolation("expires_at must be within the next 30 days.", error_code=ErrorCode.VALIDATION_ERROR, status_code=422)
    target_environment = data.get("environment", instance.environment)
    if isinstance(instance, (SecurityReview, VerificationRun, PerformanceRun)):
        _validate_controlled_references(
            actor,
            target_environment,
            data.get("evidence_refs", instance.evidence_refs),
            target_alias=data.get("target_alias", instance.target_alias) if isinstance(instance, VerificationRun) else None,
        )
    before_environment = instance.environment.code
    changed = []
    for field, value in data.items():
        setattr(instance, field, value)
        changed.append(field)
    instance.version += 1
    save_controlled(instance, [*changed, "version"])
    if isinstance(instance, EntryDecision):
        _authorized_references(actor, instance)
    _audit(
        instance,
        actor=actor,
        action="patch",
        permission=permission,
        before=instance.status,
        reason=f"Draft metadata updated; environment {before_environment}->{instance.environment.code}.",
        idempotency_key=f"patch:{instance.pk}:{instance.version}:{uuid.uuid4().hex}",
    )
    return instance


def _source_payload(resource_type, instance):
    evidence = getattr(instance, "evidence_refs", [])
    digest = hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest()
    return {
        "resource_type": resource_type,
        "resource_id": instance.id,
        "resource_version": instance.version,
        "status": instance.status,
        "evidence_digest": digest,
        "refreshed_at": instance.updated_at.isoformat() if instance.updated_at else None,
        "expires_at": getattr(instance, "expires_at", None).isoformat() if getattr(instance, "expires_at", None) else None,
    }


def _authorized_references(actor, decision):
    definitions = (
        ("security_review", SecurityReview, "security_review_ids", "pilot.security_review.view", "security_review_ids"),
        ("verification_run", VerificationRun, "verification_run_ids", "pilot.verification.view", "verification_run_ids"),
        ("performance_run", PerformanceRun, "performance_run_ids", "pilot.performance.view", "performance_run_ids"),
        ("recovery_plan", RecoveryPlan, "recovery_plan_ids", "pilot.recovery.view", "recovery_plan_ids"),
        ("release_plan", ReleasePlan, "release_plan_ids", "pilot.release.view", "release_plan_ids"),
    )
    sources = []
    blockers = []
    for resource_type, model, field, permission, scope_key in definitions:
        if not check_user_permission(actor, permission):
            raise DataScopeDenied(f"Cross-resource evidence requires {permission}.", error_code=ErrorCode.PERMISSION_DENIED)
        ids = getattr(decision, field)
        if model in (RecoveryPlan, ReleasePlan):
            queryset = filter_plan_queryset(
                actor,
                model.objects.filter(tenant=actor.tenant, environment=decision.environment),
                permission,
                plan_key=scope_key,
                channel_field="release_channel" if model is ReleasePlan else None,
            )
        else:
            queryset = filter_resource_queryset(
                actor,
                model.objects.filter(environment=decision.environment),
                permission,
                scope_key,
            )
        found = {item.id: item for item in queryset.filter(pk__in=ids)}
        if set(found) != set(ids):
            raise DataScopeDenied("Referenced evidence is missing or outside the caller scope.", error_code=ErrorCode.DATA_SCOPE_INVALID)
        for resource_id in ids:
            item = found[resource_id]
            if isinstance(item, (SecurityReview, EntryDecision)):
                item, _ = expire_if_needed(item)
            sources.append(_source_payload(resource_type, item))
            valid_status = {
                "security_review": {"approved"},
                "verification_run": {"passed"},
                "performance_run": {"passed"},
                "recovery_plan": {"approved", "scheduled", "success"},
                "release_plan": {"approved", "scheduled", "success"},
            }[resource_type]
            if item.status not in valid_status:
                blockers.append({"code": "EVIDENCE_NOT_READY", "message": f"{resource_type} {item.id} is {item.status}.", "source_type": resource_type, "source_id": item.id})
    return sources, blockers


def _snapshot_identity(source):
    return {
        "resource_type": source.get("resource_type"),
        "resource_id": source.get("resource_id"),
        "resource_version": source.get("resource_version"),
        "status": source.get("status"),
        "evidence_digest": source.get("evidence_digest"),
        "expires_at": str(source.get("expires_at")) if source.get("expires_at") else None,
    }


def _revalidate_entry_snapshot(actor, instance):
    current_sources, blockers = _authorized_references(actor, instance)
    snapshot_sources = (instance.evidence_snapshot or {}).get("sources", [])
    current = [_snapshot_identity(item) for item in current_sources]
    frozen = [_snapshot_identity(item) for item in snapshot_sources]
    if current != frozen:
        raise StateConflict("Entry evidence changed after submission; refresh and submit a new decision.")
    if instance.decision == "go" and blockers:
        raise StateConflict("A go decision requires all evidence to remain valid at approval time.")


@transaction.atomic
def transition_resource(instance, *, actor, action, data, permission, idempotency_key):
    instance = type(instance).objects.select_for_update().get(pk=instance.pk, tenant=actor.tenant)
    instance, expired = expire_if_needed(instance)
    if expired:
        raise StateConflict("The workflow resource expired before this action.")
    if _check_replay(instance, action, idempotency_key):
        return instance, True
    _check_version(instance, data["version"])
    before = instance.status
    reason = data.get("reason") or data.get("review_reason") or data.get("cancel_reason")
    fields = []

    if action == "submit":
        if before != "draft":
            raise StateConflict("Only drafts can be submitted.")
        if isinstance(instance, SecurityReview):
            _finance_boundary(actor, {"review_type": instance.review_type, "finance_scope": instance.finance_scope})
        if isinstance(instance, EntryDecision):
            sources, blockers = _authorized_references(actor, instance)
            snapshot = {"captured_at": timezone.now().isoformat(), "contract_version": CONTRACT_VERSION, "sources": sources}
            instance.evidence_snapshot = snapshot
            instance.evidence_hash = hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()
            instance.blockers = blockers
            instance.warnings = []
            instance.contract_version = CONTRACT_VERSION
            fields += ["evidence_snapshot", "evidence_hash", "blockers", "warnings", "contract_version"]
        instance.status = "submitted"
        fields.append("status")
    elif action in {"approve", "reject"}:
        if before != "submitted":
            raise StateConflict("Only submitted resources can be reviewed.")
        if instance.creator_id == actor.id:
            error = StateConflict("Creator and reviewer must be different users.")
            error.error_code = ErrorCode.SEPARATION_OF_DUTIES
            raise error
        if isinstance(instance, SecurityReview):
            _finance_boundary(actor, {"review_type": instance.review_type, "finance_scope": instance.finance_scope})
        if isinstance(instance, EntryDecision) and action == "approve":
            _revalidate_entry_snapshot(actor, instance)
        instance.status = "approved" if action == "approve" else "rejected"
        instance.reviewer = actor
        instance.review_reason = data["review_reason"]
        instance.reviewed_at = timezone.now()
        fields += ["status", "reviewer", "review_reason", "reviewed_at"]
    elif action == "cancel":
        if not isinstance(instance, (VerificationRun, PerformanceRun)) or before not in {"draft", "submitted", "approved"}:
            raise StateConflict("This workflow cannot be cancelled from its current state.")
        if before in {"submitted", "approved"} and instance.creator_id == actor.id:
            error = StateConflict("Creator cannot cancel a submitted or approved run.")
            error.error_code = ErrorCode.SEPARATION_OF_DUTIES
            raise error
        instance.status = "cancelled"
        fields.append("status")
    elif action == "record-result":
        if not isinstance(instance, (VerificationRun, PerformanceRun)) or before != "approved":
            raise StateConflict("Only approved runs can record results.")
        if instance.reviewer_id == actor.id:
            error = StateConflict("Reviewer cannot record the result.")
            error.error_code = ErrorCode.SEPARATION_OF_DUTIES
            raise error
        if isinstance(instance, VerificationRun):
            _validate_controlled_references(actor, instance.environment, data["evidence_refs"], target_alias=instance.target_alias)
            instance.status = data["result"]
            for field in ("result_summary", "evidence_refs", "started_at", "finished_at", "error_code", "error_message"):
                setattr(instance, field, data[field] or "" if field in {"error_code", "error_message"} else data[field])
            fields += ["status", "result_summary", "evidence_refs", "started_at", "finished_at", "error_code", "error_message"]
        else:
            _validate_controlled_references(actor, instance.environment, data["evidence_refs"])
            if data["result_mode"] == "manual_required":
                instance.status = "manual_required"
            else:
                thresholds = instance.thresholds
                instance.status = "passed" if (
                    data["p95_ms"] <= Decimal(str(thresholds["p95_ms_max"]))
                    and data["error_rate"] <= Decimal(str(thresholds["error_rate_max"]))
                    and data["cpu_percent"] <= Decimal(str(thresholds["cpu_percent_max"]))
                    and data["memory_percent"] <= Decimal(str(thresholds["memory_percent_max"]))
                ) else "failed"
            for field in ("p50_ms", "p95_ms", "error_rate", "cpu_percent", "memory_percent", "result_summary", "evidence_refs"):
                setattr(instance, field, data[field])
            fields += ["status", "p50_ms", "p95_ms", "error_rate", "cpu_percent", "memory_percent", "result_summary", "evidence_refs"]
        instance.recorder = actor
        fields.append("recorder")
    else:
        raise StateConflict("Unsupported UI-P8 action.")

    instance.version += 1
    fields.append("version")
    save_controlled(instance, fields)
    _audit(instance, actor=actor, action=action, permission=permission, before=before, reason=reason, idempotency_key=idempotency_key, evidence_refs=data.get("evidence_refs"))
    return instance, False


def control_room_payload(*, user, environment, as_of):
    security = SecurityReview.objects.filter(tenant=user.tenant, environment=environment)
    for item in security.filter(expires_at__lte=as_of, status__in=("draft", "submitted", "approved")):
        expire_if_needed(item)
    verification = VerificationRun.objects.filter(tenant=user.tenant, environment=environment)
    performance = PerformanceRun.objects.filter(tenant=user.tenant, environment=environment)
    entries = EntryDecision.objects.filter(tenant=user.tenant, environment=environment)
    for item in entries.filter(expires_at__lte=as_of, status__in=("draft", "submitted", "approved")):
        expire_if_needed(item)
    approved_entry = entries.filter(status="approved", decision="go", expires_at__gt=as_of).order_by("-reviewed_at").first()
    blockers = []
    if not security.filter(status="approved", expires_at__gt=as_of).exists():
        blockers.append({"code": "SECURITY_REVIEW_MISSING", "message": "No valid approved security review.", "source_type": "security_review", "source_id": None})
    if not verification.filter(status="passed").exists():
        blockers.append({"code": "VERIFICATION_MISSING", "message": "No passed controlled verification.", "source_type": "verification_run", "source_id": None})
    if not performance.filter(status="passed").exists():
        blockers.append({"code": "PERFORMANCE_MISSING", "message": "No passed performance evidence.", "source_type": "performance_run", "source_id": None})
    if not approved_entry:
        blockers.append({"code": "ENTRY_DECISION_MISSING", "message": "No valid approved go decision.", "source_type": "entry_decision", "source_id": None})
    return {
        "environment": environment.code,
        "capability_status": "pending",
        "readiness_status": "blocked" if blockers else "ready",
        "readiness_score": max(Decimal("0"), Decimal("100") - Decimal(len(blockers) * 25)),
        "gate_summary": [],
        "blockers": blockers,
        "warnings": [],
        "evidence_counts": {
            "security_reviews": security.count(),
            "verification_runs": verification.count(),
            "performance_runs": performance.count(),
            "recovery_plans": RecoveryPlan.objects.filter(tenant=user.tenant, environment=environment).count(),
            "release_plans": ReleasePlan.objects.filter(tenant=user.tenant, environment=environment).count(),
        },
        "stale_sources": [],
        "contract_version": CONTRACT_VERSION,
        "refreshed_at": as_of,
    }


def audit_failure(*, user, object_type, object_id, action, permission, exc, request_id, idempotency_key, version=0, from_status=""):
    """Persist a sanitized failed-attempt audit after the request transaction rolls back."""

    if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "tenant_id", None):
        return None
    status_code = int(getattr(exc, "status_code", 500))
    contract_error_codes = {
        403: ErrorCode.PERMISSION_DENIED,
        409: ErrorCode.STATE_CONFLICT,
        422: ErrorCode.VALIDATION_ERROR,
    }
    error_code = str(
        getattr(exc, "error_code", None)
        or contract_error_codes.get(status_code)
        or getattr(exc, "default_code", None)
        or ErrorCode.INTERNAL_ERROR
    )
    reason = str(getattr(exc, "detail", None) or "UI-P8 request failed.")[:500]
    unique_request = request_id or str(uuid.uuid4())
    return PilotAuditEvent.objects.create(
        tenant=user.tenant,
        actor=user,
        actor_type="user",
        object_type=object_type,
        object_id=str(object_id),
        action=action,
        outcome=PilotAuditEvent.Outcome.FAILED,
        error_code=error_code,
        permission_code=permission or "unknown",
        from_status=from_status,
        to_status=from_status,
        reason=reason,
        idempotency_key_hash=key_hash(f"failed:{idempotency_key or 'none'}:{unique_request}"),
        request_id=unique_request,
        version=max(int(version or 0), 0),
        evidence_refs=[],
    )
