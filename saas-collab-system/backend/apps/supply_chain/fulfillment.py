"""Read-only progress from source lines; never infer receipt from vessel status."""
from collections import defaultdict

from django.db.models import Sum, Subquery, OuterRef, IntegerField, Exists, F, Case, When, Value, CharField, Count
from django.db.models.functions import Coalesce
from rest_framework.exceptions import ValidationError

from .models import PurchaseLine, ShipmentLine, DispatchAllocation, InboundLine

LABELS = {'draft': '待下单', 'cancelled': '已取消', 'awaiting_shipment': '待发货',
    'partial_shipment': '部分发货', 'awaiting_dispatch': '待集货',
    'in_transit': '运输中', 'awaiting_inbound': '待入库', 'completed': '已完成'}


def annotate_workflow_stage(query):
    shipping = ShipmentLine.objects.filter(purchase_line_id=OuterRef('pk'), is_active=True,
        shipment__status='submitted').values('purchase_line_id').annotate(total=Sum('quantity')).values('total')
    receiving = InboundLine.objects.filter(shipment_line__purchase_line_id=OuterRef('pk'),
        shipment_line__is_active=True, shipment_line__shipment__status='submitted',
        inbound__status='confirmed', inbound__batch__status='active').values('shipment_line__purchase_line_id').annotate(
        total=Sum('received_quantity')).values('total')
    arrival = DispatchAllocation.objects.filter(shipment_line__purchase_line_id=OuterRef('pk'),
        shipment_line__is_active=True, shipment_line__shipment__status='submitted',
        membership__active_guard=True, membership__batch__status='active',
        membership__batch__stage='arrived_warehouse').values('shipment_line__purchase_line_id').annotate(
        total=Sum('quantity')).values('total')
    lines = PurchaseLine.objects.filter(order_id=OuterRef('pk'), is_active=True).annotate(
        _shipped=Coalesce(Subquery(shipping, output_field=IntegerField()), Value(0)),
        _received=Coalesce(Subquery(receiving, output_field=IntegerField()), Value(0)),
        _arrived=Coalesce(Subquery(arrival, output_field=IntegerField()), Value(0)))
    started = DispatchAllocation.objects.filter(shipment_line__shipment__order_id=OuterRef('pk'),
        shipment_line__is_active=True, shipment_line__shipment__status='submitted',
        membership__active_guard=True, membership__batch__status='active').exclude(membership__batch__stage='unmarked')
    query = query.annotate(_flow_lines=Exists(lines),
        _flow_shipping=Exists(lines.filter(quantity__gt=F('_shipped'))),
        _flow_receiving=Exists(lines.filter(quantity__gt=F('_received'))),
        _flow_arrival=Exists(lines.filter(quantity__gt=F('_arrived'))),
        _flow_shipped=Exists(lines.filter(_shipped__gt=0)), _flow_started=Exists(started))
    return query.annotate(_workflow_stage=Case(
        When(status='draft', then=Value('draft')), When(status='cancelled', then=Value('cancelled')),
        When(_flow_lines=False, then=Value('awaiting_shipment')),
        When(_flow_lines=True, _flow_receiving=False, then=Value('completed')),
        When(_flow_shipping=True, _flow_shipped=True, then=Value('partial_shipment')),
        When(_flow_shipping=True, then=Value('awaiting_shipment')),
        When(_flow_lines=True, _flow_arrival=False, then=Value('awaiting_inbound')),
        When(_flow_started=True, then=Value('in_transit')),
        default=Value('awaiting_dispatch'), output_field=CharField()))


def filter_orders(query, stage):
    if not stage:
        return query
    if stage == 'pending':
        return annotate_workflow_stage(query).filter(_workflow_stage__in=('draft', 'awaiting_shipment', 'awaiting_dispatch'))
    if stage not in LABELS:
        raise ValidationError('采购履约阶段不正确。')
    return annotate_workflow_stage(query).filter(_workflow_stage=stage)


def workflow_counts(query):
    """Count serializer-equivalent stages on an already scoped, unpaginated queryset."""
    counts = {stage: 0 for stage in LABELS}
    for row in annotate_workflow_stage(query).values('_workflow_stage').annotate(total=Count('pk')):
        counts[row['_workflow_stage']] = row['total']
    counts['pending'] = sum(counts[stage] for stage in ('draft', 'awaiting_shipment', 'awaiting_dispatch'))
    counts['all'] = sum(counts[stage] for stage in LABELS)
    return counts


