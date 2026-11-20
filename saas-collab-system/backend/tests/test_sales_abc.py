from zoneinfo import ZoneInfo

import pytest

from apps.commerce.models import RefundReturn, RefundReturnItem, SalesOrder
from apps.products.models import ProductSKU, ProductSPU
from apps.sales_management.aftersales_models import (
    AftersalesCase, ReturnAllocation, WarehouseReturnLine, WarehouseReturnReceipt,
)
from tests.test_sales_management import NOW, client_for, create_order, create_run, create_scope, grant, user_for


@pytest.mark.django_db
def test_abc_switches_ranked_units_and_retains_cancellation_and_return_context(monkeypatch):
    tenant, platform, store, warehouse = create_scope("abc-demand")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="ABC", product_name="Demand")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SKU")
    for status in ("pending", "cancelled", "completed"):
        create_order(tenant, store, status)
        order = SalesOrder.objects.get(store=store, external_order_id=f"ORDER-{status}")
        SalesOrder.objects.filter(pk=order.pk).update(normalized_status=status)
        order.items.update(internal_sku=sku, internal_spu=spu)
    order = SalesOrder.objects.get(store=store, external_order_id="ORDER-completed")
    refund = RefundReturn.objects.create(
        tenant=tenant, platform=platform, store=store, sales_order=order,
        source_run=create_run(tenant, "refund_return", "abc-refund"),
        external_return_id="ABC-REFUND", case_type="return_refund", raw_status="COMPLETED",
        normalized_status="completed", requested_at_utc=NOW, updated_at_utc=NOW,
        currency=store.currency, refund_amount=50, payload_hash="a" * 64,
    )
    RefundReturnItem.objects.create(
        refund_return=refund, sales_order_item=order.items.get(), internal_sku=sku,
        external_return_item_id="ABC-REFUND-LINE", quantity=1,
        currency=store.currency, refund_amount=50,
    )
    case = AftersalesCase.objects.create(tenant=tenant, store=store, order=order, refund=refund, source_key="abc")
    receipt = WarehouseReturnReceipt.objects.create(tenant=tenant, warehouse=warehouse, return_no="ABC", received_at=NOW)
    line = WarehouseReturnLine.objects.create(receipt=receipt, sku=sku.sku_code, received_quantity=1)
    ReturnAllocation.objects.create(line=line, case=case, case_sku=sku.sku_code, quantity=1)
    user = user_for(tenant, "abc-demand")
    for code in ("reports.view", "sales_management.view", "sales_management.skus.view", "sales_management.returns.view"):
        grant(user, code)
    client = client_for(user)
    day = NOW.astimezone(ZoneInfo(store.timezone)).date().isoformat()
    filters = {"store_id": store.pk, "date_from": day, "date_to": day}

    for mode, units in (("non_cancelled", 4), ("fulfilled", 2)):
        response = client.get("/api/report/sales-abc/", {**filters, "demand_mode": mode})
        assert response.status_code == 200, response.content
        data = response.json()["data"]
        assert data["ranked_units"] == units
        assert data["rows"] == [{
            "sku": "SKU", "ordered_units": 6, "units": units, "cancelled_units": 2,
            "refund_requested_units": 1, "refund_completed_units": 1, "return_received_units": 1,
            "abc": "A", "cumulative_percent": "100.00",
            "spu": "ABC", "legacy_spu": "", "legacy_sku": "", "product_name": "Demand", "image_url": "",
        }]
        parent, = data["spu_rows"]
        assert parent["spu"] == "ABC"
        assert parent["units"] == units
        assert parent["children"] == data["rows"]
    response = client.get("/api/report/sales-abc/", {**filters, "sku": "not-found"})
    assert response.json()["data"]["rows"] == []
    assert response.json()["data"]["ranked_units"] == 4
    response = client.post("/api/report/query/", {"dataset": "sales_abc", "filters": filters}, format="json")
    assert response.status_code == 200, response.content
    parent, = response.json()["data"]["rows"]
    assert parent["spu"] == "ABC"
    assert parent["children"][0]["sku"] == "SKU"
    assert parent["children"][0]["legacy_sku"] == ""
    flat = client.post("/api/report/query/", {"dataset": "sales_abc", "dimensions": ["spu", "legacy_spu", "product_name", "image_url", "abc", "sku"], "metrics": ["units"], "filters": filters, "ordering": "-units"}, format="json")
    assert flat.status_code == 200, flat.content
    assert flat.json()["data"]["rows"][0]["sku"] == "SKU"
    assert "children" not in flat.json()["data"]["rows"][0]
    import csv
    import io
    from apps.reports import export_services
    for code in ("reports.export", "sales_management.export"):
        grant(user, code)
    captured = []
    monkeypatch.setattr(export_services, "write_export", lambda request, content: captured.append(content))
    exported = export_services._create_self_service_export(user, {"config": {"dataset": "sales_abc", "filters": filters}}, "reports.export", "csv")
    csv_rows = list(csv.reader(io.StringIO(captured[0].decode("utf-8-sig"))))
    assert exported.row_count == 1
    assert csv_rows[1][csv_rows[0].index("新编码（SKU）")] == "SKU"
    assert csv_rows[1][csv_rows[0].index("商品名称")] == "Demand"
    assert csv_rows[0].count("商品名称") == 1


