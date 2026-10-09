from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.commerce.models import RefundReturn, SalesOrder, SalesOrderItem
from apps.sales_management.views import _currency_summary
from tests.test_sales_management import (
    NOW, client_for, create_order, create_run, create_scope, grant, user_for,
)


@pytest.mark.django_db
def test_currency_summary_uses_one_order_scan_and_preserves_currency_refund_bases():
    tenant, platform, store, _ = create_scope("summary-query")
    create_order(tenant, store, "summary-valid", "100")
    cancelled = create_order(tenant, store, "summary-cancelled", "50")
    cancelled.normalized_status = "cancelled"
    cancelled.save(update_fields=["normalized_status"])
    foreign, _, foreign_store, _ = create_scope("summary-hidden")
    create_order(foreign, foreign_store, "summary-hidden", "99999")
    for currency, status, amount in (("PHP", "completed", 20), ("GBP", "completed", 10), ("PHP", "accepted", 30)):
        suffix = f"summary-{currency}-{status}"
        RefundReturn.objects.create(
            tenant=tenant, platform=platform, store=store,
            source_run=create_run(tenant, "refund_return", suffix),
            external_return_id=suffix, case_type="refund_only", raw_status=status.upper(),
            normalized_status=status, requested_at_utc=NOW, updated_at_utc=NOW,
            currency=currency, refund_amount=amount, payload_hash="a" * 64,
        )
    with CaptureQueriesContext(connection) as captured:
        rows = _currency_summary(
            SalesOrder.objects.filter(tenant=tenant), RefundReturn.objects.filter(tenant=tenant),
        )
    by_currency = {row["currency"]: row for row in rows}
    assert set(by_currency) == {"PHP", "GBP"}
    php = by_currency["PHP"]
    assert (php["orders"], php["valid_orders"], php["cancelled_orders"], php["units"]) == (2, 1, 1, 2)
    assert php["gross"] == Decimal("100")
    assert php["refunds"] == Decimal("20")
    assert by_currency["GBP"]["orders"] == 0
    assert by_currency["GBP"]["gross"] == 0
    assert by_currency["GBP"]["refunds"] == Decimal("10")
    assert len(captured) == 3


@pytest.mark.django_db
def test_order_pagination_counts_headers_and_keeps_line_totals_and_sorting():
    tenant, _, store, _ = create_scope("page-query")
    high = create_order(tenant, store, "page-high")
    create_order(tenant, store, "page-low")
    empty = create_order(tenant, store, "page-empty")
    empty.items.all().delete()
    SalesOrderItem.objects.create(
        sales_order=high, external_line_id="page-extra", seller_sku="page-extra",
        platform_product_id="page-extra", quantity=3, currency="PHP", line_total_amount=15,
    )
    viewer = user_for(tenant, "page-viewer")
    grant(viewer, "sales_management.orders.view")
    with CaptureQueriesContext(connection) as captured:
        response = client_for(viewer).get("/api/internal/commerce/orders/", {
            "page_size": 1, "ordering": "-item_count", "include_summary": "false",
        })
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["count"] == 3
    assert data["results"][0]["id"] == high.pk
    assert data["results"][0]["item_count"] == 5
    assert data["results"][0]["line_count"] == 2
    count_queries = [row["sql"].lower() for row in captured.captured_queries
                     if "count(*)" in row["sql"].lower() and "sales_order" in row["sql"].lower()]
    assert count_queries
    assert all("sales_order_item" not in sql for sql in count_queries)
    last = client_for(viewer).get("/api/internal/commerce/orders/", {
        "page_size": 1, "page": 3, "ordering": "-item_count", "include_summary": "false",
    }).json()["data"]["results"][0]
    assert last["id"] == empty.pk
    assert last["item_count"] == last["line_count"] == 0
