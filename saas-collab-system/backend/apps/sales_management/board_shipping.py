"""Read warehouse observations; count each order on its first actual dispatch day."""
from collections import Counter
from zoneinfo import ZoneInfo
from django.apps import apps
from django.utils.dateparse import parse_datetime


def shipment_counts(rows, start, end):
    counts = Counter()
    seen = set()
    for row in rows:
        if row["order_id"] in seen:
            continue
        seen.add(row["order_id"])
        try:
            zone = ZoneInfo(row["order__store__timezone"])
        except (ValueError, TypeError, KeyError):
            continue
        stamps = []
        for package in (row.get("snapshot") or {}).get("packages", []):
            if str(package.get("status")) == "9":  # cancelled warehouse package
                continue
            try:
                stamp = parse_datetime(package.get("shipped_at_utc") or "")
            except (ValueError, TypeError):
                continue
            if stamp and stamp.utcoffset() is not None:
                stamps.append(stamp)
        if not stamps:
            continue
        day = min(stamps).astimezone(zone).date()
        if start <= day <= end:
            counts[(row["order__currency"], day.isoformat())] += 1
    return counts


def attach_shipped_trend(authorized_orders, groups, start, end, empty_group):
    try:
        model = apps.get_model("sales_management", "OrderWarehouseLookup")
    except LookupError:
        return  # older installations have no warehouse collector yet
    rows = model.objects.filter(
        order_id__in=authorized_orders.order_by().values("pk"),
        snapshot__packages__0__isnull=False,
    ).order_by().values("order_id", "order__currency", "order__store__timezone", "snapshot").iterator(chunk_size=500)
    counts = shipment_counts(rows, start, end)
    for (currency, day), count in counts.items():
        group = groups.setdefault(currency, empty_group(currency))
        group["trend_granularity"] = "hour"
        trend = group.setdefault("recent_trend", [])
        row = next((row for row in trend if row["date"] == day), None)
        if row is None:
            row = {"date": day, "sales_amount": None, "order_count": None}
            trend.append(row)
        row["shipped_order_count"] = count
    for group in groups.values():
        rows = group.setdefault("recent_trend", [])
        for row in rows:
            row.setdefault("shipped_order_count", None)
        rows.sort(key=lambda row: row["date"])
        group["shipping_note"] = "已发货按仓库实际发货时间及店铺当地日期归集，同一订单按首次发货去重；仅统计已汇入记录，缺失不代表零发货。"