def test_abc_ranks_by_units_and_keeps_threshold_crossing_sku_in_current_bucket():
    from apps.reports.sales_abc import rank_rows

    rows = [{"sku": sku, "units": units} for sku, units in (("E", 0), ("D", 4), ("C", 15), ("B", 1), ("A", 80))]
    assert rank_rows(rows) == 100
    assert [(row["sku"], row["abc"], row["cumulative_percent"]) for row in rows] == [
        ("A", "A", "80.00"), ("C", "B", "95.00"), ("D", "C", "99.00"),
        ("B", "C", "100.00"), ("E", None, None),
    ]


@pytest.mark.django_db
def test_abc_master_options_do_not_require_order_facts_and_support_country_platform():
    tenant, platform, store, _ = create_scope("abc-master-options")
    user = user_for(tenant, "abc-master-options")
    for code in ("reports.view", "sales_management.view", "sales_management.returns.view"):
        grant(user, code)
    client = client_for(user)
    response = client.get("/api/report/sales-abc-options/")
    assert response.status_code == 200, response.content
    assert any(option["value"] == str(store.pk) for option in response.json()["data"]["options"])
    day = NOW.astimezone(ZoneInfo(store.timezone)).date().isoformat()
    response = client.get("/api/report/sales-abc/", {
        "country": store.country_code, "platform": platform.platform_type,
        "date_from": day, "date_to": day,
    })
    assert response.status_code == 200, response.content
    assert response.json()["data"]["rows"] == []


@pytest.mark.django_db
def test_abc_country_platform_query_filters_real_demand_and_store_options():
    from apps.permissions.models import DataScope
    from apps.masterdata.models import StoreMaster

    tenant, platform, store, _ = create_scope("abc-country")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="ABC-C", product_name="Country")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="ABC-C")
    create_order(tenant, store, "abc-country").items.update(internal_sku=sku, internal_spu=spu)
    other = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="excluded", name="Excluded",
        country_code=store.country_code, currency=store.currency, timezone=store.timezone,
    )
    create_order(tenant, other, "excluded").items.update(internal_sku=sku, internal_spu=spu)
    user = user_for(tenant, "abc-country")
    grant(user, "reports.view")
    for code in ("sales_management.view", "sales_management.returns.view"):
        grant(user, code, DataScope.ScopeType.CUSTOM, {"store_ids": [store.pk]})
    client = client_for(user)
    options = client.get("/api/report/sales-abc-options/").json()["data"]["options"]
    assert {x["value"] for x in options} == {str(store.pk)}
    filters = {
        "country": store.country_code, "platform": platform.platform_type,
        "date_from": NOW.astimezone(ZoneInfo(store.timezone)).date().isoformat(),
        "date_to": NOW.astimezone(ZoneInfo(store.timezone)).date().isoformat(),
    }
    assert client.get("/api/report/sales-abc/", filters).json()["data"]["ranked_units"] == 2
    assert client.get("/api/report/sales-abc/", {**filters, "country": "ZZ"}).json()["data"]["rows"] == []


def test_sales_abc_is_a_valid_self_service_dataset_with_spu_tree_defaults():
    from rest_framework.exceptions import ValidationError
    from apps.reports.datasets import normalize_config

    config = normalize_config({"dataset": "sales_abc"})
    assert config["dimensions"] == ["spu", "legacy_spu", "product_name", "image_url", "abc"]
    assert "sku" in normalize_config({"dataset": "sales_abc", "dimensions": ["spu", "sku"], "metrics": ["units"]})["dimensions"]
    with pytest.raises(ValidationError):
        normalize_config({"dataset": "sales_abc", "filters": {"demand_mode": "bad"}})


@pytest.mark.django_db
def test_sales_abc_self_service_query_and_export_require_scoped_sales_permissions():
    from apps.permissions.models import DataScope
    from apps.reports.datasets import dataset_catalog
    from apps.reports.export_services import _self_service_access
    from rest_framework.exceptions import PermissionDenied

    tenant, _, _, _ = create_scope("abc-self-service")
    user = user_for(tenant, "abc-self-service")
    for code in ("reports.view", "sales_management.view", "sales_management.skus.view", "sales_management.returns.view"):
        grant(user, code)
    assert "sales_abc" in {entry["id"] for entry in dataset_catalog(user)}
    config = {"dataset": "sales_abc"}
    client = client_for(user)
    saved = client.post("/api/report/views/", {"name": "ABC test", "config": config}, format="json")
    assert saved.status_code == 201, saved.content
    assert saved.json()["data"]["config"]["dataset"] == "sales_abc"
    with pytest.raises(PermissionDenied):
        _self_service_access(user, config)
    grant(user, "reports.export")
    grant(user, "sales_management.export", DataScope.ScopeType.ALL, {})
    normalized, export_permission, source_scope = _self_service_access(user, config)
    assert normalized["dataset"] == "sales_abc"
    assert export_permission == "sales_management.export"
    assert "sales_management.skus.view" in source_scope
    assert "sales_management.returns.view" in source_scope
