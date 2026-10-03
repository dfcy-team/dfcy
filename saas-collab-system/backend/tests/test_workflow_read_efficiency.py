"""Paged workflow collections load audit events in a bounded batch."""

import pytest
import hashlib
import json
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.tenants.models import Tenant
from apps.workflows.models import ApprovalRequest, BusinessException, CollaborationEvent, WorkflowAuditEvent
from apps.workflows.serializers import (
    ApprovalRequestSerializer,
    BusinessExceptionSerializer,
    CollaborationEventSerializer,
)
from tests.test_ui_p4_workflow_collaboration import client_for, create_user, grant

pytestmark = pytest.mark.django_db


def _rows(model, tenant, actor, n, start=0):
    rows = []
    for i in range(n):
        index = start + i
        if model is ApprovalRequest:
            row = model.objects.create(tenant=tenant, approval_type="purchase", title=f"A{index}", business_type="test", business_id=str(index), requested_by=actor, idempotency_key=f"eff-{index}")
            kind = "approval"
        elif model is BusinessException:
            row = model.objects.create(tenant=tenant, module="integration", title=f"E{index}", created_by=actor)
            kind = "exception"
        else:
            row = model.objects.create(tenant=tenant, channel="wechat", event_id=f"eff-{index}", event_type="test", payload_hash="a" * 64)
            kind = "collaboration"
        WorkflowAuditEvent.objects.create(tenant=tenant, resource_type=kind, resource_id=str(row.id), action="created", actor=actor, masked_detail={"index": index})
        rows.append(row)
    return rows


@pytest.mark.parametrize(
    "model,permission,path,serializer",
    [
        (ApprovalRequest, "workflow.approvals.view", "/api/internal/workflow/approvals/", ApprovalRequestSerializer),
        (BusinessException, "workflow.exceptions.view", "/api/internal/workflow/exceptions/", BusinessExceptionSerializer),
        (CollaborationEvent, "workflow.collaboration.view", "/api/internal/workflow/collaboration-events/", CollaborationEventSerializer),
    ],
)
def test_workflow_list_audit_queries_are_constant_and_json_matches_fallback(model, permission, path, serializer):
    tenant = Tenant.objects.create(code=f"workflow-eff-{model.__name__}", name="Workflow efficiency")
    viewer = create_user(tenant, f"workflow-eff-{model.__name__}")
    grant(viewer, permission)
    client = client_for(viewer)

    _rows(model, tenant, viewer, 2)
    with CaptureQueriesContext(connection) as small_queries:
        small = client.get(path, {"page_size": 20}).json()
    _rows(model, tenant, viewer, 18, start=2)
    with CaptureQueriesContext(connection) as large_queries:
        large = client.get(path, {"page_size": 20}).json()

    assert small["success"] and large["success"]
    assert len(small["data"]["results"]) == 2
    assert len(large["data"]["results"]) == 20
    assert len(large_queries) <= len(small_queries) + 2
    assert len(large_queries) < 30

    ordered_rows = [model.objects.get(pk=item["id"]) for item in large["data"]["results"]]
    # The serializer fallback is the legacy detail path and retains the old per-object query behavior.
    small_rows = [model.objects.get(pk=item["id"]) for item in small["data"]["results"]]
    with CaptureQueriesContext(connection) as small_fallback_queries:
        small_fallback_json = [serializer(row).data for row in small_rows]
    assert small["data"]["results"] == small_fallback_json
    baseline_rows = [model.objects.get(pk=item["id"]) for item in large["data"]["results"]]
    with CaptureQueriesContext(connection) as baseline_queries:
        baseline_json = [serializer(row).data for row in baseline_rows]
    assert large["data"]["results"] == baseline_json
    print(
        f"WORKFLOW_EVIDENCE model={model.__name__} rows_small=2 rows_large=20 "
        f"optimized_queries_small={len(small_queries)} optimized_queries_large={len(large_queries)} "
        f"detail_fallback_queries_small={len(small_fallback_queries)} "
        f"detail_fallback_queries_large={len(baseline_queries)} json_equal=true "
        f"response_sha256={hashlib.sha256(json.dumps(large, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}"
    )


def test_workflow_empty_page_has_empty_audit_batch_and_preserves_pagination_contract():
    tenant = Tenant.objects.create(code="workflow-eff-empty", name="Workflow empty")
    viewer = create_user(tenant, "workflow-eff-empty")
    grant(viewer, "workflow.approvals.view")
    response = client_for(viewer).get("/api/internal/workflow/approvals/")
    assert response.status_code == 200
    assert response.json()["data"]["count"] == 0
    assert response.json()["data"]["results"] == []


def test_workflow_out_of_range_page_remains_404():
    tenant = Tenant.objects.create(code="workflow-eff-range", name="Workflow range")
    viewer = create_user(tenant, "workflow-eff-range")
    grant(viewer, "workflow.approvals.view")
    response = client_for(viewer).get("/api/internal/workflow/approvals/?page=2&page_size=2")
    assert response.status_code == 404


def test_workflow_page_boundary_and_links_are_preserved():
    tenant = Tenant.objects.create(code="workflow-eff-boundary", name="Workflow boundary")
    viewer = create_user(tenant, "workflow-eff-boundary")
    grant(viewer, "workflow.approvals.view")
    _rows(ApprovalRequest, tenant, viewer, 3)

    client = client_for(viewer)
    first_page = client.get("/api/internal/workflow/approvals/?page_size=2").json()["data"]
    second_page = client.get("/api/internal/workflow/approvals/?page=2&page_size=2").json()["data"]
    assert first_page["count"] == second_page["count"] == 3
    assert len(first_page["results"]) == 2
    assert len(second_page["results"]) == 1
    assert second_page["results"][0]["id"] == first_page["results"][-1]["id"] - 1
    assert first_page["previous"] is None and first_page["next"]
    assert second_page["next"] is None and second_page["previous"]


def test_workflow_batch_audit_lookup_is_tenant_scoped_and_missing_events_are_empty():
    tenant = Tenant.objects.create(code="workflow-eff-tenant", name="Workflow tenant")
    viewer = create_user(tenant, "workflow-eff-tenant")
    grant(viewer, "workflow.approvals.view")
    rows = _rows(ApprovalRequest, tenant, viewer, 1)
    rows.append(ApprovalRequest.objects.create(
        tenant=tenant,
        approval_type="purchase",
        title="No audit event",
        business_type="test",
        business_id="missing",
        requested_by=viewer,
        idempotency_key="eff-no-event",
    ))

    foreign = Tenant.objects.create(code="workflow-eff-foreign", name="Workflow foreign")
    foreign_actor = create_user(foreign, "workflow-eff-foreign")
    WorkflowAuditEvent.objects.create(
        tenant=foreign,
        resource_type="approval",
        resource_id=str(rows[1].id),
        action="foreign",
        actor=foreign_actor,
    )

    response = client_for(viewer).get("/api/internal/workflow/approvals/?page_size=20")
    assert response.status_code == 200
    by_id = {item["id"]: item for item in response.json()["data"]["results"]}
    assert len(by_id[rows[0].id]["audit_events"]) == 1
    assert by_id[rows[1].id]["audit_events"] == []
