"""Response-layer CNY conversion for already scoped sales facts."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError

from apps.masterdata.exchange_rates import tenant_cny_rates


MONEY_FIELDS = {
    "order_total_amount", "gross_sales", "total_sales", "net_sales", "refund_amount",
    "refund_subtotal", "refund_shipping_fee", "refund_tax", "cancelled_amount",
    "average_order_value", "average_price", "original_unit_price", "sale_unit_price",
    "discount_amount", "tax_amount", "line_total_amount", "seller_discount_amount",
    "platform_discount_amount", "shipping_fee", "buyer_paid_amount",
}
DERIVED_FIELDS = {"average_order_value", "average_price", "refund_rate", "cancellation_rate"}


def _number(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _display(value):
    normalized = format(Decimal(value or 0).normalize(), "f")
    return "0" if normalized == "-0" else normalized


def _rate(currency, rates):
    code = str(currency or "").upper()
    info = rates.get(code)
    if not info or not info.get("rate"):
        raise ValidationError({"currency_basis": f"币种 {code or '未提供'} 尚无 CNY 参考汇率，请先刷新国家信息汇率。"})
    return Decimal(info["rate"]), info


def _convert(value, currency, rates):
    number = _number(value)
    if number is None:
        return value
    rate, _ = _rate(currency, rates)
    return _display(number / rate)


def _convert_currency_map(values, rates):
    total = Decimal("0")
    for currency, value in (values or {}).items():
        number = _number(value)
        if number is not None:
            total += Decimal(_convert(number, currency, rates))
    return {"CNY": _display(total)}


def _convert_record(record, rates, inherited_currency=""):
    output = {}
    source_amounts = {}
    source_currency = str(record.get("currency") or inherited_currency or "").upper()
    for key, value in record.items():
        if key in MONEY_FIELDS and isinstance(value, dict):
            output[key] = _convert_currency_map(value, rates)
        elif key == "money" and isinstance(value, dict):
            output[key] = _convert_currency_map(value, rates)
        elif key in MONEY_FIELDS and source_currency and value is not None:
            source_amounts[key] = value
            output[key] = _convert(value, source_currency, rates)
        elif isinstance(value, dict):
            output[key] = _convert_record(value, rates, source_currency)
        elif isinstance(value, list):
            output[key] = [
                _convert_record(item, rates, source_currency) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            output[key] = value
    if source_currency and "currency" in record:
        _, info = _rate(source_currency, rates)
        output["source_currency"] = source_currency
        output["currency"] = "CNY"
        output["cny_exchange_rate"] = _display(info["rate"])
        output["exchange_rate_date"] = info["date"].isoformat() if info.get("date") else None
    if source_amounts:
        output["source_amounts"] = source_amounts
    if source_currency and str(record.get("unit") or "").upper() == source_currency and "value" in record:
        output["value"] = _convert(record["value"], source_currency, rates)
        output["unit"] = "CNY"
    return output


def _merge_metric_groups(groups, rates):
    if not groups:
        return []
    totals, templates, order = {}, {}, []
    for group in groups:
        currency = group.get("currency")
        for metric in group.get("metrics") or []:
            code = metric.get("code")
            if not code:
                continue
            if code not in templates:
                templates[code] = deepcopy(metric)
                order.append(code)
            if code in DERIVED_FIELDS:
                continue
            value = _number(metric.get("value"))
            if value is None:
                continue
            if str(metric.get("unit") or "").upper() == str(currency or "").upper():
                value = Decimal(_convert(value, currency, rates))
                templates[code]["unit"] = "CNY"
            totals[code] = totals.get(code, Decimal("0")) + value
    if "average_order_value" in templates:
        base = totals.get("total_sales", totals.get("net_sales", totals.get("gross_sales", Decimal("0"))))
        totals["average_order_value"] = base / totals.get("order_count", Decimal("1")) if totals.get("order_count") else Decimal("0")
        templates["average_order_value"]["unit"] = "CNY"
    if "average_price" in templates:
        totals["average_price"] = totals.get("total_sales", Decimal("0")) / totals.get("total_units", Decimal("1")) if totals.get("total_units") else Decimal("0")
        templates["average_price"]["unit"] = "CNY"
    if "refund_rate" in templates:
        totals["refund_rate"] = totals.get("refund_amount", Decimal("0")) / totals.get("gross_sales", Decimal("1")) if totals.get("gross_sales") else Decimal("0")
    metrics = []
    for code in order:
        metric = templates[code]
        metric["value"] = _display(totals.get(code, Decimal("0")))
        metrics.append(metric)
    return [{"currency": "CNY", "metrics": metrics}]


def _merge_daily(rows, rates):
    merged = {}
    for raw in rows or []:
        row = _convert_record(raw, rates)
        key = row.get("date")
        target = merged.setdefault(key, {"date": key, "currency": "CNY"})
        for field, value in row.items():
            if field in {"date", "currency", "source_currency", "cny_exchange_rate", "exchange_rate_date"} or field in DERIVED_FIELDS:
                continue
            number = _number(value)
            if number is not None:
                target[field] = Decimal(str(target.get(field, 0))) + number
            elif field not in target:
                target[field] = value
    for row in merged.values():
        row["net_sales"] = Decimal(row.get("gross_sales", 0)) - Decimal(row.get("refund_amount", 0))
        row["average_order_value"] = Decimal(row.get("total_sales", 0)) / Decimal(row["order_count"]) if row.get("order_count") else None
        row["refund_rate"] = Decimal(row.get("refund_amount", 0)) / Decimal(row["gross_sales"]) if row.get("gross_sales") else None
        row["cancellation_rate"] = Decimal(row.get("cancelled_order_count", 0)) / Decimal(row["order_count"]) if row.get("order_count") else None
        for key, value in list(row.items()):
            if isinstance(value, Decimal):
                row[key] = _display(value)
    return [merged[key] for key in sorted(merged, reverse=True)]


def convert_sales_payload(request, payload):
    basis = str(request.query_params.get("currency_basis") or "").strip().upper()
    if not basis:
        return payload
    if basis != "CNY":
        raise ValidationError({"currency_basis": "目前仅支持自动换算为 CNY。"})
    rates = tenant_cny_rates(request.user.tenant)
    data = deepcopy(payload)
    if "results" in data:
        data["results"] = [_convert_record(row, rates) for row in data.get("results") or []]
    elif data.get("currency"):
        data = _convert_record(data, rates)
    for key in ("order_daily", "metric_daily"):
        if key in data:
            data[key] = _merge_daily(data[key], rates)
    for key in ("currency_groups", "order_currency_groups"):
        if key in data:
            data[key] = _merge_metric_groups(data[key], rates)
    if data.get("currency_groups"):
        data["currency"] = "CNY"
        data["metrics"] = data["currency_groups"][0]["metrics"]
        data["aggregation_status"] = "converted_cny"
    if "trend" in data:
        data["trend"] = [_convert_record(row, rates) for row in data.get("trend") or []]
    if "summary_metrics" in data:
        data["summary_metrics"] = [_convert_record(metric, rates) for metric in data["summary_metrics"]]
    dates = sorted({info["date"].isoformat() for code, info in rates.items() if code != "CNY" and info.get("date")})
    data.setdefault("definition", {})["currency_basis"] = "按每日参考汇率自动换算为 CNY，不改写原始金额"
    data["currency_conversion"] = {"target": "CNY", "rate_dates": dates, "formula": "原币金额 ÷（1 CNY 兑换的原币数量）"}
    return data
