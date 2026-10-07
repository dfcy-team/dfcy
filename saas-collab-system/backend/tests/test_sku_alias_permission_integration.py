from datetime import timedelta

import pytest
from django.utils import timezone

from apps.permissions.models import DataScope, Role, RoleResourcePolicy, UserRole
from apps.masterdata.models import WarehouseMaster
from apps.products.models import ProductSKU, ProductSPU
from apps.reports.export_services import create_download_grant, create_export_request, resolve_export_file
from apps.reports.models import ReportExportRequest
from tests.test_inventory_workbench import _snapshot
from tests.test_report_revision import _second_store
from tests.test_sales_management import NOW, client_for, create_order, create_run, grant
from tests.test_sku_alias_reports import sample, add_alias, query

pytestmark = pytest.mark.django_db


def policy(actor, code, resource, config):
    role = Role.objects.get(user_roles__user=actor, permissions__code=code)
    return RoleResourcePolicy.objects.create(tenant=actor.tenant, role=role, resource_code=resource,
        permission_code=code, scope_type="custom", config=config)


def test_alias_api_uses_resource_policy_intersection_without_changing_business_grants(sample):
    tenant, _, _, sku, actor = sample
    other_spu = ProductSPU.objects.create(tenant=tenant, spu_code="OTHER-SPU", product_name="Other")
    other = ProductSKU.objects.create(tenant=tenant, spu=other_spu, sku_code="OTHER-SKU")
    path = f"/api/internal/products/skus/{sku.pk}/aliases/"
    for code in ("products.master.view", "products.master.manage"):
        policy(actor, code, "products.master", {"sku_ids": [sku.pk], "spu_ids": [other_spu.pk]})
    assert client_for(actor).get(path).status_code == 404
    assert client_for(actor).post(path, {"alias_code": "NEW-ALIAS", "effective_from": "2025-01-01", "reason": "test"}, format="json").status_code == 404
    # A product catalogue policy does not revoke independently granted sales data.
    assert query(actor, "OLD001").status_code == 200
    for item in RoleResourcePolicy.objects.filter(role__user_roles__user=actor):
        item.config = {"sku_ids": [sku.pk], "spu_ids": [sku.spu_id]}
        item.save()
    assert client_for(actor).get(path).status_code == 200
    assert client_for(actor).get(f"/api/internal/products/skus/{other.pk}/aliases/").status_code == 404


def test_sales_resource_policy_changes_invalidate_cached_alias_results(sample):
    tenant, store, _, sku, actor = sample
    hidden = _second_store(tenant, "policy-hidden")
    item = create_order(tenant, hidden, "policy-hidden").items.get()
    item.seller_sku, item.internal_sku = "OLD001", sku
    item.quantity = 7
    item.save()
    add_alias(sku, actor)
    assert sum(row["units_sold"] for row in query(actor, "OLDER001").json()["data"]["rows"]) == 17
    for code in ("sales_management.skus.view", "sales_management.view"):
        policy(actor, code, "sales_management.sales", {"store_ids": [store.pk]})
    result = query(actor, "OLDER001")
    assert result.status_code == 200
    assert sum(row["units_sold"] for row in result.json()["data"]["rows"]) == 10
    assert result.json()["data"]["cached"] is False
    UserRole.objects.filter(user=actor, role__permissions__code__startswith="sales_management.").update(status="revoked")
    assert query(actor, "OLDER001").status_code == 403


def inventory_sample(sample):
    tenant, _, warehouse, sku, actor = sample
    other = ProductSKU.objects.create(tenant=tenant, spu=sku.spu, sku_code="HIDDEN-STOCK")
    run = create_run(tenant, "inventory_snapshot", "sku-policy-stock", platform="jifeng_wms")
    _snapshot(tenant, warehouse, run, "NEW001", NOW, 2, internal_sku=sku)
    _snapshot(tenant, warehouse, run, "HIDDEN-STOCK", NOW, 9, internal_sku=other)
    return other


@pytest.mark.parametrize("permission", ["sales_management.view", "analytics.view"])
def test_inventory_resource_policy_filters_stable_identity_before_alias_resolution(sample, permission):
    _, _, warehouse, sku, actor = sample
    other = inventory_sample(sample)
    if permission == "analytics.view":
        UserRole.objects.filter(user=actor, role__permissions__code="sales_management.view").update(status="revoked")
        grant(actor, permission)
    policy(actor, permission, "commerce.inventory", {"warehouse_ids": [warehouse.pk], "sku_ids": [sku.pk]})
    body = {"dataset": "inventory", "dimensions": ["internal_sku"], "metrics": ["on_hand"], "filters": {"sku": "OLD001", "sku_mode": "related"}}
    response = client_for(actor).post("/api/report/query/", body, format="json")
    assert response.status_code == 200
    assert response.json()["data"]["rows"] == [{"internal_sku": "NEW001", "on_hand": 2}]
    body["filters"]["sku"] = other.sku_code
    assert client_for(actor).post("/api/report/query/", body, format="json").json()["data"]["rows"] == []
    if permission == "sales_management.view":
        result = client_for(actor).get("/api/internal/commerce/inventory/workbench/", {"sku": "OLD001", "sku_mode": "related"})
        assert result.status_code == 200
        assert result.json()["data"]["totals"]["available"] == 2


