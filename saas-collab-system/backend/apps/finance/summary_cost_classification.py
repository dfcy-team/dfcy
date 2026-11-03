"""Classify existing costs from tenant-scoped business evidence; never post credits."""
from collections import defaultdict
from decimal import Decimal
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware


def logistics_evidence(order, platform):
    """Use captured forward-shipment events, never label creation or return receipt."""
    if not order or platform != 'lazada':
        return None
    snapshot = (getattr(order, 'source_details', None) or {}).get('platform_logistics') or {}
    if snapshot.get('status') != 'ok' or str(snapshot.get('order_sn') or '') != order.external_order_id:
        return None
    def instant(value):
        try:
            parsed = parse_datetime(str(value or ''))
            return parsed if parsed and is_aware(parsed) else None
        except ValueError:
            return None
    collected = instant(snapshot.get('collected_at_utc'))
    if collected is None:
        return None
    # Codes are accepted together with their saved platform description.
    prefixes = {'1400': ('Your package has been delivered!', '已签收'),
        '1210': ('Your parcel has been handed over to', '已交承运商'),
        '100013': ('Your package has arrived at the sortation facility.', '已到分拣中心'),
        '100102': ('Your package has departed from the sortation facility.', '已离开分拣中心'),
        '100103': ('Your package has arrived at the last mile hub', '已到配送站'),
        '100014': ('Your package has departed from the last mile hub', '已离开配送站'),
        '100018': ('Your package is currently out for delivery', '正在派送')}
    found = []
    for package in snapshot.get('packages') or []:
        if package.get('tracking_query_status') != 'ok':
            continue
        for event in package.get('events') or []:
            code = str(event.get('status') or '')
            rule = prefixes.get(code)
            occurred = instant(event.get('occurred_at_utc'))
            if rule and str(event.get('description') or '').startswith(rule[0]) and occurred and occurred <= collected:
                found.append((occurred, code, rule[1]))
    if not found:
        return None
    occurred, code, label = max(found)
    return {'source': 'SalesOrder.source_details.platform_logistics', 'status': code, 'label': label,
        'occurred_at_utc': occurred.isoformat(), 'collected_at_utc': collected.isoformat(),
        'source_operation_id': snapshot.get('source_operation_id')}


def classify(order, *, refunds=(), cases=(), shipments=(), samples=(), financial_refund=None, platform=None, item_statuses=()):
    raw = str(order.raw_status or '').strip().casefold() if order else ''
    status = order.normalized_status if order else ''
    refund_states = sorted({r.normalized_status.casefold() for r in refunds})
    return_states = sorted({c.return_status for c in cases})
    item_states = sorted({str(value).strip().casefold() for value in item_statuses if value})
    logistics = logistics_evidence(order, platform)
    shipped = bool(logistics) or bool(shipments) or bool(order and order.delivered_at_utc) or status in {'fulfilled', 'completed'} or raw in {
        'shipped', 'delivered', 'completed', 'returned', 'to_return', 'in_transit', 'out_for_delivery'}
    proof = {'order_id': order.pk if order else None, 'raw_status': raw, 'order_status': status,
        'refund_ids': [r.pk for r in refunds], 'refund_statuses': refund_states,
        'aftersales_ids': [c.pk for c in cases], 'return_statuses': return_states,
        'shipment_ids': [r.pk for r in shipments], 'sample_ids': [r.pk for r in samples],
        'shipped': shipped, 'platform_logistics': logistics, 'item_statuses': item_states,
        'financial_refund': None if financial_refund is None else str(financial_refund)}
    def result(category, reason):
        return {'version': 1, 'category': category, 'reason': reason, 'evidence': proof}
    if not order:
        return result('pending', '未关联到本站铺的 SaaS 订单')
    if samples:
        return result('sample', '有效送样单按同租户、同店铺、完整订单号关联')
    if status == 'cancelled' or raw in {'cancelled', 'canceled'}:
        return result('cancelled_shipped' if shipped else 'pending',
                      '订单已取消且有履约依据' if shipped else '订单已取消，缺少发货／出库依据')
    successful = {'completed', 'refund_success', 'refunded', 'refund_completed', 'refund_successful', 'success'}
    ignored = {'cancelled', 'canceled', 'request_cancel', 'rejected', 'request_rejected'}
    refunded = bool(set(refund_states) & successful) or financial_refund is not None and financial_refund != 0
    if raw in {'returned', 'to_return'}:
        return result('refund', '平台原始状态为退货；不代表已核验退货入库')
    if platform == 'lazada' and 'returned' in item_states:
        return result('refund', '平台商品行存在退货状态，可能为部分退货；不代表已核验退货入库')
    if refunded:
        return result('refund' if shipped else 'pending',
                      '退款成功或平台账单已退款，且有履约依据' if shipped else '已有退款，缺少发货／出库依据')
    active_cases = [c for c in cases if c.return_status not in {'cancelled', 'not_required'}
                    and (not c.refund_id or c.refund_id in {r.pk for r in refunds if r.normalized_status.casefold() not in ignored})]
    if set(refund_states) - ignored or active_cases:
        return result('pending', '售后处理中或结果未明确，不认定退款成功')
    if shipped:
        return result('normal', '已有履约依据，未命中送样、取消或有效退款／退货')
    return result('pending', '当前订单状态不足以确认已履约，缺少发货／出库依据')


def collect_classifications(user, stores, orders, facts):
    from apps.commerce.models import RefundReturn, ShipmentRecord, SalesOrderItem
    from apps.sales_management.aftersales_models import AftersalesCase
    from apps.influencers.models import SampleFulfillment
    refunds, cases, shipments, samples = (defaultdict(list) for _ in range(4))
    item_statuses = defaultdict(list)
    for order_id, state in SalesOrderItem.objects.filter(sales_order__tenant=user.tenant,
            sales_order__store_id__in=stores).values_list('sales_order_id', 'raw_line_status'):
        item_statuses[order_id].append(state)
    for model, target, field in [(RefundReturn, refunds, 'sales_order_id'), (AftersalesCase, cases, 'order_id')]:
        for row in model.objects.filter(tenant=user.tenant, store_id__in=stores):
            target[getattr(row, field)].append(row)
    for row in ShipmentRecord.objects.filter(tenant=user.tenant, store_id__in=stores, shipped_at_utc__isnull=False):
        shipments[row.sales_order_id].append(row)
    for row in SampleFulfillment.objects.filter(tenant=user.tenant, store_id__in=stores, is_deleted=False).exclude(status='cancelled').exclude(sample_order_no=''):
        samples[(row.store_id, row.sample_order_no.strip())].append(row)
    amounts = {}
    for f in facts:
        if f['kind'] == 'refund' and f['amount'] is not None:
            key = (f['store_id'], f['external_order_id'])
            amounts[key] = amounts.get(key, Decimal('0')) + Decimal(f['amount'])
    return {(o.store_id, o.external_order_id): classify(o, refunds=refunds[o.pk], cases=cases[o.pk],
        shipments=shipments[o.pk], samples=samples[(o.store_id, o.external_order_id)],
        financial_refund=amounts.get((o.store_id, o.external_order_id)),
        platform=stores[o.store_id].platform.platform_type, item_statuses=item_statuses[o.pk]) for o in orders}
