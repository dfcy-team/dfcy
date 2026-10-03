from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.commerce.models import RefundReturn, SalesOrder, SalesOrderItem
from apps.sales_management.views import _currency_summary
from tests.test_sales_management import NOW, create_order, create_run, create_scope

pytestmark = pytest.mark.django_db


def test_currency_summary_preserves_currency_rows_statuses_freshness_and_scope():
    tenant, platform, store, _ = create_scope("currency-summary")
    valid = create_order(tenant, store, "summary-valid", "100")
    valid.currency = "USD"
    valid.updated_at_utc = NOW + timedelta(hours=1)
    valid.save()
    valid_item = valid.items.get()
    # Simulate a legacy/inconsistent fact: the summary groups items by their own source currency.
    with connection.cursor() as cursor:
        cursor.execute("UPDATE sales_order_item SET currency = %s WHERE id = %s", ["EUR", valid_item.pk])

    cancelled = create_order(tenant, store, "summary-cancelled", "70")
    cancelled.currency = "CAD"
    cancelled.normalized_status = "cancelled"
    cancelled.updated_at_utc = NOW + timedelta(hours=2)
    cancelled.save()

    completed = RefundReturn.objects.create(
        tenant=tenant, platform=platform, store=store, sales_order=None,
        source_run=create_run(tenant, "refund_return", "summary-completed"),
        external_return_id="summary-completed", case_type="return_refund", raw_status="COMPLETED",
        normalized_status="completed", requested_at_utc=NOW, updated_at_utc=NOW + timedelta(hours=3),
        currency="GBP", refund_amount=25, payload_hash="a" * 64,
    )
    RefundReturn.objects.create(
        tenant=tenant, platform=platform, store=store, sales_order=None,
        source_run=create_run(tenant, "refund_return", "summary-pending"),
        external_return_id="summary-pending", case_type="return_refund", raw_status="PENDING",
        normalized_status="pending", requested_at_utc=NOW, updated_at_utc=NOW + timedelta(hours=9),
        currency="GBP", refund_amount=90, payload_hash="b" * 64,
    )
    assert completed.currency == "GBP"

    hidden_order = create_order(tenant, store, "summary-hidden", "999")
    orders = SalesOrder.objects.filter(pk__in=[valid.pk, cancelled.pk])
    refunds = RefundReturn.objects.filter(tenant=tenant, store=store)
    with CaptureQueriesContext(connection) as queries:
        rows = _currency_summary(orders, refunds)

    by_currency = {row["currency"]: row for row in rows}
    assert list(by_currency) == ["CAD", "EUR", "GBP", "USD"]
    assert by_currency["CAD"] == {
        "currency": "CAD", "gross": Decimal("0"), "orders": 1, "valid_orders": 0,
        "cancelled_orders": 1, "units": 0, "refunds": Decimal("0"),
        "refreshed_at": NOW + timedelta(hours=2),
    }
    assert by_currency["EUR"]["units"] == 2
    assert by_currency["GBP"]["refunds"] == Decimal("25")
    assert by_currency["GBP"]["refreshed_at"] == NOW + timedelta(hours=3)
    assert by_currency["USD"]["gross"] == Decimal("100")
    assert by_currency["USD"]["orders"] == 1 and by_currency["USD"]["valid_orders"] == 1
    assert hidden_order.pk not in {row["id"] for row in orders.values("id")}

    sql = [query["sql"].lower().replace("`", '"') for query in queries.captured_queries]
    assert len(sql) == 3  # orders, items, completed refunds
    assert sum(
        statement.lstrip().startswith('select "sales_order"."currency"') and 'from "sales_order"' in statement
        for statement in sql
    ) == 1


def test_currency_summary_retains_refund_only_currency_and_excludes_pending_only_currency():
    tenant, platform, store, _ = create_scope("currency-summary-refund-only")
    RefundReturn.objects.create(
        tenant=tenant, platform=platform, store=store, sales_order=None,
        source_run=create_run(tenant, "refund_return", "summary-refund-only"),
        external_return_id="summary-refund-only", case_type="return_refund", raw_status="COMPLETED",
        normalized_status="completed", requested_at_utc=NOW, updated_at_utc=NOW,
        currency="JPY", refund_amount=12, payload_hash="c" * 64,
    )
    rows = _currency_summary(SalesOrder.objects.none(), RefundReturn.objects.filter(tenant=tenant))
    assert rows == [{
        "currency": "JPY", "gross": Decimal("0"), "orders": 0, "valid_orders": 0,
        "cancelled_orders": 0, "units": 0, "refunds": Decimal("12"), "refreshed_at": NOW,
    }]
