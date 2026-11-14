"""Only confirmed warehouse shipments may supply cost quantities."""
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from django.utils.dateparse import parse_datetime


def shipped_items(lookup, zone):
    if not lookup or lookup.status != 'matched' or not lookup.warehouse_id:
        return [], ['缺少当前唯一匹配的仓库出库依据']
    packages = lookup.snapshot.get('packages') or []
    result, reasons, seen = [], [], {}
    for package in packages:
        key = package.get('warehouse_order_no')
        if not key:
            reasons.append('缺仓库出库单号')
            continue
        if key in seen:
            if seen[key] != package:
                return [], ['同一仓库出库单存在冲突明细']
            continue
        seen[key] = package
        best = package.get('provider') == 'best_ecapi'
        if str(package.get('status')) == ('CANCELED' if best else '9'):
            continue
        try:
            shipped = parse_datetime(str(package.get('shipped_at_utc') or ''))
            if not shipped or shipped.tzinfo is None or str(package.get('status')) != ('DELIVERED' if best else '7'):
                raise ValueError()
            day = shipped.astimezone(ZoneInfo(zone)).date().isoformat()
        except (TypeError, ValueError):
            reasons.append('缺少已发货状态或实际出库日期')
            continue
        if not package.get('items'):
            reasons.append('缺实际出库商品明细')
        for item in package.get('items') or []:
            try:
                quantity = Decimal(str(item.get('quantity')))
                if not quantity.is_finite() or quantity <= 0 or quantity != quantity.to_integral_value():
                    raise ValueError()
            except (InvalidOperation, TypeError, ValueError):
                reasons.append('实际出库数量无效')
                continue
            result.append({'source_sku': str(item.get('sku') or '').strip(),
                           'quantity': int(quantity), 'shipped_date': day,
                           'warehouse_order_no': str(key)})
    if not result:
        reasons.append('缺少可核算的实际出库商品')
    return result, sorted(set(reasons))
