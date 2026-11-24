"""Secure state reconciliation for Feishu native approval_instance events."""
from django.db import transaction
from django.utils import timezone

from apps.workflows.models import ApprovalRequest
from apps.workflows.services import write_workflow_audit
from apps.tenants.models import Tenant
from .feishu_native_client import FeishuNativeClient
from .models import FeishuConnection, FeishuOperation
from .feishu_approval_models import FeishuApprovalInstance


def _reconcile_approval_event(tenant_id, event_id, event, *, client=None):
    """Fetch provider truth before updating the linked payment approval."""
    if not isinstance(event, dict):
        raise ValueError("invalid event")
    app_id, instance_code, approval_code = event.get("app_id"), event.get("instance_code"), event.get("approval_code")
    if not all(isinstance(x, str) and x for x in (app_id, instance_code, approval_code)):
        raise ValueError("incomplete event")
    connection = FeishuConnection.objects.filter(tenant_id=tenant_id, enabled=True, app_id=app_id).first()
    if not connection or not connection.encrypt_key_ref:
        raise ValueError("unconfigured native callback")
    instance = FeishuApprovalInstance.objects.select_related("approval", "mapping").filter(
        tenant_id=tenant_id, instance_code=instance_code, approval_code=approval_code,
        mapping__tenant_id=tenant_id,
        approval__tenant_id=tenant_id,
        approval__business_type__in=("supply_payment_request", "supply_payment_batch"),
    ).first()
    authoritative = None
    if instance is None:
        # Reconcile early events from provider truth, never from the event UUID.
        if not FeishuApprovalInstance.objects.filter(tenant_id=tenant_id, app_id=app_id,
                approval_code=approval_code, instance_code__isnull=True).exists():
            return "ignored"
        authoritative = (client or FeishuNativeClient()).get_instance(connection, instance_code)
        provider_uuid = authoritative.get("uuid")
        if not isinstance(provider_uuid, str):
            raise ValueError("missing submission uuid")
        instance = FeishuApprovalInstance.objects.select_related("approval", "mapping").filter(
            tenant_id=tenant_id, submission_uuid=provider_uuid, instance_code__isnull=True,
            app_id=app_id, approval_code=approval_code, approval__tenant_id=tenant_id,
            approval__business_type__in=("supply_payment_request", "supply_payment_batch"),
            approval__workflow_snapshot__approval_provider="feishu",
        ).first()
    if not instance:
        return "ignored"
    if instance.app_id != app_id:
        raise ValueError("application mismatch")
    authoritative = authoritative or (client or FeishuNativeClient()).get_instance(connection, instance_code)
    if (authoritative.get("instance_code") != instance_code or authoritative.get("approval_code") != approval_code
            or authoritative.get("open_id") != instance.payload.get("open_id")
            or authoritative.get("uuid") != str(instance.submission_uuid)):
        raise ValueError("provider instance mismatch")
    status = "REVERTED" if authoritative.get("reverted") is True else authoritative.get("status")
    if status not in {"PENDING", "APPROVED", "REJECTED", "CANCELED", "DELETED", "REVERTED"}:
        raise ValueError("unknown provider status")
    if status in {"APPROVED", "REJECTED"}:
        tasks = authoritative.get("task_list") or []
        reviewer = instance.reviewer_open_id
        if not isinstance(tasks, list) or not any(
            task.get("open_id") == reviewer and task.get("status") == status for task in tasks if isinstance(task, dict)
        ):
            raise ValueError("reviewer not verified")
    with transaction.atomic():
        Tenant.objects.select_for_update().get(pk=tenant_id)
        op, created = FeishuOperation.objects.get_or_create(
            tenant_id=tenant_id, operation_type="event", reference_type="feishu_event", reference_id=event_id,
            defaults={"status": "pending", "masked_detail": {"event_type": "approval_instance"}},
        )
        if not created:
            return "duplicate"
        locked = FeishuApprovalInstance.objects.select_for_update().select_related("approval").get(pk=instance.pk)
        approval = ApprovalRequest.objects.select_for_update().get(pk=locked.approval_id, tenant_id=tenant_id)
        from apps.supply_chain.payment_request_models import SupplyPaymentBatch, SupplyPaymentRequest
        linked = ((approval.business_type == "supply_payment_request" and SupplyPaymentRequest.objects.filter(
            tenant_id=tenant_id, approval_id=approval.pk, pk=str(approval.business_id)).exists()) or
            (approval.business_type == "supply_payment_batch" and SupplyPaymentBatch.objects.filter(
            tenant_id=tenant_id, approval_id=approval.pk, pk=str(approval.business_id)).exists()))
        if (approval.workflow_snapshot.get("approval_provider") != "feishu" or not linked
                or approval.workflow_snapshot.get("feishu_reviewer_id") != approval.designated_reviewer_id):
            raise ValueError("approval provider mismatch")
        if locked.instance_code is None:
            locked.instance_code = instance_code
        prior_status = locked.provider_status
        terminal = prior_status in {"APPROVED", "REJECTED", "CANCELED", "DELETED", "REVERTED"}
        if terminal and status == "PENDING":
            op.status = "skipped"
            op.error_code = "FEISHU_NATIVE_OUT_OF_ORDER"
            op.save(update_fields=["status", "error_code", "updated_at"])
            return "processed"
        if terminal and prior_status != status:
            locked.status = "manual_review"
            locked.last_error = "PROVIDER_TERMINAL_CONFLICT"
            op.status = "pending"
            op.error_code = "FEISHU_NATIVE_MANUAL_REVIEW"
            locked.save(update_fields=["instance_code", "status", "last_error", "updated_at"])
            op.save(update_fields=["status", "error_code", "updated_at"])
            return "processed"
        locked.provider_status = status
        if status in {"DELETED", "REVERTED"}:
            locked.status = "manual_review"
            locked.last_error = "PROVIDER_INSTANCE_REVERTED"
            op.status = "pending"
            op.error_code = "FEISHU_NATIVE_MANUAL_REVIEW"
        elif status == "PENDING":
            # Provider retries and out-of-order events never undo a local terminal decision.
            if approval.status == ApprovalRequest.Status.PENDING:
                locked.status = "submitted"
                if locked.finance_snapshot and any(t.get('open_id') == locked.reviewer_open_id and t.get('status') == 'APPROVED' for t in authoritative.get('task_list', []) if isinstance(t, dict)):
                    approval.status = 'approved'
                    approval.reviewed_by_id = approval.designated_reviewer_id
                    approval.decided_at = timezone.now()
                    approval.save(update_fields=['status','reviewed_by','decided_at','updated_at'])
                    write_workflow_audit(approval,resource_type='approval',actor=None,action='feishu_review_passed',from_status='pending',to_status='approved',detail={'awaiting_finance':True})
            op.status = "success"
        elif status in {"APPROVED", "REJECTED", "CANCELED"} and approval.status == ApprovalRequest.Status.PENDING:
            old_status = approval.status
            approval.status = {"APPROVED": "approved", "REJECTED": "rejected", "CANCELED": "withdrawn"}[status]
            approval.decided_at = timezone.now()
            if status != "CANCELED" and approval.designated_reviewer_id:
                approval.reviewed_by_id = approval.designated_reviewer_id
            approval.save(update_fields=["status", "decided_at", "reviewed_by", "updated_at"])
            write_workflow_audit(approval, resource_type="approval", actor=None, action="feishu_native_decision",
                from_status=old_status, to_status=approval.status, detail={"provider": "feishu", "provider_status": status})
            locked.status = "finished"
            op.status = "success"
        elif approval.status == 'approved' and status == 'APPROVED' and locked.finance_snapshot:
            locked.status = 'finished'
            op.status = 'success'
        elif approval.status == 'approved' and status in {'REJECTED', 'CANCELED'}:
            # Finance may already have received evidence after the reviewer
            # passed. Preserve that decision and handoff, but stop for review.
            locked.status = 'manual_review'
            locked.last_error = 'PROVIDER_TERMINAL_CONFLICT'
            op.status = 'pending'
            op.error_code = 'FEISHU_NATIVE_MANUAL_REVIEW'
        else:
            # Never reverse a terminal workflow decision from a later provider event.
            op.status = "success"
        locked.save(update_fields=["instance_code", "provider_status", "status", "last_error", "updated_at"])
        op.save(update_fields=["status", "error_code", "updated_at"])
    return "processed"


