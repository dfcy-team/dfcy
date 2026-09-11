"""Read-only report projections over already permission-scoped commerce facts."""
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Count, Q, Sum
from rest_framework.exceptions import ValidationError

from apps.commerce.models import SalesOrderItem, RefundReturnItem


def _local_date(timestamp, timezone):
    try:
        return timestamp.astimezone(ZoneInfo(timezone)).date().isoformat()
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError({"timezone": "Invalid store timezone."})


def order_daily_rows(orders, refunds):
    rows = {}
    for row in orders.values("created_at_utc", "store__timezone", "currency").annotate(
        order_count=Count("id"),
        valid_order_count=Count("id", filter=~Q(normalized_status="cancelled")),
        cancelled_order_count=Count("id", filter=Q(normalized_status="cancelled")),
        gross_sales=Sum("order_total_amount", filter=~Q(normalized_status="cancelled")),
        total_sales=Sum("order_total_amount"),
        cancelled_amount=Sum("order_total_amount", filter=Q(normalized_status="cancelled")),
    ).iterator(chunk_size=2000):
        key = (_local_date(row.pop("created_at_utc"), row.pop("store__timezone")), row["currency"])
        target = rows.setdefault(key, {"date": key[0], "currency": key[1], "refund_amount": Decimal(0), "refund_case_count": 0})
        for field in ("order_count", "valid_order_count", "cancelled_order_count", "gross_sales", "total_sales", "cancelled_amount"):
            target[field] = target.get(field, 0) + (row[field] or 0)
    for row in refunds.values("requested_at_utc", "store__timezone", "currency").annotate(refund_amount=Sum("refund_amount"), refund_case_count=Count("id")).iterator(chunk_size=2000):
        key = (_local_date(row["requested_at_utc"], row["store__timezone"]), row["currency"])
        target = rows.setdefault(key, {"date": key[0], "currency": key[1], "order_count": 0, "valid_order_count": 0, "cancelled_order_count": 0, "gross_sales": 0, "total_sales": 0, "cancelled_amount": 0})
        target["refund_amount"] = target.get("refund_amount", 0) + (row["refund_amount"] or 0)
        target["refund_case_count"] = target.get("refund_case_count", 0) + row["refund_case_count"]
    for row in rows.values():
        for field in ("gross_sales", "total_sales", "cancelled_amount", "refund_amount"):
            row[field] = row.get(field) or Decimal(0)
        row["average_order_value"] = row["total_sales"] / row["order_count"] if row["order_count"] else None
        row["net_sales"] = row["gross_sales"] - row["refund_amount"]
    return [row for _, row in sorted(rows.items(), reverse=True)]


def business_daily_rows(orders, refunds):
    rows = order_daily_rows(orders, refunds)
    quantities = {}
    for row in SalesOrderItem.objects.filter(sales_order__in=orders).values(
        'sales_order__created_at_utc', 'sales_order__store__timezone', 'currency'
    ).annotate(quantity=Sum('quantity')).iterator(chunk_size=2000):
        key = (_local_date(row['sales_order__created_at_utc'], row['sales_order__store__timezone']), row['currency'])
        quantities[key] = quantities.get(key, 0) + row['quantity']
    for row in rows:
        row['units_sold'] = quantities.get((row['date'], row['currency']), 0)
        row['cancellation_rate'] = Decimal(row['cancelled_order_count']) / row['order_count'] if row['order_count'] else None
        row['refund_rate'] = row['refund_amount'] / row['gross_sales'] if row['gross_sales'] else None
    return rows


