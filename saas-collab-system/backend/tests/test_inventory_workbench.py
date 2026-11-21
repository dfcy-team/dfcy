from datetime import UTC, datetime, timedelta

import pytest

from apps.commerce.models import InventorySnapshot
from apps.integrations.models import WarehouseAuthorization
from apps.masterdata.models import WarehouseMaster
from apps.permissions.models import DataScope
from apps.products.models import ProductSKU, ProductSPU
from django.db import connection
from django.test.utils import CaptureQueriesContext
from tests.test_sales_management import NOW, client_for, create_run, create_scope, grant, user_for


pytestmark = pytest.mark.django_db
URL = "/api/internal/commerce/inventory/workbench/"


def test_observed_days_use_one_scoped_query_and_keep_utc_midnight():
    tenant, _, _, warehouse = create_scope("observed-midnight")
    run = create_run(tenant, "inventory_snapshot", "observed-midnight", platform="jifeng_wms")
    user = user_for(tenant, "observed-midnight")
    grant(user, "sales_management.view")
    _snapshot(tenant, warehouse, run, "same", datetime(2026, 1, 1, 23, 59, tzinfo=UTC), 3)
    _snapshot(tenant, warehouse, run, "same", datetime(2026, 1, 2, 0, 1, tzinfo=UTC), 7)
    with CaptureQueriesContext(connection) as captured:
        response = client_for(user).get(URL)
    assert response.status_code == 200
    assert [row["date"] for row in response.json()["data"]["trend"]] == ["2026-01-01", "2026-01-02"]
    observed = [row["sql"] for row in captured if "SELECT DISTINCT" in row["sql"] and "snapshot_day" in row["sql"] and "LIMIT 14" in row["sql"]]
    assert len(observed) == 1


def _publish_run(tenant, warehouse, run, at):
    # The current workbench reads published complete warehouse batches.
    job = run.sync_job
    if not job.warehouse_authorization_id:
        owner = job.integration_config.created_by
        job.warehouse_authorization = WarehouseAuthorization.objects.create(
            tenant=tenant, warehouse=warehouse, integration_config=job.integration_config,
            provider='jifeng_wms', external_warehouse_code=f'{warehouse.code}-{job.pk}',
            external_warehouse_region=warehouse.country_code, status='active',
            created_by=owner, updated_by=owner,
        )
        job.save(update_fields=['warehouse_authorization'])
    run.status = 'success'
    run.finished_at = max(run.finished_at or at, at)
    if 'decision_source' not in (run.masked_log or {}):
        run.masked_log = {**(run.masked_log or {}), 'decision_source': {'started_from_initial_cursor': True,
            'ended_without_cursor': True, 'all_records_valid': True}}
    run.save(update_fields=['status', 'finished_at', 'masked_log'])


def _snapshot(tenant, warehouse, run, sku, at, available, *, reserved=0, on_hand=None, internal_sku=None):
    _publish_run(tenant, warehouse, run, at)
    return InventorySnapshot.objects.create(
        tenant=tenant,
        warehouse=warehouse,
        source_run=run,
        site_code=warehouse.country_code,
        source_sku=sku,
        internal_sku=internal_sku,
        snapshot_at_utc=at,
        on_hand_qty=available if on_hand is None else on_hand,
        available_qty=available,
        reserved_qty=reserved,
        provided_quantity_fields=['available_qty', 'on_hand_qty', 'reserved_qty', 'in_transit_qty'],
        payload_hash="f" * 64,
    )


