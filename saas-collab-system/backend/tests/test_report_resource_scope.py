from datetime import date

import pytest
from rest_framework.exceptions import PermissionDenied

from apps.commerce.models import RefundReturn, SalesOrder
from apps.masterdata.models import StoreMaster
from apps.permissions.models import DataScope, Permission, Role, RoleResourcePolicy, UserRole
from apps.reports.datasets import DATASETS, latest_sales_business_date, selected_permission
from tests.test_inventory_report_warehouse_scope import _inventory_rows, _snapshot_at, _warehouse
from tests.test_report_revision import _config
from tests.test_sales_management import NOW, client_for, create_order, create_run, create_scope, grant, user_for

pytestmark = pytest.mark.django_db
QUERY = "/api/report/query/"


def _role_for(user, permission_code):
    return user.user_roles.filter(role__permissions__code=permission_code).order_by("-pk").first().role


def _report_role(user, name):
    role = Role.objects.create(tenant=user.tenant, name=name, code=f"{name}-{user.pk}")
    role.permissions.add(Permission.objects.get(code="reports.view"))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    return role


def _explicit(user, role, resource, config):
    return RoleResourcePolicy.objects.create(tenant=user.tenant, role=role, resource_code=resource, scope_type="custom", config=config)


def test_sales_and_inventory_explicit_scopes_intersect_role36_mixed_and_business_scopes():
    tenant, platform, store_a, warehouse_a = create_scope("report-scope-intersection")
    store_b = StoreMaster.objects.create(tenant=tenant, platform=platform, code="scope-store-b", name="scope-store-b", country_code="PH", currency="PHP", timezone="Asia/Manila")
    warehouse_b = _warehouse(tenant, "report-scope-b")
    warehouse_c = _warehouse(tenant, "report-scope-c")
    create_order(tenant, store_a, "scope-a")
    create_order(tenant, store_b, "scope-b")
    for warehouse, suffix in ((warehouse_a, "a"), (warehouse_b, "b"), (warehouse_c, "c")):
        _snapshot_at(tenant, warehouse, f"scope-{suffix}")

    user = user_for(tenant, "report-scope-intersection-viewer")
    grant(user, "reports.view", DataScope.ScopeType.CUSTOM, {"warehouse_ids": [warehouse_a.id], "report_types": ["analytics_summary"]})
    report_role = _report_role(user, "report-dedicated-intersection")
    _explicit(user, report_role, "reports.sales", {"store_ids": [store_a.id]})
    _explicit(user, report_role, "reports.inventory", {"warehouse_ids": [warehouse_a.id, warehouse_b.id]})
    grant(user, "sales_management.view", DataScope.ScopeType.CUSTOM, {"store_ids": [store_a.id, store_b.id]})
    business_role = _role_for(user, "sales_management.view")
    RoleResourcePolicy.objects.create(tenant=tenant, role=business_role, resource_code="commerce.inventory", permission_code="sales_management.view", scope_type="custom", config={"warehouse_ids": [warehouse_a.id, warehouse_c.id]})
    client = client_for(user)
    sales = client.post(QUERY, _config("sales", ["store_id"], ["order_count"]), format="json")
    assert sales.status_code == 200, sales.content
    assert {row["store_id"] for row in sales.json()["data"]["rows"]} == {store_a.id}
    assert set(_inventory_rows(client)) == {warehouse_a.id}


