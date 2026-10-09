"""Read-only report projections over already permission-scoped commerce facts."""
from decimal import Decimal
from datetime import UTC, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Case, Count, DateTimeField, ExpressionWrapper, F, Max, Min, Q, Sum, Value, When
from django.db.models.functions import TruncDate
from rest_framework.exceptions import ValidationError

from apps.commerce.models import SalesOrderItem, RefundReturnItem


def _local_date(timestamp, timezone):
    try:
        return timestamp.astimezone(ZoneInfo(timezone)).date().isoformat()
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError({"timezone": "Invalid store timezone."})


def _local_day_expression(queryset, timestamp_field, timezone_field):
    """SQL date expression including DST without depending on MySQL timezone tables."""
    zones = queryset.order_by().values(timezone_field).annotate(start=Min(timestamp_field), end=Max(timestamp_field))
    cases = []
    for span in zones:
        try:
            zone = ZoneInfo(span[timezone_field])
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValidationError({"timezone": "Invalid store timezone."}) from exc
        start, end = span["start"], span["end"] + timedelta(microseconds=1)
        cursor, branch_start = start, start
        offset = start.astimezone(zone).utcoffset()
        branches = []
        while cursor < end:
            probe = min(cursor + timedelta(days=1), end)
            next_offset = probe.astimezone(zone).utcoffset()
            if next_offset != offset:
                left, right = cursor, probe
                while right - left > timedelta(seconds=1):
                    midpoint = left + (right - left) / 2
                    if midpoint.astimezone(zone).utcoffset() == offset:
                        left = midpoint
                    else:
                        right = midpoint
                transition = right.replace(microsecond=0)
                if transition.astimezone(zone).utcoffset() == offset:
                    transition += timedelta(seconds=1)
                branches.append((branch_start, transition, offset))
                branch_start, offset = transition, next_offset
            cursor = probe
        branches.append((branch_start, end, offset))
        for begin, finish, utc_offset in branches:
            shifted = ExpressionWrapper(F(timestamp_field) + Value(utc_offset), output_field=DateTimeField())
            condition = Q(**{timezone_field: span[timezone_field], timestamp_field + "__gte": begin, timestamp_field + "__lt": finish})
            cases.append(When(condition, then=shifted))
    return TruncDate(Case(*cases, default=F(timestamp_field), output_field=DateTimeField()), tzinfo=UTC)


def _local_daily_groups(queryset, timestamp_field, timezone_field, dimensions, measures):
    expression = _local_day_expression(queryset, timestamp_field, timezone_field)
    yield from queryset.order_by().annotate(local_day=expression).values("local_day", *dimensions).annotate(**measures)


def order_daily_rows(orders, refunds):
    rows = {}
    for row in _local_daily_groups(orders, "created_at_utc", "store__timezone", ["currency"], {
        "order_count": Count("id"), "valid_order_count": Count("id", filter=~Q(normalized_status="cancelled")),
        "cancelled_order_count": Count("id", filter=Q(normalized_status="cancelled")),
        "gross_sales": Sum("order_total_amount", filter=~Q(normalized_status="cancelled")),
        "total_sales": Sum("order_total_amount"), "cancelled_amount": Sum("order_total_amount", filter=Q(normalized_status="cancelled")),
    }):
        key = (row["local_day"].isoformat(), row["currency"])
        target = rows.setdefault(key, {"date": key[0], "currency": key[1], "refund_amount": Decimal(0), "refund_case_count": 0})
        for field in ("order_count", "valid_order_count", "cancelled_order_count", "gross_sales", "total_sales", "cancelled_amount"):
            target[field] = target.get(field, 0) + (row[field] or 0)
    for row in _local_daily_groups(refunds, "requested_at_utc", "store__timezone", ["currency"], {"refund_amount": Sum("refund_amount", filter=Q(normalized_status="completed")), "refund_case_count": Count("id")}):
        key = (row["local_day"].isoformat(), row["currency"])
        target = rows.setdefault(key, {"date": key[0], "currency": key[1], "order_count": 0, "valid_order_count": 0, "cancelled_order_count": 0, "gross_sales": 0, "total_sales": 0, "cancelled_amount": 0})
        target["refund_amount"] = target.get("refund_amount", 0) + (row["refund_amount"] or 0)
        target["refund_case_count"] = target.get("refund_case_count", 0) + row["refund_case_count"]
    for row in rows.values():
        for field in ("gross_sales", "total_sales", "cancelled_amount", "refund_amount"):
            row[field] = row.get(field) or Decimal(0)
        row["average_order_value"] = row["gross_sales"] / row["valid_order_count"] if row["valid_order_count"] else None
        row["net_sales"] = row["gross_sales"] - row["refund_amount"]
    return [row for _, row in sorted(rows.items(), reverse=True)]


