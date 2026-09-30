from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import override_settings

from apps.finance.ingestion import upsert_finance_transaction
from apps.integrations.models import SyncJob, SyncRun
from apps.masterdata.models import PlatformMaster, StoreMaster, WarehouseMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductCostVersion, ProductSKU, ProductSPU
from apps.reports.models import ReportExportRequest
from tests.test_lazada_order_finance_ingestion import _lazada_scope
from tests.test_inventory_workbench import _snapshot
from tests.test_sales_management import NOW, client_for, create_order, create_run, create_scope, grant, user_for


pytestmark = pytest.mark.django_db
QUERY = "/api/report/query/"
VIEWS = "/api/report/views/"


def _config(dataset, dimensions, metrics, filters=None):
    return {"dataset": dataset, "dimensions": dimensions, "metrics": metrics, "filters": filters or {}}


def _report_access(user, *codes):
    grant(user, "reports.view")
    for code in codes:
        grant(user, code)


def _second_store(tenant, suffix):
    platform = PlatformMaster.objects.get(tenant=tenant)
    return StoreMaster.objects.create(tenant=tenant, platform=platform, code=f"store-{suffix}", name=suffix,
        country_code="PH", currency="PHP", timezone="Asia/Manila")


def test_sales_dataset_groups_currency_and_separates_cancelled_orders_and_tenants():
    tenant, _, store, _ = create_scope("report-sales", currency="PHP")
    create_order(tenant, store, "kept", "125.0000")
    cancelled = create_order(tenant, store, "void", "75.0000")
    cancelled.normalized_status = "cancelled"
    cancelled.save(update_fields=["normalized_status"])
    foreign_tenant, _, foreign_store, _ = create_scope("report-sales-foreign", currency="PHP")
    create_order(foreign_tenant, foreign_store, "foreign", "900.0000")
    viewer = user_for(tenant, "report-sales-viewer")
    _report_access(viewer, "sales_management.view")

    response = client_for(viewer).post(QUERY, _config("sales", ["store_id"], ["order_count", "valid_order_count", "cancelled_order_count", "gross_sales"]), format="json")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["config"]["dimensions"] == ["store_id", "currency"]
    assert data["count"] == 1
    assert data["rows"][0]["order_count"] == 2
    assert data["rows"][0]["valid_order_count"] == 1
    assert data["rows"][0]["cancelled_order_count"] == 1
    assert Decimal(data["rows"][0]["gross_sales"]) == Decimal("125.0000")


def test_sales_dataset_obeys_custom_store_scope():
    tenant, _, visible, _ = create_scope("report-visible")
    hidden = _second_store(tenant, "hidden")
    create_order(tenant, visible, "visible")
    create_order(tenant, hidden, "hidden")
    viewer = user_for(tenant, "report-scope-viewer")
    grant(viewer, "sales_management.view", DataScope.ScopeType.CUSTOM, {"store_ids": [str(visible.id)]})
    response = client_for(viewer).post(QUERY, _config("sales", ["store_id"], ["order_count"]), format="json")
    assert response.status_code == 200
    assert [row["store_id"] for row in response.json()["data"]["rows"]] == [visible.id]


def test_inventory_uses_latest_as_of_and_excludes_latest_virtual_by_default():
    tenant, _, _, warehouse = create_scope("report-inventory")
    run = create_run(tenant, "inventory_snapshot", "report-inventory", platform="jifeng_wms")
    viewer = user_for(tenant, "report-inventory-viewer")
    _report_access(viewer, "sales_management.view")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="REPORT-SPU", product_name="Report")
    physical = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="REPORT-P", inventory_type="physical")
    virtual = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="REPORT-V", inventory_type="virtual")
    _snapshot(tenant, warehouse, run, "P", NOW, 10, on_hand=12, internal_sku=physical)
    _snapshot(tenant, warehouse, run, "P", NOW + timedelta(hours=1), 4, on_hand=6, internal_sku=physical)
    _snapshot(tenant, warehouse, run, "V", NOW, 1, on_hand=1, internal_sku=virtual)
    _snapshot(tenant, warehouse, run, "V", NOW + timedelta(hours=1), 100, on_hand=100, internal_sku=virtual)
    config = _config("inventory", ["warehouse_id"], ["sku_count", "on_hand"], {"date_to": NOW.date().isoformat()})

    response = client_for(viewer).post(QUERY, config, format="json")
    assert response.status_code == 200
    assert response.json()["data"]["rows"] == [{"warehouse_id": warehouse.id, "sku_count": 1, "on_hand": 6}]
    config["filters"]["include_virtual"] = "true"
    response = client_for(viewer).post(QUERY, config, format="json")
    assert response.status_code == 200
    assert response.json()["data"]["rows"][0]["sku_count"] == 2
    assert response.json()["data"]["rows"][0]["on_hand"] == 106


