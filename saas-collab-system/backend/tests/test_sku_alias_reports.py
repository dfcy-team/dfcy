from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import transaction

from apps.audit.models import OperationLog
from apps.commerce.models import SalesOrderItem
from apps.permissions.models import DataScope
from apps.products.models import ProductSKU, ProductSPU, ProductSKUAlias
from apps.products.sku_aliases import filter_sku_codes, latest_identity_inventory
from apps.products.sku_alias_views import create_alias
from apps.sales_management.reporting import sku_report
from tests.test_sales_management import NOW, client_for, create_order, create_scope, grant, user_for, create_run
from tests.test_inventory_workbench import _snapshot

pytestmark = pytest.mark.django_db


@pytest.fixture
def sample():
    tenant, _, store, warehouse = create_scope("alias-report")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="ALIAS-SPU", product_name="Sample")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="NEW001", legacy_sku_code="OLD001")
    for code, qty in (("OLD001", 8), ("NEW001", 2)):
        order = create_order(tenant, store, code)
        item = order.items.get()
        item.seller_sku, item.internal_sku, item.internal_spu = code, sku, spu
        item.quantity = qty
        item.line_total_amount = Decimal(qty * 10)
        item.save()
    actor = user_for(tenant, "alias-manager")
    for permission in ("products.master.view", "products.master.manage", "reports.view", "sales_management.view", "sales_management.skus.view"):
        grant(actor, permission)
    return tenant, store, warehouse, sku, actor


def add_alias(sku, actor, code="OLDER001", start=None, end=None, **extra):
    start = start or datetime(2025, 1, 1, tzinfo=UTC)
    return create_alias(sku=sku, actor=actor, values={"alias_code": code, "effective_from": start, "effective_to": end, "reason": "confirmed same item", **extra})


def query(actor, code, mode="related", **filters):
    return client_for(actor).post("/api/report/query/", {"dataset": "sales_skus", "dimensions": ["internal_sku", "sku"], "metrics": ["units_sold", "gross_sales"], "filters": {"sku": code, "sku_mode": mode, **filters}}, format="json")


@pytest.mark.parametrize("code", ["OLD001", "NEW001", "OLDER001", "OLDEST001"])
def test_related_alias_query_returns_all_linked_source_rows(sample, code):
    _, _, _, sku, actor = sample
    add_alias(sku, actor)
    add_alias(sku, actor, "OLDEST001")
    response = query(actor, code)
    assert response.status_code == 200
    rows = response.json()["data"]["rows"]
    assert sum(row["units_sold"] for row in rows) == 10
    assert {row["sku"] for row in rows} == {"OLD001", "NEW001"}
    assert {row["internal_sku"] for row in rows} == {"NEW001"}


def test_original_source_query_and_sales_product_report_keep_original_codes(sample):
    tenant, _, _, sku, actor = sample
    add_alias(sku, actor)
    response = query(actor, "OLD001", "source")
    assert sum(row["units_sold"] for row in response.json()["data"]["rows"]) == 8
    from apps.commerce.models import SalesOrder, RefundReturn
    rows, _, _ = sku_report(SalesOrder.objects.filter(tenant=tenant), RefundReturn.objects.filter(tenant=tenant), "product", "OLDER001", "related")
    assert len(rows) == 1 and rows[0]["units_sold"] == 10
    assert rows[0]["seller_sku"] == "NEW001 / OLD001"


def test_dated_alias_supersedes_undated_legacy_and_cache_is_invalidated(sample):
    _, _, _, sku, actor = sample
    alias = add_alias(sku, actor, "OLD001", end=datetime(2026, 1, 1, tzinfo=UTC))
    assert query(actor, "OLD001", mapping_as_of="2025-06-01").json()["data"]["count"] == 2
    assert query(actor, "OLD001", mapping_as_of="2026-06-01").json()["data"]["count"] == 0
    assert query(actor, "OLD001").json()["data"]["count"] == 2
    before = query(actor, "OLD001", mapping_as_of="2025-06-01").json()["data"]
    response = client_for(actor).post(f"/api/internal/products/skus/{sku.pk}/aliases/{alias.pk}/close/", {"effective_to": "2025-03-01T00:00:00Z", "reason": "end historical code", "version_no": alias.version_no}, format="json")
    assert response.status_code == 200
    after = query(actor, "OLD001", mapping_as_of="2025-06-01").json()["data"]
    assert after["count"] == 0 and before["mapping_version"] != after["mapping_version"]