def test_cost_resource_policy_does_not_expand_inventory_permission(sample):
    _, _, warehouse, sku, actor = sample
    other = inventory_sample(sample)
    for code in ("finance.view", "products.cost.view"):
        grant(actor, code)
    policy(actor, "sales_management.view", "commerce.inventory", {"sku_ids": [sku.pk]})
    policy(actor, "products.cost.view", "products.cost", {"sku_ids": [other.pk], "warehouse_ids": [warehouse.pk]})
    body = {"dataset": "inventory_value", "dimensions": ["internal_sku"], "metrics": ["on_hand"], "filters": {"sku": "OLD001", "sku_mode": "related"}}
    response = client_for(actor).post("/api/report/query/", body, format="json")
    assert response.status_code == 200 and response.json()["data"]["rows"] == []


@pytest.mark.parametrize("scope_mode", ["sales_identity", "analytics_identity", "analytics_dimensions"])
def test_report_warehouse_grant_intersects_alias_identity_and_analytics_scope(sample, scope_mode):
    tenant, _, warehouse, sku, actor = sample
    other = inventory_sample(sample)
    outside = WarehouseMaster.objects.create(tenant=tenant, code="alias-outside", name="Outside", country_code="PH", warehouse_type="third_party")
    run = create_run(tenant, "inventory_snapshot", "alias-outside", platform="jifeng_wms")
    _snapshot(tenant, outside, run, "NEW001", NOW, 20, internal_sku=sku)
    add_alias(sku, actor)
    DataScope.objects.filter(role__user_roles__user=actor, role__permissions__code="reports.view").update(
        scope_type=DataScope.ScopeType.CUSTOM, config={"warehouse_ids": [warehouse.pk]})
    permission = "sales_management.view"
    if scope_mode.startswith("analytics"):
        UserRole.objects.filter(user=actor, role__permissions__code=permission).update(status="revoked")
        permission = "analytics.view"
        grant(actor, permission, DataScope.ScopeType.CUSTOM if scope_mode == "analytics_dimensions" else DataScope.ScopeType.ALL,
              {"analytics_dimensions": [{"warehouse_id": warehouse.pk, "sku_id": sku.pk}]} if scope_mode == "analytics_dimensions" else {})
    if scope_mode != "analytics_dimensions":
        policy(actor, permission, "commerce.inventory", {"warehouse_ids": [warehouse.pk, outside.pk], "sku_ids": [sku.pk], "spu_ids": [sku.spu_id]})
    body = {"dataset": "inventory", "dimensions": ["warehouse_id", "internal_sku"], "metrics": ["on_hand"], "filters": {"sku": "OLDER001", "sku_mode": "related"}}
    result = client_for(actor).post("/api/report/query/", body, format="json")
    assert result.status_code == 200, result.content
    assert result.json()["data"]["rows"] == [{"warehouse_id": warehouse.pk, "internal_sku": "NEW001", "on_hand": 2}]
    assert result.json()["data"]["dimension_labels"] == {"warehouse_id": {str(warehouse.pk): warehouse.name}}
    body["filters"]["sku"] = other.sku_code
    assert client_for(actor).post("/api/report/query/", body, format="json").json()["data"]["rows"] == []


def test_report_warehouse_scope_change_invalidates_cached_alias_results(sample):
    tenant, _, warehouse, sku, actor = sample
    inventory_sample(sample)
    outside = WarehouseMaster.objects.create(tenant=tenant, code="alias-cache-outside", name="Outside", country_code="PH", warehouse_type="third_party")
    run = create_run(tenant, "inventory_snapshot", "alias-cache-outside", platform="jifeng_wms")
    _snapshot(tenant, outside, run, "NEW001", NOW, 20, internal_sku=sku)
    body = {"dataset": "inventory", "dimensions": ["warehouse_id"], "metrics": ["on_hand"], "filters": {"sku": "OLD001", "sku_mode": "related"}}
    client = client_for(actor)
    first = client.post("/api/report/query/", body, format="json").json()["data"]
    assert {row["warehouse_id"] for row in first["rows"]} == {warehouse.pk, outside.pk}
    assert client.post("/api/report/query/", body, format="json").json()["data"]["cached"] is True
    DataScope.objects.filter(role__user_roles__user=actor, role__permissions__code="reports.view").update(
        scope_type=DataScope.ScopeType.CUSTOM, config={"warehouse_ids": [warehouse.pk]})
    narrowed = client.post("/api/report/query/", body, format="json").json()["data"]
    assert narrowed["cached"] is False
    assert narrowed["rows"] == [{"warehouse_id": warehouse.pk, "on_hand": 2}]


