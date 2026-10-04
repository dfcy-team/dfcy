from datetime import UTC, datetime

import pytest
from django.db import connection
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.commerce.models import InventorySnapshot
from apps.masterdata.models import StoreMaster, WarehouseMaster
from apps.sales_management.views import _scoped_orders, commerce_filters_payload
from apps.permissions.models import DataScope
from tests.test_sales_management import create_order, create_run, create_scope, grant, user_for


@pytest.mark.django_db
def test_scoped_orders_keep_filters_and_default_ordering_with_grouped_store_dates():
    tenant, _, store_a, _ = create_scope("read-range-a")
    store_b = StoreMaster.objects.create(
        tenant=tenant, platform=store_a.platform, code="read-range-b", name="B",
        country_code="PH", currency="PHP", timezone="Asia/Manila",
    )
    store_c = StoreMaster.objects.create(
        tenant=tenant, platform=store_a.platform, code="read-range-c", name="C",
        country_code="PH", currency="PHP", timezone="Asia/Manila",
    )
    # Both stores use Manila time, so they share the same UTC interval.
    order_a = create_order(tenant, store_a, "read-range-a")
    order_b = create_order(tenant, store_b, "read-range-b")
    order_c = create_order(tenant, store_c, "read-range-c")
    order_c.created_at_utc = datetime(2026, 8, 16, 15, 59, tzinfo=UTC)
    order_c.save(update_fields=["created_at_utc"])
    viewer = user_for(tenant, "read-range-viewer")
    grant(viewer, "sales_management.view")
    request = Request(APIRequestFactory().get(
        "/", {"store_ids": f"{store_a.id},{store_b.id},{store_c.id}", "date_from": "2026-08-17", "date_to": "2026-08-17"}
    ))
    force_authenticate(request._request, user=viewer)
    request = Request(request._request)

    orders = _scoped_orders(request, "sales_management.view")

    assert list(orders.values_list("id", flat=True)) == [order_b.id, order_a.id]


@pytest.mark.django_db
def test_scoped_orders_date_range_keeps_los_angeles_dst_boundary_semantics():
    tenant, _, store, _ = create_scope("read-range-dst")
    store.timezone = "America/Los_Angeles"
    store.save(update_fields=["timezone"])
    before = create_order(tenant, store, "read-range-before")
    start = create_order(tenant, store, "read-range-start")
    end = create_order(tenant, store, "read-range-end")
    after = create_order(tenant, store, "read-range-after")
    for order, timestamp in (
        (before, datetime(2026, 3, 8, 7, 59, tzinfo=UTC)),
        (start, datetime(2026, 3, 8, 8, 0, tzinfo=UTC)),
        (end, datetime(2026, 3, 9, 6, 59, tzinfo=UTC)),
        (after, datetime(2026, 3, 9, 7, 0, tzinfo=UTC)),
    ):
        order.created_at_utc = timestamp
        order.save(update_fields=["created_at_utc"])
    viewer = user_for(tenant, "read-range-dst-viewer")
    grant(viewer, "sales_management.view")
    request = Request(APIRequestFactory().get("/", {"store_id": str(store.id), "date_from": "2026-03-08", "date_to": "2026-03-08"}))
    force_authenticate(request._request, user=viewer)
    request = Request(request._request)

    assert set(_scoped_orders(request, "sales_management.view").values_list("id", flat=True)) == {start.id, end.id}


