import hashlib
import hmac
import json
import time

from django.conf import settings
from django.db import transaction, models
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import CustomUser
from apps.common.exceptions import BusinessRuleViolation, StateConflict
from apps.common.security import sanitize_sensitive_data
from apps.tenants.models import Tenant

from .models import ApprovalRequest, BusinessException, CollaborationEvent, WorkflowAuditEvent


def resolve_payment_flow(*, actor, sources):
    from .models import PaymentApprovalFlow
    from apps.permissions.services import check_user_permission, user_has_finance_permission
    from apps.workflows.permissions import scope_allows_value
    from apps.accounts.models import InternalUserProfile
    department_id = InternalUserProfile.objects.filter(user_id=actor.pk).values_list("department_id", flat=True).first()
    flows = []
    for source_kind, source_id, amount, nature, is_business_source in sources:
        matches = list(PaymentApprovalFlow.objects.filter(
            tenant_id=actor.tenant_id, payment_kind=source_kind, nature=nature,
            department_key__in=["", str(department_id or "")], published=True, active=True,
            minimum_amount__lte=amount,
        ).filter(models.Q(maximum_amount__isnull=True) | models.Q(maximum_amount__gte=amount)))
        if len(matches) != 1:
            raise ValidationError("付款审批流程未配置或匹配到多个规则，请联系管理员维护流程。")
        flows.append(matches[0])
    if not flows:
        raise ValidationError("付款批次没有可审批的付款来源。")
    reviewers = {flow.reviewer_id for flow in flows}
    if len(reviewers) != 1:
        raise ValidationError("批次中不同付款来源匹配到不同审批人，请拆分批次或调整流程规则。")
    flow = flows[0]
    reviewer = flow.reviewer
    if reviewer.tenant_id != actor.tenant_id or reviewer.user_type != CustomUser.UserType.INTERNAL or not reviewer.is_active or reviewer.pk == actor.pk:
        raise ValidationError("流程指定审批人无效或与申请人相同。")
    from apps.permissions.ui_p6_scopes import finance_values_allowed
    if (not check_user_permission(reviewer, "workflow.approvals.review") or
        not check_user_permission(reviewer, "workflow.approvals.view") or
        not scope_allows_value(reviewer, "workflow.approvals.review", "approval_types", "finance") or
        not scope_allows_value(reviewer, "workflow.approvals.view", "approval_types", "finance") or
        not check_user_permission(reviewer, "supply.v2.view") or
        not check_user_permission(reviewer, "supply.v2.manage") or
        not user_has_finance_permission(reviewer, "finance.reconcile") or
        not finance_values_allowed(reviewer, "finance.reconcile", platform="", currency="CNY")):
        raise ValidationError("指定审批人缺少审批查看、审批处理、付款业务查看/管理或财务入账权限。")
    from apps.supply_chain.costs import _payment_owner
    for source_kind, source_id, _amount, _nature, is_business_source in sources:
        if not is_business_source:
            continue
        try:
            _payment_owner(reviewer, source_kind, source_id, "supply.v2.view")
            _payment_owner(reviewer, source_kind, source_id, "supply.v2.manage")
        except Exception as exc:
            raise ValidationError("指定审批人无权查看或管理本次付款来源，无法创建审批流程。") from exc
    return flow, flows


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


def review_approval(*, approval, actor, action, note="", payment=None):
    if approval.business_type == "order_registration":
        from apps.sales_management.registration_models import OrderRegistration
        from apps.sales_management.registration_services import registration_action

        registration = OrderRegistration.objects.filter(pk=approval.business_id, tenant=actor.tenant).first() if str(approval.business_id).isdigit() else None
        if not registration or registration.approval_id != approval.pk:
            raise StateConflict("This is not the current registration approval.")
        return registration_action(actor, registration.kind, registration.pk, action, note, expected_approval_id=approval.pk).approval
    return _review_approval(approval=approval, actor=actor, action=action, note=note, payment=payment)


@transaction.atomic
def _review_approval(*, approval, actor, action, note="", payment=None):
    is_payment = approval.business_type in ('supply_payment_request', 'supply_payment_batch')
    if is_payment:
        from apps.supply_chain import services as supply_services
        supply_services._tenant_lock(actor)
    approval = ApprovalRequest.objects.select_for_update().get(pk=approval.pk, tenant=actor.tenant)
    if approval.business_type == "supply_payment_request" and action in {"approve", "reject"}:
        from apps.supply_chain.payment_request_models import SupplyPaymentRequest
        from apps.supply_chain.costs import _payment_owner
        row = SupplyPaymentRequest.objects.filter(tenant_id=actor.tenant_id, approval=approval).first()
        if row:
            _payment_owner(actor, row.kind, row.source_id, "supply.v2.view")
    if approval.business_type == "supply_payment_batch" and action in {"approve", "reject"}:
        from apps.supply_chain.payment_request_models import SupplyPaymentBatch
        from apps.supply_chain.costs import _payment_owner
        batch = SupplyPaymentBatch.objects.filter(tenant_id=actor.tenant_id, approval=approval).first()
        if not batch or not batch.lines.exists():
            raise PermissionDenied("Payment batch sources are unavailable.")
        for row in batch.lines.all():
            _payment_owner(actor, row.kind, row.source_id, "supply.v2.view")
    if is_payment and action == 'approve' and approval.status == ApprovalRequest.Status.APPROVED:
        # Repeated approval never posts again. Legacy approved/unposted items use confirm.
        return approval
    if approval.status != ApprovalRequest.Status.PENDING:
        raise StateConflict("Only pending approvals can be reviewed.")
    if action in {"approve", "reject"} and approval.requested_by_id == actor.id:
        raise BusinessRuleViolation("The requester cannot review their own approval.")
    if action in {"approve", "reject"} and approval.designated_reviewer_id and approval.designated_reviewer_id != actor.id:
        raise PermissionDenied("Only the designated reviewer can review this approval.")
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
    if is_payment and action == 'approve':
        from apps.supply_chain.payment_request_evidence import ConfirmInput, post_request
        from apps.supply_chain.payment_request_models import SupplyPaymentRequest, SupplyPaymentBatch
        if payment is None:
            raise ValidationError({'payment': '请填写实际付款日期、核对版本并上传转账凭证。'})
        data = ConfirmInput(data=payment)
        data.is_valid(raise_exception=True)
        if approval.business_type == 'supply_payment_request':
            row = SupplyPaymentRequest.objects.select_for_update().filter(tenant_id=actor.tenant_id, approval=approval).first()
            if row is None or row.batch_id:
                raise ValidationError('付款申请不存在或属于批次。')
            post_request(actor, row, data.validated_data)
        else:
            from apps.supply_chain.payment_batches import post_batch
            batch = SupplyPaymentBatch.objects.select_for_update().get(tenant_id=actor.tenant_id, approval=approval)
            lines = list(batch.lines.select_for_update().order_by('pk'))
            post_batch(actor, batch, lines, data.validated_data)
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