def sku_report(orders, refunds, grouping="store", term=""):
    if grouping not in {"store", "product"}:
        raise ValidationError({"grouping": "Expected store or product."})
    rows, days, summaries = {}, {}, {}
    def bucket():
        return dict(gross_sales=Decimal(0), total_sales=Decimal(0), units_sold=0, total_units=0,
                    refund_amount=Decimal(0), refund_units=0, cancelled_amount=Decimal(0), cancelled_units=0,
                    _orders=set(), _valid_orders=set(), _cancelled_orders=set())

    def identity(item, parent):
        # Unmapped products remain isolated by store and provider identity.
        local = item.internal_sku_id
        source = (parent.store_id, item.seller_sku or (item.platform_product_id, item.platform_variant_id))
        return (local if grouping == "product" and local else source, item.currency)

    def matches(item):
        return not term or term.casefold() in item.seller_sku.casefold() or (item.internal_sku_id and term.casefold() in item.internal_sku.sku_code.casefold())

    for model, queryset, parent_field in ((SalesOrderItem, orders, "sales_order"), (RefundReturnItem, refunds, "refund_return")):
        items = model.objects.filter(**{f"{parent_field}__in": queryset}).select_related(parent_field, f"{parent_field}__store", f"{parent_field}__platform", "internal_sku")
        for item in items.iterator(chunk_size=2000):
            if not matches(item):
                continue
            parent = getattr(item, parent_field)
            key = identity(item, parent)
            entry = rows.setdefault(key, {**bucket(), "sku": item.internal_sku.sku_code if item.internal_sku_id else item.seller_sku,
                "internal_sku": item.internal_sku.sku_code if item.internal_sku_id else None,
                "currency": item.currency, "mapping_status": "mapped" if item.internal_sku_id else "unmapped",
                "_stores": set(), "_platforms": set(), "_seller_skus": set(), "_names": set(), "_products": set(), "_variants": set(), "_variations": set()})
            entry["_stores"].add(parent.store.name)
            entry["_platforms"].add(parent.platform.platform_type)
            for field, value in (("_seller_skus", item.seller_sku), ("_names", item.item_name_snapshot), ("_products", item.platform_product_id), ("_variants", item.platform_variant_id), ("_variations", getattr(item, "variation_snapshot", ""))):
                if value:
                    entry[field].add(value)
            timestamp = parent.created_at_utc if model == SalesOrderItem else parent.requested_at_utc
            date = _local_date(timestamp, parent.store.timezone)
            day = days.setdefault((date, item.currency), {**bucket(), "date": date, "currency": item.currency})
            summary = summaries.setdefault(item.currency, bucket())
            for target in (entry, day, summary):
                if model == RefundReturnItem:
                    target["refund_amount"] += item.refund_amount
                    target["refund_units"] += item.quantity
                else:
                    target["_orders"].add(parent.pk)
                    target["total_sales"] += item.line_total_amount
                    target["total_units"] += item.quantity
                    if parent.normalized_status == "cancelled":
                        target["_cancelled_orders"].add(parent.pk)
                        target["cancelled_amount"] += item.line_total_amount
                        target["cancelled_units"] += item.quantity
                    else:
                        target["_valid_orders"].add(parent.pk)
                        target["gross_sales"] += item.line_total_amount
                        target["units_sold"] += item.quantity

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
              ("average_order_value", "平均订单金额", "money"), ("refund_amount", "退款申请金额", "money"),
              ("refund_case_count", "退款售后单数", "单"), ("cancelled_order_count", "取消订单数", "单"),
              ("cancelled_amount", "取消订单金额", "money")]
    groups = []
    for currency in sorted({row["currency"] for row in rows}):
        totals = {field: sum((row.get(field) or 0) for row in rows if row["currency"] == currency) for field, _, _ in labels if field != "average_order_value"}
        totals["average_order_value"] = totals["total_sales"] / totals["order_count"] if totals["order_count"] else None
        groups.append({"currency": currency, "metrics": [{"code": field, "label": label, "unit": currency if unit == "money" else unit,
            "value": str(totals[field]) if totals[field] is not None else None,
            "definition": "全部订单金额 ÷ 订单总量，包含取消订单" if field == "average_order_value" else "当前筛选范围；退款使用申请日期，售后单数不等于去重订单数"} for field, label, unit in labels]})
    return groups