@pytest.mark.django_db
def test_commerce_filter_inventory_catalog_keeps_historical_source_and_applies_scope():
    tenant, _, store, allowed_warehouse = create_scope("catalog-visible")
    historic_warehouse = WarehouseMaster.objects.create(
        tenant=tenant, code="catalog-historic", name="Historic", country_code="PH", warehouse_type="third_party"
    )
    denied_warehouse = WarehouseMaster.objects.create(
        tenant=tenant, code="catalog-denied", name="Denied", country_code="PH", warehouse_type="third_party"
    )
    run = create_run(tenant, "inventory_snapshot", "catalog-visible", platform="jifeng_wms")
    for warehouse, sku, when in (
        (historic_warehouse, "OLD", datetime(2024, 1, 1, tzinfo=UTC)),
        (allowed_warehouse, "CURRENT", datetime(2026, 8, 17, tzinfo=UTC)),
        (denied_warehouse, "DENIED", datetime(2026, 8, 17, tzinfo=UTC)),
    ):
        InventorySnapshot.objects.create(
            tenant=tenant, site_code="PH", warehouse=warehouse, source_run=run,
            source_sku=sku, available_qty=1, snapshot_at_utc=when, payload_hash=("a" if sku == "OLD" else "b") * 64,
        )
    unsupported_run = create_run(tenant, "sales_order", "catalog-unsupported", platform="shopee")
    # An unsupported source must not enter the candidate dimensions through a legacy row.
    unsupported = InventorySnapshot.objects.create(
        tenant=tenant, site_code="PH", warehouse=allowed_warehouse, source_run=run,
        source_sku="UNSUPPORTED", available_qty=1, snapshot_at_utc=datetime(2026, 8, 17, tzinfo=UTC), payload_hash="c" * 64,
    )
    with connection.cursor() as cursor:
        cursor.execute("UPDATE inventory_snapshot SET source_run_id=%s,site_code=%s WHERE id=%s", [unsupported_run.pk, "XX", unsupported.pk])
    other_tenant, _, _, other_warehouse = create_scope("catalog-other-tenant", country="TH")
    other_run = create_run(other_tenant, "inventory_snapshot", "catalog-other-tenant", platform="jifeng_wms")
    InventorySnapshot.objects.create(
        tenant=other_tenant, site_code="TH", warehouse=other_warehouse, source_run=other_run,
        source_sku="OTHER-TENANT", available_qty=1, snapshot_at_utc=datetime(2026, 8, 17, tzinfo=UTC), payload_hash="d" * 64,
    )
    viewer = user_for(tenant, "catalog-viewer")
    grant(viewer, "sales_management.view", DataScope.ScopeType.CUSTOM, {"warehouse_ids": [allowed_warehouse.id, historic_warehouse.id]})

    payload = commerce_filters_payload(type("Request", (), {"user": viewer, "query_params": {}})(), "sales_management.view")

    assert payload["sites"] == ["PH"]
    assert payload["warehouses"] == [
        {"id": warehouse.id, "code": warehouse.code, "name": warehouse.name, "site": "PH"}
        for warehouse in sorted([allowed_warehouse, historic_warehouse], key=lambda warehouse: warehouse.code)
    ]


@pytest.mark.django_db
def test_scoped_orders_keep_tenant_isolation_and_custom_store_scope():
    tenant, _, allowed, _ = create_scope("range-scope")
    denied = StoreMaster.objects.create(tenant=tenant, platform=allowed.platform, code="range-denied", name="Denied", country_code="PH", currency="PHP", timezone="Asia/Manila")
    other_tenant, _, other_store, _ = create_scope("range-other-tenant")
    allowed_order = create_order(tenant, allowed, "range-allowed")
    create_order(tenant, denied, "range-denied")
    create_order(other_tenant, other_store, "range-other")
    viewer = user_for(tenant, "range-scoped-viewer")
    grant(viewer, "sales_management.view", DataScope.ScopeType.CUSTOM, {"store_ids": [allowed.pk]})
    raw = APIRequestFactory().get("/", {"date_from": "2026-08-17", "date_to": "2026-08-17"})
    force_authenticate(raw, user=viewer)
    assert list(_scoped_orders(Request(raw), "sales_management.view").values_list("pk", flat=True)) == [allowed_order.pk]


@pytest.mark.django_db
def test_inventory_sites_retain_database_distinct_and_ordering_semantics():
    tenant, _, _, warehouse = create_scope("catalog-collation")
    second = WarehouseMaster.objects.create(tenant=tenant, code="second-collation", name="Second", country_code="PH", warehouse_type="third_party")
    run = create_run(tenant, "inventory_snapshot", "catalog-collation", platform="jifeng_wms")
    for index, (target, site) in enumerate([(warehouse, "PH"), (second, "ph")]):
        InventorySnapshot.objects.create(tenant=tenant, source_run=run, warehouse=target, site_code=site, source_sku=f"COLLATION-{index}", snapshot_at_utc=datetime(2026, 8, 17, tzinfo=UTC), payload_hash="f" * 64)
    viewer = user_for(tenant, "catalog-collation-viewer")
    grant(viewer, "sales_management.view")
    expected = list(InventorySnapshot.objects.filter(tenant=tenant, source_run=run).values_list("site_code", flat=True).distinct().order_by("site_code"))
    payload = commerce_filters_payload(type("Request", (), {"user": viewer, "query_params": {}})(), "sales_management.view")
    assert payload["sites"] == expected
