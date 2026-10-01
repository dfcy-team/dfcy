from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from apps.masterdata.models import WarehouseMaster
from apps.permissions.models import DataScope
from apps.reports.datasets import DATASETS
from apps.integrations.feishu_reports import build_report
from tests.test_inventory_workbench import _snapshot
from tests.test_report_revision import _config
from tests.test_sales_management import NOW, client_for, create_run, create_scope, grant, user_for


pytestmark = pytest.mark.django_db
QUERY = "/api/report/query/"


def _inventory_rows(client):
    response = client.post(QUERY, _config("inventory", ["warehouse_id"], ["sku_count"]), format="json")
    assert response.status_code == 200, response.content
    return {row["warehouse_id"]: row["sku_count"] for row in response.json()["data"]["rows"]}


def _warehouse(tenant, suffix):
    return WarehouseMaster.objects.create(
        tenant=tenant, code=f"warehouse-{suffix}", name=suffix,
        country_code="PH", warehouse_type="third_party",
    )


def _snapshot_at(tenant, warehouse, suffix):
    run = create_run(tenant, "inventory_snapshot", suffix, platform="jifeng_wms")
    _snapshot(tenant, warehouse, run, f"SKU-{suffix}", NOW, 1)


def test_warehouse_report_scope_is_tenant_bounded_and_intersects_business_scope():
    tenant, _, _, first = create_scope("report-warehouse-first")
    second = _warehouse(tenant, "report-warehouse-second")
    third = _warehouse(tenant, "report-warehouse-third")
    _, _, _, foreign = create_scope("report-warehouse-foreign")
    for warehouse, suffix in ((first, "first"), (second, "second"), (third, "third"), (foreign, "foreign")):
        _snapshot_at(warehouse.tenant, warehouse, suffix)
    viewer = user_for(tenant, "report-warehouse-viewer")
    grant(viewer, "reports.view", DataScope.ScopeType.CUSTOM, {"warehouse_ids": [first.id, second.id]})
    grant(viewer, "sales_management.view", DataScope.ScopeType.ALL)
    assert set(_inventory_rows(client_for(viewer))) == {first.id, second.id}

    scoped_viewer = user_for(tenant, "report-warehouse-intersection")
    grant(scoped_viewer, "reports.view", DataScope.ScopeType.CUSTOM, {"warehouse_ids": [first.id, second.id]})
    grant(scoped_viewer, "sales_management.view", DataScope.ScopeType.CUSTOM, {"warehouse_ids": [second.id, third.id]})
    assert set(_inventory_rows(client_for(scoped_viewer))) == {second.id}


@pytest.mark.parametrize("dataset,permission,metric", [
    ("sales", "sales_management.view", "order_count"),
    ("sales_skus", "sales_management.view", "units_sold"),
    ("refunds", "sales_management.view", "case_count"),
    ("finance", "finance.view", "transaction_count"),
    ("inventory_value", "finance.view", "inventory_value"),
])
def test_warehouse_only_report_scope_does_not_authorize_other_report_types(dataset, permission, metric):
    tenant, _, _, warehouse = create_scope(f"report-warehouse-deny-{dataset}")
    viewer = user_for(tenant, f"report-warehouse-deny-{dataset}")
    grant(viewer, "reports.view", DataScope.ScopeType.CUSTOM, {"warehouse_ids": [warehouse.id]})
    grant(viewer, permission, DataScope.ScopeType.ALL)
    if dataset == "inventory_value":
        grant(viewer, "products.cost.view", DataScope.ScopeType.ALL)
    dimension = next(iter(DATASETS[dataset]["dimensions"]))
    response = client_for(viewer).post(QUERY, _config(dataset, [dimension], [metric]), format="json")
    assert response.status_code == 403


@pytest.mark.parametrize("config", [
    {"warehouse_ids": []},
    {"warehouse_ids": [True]},
    {"warehouse_ids": [1, "2"]},
    {"warehouse_ids": [1], "store_ids": [1]},
])
def test_malformed_or_mixed_warehouse_report_scope_is_denied(config):
    tenant, _, _, warehouse = create_scope("report-warehouse-invalid")
    viewer = user_for(tenant, f"report-warehouse-invalid-{str(config)}")
    grant(viewer, "reports.view", DataScope.ScopeType.CUSTOM, config)
    grant(viewer, "sales_management.view", DataScope.ScopeType.ALL)
    response = client_for(viewer).post(QUERY, _config("inventory", ["warehouse_id"], ["sku_count"]), format="json")
    assert response.status_code == 403


