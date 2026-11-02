"""CNY-converted monthly dashboard totals using saved tenant reference rates."""
from decimal import Decimal, InvalidOperation


def _valid_rate(entry):
    try:
        rate = Decimal(entry["rate"])
        return rate if rate.is_finite() and rate > 0 else None
    except (KeyError, TypeError, InvalidOperation):
        return None


def cny_summary(currencies, rates, selected_stores):
    """Build a daily CNY aggregate; rates mean one CNY in source currency units."""
    if not currencies:
        return None
    items = list(currencies)

    def has_nonzero_money(item):
        prior = item["previous"]
        if Decimal(prior["amount"]) != 0:
            return True
        if prior.get("ad_spend") is not None and Decimal(prior["ad_spend"]) != 0:
            return True
        for row in item["daily"]:
            if Decimal(row["amount"]) != 0:
                return True
            if row.get("ad_spend") is not None and Decimal(row["ad_spend"]) != 0:
                return True
            cmp = row.get("ad_comparison")
            if cmp and any(Decimal(cmp[key] or 0) != 0 for key in ("current", "previous")):
                return True
        return False

    has_any_data = any(has_nonzero_money(item) or item["previous"].get("quantity")
                       or item["previous"].get("ad_spend") is not None
                       or any(row.get("quantity") or row.get("ad_spend") is not None
                              or row.get("ad_comparison") is not None for row in item["daily"])
                       for item in items)
    if not has_any_data:
        return None
    needed_rates = {item["currency"].upper() for item in items if has_nonzero_money(item)}
    missing = sorted(code for code in needed_rates if code != "CNY" and not _valid_rate(rates.get(code)))
    if missing:
        return {"currency": "CNY_TOTAL", "previous": {"amount": None, "quantity": None, "ad_spend": None},
                "daily": [], "conversion": {"target_currency": "CNY", "rates": {},
                    "missing_currencies": missing, "status": "missing_rates",
                    "rate_basis": "当前已保存参考汇率；历史月份也使用此汇率，非历史结算汇率"}}

    def factor(currency):
        code = currency.upper()
        return Decimal("1") if code == "CNY" else (_valid_rate(rates.get(code)) or Decimal("1"))

    days = sorted({row["date"] for item in items for row in item["daily"]})
    previous = {"amount": Decimal(0), "quantity": 0, "ad_spend": None}
    daily = {day: {"date": day, "amount": Decimal(0), "quantity": 0,
                   "_ad_current": Decimal(0), "_ad_previous": Decimal(0), "_covered": 0}
             for day in days}
    for item in items:
        rate = factor(item["currency"])
        prior = item["previous"]
        previous["amount"] += Decimal(prior["amount"]) / rate
        previous["quantity"] += int(prior["quantity"] or 0)
        if prior.get("ad_spend") is not None:
            previous["ad_spend"] = (previous["ad_spend"] or Decimal(0)) + Decimal(prior["ad_spend"]) / rate
        for entry in item["daily"]:
            dst = daily[entry["date"]]
            dst["amount"] += Decimal(entry["amount"]) / rate
            dst["quantity"] += int(entry["quantity"] or 0)
            cmp = entry.get("ad_comparison")
            if cmp:
                dst["_ad_current"] += Decimal(cmp["current"]) / rate
                dst["_ad_previous"] += Decimal(cmp["previous"]) / rate
                dst["_covered"] += int(cmp["covered_stores"])

    totals = {}
    for store in selected_stores:
        code = (store.get("currency") or "").upper()
        if code:
            totals[code] = totals.get(code, 0) + 1
    output_days = []
    for day, row in daily.items():
        result = {"date": day, "amount": str(row["amount"]), "quantity": row["quantity"], "ad_spend": None}
        if row["_covered"]:
            result["ad_comparison"] = {"current": str(row["_ad_current"]), "previous": str(row["_ad_previous"]),
                                        "covered_stores": row["_covered"], "total_stores": sum(totals.values())}
        else:
            result["ad_comparison"] = None
        output_days.append(result)
    previous["amount"] = str(previous["amount"])
    previous["ad_spend"] = str(previous["ad_spend"]) if previous["ad_spend"] is not None else None
    return {"currency": "CNY_TOTAL", "previous": previous, "daily": output_days,
            "conversion": {"target_currency": "CNY", "rates": {
                code: {"rate": str(value["rate"]), "date": value.get("date").isoformat() if value.get("date") else None}
                for code, value in rates.items() if code in {item["currency"].upper() for item in items}
            }, "missing_currencies": [], "status": "available",
                "rate_basis": "当前已保存参考汇率；历史月份也使用此汇率，非历史结算汇率"}}
