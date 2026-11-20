from datetime import date
from apps.sales_management.board_shipping import shipment_counts
from apps.sales_management.display_currency import _merge_rows


def item(order=1, stamps=None):
    return {"order_id": order, "order__currency": "PHP", "order__store__timezone": "Asia/Manila", "snapshot": {"packages": stamps or []}}


def test_first_dispatch_local_day_and_duplicate_order():
    row = item(stamps=[{"status":7,"shipped_at_utc":"2026-11-15T17:00:00Z"},{"status":7,"shipped_at_utc":"2026-11-16T18:00:00Z"}])
    assert dict(shipment_counts([row,row],date(2026,11,16),date(2026,11,16))) == {("PHP","2026-11-16"):1}


def test_cancelled_missing_naive_invalid_dates_not_counted():
    rows=[item(stamps=[{"status":9,"shipped_at_utc":"2026-11-16T00:00:00Z"}]),item(2,[{"shipped_at_utc":"invalid"}]),item(3,[{"shipped_at_utc":"2026-11-16T00:00:00"}]),item(4)]
    assert not shipment_counts(rows,date(2026,11,10),date(2026,11,16))


def test_old_order_not_recounted_for_later_package():
    row=item(stamps=[{"shipped_at_utc":"2026-10-01T00:00:00Z"},{"shipped_at_utc":"2026-11-16T00:00:00Z"}])
    assert not shipment_counts([row],date(2026,11,10),date(2026,11,16))


def test_currency_merge_sums_observed_counts():
    rows=_merge_rows([[{"date":"2026-11-16","shipped_order_count":2}],[{"date":"2026-11-16","shipped_order_count":3}],[{"date":"2026-11-16","shipped_order_count":None}]],lambda row:row["date"])
    assert rows[0]["shipped_order_count"]==5
