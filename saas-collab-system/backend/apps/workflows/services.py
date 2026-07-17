import hashlib
import hmac
import json
import time

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import CustomUser
from apps.common.exceptions import BusinessRuleViolation, StateConflict
from apps.common.security import sanitize_sensitive_data
from apps.tenants.models import Tenant

from .models import ApprovalRequest, BusinessException, CollaborationEvent, WorkflowAuditEvent


def write_workflow_audit(resource, *, resource_type, actor, action, from_status="", to_status="", detail=None):
    return WorkflowAuditEvent.objects.create(
        tenant=resource.tenant,
        resource_type=resource_type,
        resource_id=str(resource.id),
        actor=actor,
        action=action,
        from_status=from_status,
        to_status=to_status,
        masked_detail=sanitize_sensitive_data(detail or {}),
    )


@transaction.atomic
def create_mock_approval(*, user, **payload):
    approval, created = ApprovalRequest.objects.get_or_create(
        tenant=user.tenant,
        idempotency_key=payload["idempotency_key"],
        defaults={**payload, "requested_by": user},
    )
    if not created:
        comparable = (approval.approval_type, approval.business_type, approval.business_id)
        incoming = (payload["approval_type"], payload["business_type"], payload["business_id"])
        if comparable != incoming:
            raise StateConflict("The approval idempotency key is already used by another request.")
        return approval, False
    approval.full_clean()
    write_workflow_audit(
        approval,
        resource_type="approval",
        actor=user,
        action="submit_mock",
        to_status=approval.status,
        detail={"approval_type": approval.approval_type, "business_type": approval.business_type},
    )
    return approval, True


@transaction.atomic
def review_approval(*, approval, actor, action, note=""):
    approval = ApprovalRequest.objects.select_for_update().get(pk=approval.pk, tenant=actor.tenant)
    if approval.status != ApprovalRequest.Status.PENDING:
        raise StateConflict("Only pending approvals can be reviewed.")
    if action in {"approve", "reject"} and approval.requested_by_id == actor.id:
        raise BusinessRuleViolation("The requester cannot review their own approval.")
    if action == "withdraw" and approval.requested_by_id != actor.id:
        raise PermissionDenied("Only the requester can withdraw this approval.")
    target = {
        "approve": ApprovalRequest.Status.APPROVED,
        "reject": ApprovalRequest.Status.REJECTED,
        "withdraw": ApprovalRequest.Status.WITHDRAWN,
    }.get(action)
    if not target:
        raise ValidationError("Unsupported approval action.")
    before = approval.status
    approval.status = target
    approval.decision_note = note
    approval.reviewed_by = actor if action != "withdraw" else None
    approval.decided_at = timezone.now()
    approval.full_clean()
    approval.save(update_fields=["status", "decision_note", "reviewed_by", "decided_at", "updated_at"])
    write_workflow_audit(
        approval,
        resource_type="approval",
        actor=actor,
        action=action,
        from_status=before,
        to_status=target,
        detail={"note": note},
    )
    return approval


@transaction.atomic
def create_mock_exception(*, user, **payload):
    exception = BusinessException.objects.create(tenant=user.tenant, created_by=user, **payload)
    exception.full_clean()
    write_workflow_audit(
        exception,
        resource_type="exception",
        actor=user,
        action="create_mock",
        to_status=exception.status,
        detail={"module": exception.module, "severity": exception.severity},
    )
    return exception


@transaction.atomic
def assign_exception(*, exception, actor, assignee_id):
    exception = BusinessException.objects.select_for_update().get(pk=exception.pk, tenant=actor.tenant)
    if exception.status not in {BusinessException.Status.OPEN, BusinessException.Status.ASSIGNED}:
        raise StateConflict("Only open or assigned exceptions can be assigned.")
    assignee = CustomUser.objects.filter(
        pk=assignee_id,
        tenant=actor.tenant,
        user_type=CustomUser.UserType.INTERNAL,
        is_active=True,
    ).first()
    if not assignee:
        raise ValidationError({"assignee_id": "Assignee must be an active internal user in the same tenant."})
    before = exception.status
    exception.assigned_to = assignee
    exception.status = BusinessException.Status.ASSIGNED
    exception.full_clean()
    exception.save(update_fields=["assigned_to", "status", "updated_at"])
    write_workflow_audit(
        exception,
        resource_type="exception",
        actor=actor,
        action="assign",
        from_status=before,
        to_status=exception.status,
        detail={"assignee_id": assignee.id},
    )
    return exception


