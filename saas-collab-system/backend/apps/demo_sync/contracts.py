RESOURCES = {
    "platforms": "平台", "country_sites": "国家站点", "stores": "店铺",
    "warehouses": "仓库", "product_categories": "商品分类", "products": "商品",
    "product_details": "SKU", "sales_orders": "订单", "sales_order_items": "订单明细",
    "inventory_snapshots": "库存快照",
}
MAX_WINDOW_DAYS = 31


def enabled():
    from django.conf import settings
    return bool(getattr(settings, "DEMO_DATA_SYNC_ENABLED", False))