def test_workbench_latest_snapshot_virtual_default_and_daily_trend():
    tenant, _, _, warehouse = create_scope("workbench-main")
    run = create_run(tenant, "inventory_snapshot", "workbench-main", platform="jifeng_wms")
    user = user_for(tenant, "workbench-viewer")
    grant(user, "sales_management.view")
    client = client_for(user)
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="WB-SPU", product_name="Workbench")
    physical = ProductSKU.objects.create(
        tenant=tenant, spu=spu, sku_code="WB-P", product_name="SKU Workbench",
        color_code="BLK", specification="M", inventory_type="physical",
    )
    virtual = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="WB-V", inventory_type="virtual")

    _snapshot(tenant, warehouse, run, "P", NOW, 10, on_hand=12, internal_sku=physical)
    _snapshot(tenant, warehouse, run, "P", NOW + timedelta(hours=1), 4, on_hand=6, internal_sku=physical)
    _snapshot(tenant, warehouse, run, "P", NOW + timedelta(days=1), 0, on_hand=2, internal_sku=physical)
    _snapshot(tenant, warehouse, run, "U", NOW, 8, on_hand=9)
    _snapshot(tenant, warehouse, run, "U", NOW + timedelta(days=1), 3, on_hand=4)
    # An older unlinked row must not replace a newer virtual row.
    _snapshot(tenant, warehouse, run, "V", NOW, 1)
    _snapshot(tenant, warehouse, run, "V", NOW + timedelta(days=1), 100, internal_sku=virtual)

    response = client.get(URL)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["totals"] == {"sku_count": 2, "on_hand": 6, "available": 3, "reserved": 0, "in_transit": 0}
    assert data["risk_counts"] == {"out": 1, "low": 1, "locked": 0, "healthy": 0}
    assert data["mapping_counts"] == {"mapped": 1, "unmapped": 1}
    assert data["refreshed_at"] == (NOW + timedelta(days=1)).isoformat().replace("+00:00", "Z")
    assert data["freshness"]["status"] in {"fresh", "delayed", "stale"}
    assert data["warehouses"] == [{
        "warehouse_id": warehouse.id,
        "warehouse_name": warehouse.name,
        "warehouse_code": warehouse.code,
        "total": 6,
        "available": 3,
        "reserved": 0,
        "at_risk": 2,
        "unmapped": 1,
        "refreshed_at": (NOW + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
    }]
    assert data["trend"] == [
        {"date": NOW.date().isoformat(), "total": 16, "available": 13, "reserved": 0},
        {"date": (NOW + timedelta(days=1)).date().isoformat(), "total": 6, "available": 3, "reserved": 0},
    ]
    assert data["focus_total"] == 2
    assert data["focus_limit"] == 50
    assert [(item["source_sku"], item["risk"], item["mapping_status"]) for item in data["focus"]] == [
        ("P", "out", "mapped"), ("U", "low", "unmapped")
    ]
    mapped_focus = next(item for item in data["focus"] if item["source_sku"] == "P")
    unmapped_focus = next(item for item in data["focus"] if item["source_sku"] == "U")
    assert (mapped_focus["product_name"], mapped_focus["color_code"], mapped_focus["specification"]) == (
        "SKU Workbench", "BLK", "M",
    )
    assert (unmapped_focus["product_name"], unmapped_focus["color_code"], unmapped_focus["specification"]) == (
        "", "", "",
    )
    assert client.get(URL, {"include_virtual": "true"}).json()["data"]["totals"]["on_hand"] == 106


def test_workbench_is_tenant_and_data_scope_bounded():
    tenant, _, _, warehouse = create_scope("workbench-scope", country="PH")
    run = create_run(tenant, "inventory_snapshot", "workbench-scope", platform="jifeng_wms")
    _snapshot(tenant, warehouse, run, "VISIBLE", NOW, 7)
    _, _, _, other_warehouse = create_scope("workbench-other-tenant", country="TH")
    other_tenant = other_warehouse.tenant
    other_run = create_run(other_tenant, "inventory_snapshot", "workbench-other-tenant", platform="jifeng_wms")
    _snapshot(other_tenant, other_warehouse, other_run, "FOREIGN", NOW, 90)
    user = user_for(tenant, "workbench-scoped-viewer")
    grant(user, "sales_management.view", scope_type=DataScope.ScopeType.CUSTOM, config={"regions": ["TH"]})
    client = client_for(user)
    empty = client.get(URL)
    assert empty.status_code == 200
    data = empty.json()["data"]
    assert data["totals"] == {"sku_count": 0, "on_hand": 0, "available": 0, "reserved": 0, "in_transit": 0}
    assert data["freshness"] == {"status": "pending", "age_hours": None, "refreshed_at": None}
    assert data["warehouses"] == data["trend"] == data["focus"] == []
    assert data["focus_total"] == 0


def test_workbench_rejects_invalid_virtual_filter():
    tenant, _, _, _ = create_scope("workbench-invalid")
    user = user_for(tenant, "workbench-invalid-viewer")
    grant(user, "sales_management.view")
    assert client_for(user).get(URL, {"include_virtual": "maybe"}).status_code == 400
    assert client_for(user).get(URL, {"perspective": "unknown"}).status_code == 400
    for params in ({"warehouse_id": "0"}, {"warehouse_id": "bad"}, {"warehouse_id": ""},
                   {"sku": "x" * 101}, {"sku": "A\x00B"}):
        assert client_for(user).get(URL, params).status_code == 400


def test_workbench_product_queue_is_not_crowded_out_by_risk_rows():
    tenant, _, _, warehouse = create_scope("workbench-personas")
    run = create_run(tenant, "inventory_snapshot", "workbench-personas", platform="jifeng_wms")
    user = user_for(tenant, "workbench-personas-viewer")
    grant(user, "sales_management.view")
    client = client_for(user)
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="WB-PERSONA-SPU", product_name="Persona")
    mapped_sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="WB-PERSONA-SKU")
    InventorySnapshot.objects.bulk_create([
        InventorySnapshot(
            tenant=tenant, warehouse=warehouse, source_run=run, site_code=warehouse.country_code,
            source_sku=f"RISK-{index:02}", internal_sku=mapped_sku, snapshot_at_utc=NOW,
            on_hand_qty=0, available_qty=0, payload_hash="f" * 64,
        )
        for index in range(51)
    ])
    _snapshot(tenant, warehouse, run, "HEALTHY-UNMAPPED", NOW, 20)

    operations = client.get(URL).json()["data"]
    assert operations["focus_total"] == 51
    assert len(operations["focus"]) == 50
    assert all(row["risk"] == "out" for row in operations["focus"])

    product_response = client.get(URL, {"perspective": "product"})
    assert product_response.status_code == 200
    product = product_response.json()["data"]
    assert product["focus_total"] == 1
    assert [(row["source_sku"], row["risk"], row["mapping_status"]) for row in product["focus"]] == [
        ("HEALTHY-UNMAPPED", "healthy", "unmapped")
    ]
    assert product["totals"] == operations["totals"]
    assert product["risk_counts"] == operations["risk_counts"]

    manager = client.get(URL, {"perspective": "manager"}).json()["data"]
    assert manager["focus_total"] == 52
    assert len(manager["focus"]) == 50