@transaction.atomic
def resolve_exception(*, exception, actor, resolution):
    exception = BusinessException.objects.select_for_update().get(pk=exception.pk, tenant=actor.tenant)
    if exception.status not in {BusinessException.Status.OPEN, BusinessException.Status.ASSIGNED}:
        raise StateConflict("Only open or assigned exceptions can be resolved.")
    before = exception.status
    exception.status = BusinessException.Status.RESOLVED
    exception.resolution = resolution
    exception.resolved_at = timezone.now()
    exception.save(update_fields=["status", "resolution", "resolved_at", "updated_at"])
    write_workflow_audit(
        exception,
        resource_type="exception",
        actor=actor,
        action="resolve",
        from_status=before,
        to_status=exception.status,
        detail={"resolution": resolution},
    )
    return exception


@transaction.atomic
def close_exception(*, exception, actor):
    exception = BusinessException.objects.select_for_update().get(pk=exception.pk, tenant=actor.tenant)
    if exception.status != BusinessException.Status.RESOLVED:
        raise StateConflict("Only resolved exceptions can be closed.")
    before = exception.status
    exception.status = BusinessException.Status.CLOSED
    exception.closed_at = timezone.now()
    exception.save(update_fields=["status", "closed_at", "updated_at"])
    write_workflow_audit(
        exception,
        resource_type="exception",
        actor=actor,
        action="close",
        from_status=before,
        to_status=exception.status,
    )
    return exception


def _canonical_payload(payload):
    return json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@transaction.atomic
def receive_mock_collaboration_event(*, channel, headers, payload):
    if getattr(settings, "UI_P4_COLLABORATION_MODE", "mock") != "mock":
        raise PermissionDenied("UI-P4 collaboration callbacks are disabled outside mock mode.")
    tenant_code = headers.get("X-UI-P4-Tenant", "")
    event_id = headers.get("X-UI-P4-Event-Id", "")
    timestamp_text = headers.get("X-UI-P4-Timestamp", "")
    signature = headers.get("X-UI-P4-Signature", "")
    if not all((tenant_code, event_id, timestamp_text, signature)):
        raise ValidationError("Required UI-P4 mock callback headers are missing.")
    try:
        timestamp = int(timestamp_text)
    except ValueError as exc:
        raise ValidationError("Callback timestamp must be an integer.") from exc
    if abs(int(time.time()) - timestamp) > 300:
        raise PermissionDenied("Callback timestamp is outside the allowed window.")
    tenant = Tenant.objects.filter(code=tenant_code, status=Tenant.Status.ACTIVE).first()
    if not tenant:
        raise PermissionDenied("Callback tenant is invalid.")
    payload_text = _canonical_payload(payload)
    payload_hash = hashlib.sha256(payload_text.encode()).hexdigest()
    signing_value = f"{tenant_code}:{event_id}:{timestamp_text}:{payload_hash}"
    expected = hmac.new(
        settings.UI_P4_MOCK_WEBHOOK_SECRET.encode(),
        signing_value.encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise PermissionDenied("Callback signature is invalid.")
    existing = CollaborationEvent.objects.filter(tenant=tenant, channel=channel, event_id=event_id).first()
    if existing:
        if existing.payload_hash != payload_hash:
            raise StateConflict("The callback event id was replayed with a different payload.")
        return existing, False
    summary = sanitize_sensitive_data({
        "subject": payload.get("subject", "") if isinstance(payload, dict) else "",
        "action": payload.get("action", "") if isinstance(payload, dict) else "",
        "reference": payload.get("reference", "") if isinstance(payload, dict) else "",
    })
    event = CollaborationEvent.objects.create(
        tenant=tenant,
        channel=channel,
        event_id=event_id,
        event_type=str(payload.get("event_type", "mock_feedback"))[:80] if isinstance(payload, dict) else "mock_feedback",
        payload_hash=payload_hash,
        masked_summary=summary,
    )
    write_workflow_audit(
        event,
        resource_type="collaboration",
        actor=None,
        action="receive_mock",
        to_status=event.status,
        detail={"channel": channel, "payload_hash": payload_hash},
    )
    return event, True


@transaction.atomic
def decide_collaboration_event(*, event, actor, action, note=""):
    event = CollaborationEvent.objects.select_for_update().get(pk=event.pk, tenant=actor.tenant)
    if event.status != CollaborationEvent.Status.PENDING_CONFIRMATION:
        raise StateConflict("Only pending collaboration feedback can be reviewed.")
    target = {
        "confirm": CollaborationEvent.Status.CONFIRMED,
        "reject": CollaborationEvent.Status.REJECTED,
    }.get(action)
    if not target:
        raise ValidationError("Unsupported collaboration action.")
    before = event.status
    event.status = target
    event.confirmed_by = actor
    event.decision_note = note
    event.processed_at = timezone.now()
    event.save(update_fields=["status", "confirmed_by", "decision_note", "processed_at"])
    write_workflow_audit(
        event,
        resource_type="collaboration",
        actor=actor,
        action=action,
        from_status=before,
        to_status=target,
        detail={"note": note, "business_write": False},
    )
    return event
