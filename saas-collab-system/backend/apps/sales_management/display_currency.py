"""Convert monetary observations without changing source-currency identity."""
from decimal import Decimal, InvalidOperation

from copy import deepcopy

from apps.masterdata.exchange_rates import tenant_cny_rates


MONEY_FIELDS = frozenset({
    "sales_amount", "ad_spend", "ad_sales_amount", "ad_rate_sales_amount",
    "tiktok_ad_spend", "observed_expense", "expense", "average_price",
    "order_total_amount", "line_total_amount", "sale_unit_price",
})


def convert_currency_group(group, source_currency, target_currency, rates):
    source = rates.get(source_currency) or {}
    target = rates.get(target_currency) or {}
    try:
        source_rate = Decimal(str(source.get("rate")))
        target_rate = Decimal(str(target.get("rate")))
        factor = target_rate / source_rate if source_rate > 0 and target_rate > 0 else None
    except (InvalidOperation, TypeError, ZeroDivisionError):
        factor = None

    def convert(value):
        if isinstance(value, list):
            return [convert(row) for row in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key in MONEY_FIELDS and item is not None and not isinstance(item, (dict, list)):
                try:
                    number = Decimal(str(item))
                    result[key] = format(number * factor, "f") if factor is not None and number.is_finite() else None
                except (InvalidOperation, TypeError):
                    result[key] = None
            else:
                result[key] = convert(item)
        return result

    result = convert(group)
    result["source_currency"] = source_currency
    result["display_currency"] = target_currency
    result["exchange_rate_missing"] = factor is None
    return result


COUNT_FIELDS = frozenset({"order_count", "valid_order_count", "units_sold", "ad_clicks", "clicks", "observed_clicks", "observed_store_count", "observed_store_hour_count"})


def _merge_rows(collections, identity, sort_field=None, limit=None):
    combined = {}
    for rows in collections:
        for row in rows:
            key = identity(row)
            if key not in combined:
                combined[key] = deepcopy(row)
                continue
            target = combined[key]
            for field in MONEY_FIELDS | COUNT_FIELDS:
                if field not in row:
                    continue
                left, right = target.get(field), row.get(field)
                if field in MONEY_FIELDS:
                    target[field] = None if left is None or right is None else format(Decimal(str(left)) + Decimal(str(right)), "f")
                else:
                    target[field] = None if left is None or right is None else int(left) + int(right)
            # Inventory is a shared observation, carried separately by country.
            if target.get("inventory_site") != row.get("inventory_site"):
                target["inventory_site"] = None
            target["inventory_countries"] = sorted(set(target.get("inventory_countries", [])) | set(row.get("inventory_countries", [])))
    result = list(combined.values())
    if sort_field:
        result.sort(key=lambda row: (row.get(sort_field) is None, -Decimal(str(row.get(sort_field) or 0)), str(identity(row))))
    return result[:limit] if limit else result


def aggregate_display_group(groups, target_currency, rates):
    converted = [convert_currency_group(group, group["currency"], target_currency, rates) for group in groups]
    if not converted:
        return None
    result = deepcopy(converted[0])
    result["currency"] = target_currency
    result["source_currencies"] = [group["currency"] for group in groups]
    result["missing_rate_currencies"] = [row["source_currency"] for row in converted if row["exchange_rate_missing"]]
    for field in MONEY_FIELDS | COUNT_FIELDS:
        values = [row.get(field) for row in converted if field in row]
        if values:
            total = sum((Decimal(str(value)) for value in values if value is not None), Decimal(0))
            result[field] = None if any(value is None for value in values) else format(total, "f") if field in MONEY_FIELDS else int(total)
    for field in ("trend", "recent_trend", "previous_hourly_trend"):
        result[field] = sorted(_merge_rows([group.get(field, []) for group in converted], lambda row: row["date"]), key=lambda row: row["date"])
    result["store_rankings"] = {
        metric: _merge_rows([group.get("store_ranking", []) for group in converted], lambda row: row["store_id"], metric)
        for metric in ("sales_amount", "order_count", "units_sold")
    }
    result["store_ranking"] = result["store_rankings"]["sales_amount"]
    result["product_rankings"] = {}
    dimensions = {dimension for group in converted for dimension in group.get("product_rankings", {})}
    for dimension in dimensions:
        result["product_rankings"][dimension] = {
            metric: _merge_rows([group.get("product_rankings", {}).get(dimension, {}).get(metric, []) for group in converted], lambda row: row["key"], metric, 10)
            for metric in ("sales_amount", "units_sold")
        }
    numerator, expense = result.get("ad_rate_sales_amount"), result.get("ad_spend")
    result["store_roi"] = format(Decimal(numerator) / Decimal(expense), "f") if numerator is not None and expense is not None and Decimal(expense) > 0 else None
    result["ad_rate"] = format(Decimal(expense) / Decimal(numerator) * 100, "f") if numerator is not None and expense is not None and Decimal(numerator) > 0 else None
    result["advertising_platforms"] = _merge_rows([group.get("advertising_platforms", []) for group in converted], lambda row: row["platform"])
    for row in result["advertising_platforms"]:
        amount = row.get("ad_spend")
        row["store_roi"] = format(Decimal(row["sales_amount"]) / Decimal(amount), "f") if amount is not None and Decimal(amount) > 0 and row.get("sales_amount") is not None else None
    for field in ("ad_store_ids", "tiktok_ad_store_ids", "ad_platforms"):
        result[field] = sorted({value for group in converted for value in group.get(field, [])})
    for row in result["advertising_platforms"]:
        matching = [item for group in converted for item in group.get("advertising_platforms", []) if item["platform"] == row["platform"]]
        row["store_ids"] = sorted({sid for item in matching for sid in item.get("store_ids", [])})
        row["partial"] = any(item.get("partial") for item in matching)
    hourly = [group["hourly_advertising"] for group in converted if group.get("hourly_advertising")]
    if hourly:
        observation = deepcopy(hourly[0])
        observation["hours"] = sorted(_merge_rows([row.get("hours", []) for row in hourly], lambda row: row["hour"]), key=lambda row: row["hour"])
        for field in ("observed_expense", "observed_clicks", "observed_store_count", "observed_store_hour_count"):
            values = [row.get(field) for row in hourly]
            available = [Decimal(str(value)) for value in values if value is not None]
            observation[field] = format(sum(available), "f") if field == "observed_expense" and available else int(sum(available)) if available else None
        observation["timezones"] = sorted({zone for row in hourly for zone in row.get("timezones", [])})
        result["hourly_advertising"] = observation
    result["ad_clicks_partial"] = any(group.get("ad_clicks_partial") for group in converted)
    result["ad_status"] = "estimated" if any(group.get("ad_status") in {"estimated", "provisional", "partial"} for group in converted) else result.get("ad_status")
    return result
