"""BEST 2.0 documented read responses, normalized without inventing missing facts."""
from datetime import timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError


def text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 191 or any(ord(c) < 32 for c in value):
        raise ValidationError('百世单号或商品编码缺失、格式无效。')
    return value.strip()


def count(value):
    try:
        if isinstance(value, bool) or value in (None, ''):
            raise ValueError()
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number != number.to_integral_value() or number > 2147483647:
            raise ValueError()
        return int(number)
    except (ValueError, InvalidOperation):
        raise ValidationError('百世数量缺失或不是非负整数，未截断或默认为零。') from None


def rows(container, key):
    if container in (None, ''):
        return []
    if not isinstance(container, dict):
        raise ValidationError('百世明细结构无效。')
    value = container.get(key)
    if value in (None, ''):
        return []
    result = value if isinstance(value, list) else [value]
    if any(not isinstance(item, dict) for item in result):
        raise ValidationError('百世明细结构无效。')
    return result


def utc_time(value):
    if value in (None, ''):
        return None
    try:
        parsed = parse_datetime(str(value))
    except ValueError:
        parsed = None
    if parsed is None:
        raise ValidationError('百世时间格式无效。')
    # Until the warehouse clock is confirmed, naive values cannot date costs.
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt_timezone.utc).isoformat()


def request_payload(authorization, **fields):
    root = ET.Element('request')
    fields = {'customerCode': text(authorization.integration_config.platform_config.get('customer_code')),
              'warehouseCode': text(authorization.external_warehouse_code), **fields}
    for key, value in fields.items():
        ET.SubElement(root, key).text = str(value)
    return {'bizData': ET.tostring(root, encoding='unicode')}


def return_receipt(data, return_no):
    value = data.get('rma')
    if not isinstance(value, dict) or text(value.get('rmaCode')) != return_no:
        raise ValidationError('百世退货单号与查询不一致，未关联。')
    status = text(value.get('rmaStatus'))
    result = {'return_no': return_no, 'erp_no': '', 'platform_order_no': '', 'tracking_no': '',
              'provider_status': status, 'received_at': None, 'lines': []}
    if status not in {'INPROCESS', 'FULFILLED'}:
        return result
    products = rows(value.get('products'), 'product')
    if not products:
        raise ValidationError('百世退货缺少实收商品明细。')
    for item in products:
        quantity = count(item.get('normalQuantity')) + count(item.get('defectiveQuantity'))
        result['lines'].append({'sku': text(item.get('skuCode')), 'received_quantity': quantity})
    # Costs require putaway completion (wmsUpdateTime). The query contract only
    # supplies receiveTime; never substitute receipt completion for putaway.
    return result


STATUS_LABELS = {'NEW': '待审核', 'WMS_ACCEPT': '已接单', 'EXCEPTION': '异常',
    'WMS_PRINT': '打印', 'WMS_PICK': '拣货', 'WMS_CHECK': '复核', 'WMS_PACKAGE': '打包',
    'WMS_WEIGH': '称重', 'DELIVERED': '已发货', 'CLOSED': '已关闭', 'CANCELED': '已取消'}


def packages(order, authorization):
    if (order.get('warehouseCode') != authorization.external_warehouse_code or
            order.get('customerCode') != authorization.integration_config.platform_config['customer_code']):
        raise ValidationError('百世出库单客户或仓库不一致。')
    number, erp_no = text(order.get('salesOrderNo')), text(order.get('orderCode'))
    base = {'provider': 'best_ecapi', 'warehouse_order_no': number, 'erp_no': erp_no,
            'status': text(order.get('status')), 'status_label': STATUS_LABELS.get(order.get('status'), '未知仓库状态'),
            'tracking_no': order.get('shippingOrderNo') or '', 'carrier': order.get('logisticsProviderCode') or '',
            'shipped_at_utc': utc_time(order.get('deliveryTime')) if order.get('status') == 'DELIVERED' else None}
    result, seen = [], set()
    for item in rows(order.get('packageList'), 'packageItem'):
        code = text(item.get('packCode'))
        if code in seen or item.get('orderCode') != erp_no or item.get('customerCode') != order['customerCode']:
            raise ValidationError('百世包裹重复或归属不一致。')
        seen.add(code)
        products = rows(item.get('packProduct'), 'packProduct')
        details = []
        for product in products:
            quantity = count(product.get('packQuantity'))
            if product.get('packDecimalQty') not in (None, '') and count(product['packDecimalQty']) != quantity:
                raise ValidationError('百世包裹整数与小数数量不一致。')
            details.append({'sku': text(product.get('packSkuCode')), 'quantity': quantity,
                            'name': product.get('packSkuName') or ''})
        result.append({**base, 'warehouse_order_no': number + '/' + code, 'source_order_no': number,
                       'package_no': code, 'tracking_no': item.get('packShippingOrderNo') or base['tracking_no'],
                       'carrier': item.get('packLogisticsProviderCode') or base['carrier'], 'items': details})
    return result or [{**base, 'items': []}]
