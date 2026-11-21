"""SPU presentation aggregates computed from the complete authorized SKU set."""
from decimal import Decimal, InvalidOperation


def numeric(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = Decimal(str(value))
        return value if value.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def summarize_variants(rows, *, window_days=30, target_days=60):
    """Retain unknown coverage and distinguish a stockout from zero observation."""
    rows = list(rows)
    available, sold = [], []
    unknown_inventory = unknown_sales = stocked = sold_out = slow = over = 0
    ranked = []
    for row in rows:
        stock = numeric(row.get("available"))
        units = numeric(row.get("sales"))
        unknown_inventory += stock is None
        unknown_sales += units is None
        if stock is not None:
            available.append(stock)
            stocked += stock > 0
        if units is not None:
            sold.append(units)
            ranked.append((units, str(row.get("code", ""))))
        if stock is not None and units is not None:
            sold_out += stock <= 0 and units > 0
            slow += stock > 0 and units == 0
            over += stock > 0 and units > 0 and stock * window_days > units * target_days
    ranked.sort(key=lambda item: (-item[0], item[1]))
    leaders = {code for units, code in ranked[:3] if units > 0}
    lead_out = any(row.get("code", "") in leaders and numeric(row.get("available")) is not None
                   and numeric(row.get("available")) <= 0 for row in rows)
    if lead_out:
        status = "主销规格缺货"
    elif sold_out:
        status = "部分有销量规格缺货"
    elif unknown_inventory or unknown_sales:
        status = "部分规格数据待核对"
    elif slow and stocked:
        status = "部分规格有库存无销售"
    elif over:
        status = "部分规格库存偏多"
    else:
        status = "查看规格分布"
    return {
        "sku_count": len(rows),
        "stocked_sku_count": stocked,
        "sold_out_sku_count": sold_out,
        "stock_no_sales_sku_count": slow,
        "over_target_sku_count": over,
        "unknown_stock_sku_count": unknown_inventory,
        "unknown_sales_sku_count": unknown_sales,
        "available": sum(available) if available else None,
        "sales": sum(sold) if sold else None,
        "inventory_complete": not unknown_inventory,
        "sales_complete": not unknown_sales,
        "leading_skus": [code for units, code in ranked[:3] if units > 0],
        "variant_status": status,
    }

def group_product_rows(products, inventory, sales, *, window_days=30, target_days=60):
    """Group all scoped variants before applying SPU pagination."""
    from collections import defaultdict

    groups = defaultdict(list)
    for product in products:
        groups[product["spu_id"]].append({
            "id": product["id"], "code": product["sku_code"],
            "legacy": product.get("legacy_sku_code", ""),
            "name": product.get("product_name", ""),
            "specification": product.get("specification", ""),
            "available": inventory.get(product["id"]),
            "sales": sales.get(product["id"]),
        })
    headers = {row["spu_id"]: row for row in products}
    result = []
    for spu_id, variants in groups.items():
        header = headers[spu_id]
        result.append({
            "id": spu_id, "name": header.get("spu__product_name", ""),
            "code": header.get("spu__spu_code", ""),
            "variants": variants,
            **summarize_variants(variants, window_days=window_days, target_days=target_days),
        })
    return sorted(result, key=lambda row: (row["code"], row["id"]))
