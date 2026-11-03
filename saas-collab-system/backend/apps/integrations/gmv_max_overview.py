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


def shop_overview(rows, subjects, start, end):
    """Aggregate stored account reports, without changing binding eligibility."""
    if rows is None:
        return None
    allowed = {(s['store_code'], s['advertiser_id']): s for s in subjects
               if s.get('historical_binding_confirmed')}
    eligible = [r for r in rows if (r['store_code'], r['advertiser_id']) in allowed]
    accounts = overview(eligible, start, end)
    groups = {}
    days = (end - start).days + 1
    for account in accounts:
        key = tuple(account[k] for k in ('store_code', 'platform_store_id', 'currency', 'timezone'))
        groups.setdefault(key, []).append(account)
    result = []
    for (store, platform_store, currency, timezone), items in groups.items():
        # Include missing mapped accounts in coverage, even if they returned no rows.
        expected_accounts = {a for (s, a), sub in allowed.items() if s == store
                             and sub['currency'] == currency and sub['mapping_timezone'] == timezone}
        expected_accounts.update(a['advertiser_id'] for a in items)
        conflict = any(a['conflict'] for a in items)
        cost = sum((Decimal(a['cost']) for a in items if a['cost'] is not None), Decimal(0))
        revenue = sum((Decimal(a['gross_revenue']) for a in items if a['gross_revenue'] is not None), Decimal(0))
        orders = sum(a['orders'] or 0 for a in items)
        stored = sum(a['stored_days'] for a in items)
        expected = len(expected_accounts) * days
        def ratio(n, d):
            return str((n / d).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)) if d and not conflict else None
        result.append(dict(store_code=store, platform_store_id=platform_store,
            currency=currency, timezone=timezone, advertiser_count=len(expected_accounts),
            stored_days=stored, expected_days=expected, complete=not conflict and stored == expected,
            conflict=conflict, cost=None if conflict else str(cost),
            gross_revenue=None if conflict else str(revenue), orders=None if conflict else orders,
            roi=ratio(revenue, cost), cost_per_order=ratio(cost, orders)))
    return result
