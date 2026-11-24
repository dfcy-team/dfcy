"""Additive CNY summaries for already scoped currency groups."""
from decimal import Decimal, InvalidOperation

from apps.masterdata.exchange_rates import tenant_cny_rates


def _decimal(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def cny_summary(request, groups, sales_field, ad_sales_field=None, ad_spend_field="ad_spend"):
    rates = tenant_cny_rates(request.user.tenant)
    totals = {"sales": Decimal(0), "ad_spend": Decimal(0), "roi_sales": Decimal(0), "roi_spend": Decimal(0)}
    coverage = {"sales": 0, "ad_spend": 0}
    excluded = []
    missing_rates, incomparable_roi = [], []
    roi_coverage = 0
    dates = set()
    for group in groups:
        code = str(group.get("currency") or "").upper()
        rate_info = rates.get(code)
        rate = _decimal((rate_info or {}).get("rate"))
        if rate is None or rate <= 0:
            excluded.append(code or "未知币种")
            missing_rates.append(code or "未知币种")
            continue
        if rate_info.get("date"):
            dates.add(rate_info["date"].isoformat())
        for output, field in (("sales", sales_field), ("ad_spend", ad_spend_field)):
            amount = _decimal(group.get(field))
            if amount is not None:
                totals[output] += amount / rate
                coverage[output] += 1
        if ad_sales_field:
            numerator, expense = _decimal(group.get(ad_sales_field)), _decimal(group.get(ad_spend_field))
            source_roi = group.get("roi", group.get("store_roi"))
            if numerator is not None and expense is not None and expense >= 0 and (source_roi is not None or (expense == 0 and group.get("ad_status") in {"estimated", "provisional", "reference_unverified", "ready", "complete"})):
                totals["roi_sales"] += numerator / rate
                totals["roi_spend"] += expense / rate
                roi_coverage += 1
            elif numerator is not None or expense is not None:
                incomparable_roi.append(code)
    sales_value = format(totals["sales"].normalize(), "f") if coverage["sales"] else None
    spend_value = format(totals["ad_spend"].normalize(), "f") if coverage["ad_spend"] else None
    return {
        "sales_amount": sales_value,
        "ad_spend": spend_value,
        "roi_sales_amount": format(totals["roi_sales"].normalize(), "f") if roi_coverage else None,
        "roi_ad_spend": format(totals["roi_spend"].normalize(), "f") if roi_coverage else None,
        "roi": format((totals["roi_sales"] / totals["roi_spend"]).normalize(), "f") if totals["roi_spend"] else None,
        "roi_sales_scope": "各币种源 ROI 可计算范围内的店铺 GMV 之和（包括零广告费店铺）",
        "excluded_currencies": sorted(set(excluded)), "rate_dates": sorted(dates),
        "missing_rate_currencies": sorted(set(missing_rates)),
        "incomparable_roi_currencies": sorted(set(incomparable_roi)),
        "coverage": {"sales_currency_count": coverage["sales"], "ad_spend_currency_count": coverage["ad_spend"]},
        "ad_partial": any(group.get("ad_status") in {"estimated", "provisional", "partial"} for group in groups),
    }


def cny_store_rankings(request, groups):
    rates = tenant_cny_rates(request.user.tenant)
    stores = {}
    for group in groups:
        currency = group["currency"]
        rate = _decimal((rates.get(currency) or {}).get("rate"))
        for row in group.get("store_ranking", []):
            target = stores.setdefault(row["store_id"], {
                "store_id": row["store_id"], "store_name": row["store_name"],
                "country_code": row.get("country_code"), "sales_amount": Decimal(0),
                "order_count": 0, "original_amounts": [], "missing_rates": [],
            })
            amount = _decimal(row["sales_amount"])
            target["order_count"] += row["order_count"]
            target["original_amounts"].append({"currency": currency, "sales_amount": row["sales_amount"]})
            if rate is None or rate <= 0 or amount is None:
                target["missing_rates"].append(currency)
            else:
                target["sales_amount"] += amount / rate
    rows = list(stores.values())
    for row in rows:
        row["sales_amount"] = None if row["missing_rates"] else format(row["sales_amount"], "f")
    sales = sorted(rows, key=lambda row: (row["sales_amount"] is None, -Decimal(row["sales_amount"] or 0), row["store_id"]))
    orders = sorted(rows, key=lambda row: (-row["order_count"], row["store_id"]))
    return {"currency": "CNY", "store_count": len(rows), "sales_amount": sales, "order_count": orders}
