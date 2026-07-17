import hashlib
import hmac
import json
import time

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models.deletion import ProtectedError
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.reports.models import ReportExportAuditLog, ReportExportRequest
from apps.tenants.models import Tenant
from apps.workflows.models import ApprovalRequest, BusinessException, CollaborationEvent, WorkflowAuditEvent


pytestmark = pytest.mark.django_db


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(
        username=username,
        password="not-a-real-password",
        tenant=tenant,
        user_type=user_type,
    )


def grant(user, *codes, scope_type=DataScope.ScopeType.ALL, config=None):
    role = Role.objects.create(tenant=user.tenant, code=f"role-{user.username}-{Role.objects.count()}", name=user.username)
    for code in codes:
        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": code.split(".", 1)[0], "action": code.split(".", 1)[1]},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=scope_type, config=config or {})


def client_for(user=None):
    client = APIClient()
    if user:
        client.force_authenticate(user)
    return client


def create_approval(tenant, requester, approval_type=ApprovalRequest.ApprovalType.PURCHASE, key="demo-key"):
    return ApprovalRequest.objects.create(
        tenant=tenant,
        approval_type=approval_type,
        title="Demo approval",
        business_type="demo",
        business_id="demo-001",
        requested_by=requester,
        idempotency_key=key,
    )


def callback_headers(tenant, event_id, payload, timestamp=None, signature=None):
    timestamp = int(time.time()) if timestamp is None else timestamp
    payload_text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    payload_hash = hashlib.sha256(payload_text.encode()).hexdigest()
    signing_value = f"{tenant.code}:{event_id}:{timestamp}:{payload_hash}"
    signature = signature or hmac.new(b"not-a-real-ui-p4-secret", signing_value.encode(), hashlib.sha256).hexdigest()
    return {
        "HTTP_X_UI_P4_TENANT": tenant.code,
        "HTTP_X_UI_P4_EVENT_ID": event_id,
        "HTTP_X_UI_P4_TIMESTAMP": str(timestamp),
        "HTTP_X_UI_P4_SIGNATURE": signature,
    }


def test_approval_list_is_tenant_and_permission_scope_filtered():
    tenant = Tenant.objects.create(name="Tenant A", code="ui-p4-a")
    other = Tenant.objects.create(name="Tenant B", code="ui-p4-b")
    viewer = create_user(tenant, "approval-viewer")
    grant(
        viewer,
        "workflow.approvals.view",
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"approval_types": ["purchase"]},
    )
    visible = create_approval(tenant, viewer, key="visible")
    create_approval(tenant, viewer, ApprovalRequest.ApprovalType.PRICE, "hidden-type")
    create_approval(other, create_user(other, "other-requester"), key="hidden-tenant")

    response = client_for(viewer).get("/api/internal/workflow/approvals/")

    assert response.status_code == 200
    assert response.data["data"]["count"] == 1
    assert response.data["data"]["results"][0]["id"] == visible.id


def test_mock_approval_idempotency_and_conflict_are_enforced():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p4-idempotency")
    submitter = create_user(tenant, "submitter")
    grant(submitter, "workflow.approvals.submit")
    payload = {
        "approval_type": "purchase", "title": "Demo", "business_type": "demo",
        "business_id": "demo-1", "idempotency_key": "same-key",
    }
    client = client_for(submitter)

    created = client.post("/api/internal/workflow/approvals/mock/", payload, format="json")
    duplicate = client.post("/api/internal/workflow/approvals/mock/", payload, format="json")
    conflict = client.post(
        "/api/internal/workflow/approvals/mock/",
        {**payload, "business_id": "demo-2"},
        format="json",
    )

    assert created.status_code == 201
    assert duplicate.status_code == 200 and duplicate.data["data"]["created"] is False
    assert conflict.status_code == 409 and conflict.data["code"] == "STATE_CONFLICT"
    assert ApprovalRequest.objects.count() == 1


