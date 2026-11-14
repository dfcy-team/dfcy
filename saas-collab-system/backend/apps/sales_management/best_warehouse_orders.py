"""Bounded BEST delivery-list lookup; only an exact extCode identifies a platform order."""
from datetime import timedelta, timezone as dt_timezone

from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.integrations.best_business import count, packages, request_payload, rows, text
from apps.integrations.models import WarehouseAuthorization
from apps.integrations.warehouse_api_service import execute_operation
from apps.permissions.ui_p6_scopes import integration_values_allowed


def fetch_packages(actor, authorization, order, is_current):
    from .warehouse_orders import require_access
    start = order.created_at_utc.replace(microsecond=0) - timedelta(days=1)
    finish = timezone.now().replace(microsecond=0)
    if start > finish:
        raise ValidationError('订单创建时间晚于当前时间。')
    result, matched = [], set()
    calls = 0

    def call(name, **fields):
        nonlocal authorization, calls
        if not is_current() or calls >= 100:
            raise ValidationError('百世查询已过期或超过单订单查询预算，未保存不完整结果。')
        actor.refresh_from_db()
        require_access(actor, order)
        authorization = WarehouseAuthorization.objects.select_related('warehouse', 'integration_config').get(pk=authorization.pk)
        if authorization.warehouse.country_code.upper() != order.store.country_code.upper():
            raise ValidationError('百世仓库国家与订单不一致。')
        if not integration_values_allowed(actor, 'integrations.warehouse.view', platform=authorization.provider,
                environment=authorization.integration_config.environment, regions=[authorization.external_warehouse_region],
                config_id=authorization.integration_config_id, warehouse_id=authorization.warehouse_id):
            raise PermissionDenied('百世仓库不在查看范围内。')
        calls += 1
        value = execute_operation(actor=actor, authorization=authorization, name=name,
                                  payload=request_payload(authorization, **fields)).get('data')
        if not isinstance(value, dict):
            raise ValidationError('百世响应缺少业务对象。')
        return value

    while start <= finish:
        end = min(start + timedelta(days=30), finish)
        for order_type in ('NORMAL', 'WDO'):
            seen, total, pages = set(), None, None
            for page in range(1, 101):
                data = call('WMS_SO_LIST_QUERY', orderType=order_type, currentPage=page,
                    deliveryTimeFrom=start.astimezone(dt_timezone.utc).isoformat(),
                    deliveryTimeTo=end.astimezone(dt_timezone.utc).isoformat())
                current, size, last = (count(data.get(key)) for key in ('currentPage', 'totalCount', 'totalPage'))
                if current != page or (total is not None and (total, pages) != (size, last)):
                    raise ValidationError('百世分页计数变化或当前页不一致。')
                total, pages = size, last
                records = rows(data.get('orders'), 'order')
                for item in records:
                    number = text(item.get('salesOrderNo'))
                    if number in seen or item.get('orderType') != order_type:
                        raise ValidationError('百世分页重复或订单类型不一致。')
                    seen.add(number)
                    if item.get('extCode') != order.external_order_id:
                        continue
                    if number in matched:
                        raise ValidationError('百世跨时间窗口返回重复出库单。')
                    parsed = packages(item, authorization)
                    if any(not package['items'] for package in parsed):
                        # Some official list responses omit package products. Query ERP number
                        # from this identity-checked list, never assume it equals platform ID.
                        detail = call('WMS_SO_STATUS_QUERY', orderCode=item['orderCode']).get('salesOrder')
                        if not isinstance(detail, dict) or detail.get('orderCode') != item['orderCode'] or detail.get('orderStatus') != item['status']:
                            raise ValidationError('百世出库详情归属或状态变化，请重试。')
                        products = rows(detail.get('products'), 'product')
                        items = [{'sku': text(p.get('skuCode')),
                                  'quantity': count(p.get('normalQuantity')) + count(p.get('defectiveQuantity'))}
                                 for p in products]
                        # Detail quantities are order-level: do not copy them into every parcel.
                        parsed = [{**parsed[0], 'warehouse_order_no': number, 'items': items,
                                   'package_no': '', 'tracking_no': detail.get('shippingOrderNo') or item.get('shippingOrderNo') or ''}]
                    result.extend(parsed)
                    matched.add(number)
                if page >= last:
                    if len(seen) != total or (last == 0 and total != 0):
                        raise ValidationError('百世分页数量不完整。')
                    break
                if not records:
                    raise ValidationError('百世分页提前结束。')
            else:
                raise ValidationError('百世分页超出查询上限。')
        start = end + timedelta(seconds=1)
    return result
