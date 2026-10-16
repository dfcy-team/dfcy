from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.commerce.models import SalesOrder
from apps.reports.datasets import query_dataset
from apps.reports.query_hints import _sales_time_index, _finance_date_index
from apps.sales_management.reporting import _local_day_expression
from tests.test_sales_management import create_scope, create_order, grant, user_for


def test_mysql_hint_keeps_bind_parameters_and_only_changes_select_plan():
    execute = Mock(return_value="rows")
    params = (42, "2026-01-01", "2026-02-01")
    sql = "SELECT COUNT(*) FROM `sales_order` WHERE tenant_id=%s AND created_at_utc>=%s AND created_at_utc<%s"
    assert _sales_time_index(execute, sql, params, False, {}) == "rows"
    called = execute.call_args.args
    assert called[0] == sql.replace("FROM `sales_order`", "FROM `sales_order` FORCE INDEX (`idx_sales_order_store_time`)")
    assert called[1] is params
    _sales_time_index(execute, "DELETE FROM `sales_order` WHERE id=%s", (1,), False, {})
    assert execute.call_args.args[0] == "DELETE FROM `sales_order` WHERE id=%s"
    finance_sql = "SELECT SUM(signed_amount) FROM `finance_platformfinancetransaction` WHERE tenant_id=%s"
    _finance_date_index(execute, finance_sql, params, False, {})
    assert "FORCE INDEX (`idx_fin_tx_tenant_date`)" in execute.call_args.args[0]
    assert execute.call_args.args[1] is params


@pytest.mark.django_db
@pytest.mark.parametrize("timestamp,expected", [
    (datetime(2026, 3, 8, 7, 59, tzinfo=UTC), "2026-03-07"),
    (datetime(2026, 3, 8, 10, 1, tzinfo=UTC), "2026-03-08"),
    (datetime(2026, 11, 1, 8, 59, tzinfo=UTC), "2026-11-01"),
    (datetime(2026, 11, 2, 7, 59, tzinfo=UTC), "2026-11-01"),
])
def test_store_id_day_projection_matches_local_dates_across_dst(timestamp, expected):
    tenant, _, store, _ = create_scope("projection-dst")
    store.timezone = "America/Los_Angeles"
    store.save(update_fields=["timezone"])
    order = create_order(tenant, store, "projection-order")
    order.created_at_utc = timestamp
    order.save(update_fields=["created_at_utc"])
    # Include a second fact on the opposite side of a DST transition, so the
    # expression actually has to construct both offset branches.
    other = create_order(tenant, store, "projection-offset")
    other.created_at_utc = datetime(timestamp.year, timestamp.month, 15, tzinfo=UTC)
    other.save(update_fields=["created_at_utc"])
    qs = SalesOrder.objects.filter(tenant=tenant)
    original = _local_day_expression(qs, "created_at_utc", "store__timezone")
    optimized = _local_day_expression(qs, "created_at_utc", "store__timezone", timezone_store_ids={store.timezone: [store.pk]})
    rows = list(qs.annotate(before=original, after=optimized).values("pk", "before", "after"))
    assert all(row["before"] == row["after"] for row in rows)
    assert str(next(row["after"] for row in rows if row["pk"] == order.pk)) == expected


@pytest.mark.django_db
def test_daily_aggregate_refresh_time_matches_source_without_second_scan():
    tenant, _, store, _ = create_scope("projection-refresh")
    order = create_order(tenant, store, "projection-fresh")
    user = user_for(tenant, "projection-reader")
    grant(user, "reports.view")
    grant(user, "sales_management.view")
    result = query_dataset(SimpleNamespace(user=user), {
        "dataset": "sales", "dimensions": ["date", "currency"], "metrics": ["gross_sales"],
        "filters": {"date_from": "2026-08-01", "date_to": "2026-08-31"},
    }, use_cache=False)
    assert result["refreshed_at"] == order.updated_at_utc