def test_inventory_value_requires_grants_and_uses_warehouse_effective_costs():
    tenant, _, _, warehouse = create_scope("report-cost")
    run = create_run(tenant, "inventory_snapshot", "report-cost", platform="jifeng_wms")
    viewer = user_for(tenant, "report-cost-viewer")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="COST-SPU", product_name="Cost")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="COST-SKU")
    missing = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="NO-COST")
    _snapshot(tenant, warehouse, run, "COST-SKU", NOW, 3, on_hand=3, internal_sku=sku)
    _snapshot(tenant, warehouse, run, "NO-COST", NOW, 5, on_hand=5, internal_sku=missing)
    config = _config("inventory_value", ["warehouse_id"], ["valued_count", "missing_cost_count", "zero_cost_count", "inventory_value"], {"date_to": NOW.date().isoformat()})
    client = client_for(viewer)
    assert client.post(QUERY, config, format="json").status_code == 403
    _report_access(viewer, "sales_management.view", "finance.view")
    assert client.post(QUERY, config, format="json").status_code == 403
    grant(viewer, "products.cost.view")
    ProductCostVersion.objects.create(tenant=tenant, sku=sku, warehouse=warehouse, version_no=1,
        status="confirmed", currency="PHP", confirmed_cost=Decimal("4.2500"),
        effective_from=NOW - timedelta(days=1), created_by=viewer)
    ProductCostVersion.objects.create(tenant=tenant, sku=sku, warehouse=WarehouseMaster.objects.create(
        tenant=tenant, code="other-wh", name="Other", country_code="PH", warehouse_type="third_party"),
        version_no=2, status="confirmed", currency="PHP", confirmed_cost=Decimal("90.0000"),
        effective_from=NOW - timedelta(days=1), created_by=viewer)
    response = client.post(QUERY, config, format="json")
    assert response.status_code == 200
    assert response.json()["data"]["config"]["dimensions"] == ["warehouse_id", "currency"]
    rows = {row["currency"]: row for row in response.json()["data"]["rows"]}
    assert rows["PHP"]["valued_count"] == 1 and rows["PHP"]["missing_cost_count"] == 0
    assert rows["PHP"]["zero_cost_count"] == 0
    assert Decimal(rows["PHP"]["inventory_value"]) == Decimal("12.7500")
    assert rows[None]["valued_count"] == 0 and rows[None]["missing_cost_count"] == 1
    assert rows[None]["inventory_value"] is None


def test_saved_views_are_private_or_shared_but_queries_use_viewer_scope():
    tenant, _, visible_store, _ = create_scope("report-view-visible")
    hidden_store = _second_store(tenant, "view-hidden")
    create_order(tenant, visible_store, "view-visible")
    create_order(tenant, hidden_store, "view-hidden")
    owner = user_for(tenant, "report-view-owner")
    viewer = user_for(tenant, "report-view-reader")
    _report_access(owner, "sales_management.view")
    grant(viewer, "reports.view")
    grant(viewer, "sales_management.view", DataScope.ScopeType.CUSTOM, {"store_ids": [str(visible_store.id)]})
    owner_client, viewer_client = client_for(owner), client_for(viewer)
    config = _config("sales", ["store_id"], ["order_count"])
    private = owner_client.post(VIEWS, {"name": "Private", "config": config}, format="json")
    shared = owner_client.post(VIEWS, {"name": "Shared", "config": config, "is_shared": True}, format="json")
    assert private.status_code == shared.status_code == 201
    assert [item["id"] for item in viewer_client.get(VIEWS).json()["data"]] == [shared.json()["data"]["id"]]
    assert viewer_client.post(QUERY, shared.json()["data"]["config"], format="json").json()["data"]["rows"] == [
        {"store_id": visible_store.id, "order_count": 1}
    ]
    assert owner_client.put(f"{VIEWS}{shared.json()['data']['id']}/", {"name": "Edited", "config": config, "is_shared": False}, format="json").status_code == 200
    assert owner_client.delete(f"{VIEWS}{private.json()['data']['id']}/").status_code == 200


def test_dataset_catalog_and_query_reject_unavailable_or_invalid_config():
    tenant, _, _, _ = create_scope("report-catalog")
    viewer = user_for(tenant, "report-catalog-viewer")
    grant(viewer, "reports.view")
    grant(viewer, "sales_management.view")
    client = client_for(viewer)
    catalog = client.get("/api/report/datasets/")
    assert catalog.status_code == 200
    assert {row["id"] for row in catalog.json()["data"]["datasets"]} == {"sales", "sales_skus", "refunds", "inventory"}
    assert client.post(QUERY, _config("sales", ["invented"], ["order_count"]), format="json").status_code == 400
    assert client.post(QUERY, {**_config("sales", ["store_id"], ["order_count"]), "raw_sql": "select"}, format="json").status_code == 400