@pytest.mark.parametrize("dataset,metric", [("sales_skus", "units_sold"), ("refunds", "case_count")])
def test_sales_skus_and_refunds_share_explicit_store_filter(dataset, metric):
    tenant, platform, store_a, _ = create_scope(f"report-child-{dataset}")
    store_b = StoreMaster.objects.create(tenant=tenant, platform=platform, code=f"child-b-{dataset}", name=f"child-b-{dataset}", country_code="PH", currency="PHP", timezone="Asia/Manila")
    order_a = create_order(tenant, store_a, f"child-a-{dataset}")
    order_b = create_order(tenant, store_b, f"child-b-{dataset}")
    run = create_run(tenant, "refund_return", f"child-refund-{dataset}")
    for store, order, suffix in ((store_a, order_a, "a"), (store_b, order_b, "b")):
        RefundReturn.objects.create(tenant=tenant, platform=platform, store=store, sales_order=order, source_run=run,
            external_return_id=f"RETURN-{dataset}-{suffix}", case_type="return_refund", raw_status="COMPLETED", normalized_status="completed",
            requested_at_utc=NOW, updated_at_utc=NOW, currency="PHP", refund_amount="5.0000", payload_hash=suffix * 64)
    user = user_for(tenant, f"report-child-viewer-{dataset}")
    grant(user, "reports.view", DataScope.ScopeType.ALL)
    _explicit(user, _role_for(user, "reports.view"), "reports.sales", {"store_ids": [store_a.id]})
    grant(user, "sales_management.view", DataScope.ScopeType.ALL)
    response = client_for(user).post(QUERY, _config(dataset, ["store_id"], [metric]), format="json")
    assert response.status_code == 200, response.content
    assert {row["store_id"] for row in response.json()["data"]["rows"]} == {store_a.id}


@pytest.mark.parametrize("bad_config", [{"store_ids": [True]}, {"store_ids": [1], "unknown": [2]}, {"store_ids": []}])
def test_invalid_explicit_config_fails_closed(bad_config):
    tenant, _, store, _ = create_scope("report-scope-invalid")
    user = user_for(tenant, "report-scope-invalid-viewer")
    grant(user, "reports.view", DataScope.ScopeType.ALL)
    policy = _explicit(user, _role_for(user, "reports.view"), "reports.sales", {"store_ids": [store.id]})
    RoleResourcePolicy.objects.filter(pk=policy.pk).update(config=bad_config)
    grant(user, "sales_management.view", DataScope.ScopeType.ALL)
    with pytest.raises(PermissionDenied):
        selected_permission(user, DATASETS["sales"])


def test_foreign_tenant_and_expired_report_roles_do_not_authorize():
    tenant, _, store, _ = create_scope("report-scope-tenant-a")
    _, _, foreign_store, _ = create_scope("report-scope-tenant-b")
    user = user_for(tenant, "report-scope-tenant-viewer")
    grant(user, "reports.view", DataScope.ScopeType.ALL)
    report_role = _role_for(user, "reports.view")
    policy = _explicit(user, report_role, "reports.sales", {"store_ids": [store.id]})
    RoleResourcePolicy.objects.filter(pk=policy.pk).update(config={"store_ids": [foreign_store.id]})
    grant(user, "sales_management.view", DataScope.ScopeType.ALL)
    with pytest.raises(PermissionDenied):
        selected_permission(user, DATASETS["sales"])
    UserRole.objects.filter(user=user, role=report_role).update(valid_until="2020-01-01T00:00:00Z")
    with pytest.raises(PermissionDenied):
        selected_permission(user, DATASETS["sales"])


def test_explicit_sales_policy_overrides_mixed_typed_unknown_legacy_role_without_expanding():
    tenant, platform, store_a, _ = create_scope("report-typed-explicit-a")
    store_b = StoreMaster.objects.create(tenant=tenant, platform=platform, code="typed-explicit-b", name="typed-explicit-b", country_code="PH", currency="PHP", timezone="Asia/Manila")
    create_order(tenant, store_a, "typed-explicit-a")
    create_order(tenant, store_b, "typed-explicit-b")
    user = user_for(tenant, "report-typed-explicit-viewer")
    grant(user, "reports.view", DataScope.ScopeType.CUSTOM, {"report_types": ["sales_details", "unknown_report"]})
    role = _report_role(user, "typed-explicit-dedicated")
    _explicit(user, role, "reports.sales", {"store_ids": [store_a.id]})
    grant(user, "sales_management.view", DataScope.ScopeType.ALL)
    response = client_for(user).post(QUERY, _config("sales", ["store_id"], ["order_count"]), format="json")
    assert response.status_code == 200, response.content
    assert {row["store_id"] for row in response.json()["data"]["rows"]} == {store_a.id}


