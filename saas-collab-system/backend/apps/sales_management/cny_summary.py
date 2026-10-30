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
    excluded = []
    dates = set()
    for group in groups:
        code = str(group.get("currency") or "").upper()
        rate_info = rates.get(code)
        rate = _decimal((rate_info or {}).get("rate"))
        if rate is None or rate <= 0:
            excluded.append(code or "未知币种")
            continue
        if rate_info.get("date"):
            dates.add(rate_info["date"].isoformat())
        for output, field in (("sales", sales_field), ("ad_spend", ad_spend_field)):
            amount = _decimal(group.get(field))
            if amount is not None:
                totals[output] += amount / rate
        if ad_sales_field:
            numerator, expense = _decimal(group.get(ad_sales_field)), _decimal(group.get(ad_spend_field))
            if numerator is not None and expense is not None and expense > 0:
                totals["roi_sales"] += numerator / rate
                totals["roi_spend"] += expense / rate
    return {
        "sales_amount": format(totals["sales"].normalize(), "f"),
        "ad_spend": format(totals["ad_spend"].normalize(), "f"),
        "roi_sales_amount": format(totals["roi_sales"].normalize(), "f") if totals["roi_spend"] else None,
        "roi_ad_spend": format(totals["roi_spend"].normalize(), "f") if totals["roi_spend"] else None,
        "roi": format((totals["roi_sales"] / totals["roi_spend"]).normalize(), "f") if totals["roi_spend"] else None,
        "roi_sales_scope": "各币种已具备可比销售额及正广告费的店铺 GMV 之和",
        "excluded_currencies": sorted(set(excluded)), "rate_dates": sorted(dates),
        "ad_partial": any(group.get("ad_status") in {"estimated", "provisional", "partial"} for group in groups),
    }
