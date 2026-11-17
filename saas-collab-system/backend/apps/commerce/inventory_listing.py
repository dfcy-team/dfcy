from decimal import Decimal, InvalidOperation

from apps.integrations.models import MarketplaceProductMapping
from apps.listings.models import PlatformProductDetail


def linked_sku_ids(tenant_id, country_code, sku_ids):
    """Resolve both supported platform associations in one batch per country."""
    ids = set(sku_ids)
    if not ids:
        return set()
    linked = set(MarketplaceProductMapping.objects.filter(
        tenant_id=tenant_id, sku_id__in=ids, status='mapped',
        store_mapping__store__country_code__iexact=country_code,
    ).values_list('sku_id', flat=True))
    linked.update(PlatformProductDetail.objects.filter(
        tenant_id=tenant_id, internal_sku_id__in=ids,
        store__country_code__iexact=country_code,
    ).values_list('internal_sku_id', flat=True))
    return linked


def apply_listing_observation(row, linked, *, window_days=30, target_days=60):
    """Decorate facts without creating purchase demand or changing alert rules."""
    if row.pop('stock_sales_reason', None) and row.get('operations') is not None:
        from .inventory_operations import operating_assessment
        row['operations'] = operating_assessment(row, window_days=window_days, target_days=target_days)
    row.pop('stock_sales_status', None)
    row['platform_mapping_status'] = 'linked' if linked else 'unlinked'
    if linked:
        row['platform_mapping_label'] = '已关联平台商品'
        return row
    row['platform_mapping_label'] = '未关联平台商品'
    # The existence of known sales takes precedence over absent current mapping.
    units = row.get('mapped_sales_units')
    if units is None:
        units = row.get('total_demand_quantity')
    if units is None:
        window = next((item for item in row.get('sales_windows', []) if item.get('days') == window_days), {})
        units = window.get('units')
    try:
        if units is not None and Decimal(str(units)) > 0:
            return row
        warehouses = row.get('warehouses') or []
        quantities = [w.get('available_qty') if w.get('available_qty') is not None
                      else w.get('last_synced_qty') for w in warehouses]
        stock = row.get('on_hand_stock')
        if stock is None:
            stock = row.get('available_stock')
        if stock is None and quantities and all(v is not None for v in quantities):
            stock = sum(Decimal(str(v)) for v in quantities)
        if stock is None or Decimal(str(stock)) <= 0:
            return row
    except (InvalidOperation, ValueError, TypeError):
        return row
    row['stock_sales_status'] = 'stock_no_sales'
    row['stock_sales_reason'] = '有库存，未关联本国家平台商品'
    operations = row.get('operations')
    if operations is not None:
        row['operations'] = {**operations, 'sales_status': 'no_sales',
                             'sales_label': '有库存无销售 · 未关联平台商品',
                             'action': '安排上架或关联平台商品'}
    return row