def business_daily_rows(orders, refunds):
    rows = order_daily_rows(orders, refunds)
    quantities = {}
    for row in _local_daily_groups(SalesOrderItem.objects.filter(sales_order__in=orders.exclude(normalized_status="cancelled")), "sales_order__created_at_utc", "sales_order__store__timezone", ["currency"], {"quantity": Sum("quantity")}):
        key = (row['local_day'].isoformat(), row['currency'])
        quantities[key] = quantities.get(key, 0) + row['quantity']
    for row in rows:
        row['units_sold'] = quantities.get((row['date'], row['currency']), 0)
        row['cancellation_rate'] = Decimal(row['cancelled_order_count']) / row['order_count'] if row['order_count'] else None
        row['refund_rate'] = row['refund_amount'] / row['gross_sales'] if row['gross_sales'] else None
    return rows


def sku_report(orders, refunds, grouping="store", term="", sku_mode="", mapping_as_of=""):
    if grouping not in {"store", "product"}:
        raise ValidationError({"grouping": "Expected store or product."})
    from apps.products.sku_aliases import filter_sku_codes, validate_sku_mode
    validate_sku_mode(sku_mode, mapping_as_of)
    rows, days, summaries = {}, {}, {}
    def bucket():
        return dict(gross_sales=Decimal(0), total_sales=Decimal(0), units_sold=0, total_units=0,
                    refund_amount=Decimal(0), refund_units=0, cancelled_amount=Decimal(0), cancelled_units=0,
                    _orders=set(), _valid_orders=set(), _cancelled_orders=set())

    def identity(item, parent_field):
        # Unmapped products remain isolated by store and provider identity.
        local = item["internal_sku_id"]
        source = (item[f"{parent_field}__store_id"], item["seller_sku"] or (item["platform_product_id"], item["platform_variant_id"]))
        return (local if grouping == "product" and local else source, item["currency"])

    def matches(item):
        return not term or term.casefold() in item["seller_sku"].casefold() or (item["internal_sku_id"] and term.casefold() in item["internal_sku__sku_code"].casefold())

    sources, target_ids = [], set()
    for model, queryset, parent_field in ((SalesOrderItem, orders, "sales_order"), (RefundReturnItem, refunds, "refund_return")):
        items = model.objects.filter(**{f"{parent_field}__in": queryset})
        if sku_mode:
            tenant_id = queryset.values_list("tenant_id", flat=True).first()
            items = filter_sku_codes(items, tenant_id=tenant_id, code=term, mode=sku_mode, store_field=f"{parent_field}__store_id", mapping_as_of=mapping_as_of)
            if term and sku_mode == "related":
                target_ids.update(items.exclude(internal_sku=None).values_list("internal_sku_id", flat=True).distinct().order_by()[:2])
        if model == SalesOrderItem:
            projection = ["sales_order_id", "sales_order__store_id", "sales_order__store__name", "sales_order__store__timezone",
                          "sales_order__platform__platform_type", "sales_order__created_at_utc", "sales_order__normalized_status",
                          "internal_sku_id", "internal_sku__sku_code", "seller_sku", "platform_product_id", "platform_variant_id",
                          "item_name_snapshot", "variation_snapshot", "currency", "quantity", "line_total_amount"]
        else:
            projection = ["refund_return_id", "refund_return__store_id", "refund_return__store__name", "refund_return__store__timezone",
                          "refund_return__platform__platform_type", "refund_return__requested_at_utc", "refund_return__normalized_status",
                          "internal_sku_id", "internal_sku__sku_code", "seller_sku", "platform_product_id", "platform_variant_id",
                          "item_name_snapshot", "currency", "quantity", "refund_amount"]
        items = items.values(*projection)
        sources.append((model, parent_field, items))
    if len(target_ids) > 1:
        raise ValidationError({"sku": "销售与退款中的该编码对应多个商品，请限定店铺或映射日期后核对。"})
    for model, parent_field, items in sources:
        for item in items.iterator(chunk_size=2000):
            if not sku_mode and not matches(item):
                continue
            parent_id = item[f"{parent_field}_id"]
            key = identity(item, parent_field)
            entry = rows.setdefault(key, {**bucket(), "sku": item["internal_sku__sku_code"] if item["internal_sku_id"] else item["seller_sku"],
                "internal_sku": item["internal_sku__sku_code"] if item["internal_sku_id"] else None,
                "currency": item["currency"], "mapping_status": "mapped" if item["internal_sku_id"] else "unmapped",
                "_stores": set(), "_platforms": set(), "_seller_skus": set(), "_names": set(), "_products": set(), "_variants": set(), "_variations": set()})
            entry["_stores"].add(item[f"{parent_field}__store__name"])
            entry["_platforms"].add(item[f"{parent_field}__platform__platform_type"])
            for field, value in (("_seller_skus", item["seller_sku"]), ("_names", item["item_name_snapshot"]), ("_products", item["platform_product_id"]), ("_variants", item["platform_variant_id"]), ("_variations", item.get("variation_snapshot", ""))):
                if value:
                    entry[field].add(value)
            timestamp = item["sales_order__created_at_utc"] if model == SalesOrderItem else item["refund_return__requested_at_utc"]
            date = _local_date(timestamp, item[f"{parent_field}__store__timezone"])
            day = days.setdefault((date, item["currency"]), {**bucket(), "date": date, "currency": item["currency"]})
            summary = summaries.setdefault(item["currency"], bucket())
            for target in (entry, day, summary):
                if model == RefundReturnItem:
                    if item["refund_return__normalized_status"] == "completed":
                        target["refund_amount"] += item["refund_amount"]
                        target["refund_units"] += item["quantity"]
                else:
                    target["_orders"].add(parent_id)
                    target["total_sales"] += item["line_total_amount"]
                    target["total_units"] += item["quantity"]
                    if item["sales_order__normalized_status"] == "cancelled":
                        target["_cancelled_orders"].add(parent_id)
                        target["cancelled_amount"] += item["line_total_amount"]
                        target["cancelled_units"] += item["quantity"]
                    else:
                        target["_valid_orders"].add(parent_id)
                        target["gross_sales"] += item["line_total_amount"]
                        target["units_sold"] += item["quantity"]

    def finish(row):
        for field, source in (("order_count", "_orders"), ("valid_order_count", "_valid_orders"), ("cancelled_order_count", "_cancelled_orders")):
            row[field] = len(row.pop(source))
        row["net_sales"] = row["gross_sales"] - row["refund_amount"]
        row["average_price"] = row["total_sales"] / row["total_units"] if row["total_units"] else None
        return row

    for row in rows.values():
        finish(row)
        for field, source in (("store_name", "_stores"), ("platform", "_platforms"), ("seller_sku", "_seller_skus"), ("product_name", "_names"), ("platform_product_id", "_products"), ("platform_variant_id", "_variants"), ("variation", "_variations")):
            row[field] = " / ".join(sorted(row.pop(source)))
    labels = [("gross_sales", "非取消商品销售额", "money"), ("units_sold", "非取消商品销量", "件"), ("valid_order_count", "非取消订单数", "单"), ("refund_amount", "退款产品金额", "money"), ("refund_units", "退款产品数", "件"), ("total_sales", "全部商品销售额", "money"), ("total_units", "全部商品销量", "件"), ("order_count", "订单总量", "单"), ("cancelled_amount", "取消商品金额", "money")]
    groups = []
    for currency, row in sorted(summaries.items()):
        finish(row)
        groups.append({"currency": currency, "metrics": [{"code": field, "label": label, "value": str(row[field]), "unit": currency if unit == "money" else unit, "definition": "按商品行统计；订单数按订单去重，退款按申请日期统计。"} for field, label, unit in labels]})
    trend_fields = [field for field, _, _ in labels] + ["net_sales"]
    trend = [{"date": date, **{field: {currency: str(row[field])} for field in trend_fields}} for (date, currency), raw in sorted(days.items()) for row in [finish(raw)]]
    return list(rows.values()), groups, trend


def order_report_groups(rows):
    labels = [("order_count", "订单总量", "单"), ("valid_order_count", "非取消订单数", "单"),
              ("gross_sales", "非取消订单销售额", "money"), ("total_sales", "全部订单金额", "money"),
              ("average_order_value", "非取消订单均额", "money"), ("refund_amount", "已完成退款金额", "money"),
              ("refund_case_count", "退款售后单数", "单"), ("cancelled_order_count", "取消订单数", "单"),
              ("cancelled_amount", "取消订单金额", "money")]
    groups = []
    for currency in sorted({row["currency"] for row in rows}):
        totals = {field: sum((row.get(field) or 0) for row in rows if row["currency"] == currency) for field, _, _ in labels if field != "average_order_value"}
        totals["average_order_value"] = totals["gross_sales"] / totals["valid_order_count"] if totals["valid_order_count"] else None
        groups.append({"currency": currency, "metrics": [{"code": field, "label": label, "unit": currency if unit == "money" else unit,
            "value": str(totals[field]) if totals[field] is not None else None,
            "definition": "非取消订单销售额 ÷ 非取消订单量" if field == "average_order_value" else "当前筛选范围；只扣减 completed 退款，售后申请量独立统计"} for field, label, unit in labels]})
    return groups