def test_approval_rejects_self_review_and_terminal_replay():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p4-review")
    requester = create_user(tenant, "requester")
    reviewer = create_user(tenant, "reviewer")
    grant(requester, "workflow.approvals.review")
    grant(reviewer, "workflow.approvals.review")
    approval = create_approval(tenant, requester)

    self_review = client_for(requester).post(f"/api/internal/workflow/approvals/{approval.id}/approve/", {}, format="json")
    approved = client_for(reviewer).post(f"/api/internal/workflow/approvals/{approval.id}/approve/", {"note": "Demo"}, format="json")
    replay = client_for(reviewer).post(f"/api/internal/workflow/approvals/{approval.id}/reject/", {}, format="json")

    assert self_review.status_code == 422
    assert approved.status_code == 200 and approved.data["data"]["status"] == "approved"
    assert replay.status_code == 409
    assert WorkflowAuditEvent.objects.filter(resource_type="approval", resource_id=str(approval.id), action="approve").exists()


def test_only_requester_can_withdraw_pending_approval():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p4-withdraw")
    requester = create_user(tenant, "withdraw-requester")
    other = create_user(tenant, "withdraw-other")
    grant(requester, "workflow.approvals.withdraw")
    grant(other, "workflow.approvals.withdraw")
    approval = create_approval(tenant, requester)

    denied = client_for(other).post(f"/api/internal/workflow/approvals/{approval.id}/withdraw/", {}, format="json")
    withdrawn = client_for(requester).post(f"/api/internal/workflow/approvals/{approval.id}/withdraw/", {}, format="json")

    assert denied.status_code == 403
    assert withdrawn.status_code == 200 and withdrawn.data["data"]["status"] == "withdrawn"


def test_exception_state_machine_is_audited_and_cannot_close_early():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p4-exception")
    manager = create_user(tenant, "exception-manager")
    grant(manager, "workflow.exceptions.manage")
    item = BusinessException.objects.create(
        tenant=tenant,
        module=BusinessException.Module.INTEGRATION,
        title="Demo exception",
        created_by=manager,
    )
    client = client_for(manager)

    early = client.post(f"/api/internal/workflow/exceptions/{item.id}/close/", {}, format="json")
    resolved = client.post(
        f"/api/internal/workflow/exceptions/{item.id}/resolve/",
        {"resolution": "Demo resolution"},
        format="json",
    )
    closed = client.post(f"/api/internal/workflow/exceptions/{item.id}/close/", {}, format="json")

    assert early.status_code == 409
    assert resolved.status_code == 200 and resolved.data["data"]["status"] == "resolved"
    assert closed.status_code == 200 and closed.data["data"]["status"] == "closed"
    assert list(WorkflowAuditEvent.objects.filter(resource_type="exception").values_list("action", flat=True)) == ["resolve", "close"]


@pytest.mark.parametrize("user_type", [CustomUser.UserType.EXTERNAL, CustomUser.UserType.RPA])
def test_workflow_internal_endpoints_reject_external_and_rpa_users(user_type):
    tenant = Tenant.objects.create(name="Tenant", code=f"ui-p4-{user_type}")
    user = create_user(tenant, f"blocked-{user_type}", user_type)
    grant(user, "workflow.approvals.view")
    assert client_for(user).get("/api/internal/workflow/approvals/").status_code == 403


def test_mock_callback_validates_signature_is_idempotent_and_never_writes_business_state():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p4-webhook")
    payload = {"event_type": "mock_feedback", "subject": "Demo", "action": "acknowledge", "token": "not-real"}
    headers = callback_headers(tenant, "event-001", payload)
    client = client_for()

    created = client.post("/api/feishu/mock-callback/", payload, format="json", **headers)
    duplicate = client.post("/api/feishu/mock-callback/", payload, format="json", **headers)

    assert created.status_code == 201
    assert created.data["data"]["event"]["status"] == "pending_confirmation"
    assert created.data["data"]["business_write"] is False
    assert created.data["data"]["event"]["masked_summary"].get("token") is None
    assert duplicate.status_code == 200 and duplicate.data["data"]["duplicate"] is True
    assert CollaborationEvent.objects.count() == 1