def test_alias_api_validation_scope_audit_and_stale_close(sample):
    _, _, _, sku, actor = sample
    path = f"/api/internal/products/skus/{sku.pk}/aliases/"
    payload = {"alias_code": "000old-A", "effective_from": "2025-01-01T00:00:00Z", "reason": "same physical item"}
    client = client_for(actor)
    created = client.post(path, payload, format="json")
    assert created.status_code == 201
    record = created.json()["data"]
    assert record["alias_code"] == "000old-A" and record["version_no"] == 1
    assert client.post(path, payload, format="json").status_code == 400
    assert client.get(path).json()["data"]["items"][0]["id"] == record["id"]
    assert OperationLog.objects.filter(action="product_sku.alias_create", object_id=str(record["id"])).count() == 1
    close = f'{path}{record["id"]}/close/'
    body = {"effective_to": "2025-12-01T00:00:00Z", "reason": "confirmed end", "version_no": 1}
    assert client.post(close, body, format="json").status_code == 200
    assert client.post(close, body, format="json").status_code == 400
    assert ProductSKUAlias.objects.filter(pk=record["id"]).exists()
    assert OperationLog.objects.filter(action="product_sku.alias_close").count() == 1


def test_read_only_foreign_and_custom_product_scope_cannot_manage_aliases(sample):
    tenant, _, _, sku, actor = sample
    read_only = user_for(tenant, "alias-read")
    grant(read_only, "products.master.view")
    path = f"/api/internal/products/skus/{sku.pk}/aliases/"
    assert client_for(read_only).get(path).status_code == 200
    assert client_for(read_only).post(path, {}, format="json").status_code == 403
    restricted = user_for(tenant, "alias-restricted")
    grant(restricted, "products.master.view", DataScope.ScopeType.CUSTOM, {"sku_ids": [str(sku.pk + 999)]})
    assert client_for(restricted).get(path).status_code == 404
    foreign, _, _, _ = create_scope("alias-foreign")
    other = user_for(foreign, "alias-foreign")
    grant(other, "products.master.view")
    grant(other, "products.master.manage")
    assert client_for(other).get(path).status_code == 404
    assert client_for(other).post(path, {}, format="json").status_code == 404


def test_alias_audit_failure_rolls_back_and_never_changes_source_facts(sample):
    _, _, _, sku, actor = sample
    before = list(SalesOrderItem.objects.filter(internal_sku=sku).values())
    with patch("apps.products.sku_alias_views.write_operation_log", side_effect=RuntimeError("audit unavailable")):
        with pytest.raises(RuntimeError):
            client_for(actor).post(f"/api/internal/products/skus/{sku.pk}/aliases/", {"alias_code": "FAIL", "effective_from": "2025-01-01T00:00:00Z", "reason": "test"}, format="json")
    assert not ProductSKUAlias.objects.exists()
    assert before == list(SalesOrderItem.objects.filter(internal_sku=sku).values())


def test_unmapped_and_distinct_variants_never_merge_implicitly(sample):
    tenant, store, _, sku, actor = sample
    item = create_order(tenant, store, "unmapped").items.get()
    item.seller_sku = "NO-MAP"
    item.internal_sku = None
    item.quantity = 3
    item.save()
    response = query(actor, "NO-MAP")
    assert response.status_code == 200
    assert response.json()["data"]["rows"][0]["internal_sku"] is None
    other = ProductSKU.objects.create(tenant=tenant, spu=sku.spu, sku_code="VARIANT-2")
    item.seller_sku, item.internal_sku = "OLD001", other
    item.save()
    assert query(actor, "OLD001").status_code == 400