def test_workbench_focus_filters_before_limit_without_changing_overview():
    tenant, _, _, warehouse = create_scope("workbench-filter")
    other_warehouse = WarehouseMaster.objects.create(
        tenant=tenant, code="warehouse-workbench-filter-other", name="Other",
        country_code=warehouse.country_code, warehouse_type="third_party",
    )
    run = create_run(tenant, "inventory_snapshot", "workbench-filter", platform="jifeng_wms")
    user = user_for(tenant, "workbench-filter-viewer")
    grant(user, "sales_management.view")
    client = client_for(user)
    InventorySnapshot.objects.bulk_create([
        InventorySnapshot(
            tenant=tenant, warehouse=warehouse, source_run=run, site_code=warehouse.country_code,
            source_sku=f"COMMON-{index:02}", snapshot_at_utc=NOW,
            on_hand_qty=0, available_qty=0, payload_hash="f" * 64,
        ) for index in range(55)
    ])
    _publish_run(tenant, warehouse, run, NOW)
    other_run = create_run(tenant, "inventory_snapshot", "workbench-filter-other", platform="jifeng_wms")
    _snapshot(tenant, other_warehouse, other_run, "TARGET-ONE", NOW, 0)
    _snapshot(tenant, other_warehouse, other_run, "TARGET-TWO", NOW, 2)

    unfiltered = client.get(URL).json()["data"]
    assert unfiltered["focus_total"] == 57
    assert len(unfiltered["focus"]) == 50
    assert all(item["warehouse_id"] == warehouse.id for item in unfiltered["focus"])

    filtered_response = client.get(URL, {"warehouse_id": other_warehouse.id, "sku": " target "})
    assert filtered_response.status_code == 200
    filtered = filtered_response.json()["data"]
    assert filtered["focus_total"] == 2
    assert [item["source_sku"] for item in filtered["focus"]] == ["TARGET-ONE", "TARGET-TWO"]
    assert filtered["totals"] == unfiltered["totals"]
    assert filtered["warehouses"] == unfiltered["warehouses"]
    assert filtered["trend"] == unfiltered["trend"]
    assert client.get(URL, {"warehouse_id": other_warehouse.id, "sku": "missing"}).json()["data"]["focus_total"] == 0