def test_mock_callback_rejects_invalid_signature_stale_timestamp_and_payload_replay():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p4-webhook-security")
    client = client_for()
    payload = {"event_type": "mock_feedback", "subject": "Demo"}

    invalid = client.post(
        "/api/wechat/mock-callback/",
        payload,
        format="json",
        **callback_headers(tenant, "invalid", payload, signature="bad-signature"),
    )
    stale = client.post(
        "/api/wechat/mock-callback/",
        payload,
        format="json",
        **callback_headers(tenant, "stale", payload, timestamp=int(time.time()) - 301),
    )
    good_headers = callback_headers(tenant, "replay", payload)
    client.post("/api/wechat/mock-callback/", payload, format="json", **good_headers)
    changed = {"event_type": "mock_feedback", "subject": "Changed"}
    replay = client.post(
        "/api/wechat/mock-callback/",
        changed,
        format="json",
        **callback_headers(tenant, "replay", changed),
    )

    assert invalid.status_code == 403
    assert stale.status_code == 403
    assert replay.status_code == 409


@override_settings(UI_P4_COLLABORATION_MODE="disabled")
def test_mock_callback_is_disabled_outside_controlled_mock_mode():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p4-disabled-callback")
    payload = {"event_type": "mock_feedback", "subject": "Demo"}

    response = client_for().post(
        "/api/feishu/mock-callback/",
        payload,
        format="json",
        **callback_headers(tenant, "disabled", payload),
    )

    assert response.status_code == 403
    assert CollaborationEvent.objects.count() == 0


