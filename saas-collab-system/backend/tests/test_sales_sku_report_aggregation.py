from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.db.models.sql.compiler import SQLCompiler
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.commerce.models import RefundReturn, RefundReturnItem, SalesOrder, SalesOrderItem
from apps.masterdata.models import StoreMaster
from apps.permissions.models import DataScope
from apps.sales_management.reporting import sku_report
from apps.sales_management.views import _sales_page_context
from tests.test_sales_management import NOW, client_for, create_order, create_run, create_scope, grant, user_for

pytestmark = pytest.mark.django_db


def _querysets(tenant):
    return SalesOrder.objects.filter(tenant=tenant), RefundReturn.objects.filter(tenant=tenant)


def _refund(tenant, platform, store, suffix, status="completed", timestamp=NOW):
    return RefundReturn.objects.create(
        tenant=tenant, platform=platform, store=store, source_run=create_run(tenant, "refund_return", suffix),
        external_return_id=suffix, case_type="refund_only", raw_status=status.upper(), normalized_status=status,
        requested_at_utc=timestamp, updated_at_utc=timestamp, currency=store.currency, refund_amount=3,
        payload_hash="a" * 64)


def test_sku_report_transfers_groups_instead_of_every_fact_row(monkeypatch):
    tenant, _, store, _ = create_scope("sku-scaling")
    order = create_order(tenant, store, "sku-scaling")
    first = order.items.get()
    SalesOrderItem.objects.bulk_create([
        SalesOrderItem(sales_order=order, external_line_id=f"extra-{index}", seller_sku=first.seller_sku,
                       platform_product_id=first.platform_product_id, quantity=1, currency="PHP", line_total_amount=1)
        for index in range(1000)
    ])
    original = SQLCompiler.results_iter
    transferred = 0

    def measured(compiler, *args, **kwargs):
        nonlocal transferred
        for row in original(compiler, *args, **kwargs):
            transferred += 1
            yield row

    monkeypatch.setattr(SQLCompiler, "results_iter", measured)
    rows, groups, trend = sku_report(*_querysets(tenant))
    assert len(rows) == 1 and rows[0]["order_count"] == 1
    assert rows[0]["gross_sales"] == 1100 and rows[0]["units_sold"] == 1002
    assert trend[0]["valid_order_count"]["PHP"] == "1"
    assert Decimal(groups[0]["metrics"][0]["value"]) == 1100
    assert transferred < 30, f"Transferred {transferred} rows for 1001 facts in one SKU group"


def test_sku_identity_and_unicode_partial_search_remain_exact():
    tenant, _, store, _ = create_scope("sku-exact")
    order = create_order(tenant, store, "sku-exact")
    order.items.all().delete()
    for index, code in enumerate(("abc", "ABC", "abc ", "ábc", "Straße", " ", "")):
        SalesOrderItem.objects.create(sales_order=order, external_line_id=f"code-{index}", seller_sku=code,
                                     platform_product_id="fallback", platform_variant_id="variant",
                                     quantity=1, currency="PHP", line_total_amount=index + 1)
    rows, _, _ = sku_report(*_querysets(tenant), grouping="product")
    assert len(rows) == 7
    assert {row["sku"] for row in rows} == {"abc", "ABC", "abc ", "ábc", "Straße", " ", ""}
    matched = sku_report(*_querysets(tenant), term="STRASSE")[0]
    assert len(matched) == 1 and matched[0]["sku"] == "Straße"
    assert sku_report(*_querysets(tenant), term="not-present") == ([], [], [])


def test_pending_refund_retains_zero_row_and_local_day_and_completed_refund_amount():
    tenant, platform, store, _ = create_scope("sku-refunds")
    for status, code in (("pending", "pending-only"), ("completed", "completed-only")):
        refund = _refund(tenant, platform, store, status, status)
        RefundReturnItem.objects.create(refund_return=refund, external_return_item_id=status, seller_sku=code,
                                        quantity=2, currency="PHP", refund_amount=3)
    rows, groups, trend = sku_report(*_querysets(tenant))
    by_code = {row["sku"]: row for row in rows}
    assert by_code["pending-only"]["refund_amount"] == 0 and by_code["pending-only"]["order_count"] == 0
    assert by_code["completed-only"]["refund_amount"] == 3
    assert by_code["completed-only"]["refund_units"] == 2
    assert len(trend) == 1 and Decimal(trend[0]["refund_amount"]["PHP"]) == 3
    assert Decimal(next(metric["value"] for metric in groups[0]["metrics"] if metric["code"] == "refund_amount")) == 3