def test_business_scope_change_updates_query_and_latest_sales_date_then_binding_removal_denies():
    tenant, _, store_a, warehouse = create_scope("report-live-business-a")
    store_b = StoreMaster.objects.create(tenant=tenant, platform=store_a.platform, code="report-live-business-b", name="report-live-business-b", country_code="PH", currency="PHP", timezone="Asia/Manila")
    order_a, order_b = create_order(tenant, store_a, "live-business-a"), create_order(tenant, store_b, "live-business-b")
    SalesOrder.objects.filter(pk=order_a.pk).update(business_date=date(2026, 9, 20))
    SalesOrder.objects.filter(pk=order_b.pk).update(business_date=date(2026, 9, 30))
    user = user_for(tenant, "report-live-business-viewer")
    grant(user, "reports.view", DataScope.ScopeType.CUSTOM, {"warehouse_ids": [warehouse.id], "report_types": ["analytics_summary"]})
    report_role = _report_role(user, "report-live-business-dedicated")
    report_policy = _explicit(user, report_role, "reports.sales", {"store_ids": [store_a.id, store_b.id]})
    grant(user, "sales_management.view", DataScope.ScopeType.ALL)
    business_role = _role_for(user, "sales_management.view")
    business_policy = RoleResourcePolicy.objects.create(tenant=tenant, role=business_role, permission_code="sales_management.view", resource_code="sales_management.sales", scope_type="custom", config={"store_ids": [store_a.id]})
    client, config = client_for(user), _config("sales", ["store_id"], ["order_count"])
    first = client.post(QUERY, config, format="json").json()["data"]
    assert {row["store_id"] for row in first["rows"]} == {store_a.id}
    assert latest_sales_business_date(user, "sales") == date(2026, 9, 20)
    business_policy.config = {"store_ids": [store_b.id]}
    business_policy.save()
    second = client.post(QUERY, config, format="json").json()["data"]
    assert {row["store_id"] for row in second["rows"]} == {store_b.id} and second["cached"] is False
    assert latest_sales_business_date(user, "sales") == date(2026, 9, 30)
    report_policy.delete()
    UserRole.objects.filter(user=user, role=report_role).delete()
    assert client.post(QUERY, config, format="json").status_code == 403


def test_expired_explicit_role_cannot_use_business_role_as_reports_grant():
    tenant, _, store, _ = create_scope("report-explicit-expired-role")
    user = user_for(tenant, "report-explicit-expired-viewer")
    grant(user, "reports.view", DataScope.ScopeType.ALL)
    role = _role_for(user, "reports.view")
    _explicit(user, role, "reports.sales", {"store_ids": [store.id]})
    grant(user, "sales_management.view", DataScope.ScopeType.ALL)
    UserRole.objects.filter(user=user, role=role).update(valid_until="2020-01-01T00:00:00Z")
    with pytest.raises(PermissionDenied):
        selected_permission(user, DATASETS["sales"])


def test_finance_and_inventory_value_remain_denied_with_explicit_report_resources():
    tenant, _, store, warehouse = create_scope("report-finance-boundary")
    user = user_for(tenant, "report-finance-boundary-viewer")
    grant(user, "reports.view", DataScope.ScopeType.CUSTOM, {"report_types": ["sales_details", "analytics_summary"], "warehouse_ids": [warehouse.id]})
    role = _report_role(user, "report-finance-boundary-dedicated")
    _explicit(user, role, "reports.sales", {"store_ids": [store.id]})
    _explicit(user, role, "reports.inventory", {"warehouse_ids": [warehouse.id]})
    grant(user, "sales_management.view", DataScope.ScopeType.ALL)
    grant(user, "finance.view", DataScope.ScopeType.ALL)
    grant(user, "products.cost.view", DataScope.ScopeType.ALL)
    with pytest.raises(PermissionDenied):
        selected_permission(user, DATASETS["finance"])
    with pytest.raises(PermissionDenied):
        selected_permission(user, DATASETS["inventory_value"])