def test_requested_outside_warehouse_filter_cannot_expand_report_scope():
    tenant, _, _, allowed = create_scope("report-warehouse-filter")
    outside = _warehouse(tenant, "report-warehouse-filter-outside")
    _snapshot_at(tenant, allowed, "filter-allowed")
    _snapshot_at(tenant, outside, "filter-outside")
    viewer = user_for(tenant, "report-warehouse-filter-viewer")
    grant(viewer, "reports.view", DataScope.ScopeType.CUSTOM, {"warehouse_ids": [allowed.id]})
    grant(viewer, "sales_management.view", DataScope.ScopeType.ALL)
    response = client_for(viewer).post(
        QUERY, _config("inventory", ["warehouse_id"], ["sku_count"], {"warehouse_id": outside.id}), format="json"
    )
    assert response.status_code == 200
    assert response.json()["data"]["rows"] == []


def test_typed_report_scope_remains_supported_and_business_warehouse_scope_still_bounds_all_reports():
    tenant, _, _, allowed = create_scope("report-warehouse-typed")
    outside = _warehouse(tenant, "report-warehouse-typed-outside")
    _snapshot_at(tenant, allowed, "typed-allowed")
    _snapshot_at(tenant, outside, "typed-outside")
    typed = user_for(tenant, "report-warehouse-typed-viewer")
    grant(typed, "reports.view", DataScope.ScopeType.CUSTOM, {"report_types": ["analytics_summary"]})
    grant(typed, "sales_management.view", DataScope.ScopeType.ALL)
    assert set(_inventory_rows(client_for(typed))) == {allowed.id, outside.id}

    bounded = user_for(tenant, "report-warehouse-business-bounded")
    grant(bounded, "reports.view", DataScope.ScopeType.ALL)
    grant(bounded, "sales_management.view", DataScope.ScopeType.CUSTOM, {"warehouse_ids": [allowed.id]})
    assert set(_inventory_rows(client_for(bounded))) == {allowed.id}


@pytest.mark.parametrize("extra_scope", [{}, {"supplier_ids": [1]}, {"platform_ids": [1]}])
def test_malformed_business_warehouse_scope_fails_closed(extra_scope):
    tenant, _, _, warehouse = create_scope("report-warehouse-business-invalid")
    viewer = user_for(tenant, "report-warehouse-business-invalid-viewer")
    grant(viewer, "reports.view", DataScope.ScopeType.ALL)
    scope = {"warehouse_ids": [warehouse.id] if extra_scope else [True], **extra_scope}
    grant(viewer, "sales_management.view", DataScope.ScopeType.CUSTOM, scope)
    response = client_for(viewer).post(QUERY, _config("inventory", ["warehouse_id"], ["sku_count"]), format="json")
    assert response.status_code == 403


def test_feishu_inventory_report_uses_recipient_warehouse_scope():
    tenant, _, _, allowed = create_scope("feishu-report-warehouse-allowed")
    outside = _warehouse(tenant, "feishu-report-warehouse-outside")
    _, _, _, foreign = create_scope("feishu-report-warehouse-foreign")
    fixed = datetime(2026, 8, 17, 8, 0, tzinfo=UTC)
    for warehouse, suffix in ((allowed, "feishu-allowed"), (outside, "feishu-outside"), (foreign, "feishu-foreign")):
        run = create_run(warehouse.tenant, "inventory_snapshot", suffix, platform="jifeng_wms")
        _snapshot(warehouse.tenant, warehouse, run, f"SKU-{suffix}", fixed, 3, on_hand=7)
    recipient = user_for(tenant, "feishu-report-warehouse-recipient")
    grant(recipient, "reports.view", DataScope.ScopeType.CUSTOM, {"warehouse_ids": [allowed.id]})
    grant(recipient, "sales_management.view", DataScope.ScopeType.CUSTOM, {"warehouse_ids": [allowed.id]})
    report = build_report(
        SimpleNamespace(config={"report_type": "inventory", "filters": {"date_from": "2026-08-17", "date_to": "2026-08-17"}}),
        recipient,
    )
    inventory = next(section for section in report["sections"] if section["dataset"] == "inventory")
    assert inventory["status"] == "available"
    assert inventory["rows"] == [{"sku_count": 1, "on_hand": 7, "available": 3, "unmapped_count": 1}]