def reconcile_native_event(tenant_id, event_id, event, *, client=None):
    client = client or FeishuNativeClient()
    outcome = _reconcile_approval_event(tenant_id, event_id, event, client=client)
    if outcome == 'ignored':return outcome
    instance = FeishuApprovalInstance.objects.select_related('approval').filter(tenant_id=tenant_id,
        instance_code=event.get('instance_code'),approval_code=event.get('approval_code'),app_id=event.get('app_id')).first()
    if not instance or not instance.finance_snapshot:return outcome
    # Approval events may already be deduplicated while evidence downloads need
    # retrying. This step intentionally runs even after a duplicate event.
    connection=FeishuConnection.objects.get(tenant_id=tenant_id,enabled=True,app_id=instance.app_id)
    authoritative=client.get_instance(connection,instance.instance_code)
    if (authoritative.get('instance_code') != instance.instance_code or authoritative.get('uuid') != str(instance.submission_uuid) or
            authoritative.get('approval_code') != instance.approval_code or authoritative.get('open_id') != instance.payload.get('open_id')):
        raise ValueError('finance source mismatch')
    from .feishu_finance_handoff import finance_ready, sync_finance_handoff
    if not finance_ready(instance,authoritative):return outcome
    existing=getattr(instance,'finance_handoff',None)
    if existing and existing.status == 'needs_review':return outcome
    # A delayed finance callback after payment posting must not retry a
    # handoff that is intentionally valid only for submitted requests.
    from apps.supply_chain.payment_request_models import SupplyPaymentBatch, SupplyPaymentRequest
    approval = instance.approval
    if approval.business_type == 'supply_payment_request':
        parent = SupplyPaymentRequest.objects.filter(tenant_id=instance.tenant_id, pk=approval.business_id, approval=approval).first()
        if parent and (parent.status == 'paid' or parent.payment_id):return outcome
    elif approval.business_type == 'supply_payment_batch':
        parent = SupplyPaymentBatch.objects.filter(tenant_id=instance.tenant_id, pk=approval.business_id, approval=approval).first()
        if parent and parent.status == 'paid':return outcome
    from .feishu_finance_form import parse_finance_form
    from .feishu_finance_download import download_finance_file
    parsed=parse_finance_form(authoritative.get('form',[]),date_widget_id=instance.finance_snapshot['date_widget_id'],voucher_widget_id=instance.finance_snapshot['voucher_widget_id'])
    import time
    started=time.monotonic();files=[];total=0
    for item in parsed['files']:
        if len(files)>=20 or time.monotonic()-started>60:raise ValueError('finance download budget exceeded')
        file=download_finance_file(item,allowed_hosts=instance.finance_snapshot.get('attachment_hosts',[]))
        total+=file['byte_size']
        if total>64*1024*1024:raise ValueError('finance download budget exceeded')
        files.append(file)
    sync_finance_handoff(instance,authoritative,files)
    return outcome