def test_store_scoped_alias_ignores_hidden_target(sample):
    tenant, store, _, sku, actor = sample
    from tests.test_report_revision import _second_store
    hidden = _second_store(tenant, "alias-hidden")
    other = ProductSKU.objects.create(tenant=tenant, spu=sku.spu, sku_code="HIDDEN")
    item = create_order(tenant, hidden, "hidden-alias").items.get()
    item.seller_sku, item.internal_sku = "HIDDEN", other
    item.save()
    add_alias(sku, actor, "SHARED", scope_type="store", store_id=store.pk)
    add_alias(other, actor, "SHARED", scope_type="store", store_id=hidden.pk)
    assert query(actor, "SHARED").status_code == 400
    restricted = user_for(tenant, "alias-visible-only")
    grant(restricted, "reports.view")
    grant(restricted, "sales_management.view", DataScope.ScopeType.CUSTOM, {"store_ids": [str(store.pk)]})
    result = query(restricted, "SHARED")
    assert result.status_code == 200
    assert {row["internal_sku"] for row in result.json()["data"]["rows"]} == {"NEW001"}


def test_inventory_rename_keeps_latest_stock_and_rejects_same_batch_duplicates(sample):
    tenant, _, warehouse, sku, actor = sample
    from apps.commerce.models import InventorySnapshot
    run1 = create_run(tenant, "inventory_snapshot", "alias-run-1", platform="jifeng_wms")
    old = _snapshot(tenant, warehouse, run1, "OLD001", NOW - timedelta(days=1), 8, on_hand=8)
    old.internal_sku = sku
    old.save()
    run2 = create_run(tenant, "inventory_snapshot", "alias-run-2", platform="jifeng_wms")
    new = _snapshot(tenant, warehouse, run2, "NEW001", NOW, 2, on_hand=2)
    new.internal_sku = sku
    new.save()
    rows = filter_sku_codes(InventorySnapshot.objects.filter(tenant=tenant), tenant_id=tenant.pk, code="OLD001", mode="related", source_field="source_sku", warehouse_field="warehouse_id")
    assert list(latest_identity_inventory(rows).values_list("on_hand_qty", flat=True)) == [2]
    new.source_run = run1
    new.save()
    from rest_framework.exceptions import ValidationError
    with pytest.raises(ValidationError):
        latest_identity_inventory(rows)


@pytest.mark.parametrize("filters", [{"sku_mode": "unsafe"}, {"mapping_as_of": "invalid"}])
def test_invalid_query_mode_or_date_is_rejected(sample, filters):
    *_, actor = sample
    body = {"dataset": "sales_skus", "filters": filters}
    assert client_for(actor).post("/api/report/query/", body, format="json").status_code == 400


@pytest.mark.parametrize("entry", ["workbench", "analysis", "inventory", "inventory_value"])
def test_inventory_later_batch_cannot_hide_earlier_batch_alias_conflict(sample, entry):
    tenant, _, warehouse, sku, actor = sample
    for permission in ("analytics.view", "finance.view", "products.cost.view"):
        grant(actor, permission)
    run1 = create_run(tenant, "inventory_snapshot", "conflict-r1", platform="jifeng_wms")
    run2 = create_run(tenant, "inventory_snapshot", "conflict-r2", platform="jifeng_wms")
    for run, code, at in ((run1, "A", NOW - timedelta(days=1)), (run1, "B", NOW - timedelta(days=1)), (run2, "B", NOW)):
        _snapshot(tenant, warehouse, run, code, at, 2, internal_sku=sku)
    client = client_for(actor)
    if entry in {"inventory", "inventory_value"}:
        body = {"dataset": entry, "dimensions": ["internal_sku"], "metrics": ["on_hand"], "filters": {"sku": sku.sku_code, "sku_mode": "related"}}
        assert client.post("/api/report/query/", body, format="json").status_code == 400
        body["filters"] = {"sku": "A", "sku_mode": "source"}
        assert client.post("/api/report/query/", body, format="json").status_code == 200
    else:
        url = "/api/internal/commerce/inventory/workbench/" if entry == "workbench" else "/api/internal/analytics/inventory/"
        assert client.get(url, {"sku": sku.sku_code, "sku_mode": "related"}).status_code == 400
        assert client.get(url, {"sku": "A", "sku_mode": "source"}).status_code == 200


def test_drill_source_group_keeps_related_query_scope(sample):
    _, _, _, sku, actor = sample
    grant(actor, "sales_management.orders.view")
    add_alias(sku, actor)
    response = client_for(actor).get("/api/internal/sales-management/orders/", {"sku": "OLDER001", "sku_mode": "related", "source_sku": "OLD001"})
    assert response.status_code == 200
    rows = response.json()["data"]["results"]
    assert len(rows) == 1
    assert rows[0]["id"] == SalesOrderItem.objects.get(internal_sku=sku, seller_sku="OLD001").sales_order_id


