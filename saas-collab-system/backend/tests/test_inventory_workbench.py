from datetime import timedelta

import pytest

from apps.commerce.models import InventorySnapshot
from apps.masterdata.models import WarehouseMaster
from apps.permissions.models import DataScope
from apps.products.models import ProductSKU, ProductSPU
from tests.test_sales_management import NOW, client_for, create_run, create_scope, grant, user_for


pytestmark = pytest.mark.django_db
URL = "/api/internal/commerce/inventory/workbench/"


def _snapshot(tenant, warehouse, run, sku, at, available, *, reserved=0, on_hand=None, internal_sku=None):
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
        payload_hash="f" * 64,
    )


def test_workbench_latest_snapshot_virtual_default_and_daily_trend():
    tenant, _, _, warehouse = create_scope("workbench-main")
    run = create_run(tenant, "inventory_snapshot", "workbench-main", platform="jifeng_wms")
    user = user_for(tenant, "workbench-viewer")
    grant(user, "sales_management.view")
    client = client_for(user)
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="WB-SPU", product_name="Workbench")
    physical = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="WB-P", inventory_type="physical")
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
    _snapshot(tenant, other_warehouse, run, "TARGET-ONE", NOW, 0)
    _snapshot(tenant, other_warehouse, run, "TARGET-TWO", NOW, 2)

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