@override_settings(REPORT_EXPORT_ROOT="")
def test_self_service_export_file_and_download_recheck_source_scope(tmp_path, settings):
    settings.REPORT_EXPORT_ROOT = str(tmp_path / "report-exports")
    tenant, _, visible_store, _ = create_scope("report-export-visible")
    hidden_store = _second_store(tenant, "export-hidden")
    create_order(tenant, visible_store, "export-visible", "23.0000")
    create_order(tenant, hidden_store, "export-hidden", "99.0000")
    user = user_for(tenant, "report-export-user")
    _report_access(user, "sales_management.view", "sales_management.export", "reports.export", "reports.download")
    client = client_for(user)
    config = _config("sales", ["store_id"], ["order_count"], {"store_id": str(visible_store.id)})
    created = client.post("/api/report/exports/", {"report_type": "self_service", "filters": {"config": config}}, format="json")
    assert created.status_code == 201
    export = created.json()["data"]
    assert export["has_file"] is True
    assert export["filters"]["config"] == {**config, "chart": "table", "pivot": "", "ordering": ""}
    export_record = ReportExportRequest.objects.get(pk=export["id"])
    stored = (tmp_path / "report-exports" / export_record.storage_key).read_bytes()
    assert stored.startswith(b"\xef\xbb\xbf")
    lines = stored.decode("utf-8-sig").splitlines()
    assert len(lines) == 2
    assert str(visible_store.id) in lines[1] and "1" in lines[1]
    assert str(hidden_store.id) not in "\n".join(lines)

    grant_response = client.post(f"/api/report/exports/{export['id']}/download/", {}, format="json")
    assert grant_response.status_code == 200
    download_url = grant_response.json()["data"]["download_reference"]
    token = parse_qs(urlparse(download_url).query)["token"][0]
    file_path = f"/api/report/exports/{export['id']}/file/"
    assert client.get(file_path, {"token": token}).status_code == 200

    view_scope = DataScope.objects.get(role__user_roles__user=user, role__permissions__code="sales_management.view")
    view_scope.scope_type = DataScope.ScopeType.CUSTOM
    view_scope.config = {"store_ids": [str(hidden_store.id)]}
    view_scope.save(update_fields=["scope_type", "config"])
    assert client.post(f"/api/report/exports/{export['id']}/download/", {}, format="json").status_code == 403
    assert client.get(file_path, {"token": token}).status_code == 403


def test_finance_scope_limits_transaction_collection_and_report_drillthrough():
    tenant, user, store, config, authorization = _lazada_scope("report-finance-scope")
    role = Role.objects.create(tenant=tenant, name="Finance scoped", code=f"finance-scope-{user.id}")
    permission, _ = Permission.objects.get_or_create(code="finance.view", defaults={"name": "Finance view", "module": "finance", "action": "view"})
    role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.CUSTOM, config={"platforms": ["lazada"], "currencies": ["USD"]})
    job = SyncJob.objects.create(tenant=tenant, integration_config=config, store_authorization=authorization, resource_type="settlement_bill")
    run = SyncRun.objects.create(tenant=tenant, sync_job=job, run_id="report-finance", idempotency_key="report-finance")
    for currency, amount in (("USD", "11.00"), ("EUR", "77.00")):
        upsert_finance_transaction(tenant=tenant, store=store, authorization=authorization, source_run=run, payload={
            "contract_version": "finance_transaction.v1", "source_key": f"scope-{currency}",
            "external_transaction_id": f"scope-{currency}", "raw_fee_name": "Commission",
            "raw_amount": amount, "currency": currency, "occurred_at_utc": NOW.isoformat(),
        })
    client = client_for(user)
    collection = client.get("/api/finance/transactions/")
    assert collection.status_code == 200
    assert [item["currency"] for item in collection.json()["data"]["items"]] == ["USD"]
    narrowed = client.get("/api/finance/transactions/", {"store_ids": str(store.id), "platforms": "lazada", "raw_fee_name": "Commission"})
    assert narrowed.status_code == 200 and len(narrowed.json()["data"]["items"]) == 1
    assert client.get("/api/finance/transactions/", {"store_ids": "9223372036854775808"}).status_code == 400
    assert client.get("/api/finance/transactions/", {"raw_fee_name": "Unrelated name"}).json()["data"]["items"] == []
    report = client.post(QUERY, _config("finance", ["currency"], ["transaction_count", "signed_amount"]), format="json")
    assert report.status_code == 200
    report_rows = report.json()["data"]["rows"]
    assert len(report_rows) == 1
    assert report_rows[0]["currency"] == "USD" and report_rows[0]["transaction_count"] == 1
    assert Decimal(report_rows[0]["signed_amount"]) == Decimal("-11.0000")



def test_order_drill_preserves_exact_sku_and_excludes_cancelled_without_inflating_units():
    tenant, _, store, _ = create_scope('report-exact-drill')
    kept = create_order(tenant, store, 'drill')
    similar = create_order(tenant, store, 'drill-long')
    cancelled = create_order(tenant, store, 'drill-void')
    cancelled.items.update(seller_sku='SKU-drill')
    cancelled.normalized_status = 'cancelled'
    cancelled.save(update_fields=['normalized_status'])
    viewer = user_for(tenant, 'report-exact-viewer')
    grant(viewer, 'sales_management.orders.view')
    response = client_for(viewer).get('/api/internal/sales-management/orders/', {
        'sku': 'SKU-drill', 'sku_exact': 'true', 'exclude_cancelled': 'true', 'include_summary': 'false'})
    assert response.status_code == 200
    rows = response.json()['data']['results']
    assert [row['id'] for row in rows] == [kept.id]
    assert rows[0]['item_count'] == 2