def test_sku_status_comparisons_preserve_python_case_sensitivity_for_legacy_facts():
    tenant, platform, store, _ = create_scope("sku-legacy-status")
    order = create_order(tenant, store, "legacy-status", "10")
    refund = _refund(tenant, platform, store, "legacy-status-refund", "pending")
    RefundReturnItem.objects.create(refund_return=refund, external_return_item_id="legacy-status", seller_sku="refund",
                                    quantity=1, currency="PHP", refund_amount=3)
    with connection.cursor() as cursor:
        cursor.execute("UPDATE sales_order SET normalized_status = %s WHERE id = %s", ["Cancelled", order.pk])
        cursor.execute("UPDATE refund_return SET normalized_status = %s WHERE id = %s", ["Completed", refund.pk])
    rows, _, trend = sku_report(*_querysets(tenant))
    assert next(row for row in rows if row["seller_sku"] == "SKU-legacy-status")["gross_sales"] == 10
    assert next(row for row in rows if row["seller_sku"] == "refund")["refund_amount"] == 0
    assert trend[0]["valid_order_count"]["PHP"] == "1"


def test_sku_daily_counts_follow_dst_and_do_not_duplicate_orders_across_sku_labels():
    tenant, _, store, _ = create_scope("sku-dst")
    store.timezone = "America/Los_Angeles"
    store.save(update_fields=["timezone"])
    for index, timestamp in enumerate((datetime(2026, 11, 1, 8, 30, tzinfo=UTC),
                                       datetime(2026, 11, 1, 9, 30, tzinfo=UTC),
                                       datetime(2026, 11, 2, 8, 30, tzinfo=UTC))):
        order = create_order(tenant, store, f"sku-dst-{index}", "10")
        order.created_at_utc = timestamp
        order.save(update_fields=["created_at_utc"])
        SalesOrderItem.objects.create(sales_order=order, external_line_id="other-sku", seller_sku="shared",
                                     item_name_snapshot=f"snapshot-{index}", platform_product_id="shared",
                                     quantity=1, currency="PHP", line_total_amount=1)
    rows, groups, trend = sku_report(*_querysets(tenant))
    assert next(row for row in rows if row["seller_sku"] == "shared")["order_count"] == 3
    assert [(row["date"], row["order_count"]["PHP"]) for row in trend] == [("2026-11-01", "2"), ("2026-11-02", "1")]
    assert next(metric["value"] for metric in groups[0]["metrics"] if metric["code"] == "order_count") == "3"


def test_sku_pagination_retains_global_totals_and_permission_and_date_scope():
    tenant, platform, store, _ = create_scope("sku-page")
    hidden = StoreMaster.objects.create(tenant=tenant, platform=platform, code="HIDDEN", name="Hidden",
                                       country_code="PH", currency="PHP", timezone="Asia/Manila")
    create_order(tenant, store, "page-a", "10")
    create_order(tenant, store, "page-b", "20")
    create_order(tenant, hidden, "page-hidden", "999")
    outside = create_order(tenant, store, "page-outside", "888")
    outside.created_at_utc = datetime(2026, 8, 18, 0, 0, tzinfo=UTC)
    outside.save(update_fields=["created_at_utc"])
    viewer = user_for(tenant, "sku-page-viewer")
    grant(viewer, "sales_management.skus.view", DataScope.ScopeType.CUSTOM, {"store_ids": [str(store.id)]})
    params = {"report": "true", "date_from": "2026-08-17", "date_to": "2026-08-17",
              "page_size": 1, "ordering": "-gross_sales"}
    client = client_for(viewer)
    first = client.get("/api/internal/commerce/sales/skus/", params)
    assert first.status_code == 200
    data = first.json()["data"]
    assert data["count"] == 2 and data["results"][0]["seller_sku"] == "SKU-page-b"
    assert Decimal(data["currency_groups"][0]["metrics"][0]["value"]) == 30
    second = client.get("/api/internal/commerce/sales/skus/", dict(params, page=2)).json()["data"]
    assert second["results"][0]["seller_sku"] == "SKU-page-a"
    assert second["currency_groups"] == data["currency_groups"] and second["trend"] == data["trend"]


def test_page_context_reuses_counts_for_pending_refunds_and_empty_sources():
    tenant, platform, store, _ = create_scope("sku-context")
    _refund(tenant, platform, store, "context-pending", "pending")
    with CaptureQueriesContext(connection) as captured:
        data = _sales_page_context(*_querysets(tenant))
    assert data["source_status"] == "ready"
    assert data["quality"]["linkage"]["refund_count"] == 1
    assert next(metric["change"] for metric in data["summary_metrics"] if metric["code"] == "refund_rate") == "1 个退款退货单"
    assert len(captured) == 7
    data = _sales_page_context(SalesOrder.objects.none(), RefundReturn.objects.none())
    assert data["source_status"] == "pending"
    assert data["quality"]["checked_rows"] == 0