def test_workbench_sparse_trend_is_bounded_to_last_14_observed_days():
    tenant, _, _, warehouse = create_scope("workbench-sparse-trend")
    run = create_run(tenant, "inventory_snapshot", "workbench-sparse-trend", platform="jifeng_wms")
    user = user_for(tenant, "workbench-sparse-viewer")
    grant(user, "sales_management.view")
    client = client_for(user)
    for index in range(16):
        day = NOW + timedelta(days=index * 2)
        _snapshot(tenant, warehouse, run, "SPARSE", day, index + 1)
        _snapshot(tenant, warehouse, run, "SPARSE", day + timedelta(hours=1), index + 2)

    response = client.get(URL)
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["trend"]) == 14
    assert data["trend"][0] == {
        "date": (NOW + timedelta(days=4)).date().isoformat(),
        "total": 4, "available": 4, "reserved": 0,
    }
    assert data["trend"][-1]["available"] == 17
    assert data["totals"]["available"] == 17
    grant(user, "analytics.view")
    analysis = client.get("/api/internal/analytics/inventory/", {"include_virtual": "false"}).json()["data"]
    assert int(analysis["metrics"][0]["value"]) == data["totals"]["on_hand"]
    assert analysis["count"] == data["totals"]["sku_count"]
    assert [point["total"] for point in analysis["trend"]] == [point["total"] for point in data["trend"]]


def test_risk_filter_uses_full_authorized_source_not_only_first_fifty_rows():
    tenant, _, _, warehouse = create_scope("workbench-risk-filter")
    run = create_run(tenant, "inventory_snapshot", "workbench-risk-filter", platform="jifeng_wms")
    user = user_for(tenant, "risk-filter-viewer")
    grant(user, "sales_management.view")
    for index in range(55):
        _snapshot(tenant, warehouse, run, f"out-{index}", NOW, 0)
    _snapshot(tenant, warehouse, run, "low-after-first-fifty", NOW, 3)
    client = client_for(user)
    response = client.get(URL, {"risk": "low"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["focus_total"] == 1 and data["focus"][0]["source_sku"] == "low-after-first-fifty"
    assert data["risk_counts"]["out"] == 55 and data["focus_risk"] == "low"
    assert client.get(URL, {"risk": "unmapped"}).json()["data"]["focus_total"] == 56
    assert client.get(URL, {"risk": "invalid"}).status_code == 400


def test_workbench_product_detail_reads_are_bounded_as_focus_rows_grow():
    tenant, _, _, warehouse = create_scope("workbench-product-query-count")
    run = create_run(tenant, "inventory_snapshot", "workbench-product-query-count", platform="jifeng_wms")
    user = user_for(tenant, "workbench-product-query-count-viewer")
    grant(user, "sales_management.view")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="WB-Q-SPU", product_name="Fallback name")
    skus = [
        ProductSKU.objects.create(
            tenant=tenant, spu=spu, sku_code=f"WB-Q-{index}", color_code="RED", specification="L",
        )
        for index in range(4)
    ]
    _snapshot(tenant, warehouse, run, "Q-0", NOW, 0, internal_sku=skus[0])
    client = client_for(user)
    with CaptureQueriesContext(connection) as small_queries:
        small = client.get(URL)
    for index, sku in enumerate(skus[1:], 1):
        _snapshot(tenant, warehouse, run, f"Q-{index}", NOW, 0, internal_sku=sku)
    with CaptureQueriesContext(connection) as large_queries:
        large = client.get(URL)
    assert small.status_code == large.status_code == 200
    product_query_count = lambda queries: sum(
        "products_productsku" in query["sql"] or "products_productspu" in query["sql"]
        for query in queries
    )
    assert product_query_count(large_queries) == product_query_count(small_queries)
    assert {row["product_name"] for row in large.json()["data"]["focus"]} == {"Fallback name"}


def test_business_workbench_hides_only_confirmed_zero_stock_and_zero_sales(monkeypatch):
    tenant, _, store, warehouse = create_scope("workbench-zero-sales")
    run = create_run(tenant, "inventory_snapshot", "workbench-zero-sales", platform="jifeng_wms")
    user = user_for(tenant, "workbench-zero-sales")
    grant(user, "sales_management.view")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="ZERO-SPU")
    skus = [ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code=code, inventory_type="physical")
            for code in ["ZERO", "SOLD", "RESERVED"]]
    for sku, on_hand in zip(skus, [0, 0, 3], strict=True):
        _snapshot(tenant, warehouse, run, sku.sku_code, NOW, 0, internal_sku=sku, on_hand=on_hand)
    window = {"coverage_complete": True, "unmapped": False, "bundle_composition_unverified": False,
              "stores": [{"id": store.pk}], "units_by_sku": {skus[1].pk: 2}}
    monkeypatch.setattr("apps.commerce.country_decisions.sales_windows", lambda *args, **kwargs: {30: window})
    store.country_code = warehouse.country_code
    store.status = "active"
    store.save(update_fields=["country_code", "status"])
    api = client_for(user)
    params = {"exclude_zero_without_sales": "true"}
    result = api.get(URL, params).json()["data"]
    assert result["risk_counts"]["out"] == 2
    assert {item["source_sku"] for item in result["focus"]} == {"SOLD", "RESERVED"}
    summary = api.get(URL, {"sales_report": "true", "summary_only": "true"}).json()["data"]
    assert summary["sales_category_counts"] == {"stock_no_sales": 1, "sales_no_stock": 1, "sales_unknown": 0}
    assert summary["focus"] == []
    details = api.get(URL, {"sales_report": "true", "risk": "sales_no_stock"}).json()["data"]
    assert [(row["source_sku"], row["sales_units_30d"]) for row in details["focus"]] == [("SOLD", 2)]
    window["coverage_complete"] = False
    summary = api.get(URL, {"sales_report": "true", "summary_only": "true"}).json()["data"]
    assert summary["sales_category_counts"] == {"stock_no_sales": 1, "sales_no_stock": 1, "sales_unknown": 1}
    detail = api.get(URL, {"sales_report": "true", "risk": "stock_no_sales"}).json()["data"]
    assert [row["source_sku"] for row in detail["focus"]] == ["RESERVED"]
    from apps.listings.models import PlatformProductDetail
    PlatformProductDetail.objects.create(
        tenant=tenant, platform=store.platform, store=store,
        platform_product_id="listed", platform_variant_id="listed",
        internal_sku=skus[2],
    )
    linked = api.get(URL, {"sales_report": "true", "summary_only": "true"}).json()["data"]
    assert linked["sales_category_counts"] == {"stock_no_sales": 0, "sales_no_stock": 1, "sales_unknown": 2}
    result = api.get(URL, params).json()["data"]
    assert result["risk_counts"]["out"] == 3


