from copy import deepcopy

import pytest

from apps.permissions.models import DataScope
from apps.workflows.models import BusinessException, WorkflowAuditEvent
from tests.test_sales_management import client_for, create_order, create_scope, grant, user_for

pytestmark = pytest.mark.django_db
URL = "/api/report/exceptions/"


def scenario(suffix):
    tenant, _, store, _ = create_scope(suffix, currency="PHP")
    create_order(tenant, store, "order", "12")
    user = user_for(tenant, f"{suffix}-user")
    for code in ("reports.view", "sales_management.view", "workflow.exceptions.manage", "workflow.exceptions.view"):
        grant(user, code)
    payload = {"config": {"dataset": "sales", "dimensions": ["store_id", "currency"], "metrics": ["order_count"]},
        "group": {"store_id": store.pk, "currency": "PHP"}, "title": "门店订单核查", "request_key": "8b65d2d4-c3b2-4ce8-87b6-e80879379952"}
    return tenant, store, user, payload


def test_real_exception_lineage_idempotency_audit_and_return_source():
    tenant, store, user, payload = scenario("real-report-exception")
    client = client_for(user)
    response = client.post(URL, payload, format="json")
    assert response.status_code == 201, response.content
    exception = BusinessException.objects.get(pk=response.json()["data"]["id"])
    assert exception.module == "sales" and exception.business_type == "report_group"
    assert exception.report_context["group"] == {"store_id": store.pk, "currency": "PHP"}
    assert "rows" not in exception.report_context and "order_count" not in exception.report_context["group"]
    assert exception.report_context["metric_version"]
    assert client.post(URL, payload, format="json").status_code == 200
    assert BusinessException.objects.filter(tenant=tenant).count() == 1
    assert WorkflowAuditEvent.objects.filter(tenant=tenant, resource_type="exception", action="create").count() == 1
    source = client.get(f"{URL}{exception.pk}/source/")
    assert source.status_code == 200 and source.json()["data"]["source"]["config"]["dataset"] == "sales"
    altered = deepcopy(payload); altered["title"] = "另一个事项"
    assert client.post(URL, altered, format="json").status_code == 400


def test_rejects_group_outside_business_scope_and_foreign_tenant_source():
    tenant, store, user, payload = scenario("scope-report-exception")
    foreign_tenant, _, foreign_store, _ = create_scope("foreign-report-exception", currency="PHP")
    create_order(foreign_tenant, foreign_store, "foreign", "99")
    payload["group"]["store_id"] = foreign_store.pk
    response = client_for(user).post(URL, payload, format="json")
    assert response.status_code == 403
    assert not BusinessException.objects.filter(tenant=tenant).exists()


def test_rechecks_same_tenant_store_scope_and_permission_after_creation():
    tenant, store, user, payload = scenario("recheck-report-exception")
    client = client_for(user)
    exception_id = client.post(URL, payload, format="json").json()["data"]["id"]
    from apps.masterdata.models import StoreMaster
    hidden = StoreMaster.objects.create(tenant=tenant, platform=store.platform, code="hidden", name="隐藏门店", country_code="PH", currency="PHP", timezone="Asia/Manila")
    create_order(tenant, hidden, "same-tenant-hidden", "40")
    scope = DataScope.objects.get(role__user_roles__user=user, role__permissions__code="sales_management.view")
    scope.scope_type = DataScope.ScopeType.CUSTOM
    scope.config = {"store_ids": [str(hidden.pk)]}
    scope.save()
    assert client.post(URL, payload, format="json").status_code == 403
    assert client.get(f"{URL}{exception_id}/source/").status_code == 403
    assert BusinessException.objects.filter(tenant=tenant).count() == 1
    scope.delete()
    assert client.get(f"{URL}{exception_id}/source/").status_code == 403


def test_requires_workflow_module_scope_and_current_source_permission():
    tenant, store, user, payload = scenario("workflow-report-exception")
    restricted = user_for(tenant, "workflow-restricted")
    grant(restricted, "reports.view"); grant(restricted, "sales_management.view")
    grant(restricted, "workflow.exceptions.manage", DataScope.ScopeType.CUSTOM, {"exception_modules": ["finance"]})
    assert client_for(restricted).post(URL, payload, format="json").status_code == 403
    exception = client_for(user).post(URL, payload, format="json").json()["data"]["id"]
    no_source = user_for(tenant, "workflow-no-source")
    grant(no_source, "reports.view"); grant(no_source, "workflow.exceptions.view")
    assert client_for(no_source).get(f"{URL}{exception}/source/").status_code == 403


def test_rejects_unqueried_or_incomplete_group():
    tenant, store, user, payload = scenario("invalid-report-exception")
    del payload["group"]["currency"]
    assert client_for(user).post(URL, payload, format="json").status_code == 400
    assert not BusinessException.objects.filter(tenant=tenant).exists()
