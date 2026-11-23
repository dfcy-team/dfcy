"""Read-only payment process projections; never invent historical payable balances."""
from decimal import Decimal


def source_links(kind, obj):
    if kind == 'purchase':
        return [{'label': f'采购单 {obj.number}', 'href': f'/supply-chain/purchase-orders?order_id={obj.pk}'}]
    if kind in ('shipment', 'domestic_freight'):
        from .shipment_sources import source_order_ids
        source_orders = getattr(obj, '_source_orders', None)
        if source_orders is None:
            source_orders = list(obj.order.__class__.objects.filter(tenant_id=obj.tenant_id,
                pk__in=source_order_ids(obj)).order_by('pk'))
        return [
            {'label': f'发货单 {obj.number}', 'href': f'/supply-chain/supplier-shipments?shipment_id={obj.pk}'},
            *[{'label': f'采购单 {order.number}', 'href': f'/supply-chain/purchase-orders?order_id={order.pk}'} for order in source_orders],
            *([{'label': '关联采购定金', 'href': f'/supply-chain/costs?kind=purchase&id={source_orders[0].pk}'}] if len(source_orders) == 1 else [
                {'label': f'采购定金 {order.number}', 'href': f'/supply-chain/costs?kind=purchase&id={order.pk}'} for order in source_orders]),
            {'label': '货款、国内费用与分摊', 'href': f'/supply-chain/costs?kind=shipment&id={obj.pk}'},
        ]
    if kind == 'batch':
        return [{'label': f'发运批次 {obj.number}', 'href': f'/supply-chain/logistics?batch_id={obj.pk}'}]
    if kind == 'inbound':
        return [{'label': f'入库单 {obj.number}', 'href': f'/supply-chain/logistics?inbound_id={obj.pk}'},
                {'label': f'发运批次 {obj.batch.number}', 'href': f'/supply-chain/logistics?batch_id={obj.batch_id}'}]
    return []


def annotate_process(entries, due, kind):
    # Use registration order, not a user-editable/backdated transfer date. Opening is always first.
    ordered = sorted(entries, key=lambda row: (
        row['entry_type'] != 'opening', str(row.get('recorded_at', '')),
        row['entry_type'], str(row['id'])))
    paid = applied = Decimal('0')
    for index, row in enumerate(ordered, 1):
        delta = Decimal(row['amount']) * (-1 if row.get('is_reversal') else 1)
        cash_delta = delta if row['entry_type'] != 'application' else Decimal('0')
        application_delta = delta if row['entry_type'] == 'application' else Decimal('0')
        paid += cash_delta
        applied += application_delta
        def fmt(value):
            return None if value is None else format(value, '.4f')
        row.update(sequence=index, cash_change=fmt(cash_delta), application_change=fmt(application_delta),
                   paid_after=fmt(paid), applied_after=fmt(applied),
                   remaining_after=fmt(None if due is None else due-paid-(applied if kind != 'purchase' else 0)),
                   available_after=fmt(paid-applied) if kind == 'purchase' else None)
    return ordered