def test_warehouse_details_paginates_filtered_exceptions_without_overlap():
    tenant, _, _, warehouse = create_scope("warehouse-details-pages")
    run = create_run(tenant, "inventory_snapshot", "warehouse-details-pages", platform="jifeng_wms")
    user = user_for(tenant, "warehouse-details-pages")
    grant(user, "sales_management.view")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="PAGES")
    for index in range(61):
        code = f"{'PAGE' if index < 60 else 'OTHER'}-{index:03}"
        sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code=code, inventory_type="physical")
        _snapshot(tenant, warehouse, run, code, NOW, 3, internal_sku=sku)

    api = client_for(user)
    filters = {"sales_report": "true", "risk": "stock_no_sales", "sku": "PAGE", "warehouse_id": warehouse.pk}
    pages = [api.get(URL, {**filters, "offset": offset}).json()["data"] for offset in (0, 50)]
    assert [page["focus_offset"] for page in pages] == [0, 50]
    assert [len(page["focus"]) for page in pages] == [50, 10]
    assert {page["focus_total"] for page in pages} == {60}
    assert len({row["source_sku"] for page in pages for row in page["focus"]}) == 60
    assert api.get(URL, {**filters, "offset": -1}).status_code == 400


def test_latest_complete_warehouse_batch_excludes_older_and_partial_skus(settings):
    from apps.integrations.models import WarehouseAuthorization

    settings.INVENTORY_COMPLETE_BATCH_READS_ENABLED = True
    tenant, _, _, warehouse = create_scope("complete-inventory-batch")
    user = user_for(tenant, "complete-inventory-reader")
    grant(user, "sales_management.view")
    evidence = dict(started_from_initial_cursor=True, ended_without_cursor=True, all_records_valid=True)
    for index, sku in enumerate(("OLD", "CURRENT", "PARTIAL")):
        run = create_run(tenant, "inventory_snapshot", sku, platform="jifeng_wms")
        authorization = WarehouseAuthorization.objects.create(
            tenant=tenant, integration_config=run.sync_job.integration_config, warehouse=warehouse,
            provider="jifeng_wms", status="active", external_warehouse_code=sku,
            external_warehouse_region=warehouse.country_code, created_by=user, updated_by=user,
        )
        run.sync_job.warehouse_authorization = authorization
        run.sync_job.save(update_fields=["warehouse_authorization"])
        run.status = "success"
        run.finished_at = NOW + timedelta(minutes=index)
        run.masked_log = {"decision_source": {**evidence, "started_from_initial_cursor": sku != "PARTIAL"}}
        run.save(update_fields=["status", "finished_at", "masked_log"])
        _snapshot(tenant, warehouse, run, sku, run.finished_at, 0)

    response = client_for(user).get(URL, {"risk": "out"})
    assert response.status_code == 200
    assert [row["source_sku"] for row in response.json()["data"]["focus"]] == ["CURRENT"]
