"""Query budgets and request-local authorization for saved report reads."""
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.permissions.models import DataScope, RoleResourcePolicy
from apps.reports.models import SavedReportView
from apps.tenants.models import Tenant
from tests.test_sales_management import client_for, create_scope, grant, user_for

pytestmark = pytest.mark.django_db


def config(dataset="sales"):
    return {"dataset": dataset, "dimensions": ["currency"], "metrics": ["order_count"] if dataset == "sales" else ["transaction_count"], "filters": {}}


def dashboard():
    return {"kind": "dashboard", "version": 1, "module": "销售管理", "filters": {}, "widgets": [
        {"id": f"w-{i}", "title": str(i), "type": "table", "width": 6, "height": 300, "config": config()}
        for i in range(8)
    ]}


def viewer_for(code):
    tenant = Tenant.objects.create(code=code, name=code)
    user = user_for(tenant, code)
    grant(user, "reports.view")
    grant(user, "sales_management.view")
    return user


def test_saved_view_query_budget_does_not_grow_with_views_or_widgets():
    viewer = viewer_for("view-query-budget")
    client = client_for(viewer)
    for i in range(2):
        SavedReportView.objects.create(tenant=viewer.tenant, owner=viewer, name=str(i), config=config() if i % 2 else dashboard())
    with CaptureQueriesContext(connection) as small:
        first = client.get("/api/report/views/")
    assert first.status_code == 200
    assert len(first.json()["data"]) == 2
    for i in range(2, 20):
        SavedReportView.objects.create(tenant=viewer.tenant, owner=viewer, name=str(i), config=config() if i % 2 else dashboard())
    with CaptureQueriesContext(connection) as larger:
        second = client.get("/api/report/views/")
    assert second.status_code == 200
    assert len(second.json()["data"]) == 20
    # Allow middleware initialization, while rejecting a per-view/per-widget tail.
    assert len(larger) <= len(small) + 2
    assert len(larger) < 30


def test_saved_view_reads_recheck_revoked_grants_on_the_next_request():
    viewer = viewer_for("view-fresh-permissions")
    view = SavedReportView.objects.create(tenant=viewer.tenant, owner=viewer, name="own", config=dashboard())
    client = client_for(viewer)
    assert [v["id"] for v in client.get("/api/report/views/").json()["data"]] == [view.id]
    scope = DataScope.objects.get(role__user_roles__user=viewer, role__permissions__code="reports.view")
    scope.scope_type = DataScope.ScopeType.CUSTOM
    scope.config = {"report_types": ["analytics_summary"]}
    scope.save(update_fields=["scope_type", "config"])
    assert client.get("/api/report/views/").json()["data"] == []
    catalog = client.get("/api/report/datasets/").json()["data"]["datasets"]
    assert "sales" not in {row["id"] for row in catalog}


def test_saved_view_resource_scope_is_bounded_and_rechecked_next_request():
    tenant, _, store, _ = create_scope("view-resource-budget")
    viewer = user_for(tenant, "view-resource-budget")
    grant(viewer, "reports.view")
    grant(viewer, "sales_management.view")
    role = viewer.user_roles.get(role__permissions__code="reports.view").role
    RoleResourcePolicy.objects.create(
        tenant=tenant, role=role, resource_code="reports.sales",
        scope_type="custom", config={"store_ids": [store.id]},
    )
    for i in range(20):
        SavedReportView.objects.create(tenant=tenant, owner=viewer, name=str(i), config=dashboard())
    client = client_for(viewer)
    with CaptureQueriesContext(connection) as queries:
        response = client.get("/api/report/views/")
    assert response.status_code == 200
    assert len(response.json()["data"]) == 20
    assert len(queries) < 30
    role.status = role.Status.INACTIVE
    role.save(update_fields=["status"])
    assert client.get("/api/report/views/").status_code == 403


def test_saved_view_bulk_authorization_keeps_owner_tenant_and_dataset_rules():
    viewer = viewer_for("view-owner-tenant")
    peer = user_for(viewer.tenant, "view-peer")
    foreign = viewer_for("view-foreign")
    own = SavedReportView.objects.create(tenant=viewer.tenant, owner=viewer, name="own", config=config())
    shared = SavedReportView.objects.create(tenant=viewer.tenant, owner=peer, name="shared", is_shared=True, config=dashboard())
    SavedReportView.objects.create(tenant=viewer.tenant, owner=peer, name="private", config=config())
    SavedReportView.objects.create(tenant=foreign.tenant, owner=foreign, name="foreign-shared", is_shared=True, config=config())
    SavedReportView.objects.create(tenant=viewer.tenant, owner=peer, name="ungranted-finance", is_shared=True, config=config("finance"))
    client = client_for(viewer)
    response = client.get("/api/report/views/")
    assert response.status_code == 200
    assert {v["id"] for v in response.json()["data"]} == {own.id, shared.id}
    grant(viewer, "finance.view")
    assert len(client.get("/api/report/views/").json()["data"]) == 3
