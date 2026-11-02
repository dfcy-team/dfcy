"""Decimal-only range summaries of permission-filtered, verified daily snapshots."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP


def overview(rows, start, end):
    if rows is None:
        return None
    expected = {(start + timedelta(days=i)).isoformat()
                for i in range((end - start).days + 1)}
    groups = {}
    for row in rows:
        key = tuple(row[k] for k in (
            "store_code", "advertiser_id", "platform_store_id", "currency", "timezone"))
        group = groups.setdefault(key, {"identity": row, "days": set(),
            "cost": Decimal(0), "gross_revenue": Decimal(0), "orders": 0,
            "duplicate": False})
        if row["date"] not in expected:
            continue
        if row["date"] in group["days"]:
            group["duplicate"] = True
            continue
        group["days"].add(row["date"])
        group["cost"] += Decimal(row["cost"])
        group["gross_revenue"] += Decimal(row["gross_revenue"])
        group["orders"] += row["orders"]
    result = []
    for group in groups.values():
        row = group["identity"]
        def ratio(n, d):
            return str((n / d).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if d else None
        conflict = group["duplicate"]
        result.append({**{k: row[k] for k in ("store_code", "advertiser_id",
            "advertiser_name", "platform_store_id", "currency", "timezone")},
            "stored_days": len(group["days"]), "expected_days": len(expected),
            "complete": not conflict and group["days"] == expected,
            "conflict": conflict,
            "cost": None if conflict else str(group["cost"]),
            "gross_revenue": None if conflict else str(group["gross_revenue"]),
            "orders": None if conflict else group["orders"],
            "roi": None if conflict else ratio(group["gross_revenue"], group["cost"]),
            "cost_per_order": None if conflict else ratio(group["cost"], group["orders"])})
    return result