def test_report_store_names_include_only_authorized_visible_groups(sample):
    tenant, store, _, sku, actor = sample
    hidden = _second_store(tenant, "name-hidden")
    item = create_order(tenant, hidden, "name-hidden").items.get()
    item.internal_sku = sku
    item.save()
    policy(actor, "sales_management.skus.view", "sales_management.sales", {"store_ids": [store.pk]})
    body = {"dataset": "sales_skus", "dimensions": ["store_id"], "metrics": ["units_sold"], "filters": {}}
    result = client_for(actor).post("/api/report/query/", body, format="json")
    assert result.status_code == 200, result.content
    assert result.json()["data"]["dimension_labels"] == {"store_id": {str(store.pk): store.name}}


@pytest.mark.parametrize("report_type", ["self_service", "sales_details"])
def test_export_snapshot_and_existing_download_token_are_revoked_after_resource_policy_change(sample, settings, tmp_path, report_type):
    tenant, store, _, sku, actor = sample
    hidden = _second_store(tenant, "download-policy-hidden")
    add_alias(sku, actor)
    for code in ("reports.export", "reports.download", "sales_management.export"):
        grant(actor, code)
    for code in ("sales_management.skus.view", "sales_management.view", "sales_management.export"):
        policy(actor, code, "sales_management.sales", {"store_ids": [store.pk]})
    settings.REPORT_EXPORT_ROOT = tmp_path
    selection = {"sku": "OLDER001", "sku_mode": "related"}
    filters = {"config": {"dataset": "sales_skus", "dimensions": ["sku", "internal_sku"], "metrics": ["units_sold"], "filters": selection}} if report_type == "self_service" else selection
    exported = create_export_request(user=actor, report_type=report_type, filters=filters)
    assert exported.status == ReportExportRequest.Status.COMPLETED and exported.row_count == 2
    signed = create_download_grant(export_request=exported, actor=actor)
    from urllib.parse import parse_qs, urlsplit
    token = parse_qs(urlsplit(signed["download_reference"]).query)["token"][0]
    assert resolve_export_file(export_request=exported, actor=actor, token=token).is_file()
    for item in RoleResourcePolicy.objects.filter(resource_code="sales_management.sales", role__user_roles__user=actor):
        item.config = {"store_ids": [hidden.pk]}
        item.save()
    from rest_framework.exceptions import PermissionDenied
    with pytest.raises(PermissionDenied):
        create_download_grant(export_request=exported, actor=actor)
    with pytest.raises(PermissionDenied):
        resolve_export_file(export_request=exported, actor=actor, token=token)


def test_expired_source_binding_stops_alias_management_on_next_request(sample):
    _, _, _, sku, actor = sample
    UserRole.objects.filter(user=actor, role__permissions__code="products.master.manage").update(valid_until=timezone.now() - timedelta(seconds=1))
    path = f"/api/internal/products/skus/{sku.pk}/aliases/"
    assert client_for(actor).get(path).status_code == 200
    assert client_for(actor).post(path, {}, format="json").status_code == 403


def test_inventory_resource_policies_intersect_dimensions_and_union_effective_roles(sample):
    tenant, _, warehouse, sku, actor = sample
    other = inventory_sample(sample)
    foreign_spu = ProductSPU.objects.create(tenant=tenant, spu_code="SCOPE-EMPTY", product_name="Different product")
    policy(actor, "sales_management.view", "commerce.inventory", {
        "warehouse_ids": [warehouse.pk], "sku_ids": [sku.pk], "spu_ids": [foreign_spu.pk]})
    from apps.permissions.models import DataScope, Permission
    role = Role.objects.create(tenant=tenant, name="Second stock role", code="second-stock-role")
    role.permissions.add(Permission.objects.get(code="sales_management.view"))
    UserRole.objects.create(tenant=tenant, user=actor, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type="all", config={})
    RoleResourcePolicy.objects.create(tenant=tenant, role=role, resource_code="commerce.inventory",
        scope_type="custom", config={"warehouse_ids": [warehouse.pk], "sku_ids": [other.pk]})
    body = {"dataset": "inventory", "dimensions": ["internal_sku"], "metrics": ["on_hand"], "filters": {}}
    response = client_for(actor).post("/api/report/query/", body, format="json")
    assert response.status_code == 200
    assert response.json()["data"]["rows"] == [{"internal_sku": "HIDDEN-STOCK", "on_hand": 9}]