def prepare_orders(orders):
    if not orders:
        return
    for tenant_id in {order.tenant_id for order in orders}:
        scoped = [order for order in orders if order.tenant_id == tenant_id]
        ids = [order.pk for order in scoped]
        lines = list(PurchaseLine.objects.filter(tenant_id=tenant_id, order_id__in=ids, is_active=True))
        by_order, shipped, dispatched, arrived, received = defaultdict(list), defaultdict(int), defaultdict(int), defaultdict(int), defaultdict(int)
        extras, ship_refs, batch_refs, inbound_refs = defaultdict(int), defaultdict(dict), defaultdict(dict), defaultdict(dict)
        for line in lines:
            by_order[line.order_id].append(line)
        shipping = ShipmentLine.objects.filter(tenant_id=tenant_id, shipment__order_id__in=ids,
            shipment__status='submitted', is_active=True).select_related('shipment')
        line_ids = {line.pk for line in lines}
        for line in shipping:
            order_id = line.shipment.order_id
            record = ship_refs[order_id].setdefault(line.shipment_id, {'id': line.shipment_id,
                'number': line.shipment.number, 'quantity': 0, 'status': line.shipment.status, 'shipment_date': str(line.shipment.shipment_date)})
            record['quantity'] += line.quantity
            if line.purchase_line_id in line_ids:
                shipped[line.purchase_line_id] += line.quantity
            else:
                extras[order_id] += line.quantity
        allocations = DispatchAllocation.objects.filter(tenant_id=tenant_id,
            shipment_line__shipment__order_id__in=ids, membership__active_guard=True,
            membership__batch__status='active', shipment_line__is_active=True,
            shipment_line__shipment__status='submitted').select_related('shipment_line__shipment', 'membership__batch')
        for allocation in allocations:
            source, batch = allocation.shipment_line, allocation.membership.batch
            ref = batch_refs[source.shipment.order_id].setdefault(batch.pk, {'id': batch.pk,
                'number': batch.number, 'stage': batch.stage, 'quantity': 0})
            ref['quantity'] += allocation.quantity
            if source.purchase_line_id in line_ids:
                dispatched[source.purchase_line_id] += allocation.quantity
                if batch.stage == 'arrived_warehouse':
                    arrived[source.purchase_line_id] += allocation.quantity
        receipts = InboundLine.objects.filter(tenant_id=tenant_id,
            shipment_line__shipment__order_id__in=ids, inbound__batch__status='active',
            shipment_line__is_active=True, shipment_line__shipment__status='submitted').select_related('inbound', 'shipment_line__shipment')
        for receipt in receipts:
            source, inbound = receipt.shipment_line, receipt.inbound
            ref = inbound_refs[source.shipment.order_id].setdefault(inbound.pk, {'id': inbound.pk,
                'number': inbound.number, 'status': inbound.status, 'quantity': 0})
            if inbound.status == 'confirmed' and receipt.received_quantity is not None:
                ref['quantity'] += receipt.received_quantity
                if source.purchase_line_id in line_ids:
                    received[source.purchase_line_id] += receipt.received_quantity
        for order in scoped:
            source = by_order[order.pk]
            pending_ship = sum(max(line.quantity - shipped[line.pk], 0) for line in source)
            pending_receipt = sum(max(line.quantity - received[line.pk], 0) for line in source)
            stage = 'awaiting_shipment'
            if order.status != 'confirmed':
                stage = order.status
            elif source and pending_receipt == 0:
                stage = 'completed'
            elif pending_ship:
                stage = 'partial_shipment' if any(shipped[line.pk] for line in source) else 'awaiting_shipment'
            elif source and all(arrived[line.pk] >= line.quantity for line in source):
                stage = 'awaiting_inbound'
            elif any(ref['stage'] in ('departed', 'arrived_port', 'arrived_warehouse') for ref in batch_refs[order.pk].values()):
                stage = 'in_transit'
            else:
                stage = 'awaiting_dispatch'
            order._read_fulfillment = {'stage': stage, 'label': LABELS.get(stage, stage),
                'ordered_quantity': sum(line.quantity for line in source),
                'shipped_quantity': sum(shipped[line.pk] for line in source),
                'unshipped_quantity': pending_ship,
                'dispatched_quantity': sum(dispatched[line.pk] for line in source),
                'undispatched_quantity': sum(max(line.quantity-dispatched[line.pk],0) for line in source),
                'unreceived_quantity': pending_receipt,
                'arrived_quantity': sum(arrived[line.pk] for line in source),
                'received_quantity': sum(received[line.pk] for line in source),
                'extra_shipped_quantity': extras[order.pk],
                'shipment_count': len(ship_refs[order.pk]), 'batch_count': len(batch_refs[order.pk]),
                'inbound_count': len(inbound_refs[order.pk])}
            order._read_line_fulfillment = {line.pk: {'shipped_quantity': shipped[line.pk],
                'unshipped_quantity': max(line.quantity - shipped[line.pk], 0)} for line in source}
            order._read_flow_relations = {'shipments': sorted(ship_refs[order.pk].values(), key=lambda r: r['id']),
                'batches': sorted(batch_refs[order.pk].values(), key=lambda r: r['id']),
                'inbounds': sorted(inbound_refs[order.pk].values(), key=lambda r: r['id'])}


def enrich_order(order, data, *, related=False):
    if not hasattr(order, '_read_fulfillment'):
        prepare_orders([order])
    data['fulfillment'] = order._read_fulfillment
    for line in data.get('lines', []):
        line.update(order._read_line_fulfillment.get(line['id'], {}))
    if related:
        data['flow_relations'] = order._read_flow_relations
    return data