def test_repeated_recode_preserves_each_previous_code_and_stable_identity(sample):
    tenant, _, _, sku, actor = sample
    from apps.products.recode_services import execute_recode
    original_id = sku.pk
    sku.sku_code = "AA000-1"
    sku.save()
    spu = sku.spu
    spu.spu_code = "AA000"
    spu.save()
    for target in ("AA001", "AA002"):
        execute_recode(tenant, [{"spu": spu, "target": target, "attribute_code": "1", "product_name": None}], actor=actor)
        spu.refresh_from_db()
    sku.refresh_from_db()
    assert sku.pk == original_id and sku.sku_code == "AA002-1"
    assert set(sku.code_aliases.values_list("alias_code", flat=True)) == {"AA000-1", "AA001-1"}
    assert {item.internal_sku_id for item in SalesOrderItem.objects.all()} == {original_id}
    assert {item.seller_sku for item in SalesOrderItem.objects.all()} == {"OLD001", "NEW001"}
    assert sum(row["units_sold"] for row in query(actor, "AA001-1").json()["data"]["rows"]) == 10


def test_date_only_alias_form_and_export_preserve_query_and_mapping_snapshot(sample, tmp_path, settings):
    _, _, _, sku, actor = sample
    client = client_for(actor)
    created = client.post(f"/api/internal/products/skus/{sku.pk}/aliases/", {"alias_code": "DATE-ONLY", "effective_from": "2025-01-01", "reason": "confirmed date"}, format="json")
    assert created.status_code == 201
    grant(actor, "reports.export")
    grant(actor, "sales_management.export")
    settings.REPORT_EXPORT_ROOT = tmp_path
    config = {"dataset": "sales_skus", "dimensions": ["sku", "internal_sku"], "metrics": ["units_sold"], "filters": {"sku": "DATE-ONLY", "sku_mode": "related", "mapping_as_of": "2025-06-01"}}
    result = client.post("/api/report/exports/", {"report_type": "self_service", "filters": {"config": config}}, format="json")
    assert result.status_code == 201
    saved = result.json()["data"]
    assert saved["row_count"] == 2
    assert saved["filters"]["config"]["filters"] == config["filters"]
    assert saved["filters"]["snapshot"]["mapping_version"]["records"] == 1


def test_sales_and_refund_conflicting_identities_are_not_merged(sample):
    tenant, store, _, sku, _ = sample
    from apps.commerce.models import SalesOrder, RefundReturn, RefundReturnItem
    from rest_framework.exceptions import ValidationError
    other = ProductSKU.objects.create(tenant=tenant, spu=sku.spu, sku_code="OTHER-REFUND")
    refund = RefundReturn.objects.create(tenant=tenant, platform=store.platform, store=store,
        source_run=create_run(tenant, "refund_return", "alias-conflict-refund"), external_return_id="alias-conflict",
        case_type="return_refund", raw_status="COMPLETED", normalized_status="completed",
        requested_at_utc=NOW, updated_at_utc=NOW, currency="PHP", refund_amount=10, payload_hash="a" * 64)
    RefundReturnItem.objects.create(refund_return=refund, seller_sku="OLD001", internal_sku=other,
        external_return_item_id="alias-conflict-item", quantity=1, currency="PHP", refund_amount=10)
    with pytest.raises(ValidationError):
        sku_report(SalesOrder.objects.filter(tenant=tenant), RefundReturn.objects.filter(tenant=tenant), "product", "OLD001", "related")


def test_source_query_keeps_case_leading_zeros_and_trailing_spaces_distinct(sample):
    tenant, store, _, sku, actor = sample
    for index, (code, quantity) in enumerate((("OLD001 ", 3), ("000OLD001", 4), ("old001", 5))):
        item = create_order(tenant, store, f"source-exact-{index}").items.get()
        item.seller_sku, item.internal_sku, item.quantity = code, sku, quantity
        item.save()
    for code, expected in (("OLD001", 8), ("OLD001 ", 3), ("000OLD001", 4), ("old001", 5)):
        response = query(actor, code, "source")
        assert response.status_code == 200
        assert sum(row["units_sold"] for row in response.json()["data"]["rows"]) == expected