def test_collaboration_confirmation_requires_scope_and_does_not_write_business_data():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p4-collaboration")
    confirmer = create_user(tenant, "collaboration-confirmer")
    grant(
        confirmer,
        "workflow.collaboration.confirm",
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"collaboration_channels": ["feishu"]},
    )
    event = CollaborationEvent.objects.create(
        tenant=tenant,
        channel="feishu",
        event_id="demo-confirm",
        event_type="mock_feedback",
        payload_hash="a" * 64,
        masked_summary={"subject": "Demo"},
    )
    response = client_for(confirmer).post(
        f"/api/internal/workflow/collaboration-events/{event.id}/confirm/",
        {"note": "Confirmed only as feedback."},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["data"]["status"] == "confirmed"
    audit = WorkflowAuditEvent.objects.get(resource_type="collaboration", resource_id=str(event.id))
    assert audit.masked_detail["business_write"] is False


def test_report_download_requires_permission_and_writes_audit():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p4-report")
    owner = create_user(tenant, "report-owner")
    viewer = create_user(tenant, "report-viewer")
    denied_owner = create_user(tenant, "report-denied-owner")
    grant(owner, "reports.download", "reports.view")
    grant(viewer, "reports.download", "reports.view")
    grant(denied_owner, "reports.view")
    export = ReportExportRequest(
        tenant=tenant,
        report_type=ReportExportRequest.ReportType.INVENTORY_ALERTS,
        requested_by=owner,
        data_scope=[{"scope_type": "all", "config": {}}],
        status=ReportExportRequest.Status.COMPLETED,
        masked_file_reference="placeholder://report-export/demo",
    )
    export._export_service_write = True
    export.save()
    denied_export = ReportExportRequest(
        tenant=tenant,
        report_type=ReportExportRequest.ReportType.INVENTORY_ALERTS,
        requested_by=denied_owner,
        data_scope=[{"scope_type": "all", "config": {}}],
        status=ReportExportRequest.Status.COMPLETED,
        masked_file_reference="placeholder://report-export/denied",
    )
    denied_export._export_service_write = True
    denied_export.save()
    rejected_export = ReportExportRequest(
        tenant=tenant,
        report_type=ReportExportRequest.ReportType.INVENTORY_ALERTS,
        requested_by=owner,
        data_scope=[{"scope_type": "all", "config": {}}],
        status=ReportExportRequest.Status.REJECTED,
        rejection_reason="row_limit_exceeded",
    )
    rejected_export._export_service_write = True
    rejected_export.save()
    report_permission_export = ReportExportRequest(
        tenant=tenant,
        report_type=ReportExportRequest.ReportType.ANALYTICS_SUMMARY,
        requested_by=owner,
        data_scope=[{"scope_type": "all", "config": {}}],
        status=ReportExportRequest.Status.COMPLETED,
        masked_file_reference="placeholder://report-export/report-permission",
    )
    report_permission_export._export_service_write = True
    report_permission_export.save()
    changed_scope_export = ReportExportRequest(
        tenant=tenant,
        report_type=ReportExportRequest.ReportType.INVENTORY_ALERTS,
        requested_by=owner,
        data_scope=[{"scope_type": "custom", "config": {"sku_ids": [999]}}],
        status=ReportExportRequest.Status.COMPLETED,
        masked_file_reference="placeholder://report-export/changed-scope",
    )
    changed_scope_export._export_service_write = True
    changed_scope_export.save()

    denied = client_for(viewer).post(f"/api/report/exports/{export.id}/download/", {}, format="json")
    missing_permission = client_for(denied_owner).post(
        f"/api/report/exports/{denied_export.id}/download/",
        {},
        format="json",
    )
    invalid_status = client_for(owner).post(
        f"/api/report/exports/{rejected_export.id}/download/",
        {},
        format="json",
    )
    missing_report_permission = client_for(owner).post(
        f"/api/report/exports/{report_permission_export.id}/download/",
        {},
        format="json",
    )
    changed_scope = client_for(owner).post(
        f"/api/report/exports/{changed_scope_export.id}/download/",
        {},
        format="json",
    )
    granted = client_for(owner).post(f"/api/report/exports/{export.id}/download/", {}, format="json")

    assert denied.status_code == 404
    assert missing_permission.status_code == 403
    assert invalid_status.status_code == 422
    assert missing_report_permission.status_code == 403
    assert changed_scope.status_code == 403
    assert granted.status_code == 200
    assert granted.data["data"]["placeholder_only"] is True
    assert granted.data["data"]["download_reference"].startswith("placeholder://")
    assert ReportExportAuditLog.objects.filter(export_request=export, action="download").count() == 1
    assert ReportExportAuditLog.objects.filter(
        export_request=denied_export,
        action="download",
        result="denied_permission",
    ).exists()
    assert ReportExportAuditLog.objects.filter(
        export_request=rejected_export,
        action="download",
        result="rejected_status",
    ).exists()
    assert ReportExportAuditLog.objects.filter(
        export_request=report_permission_export,
        action="download",
        result="denied_report_permission",
    ).exists()
    assert ReportExportAuditLog.objects.filter(
        export_request=changed_scope_export,
        action="download",
        result="denied_scope_changed",
    ).exists()


def test_workflow_audit_events_reject_direct_and_bulk_mutation():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p4-audit-immutable")
    actor = create_user(tenant, "audit-actor")
    audit = WorkflowAuditEvent.objects.create(
        tenant=tenant,
        resource_type="exception",
        resource_id="demo-001",
        action="create_mock",
        actor=actor,
    )

    with pytest.raises(DjangoValidationError):
        WorkflowAuditEvent.objects.filter(pk=audit.pk).update(action="tampered")
    with pytest.raises(DjangoValidationError):
        WorkflowAuditEvent.objects.filter(pk=audit.pk).delete()
    with pytest.raises(DjangoValidationError):
        audit.delete()
    audit.action = "tampered"
    with pytest.raises(DjangoValidationError):
        audit.save()
    forged_replacement = WorkflowAuditEvent(
        pk=audit.pk,
        tenant=tenant,
        resource_type="exception",
        resource_id="demo-001",
        action="forged",
        actor=actor,
    )
    with pytest.raises(DjangoValidationError):
        forged_replacement.save()
    with pytest.raises(DjangoValidationError):
        WorkflowAuditEvent.objects.bulk_create([
            WorkflowAuditEvent(
                tenant=tenant,
                resource_type="exception",
                resource_id="demo-002",
                action="forged",
                actor=actor,
            ),
        ])


@pytest.mark.parametrize("with_actor", [False, True])
def test_workflow_audit_survives_base_manager_and_tenant_delete_attempts(with_actor):
    tenant = Tenant.objects.create(name="Tenant", code=f"ui-p4-workflow-audit-protect-{with_actor}")
    actor = create_user(tenant, f"workflow-audit-protect-{with_actor}") if with_actor else None
    audit = WorkflowAuditEvent.objects.create(
        tenant=tenant,
        resource_type="exception",
        resource_id=f"demo-protect-{with_actor}",
        action="create_mock",
        actor=actor,
    )

    with pytest.raises(DjangoValidationError):
        WorkflowAuditEvent._base_manager.filter(pk=audit.pk).delete()
    with pytest.raises(ProtectedError):
        Tenant._base_manager.filter(pk=tenant.pk).delete()

    assert Tenant._base_manager.filter(pk=tenant.pk).exists()
    assert WorkflowAuditEvent._base_manager.filter(pk=audit.pk).exists()


def test_report_download_audit_rejects_update_and_delete_mutation():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p4-report-audit-immutable")
    actor = create_user(tenant, "report-audit-actor")
    export = ReportExportRequest(
        tenant=tenant,
        report_type=ReportExportRequest.ReportType.INVENTORY_ALERTS,
        requested_by=actor,
        data_scope=[],
        status=ReportExportRequest.Status.COMPLETED,
        masked_file_reference="placeholder://report-export/audit",
    )
    export._export_service_write = True
    export.save()
    audit = ReportExportAuditLog(
        tenant=tenant,
        export_request=export,
        actor=actor,
        action=ReportExportAuditLog.Action.DOWNLOAD,
        result="placeholder_grant",
    )
    audit._export_service_write = True
    audit.save()

    with pytest.raises(DjangoValidationError):
        ReportExportAuditLog.objects.filter(pk=audit.pk).update(result="tampered")
    with pytest.raises(DjangoValidationError):
        ReportExportAuditLog.objects.filter(pk=audit.pk).delete()
    with pytest.raises(DjangoValidationError):
        audit.delete()
    audit.result = "tampered"
    audit._export_service_write = True
    with pytest.raises(DjangoValidationError):
        audit.save()
    forged_replacement = ReportExportAuditLog(
        pk=audit.pk,
        tenant=tenant,
        export_request=export,
        actor=actor,
        action=ReportExportAuditLog.Action.DOWNLOAD,
        result="forged",
    )
    forged_replacement._export_service_write = True
    with pytest.raises(DjangoValidationError):
        forged_replacement.save()


def test_report_export_audit_survives_parent_and_tenant_delete_attempts():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p4-report-audit-parent-protect")
    actor = create_user(tenant, "report-audit-parent-actor")
    export = ReportExportRequest(
        tenant=tenant,
        report_type=ReportExportRequest.ReportType.INVENTORY_ALERTS,
        requested_by=actor,
        data_scope=[],
        status=ReportExportRequest.Status.COMPLETED,
        masked_file_reference="placeholder://report-export/parent-protect",
    )
    export._export_service_write = True
    export.save()
    audit = ReportExportAuditLog(
        tenant=tenant,
        export_request=export,
        actor=actor,
        action=ReportExportAuditLog.Action.DOWNLOAD,
        result="placeholder_grant",
    )
    audit._export_service_write = True
    audit.save()

    with pytest.raises(DjangoValidationError):
        export.delete()
    with pytest.raises(DjangoValidationError):
        ReportExportRequest.objects.filter(pk=export.pk).delete()
    with pytest.raises(ProtectedError):
        ReportExportRequest._base_manager.filter(pk=export.pk).delete()
    with pytest.raises(ProtectedError):
        Tenant._base_manager.filter(pk=tenant.pk).delete()

    assert ReportExportRequest.objects.filter(pk=export.pk).exists()
    assert ReportExportAuditLog.objects.filter(pk=audit.pk).exists()
