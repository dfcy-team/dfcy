"""Read-only, actor-scoped supply cockpit. Aggregate facts before joining owners.

No warehouse balance is inferred from local receipts. Settlement revisions are
cumulative observations: only the current revision is counted.
"""
from decimal import Decimal

from django.db.models import (Case, Count, DecimalField, ExpressionWrapper, F,
    IntegerField, OuterRef, Q, Subquery, Sum, Value, When)
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.masterdata.models import CountrySiteMaster
from apps.sales_management import operating
from apps.sales_management.operating_models import OperatingOrderLine
from .cost_models import FeeRecord, SettlementRecord
from .dates import business_date
from .logistics import batches_for
from .models import (DispatchAllocation, InboundLine, InboundOrder,
    OperatingAllocation, PurchaseLine, PurchaseOrder, ShipmentLine, SupplierShipment)
from .permissions import internal_orders
from .views import InternalAPI


MONEY = DecimalField(max_digits=30, decimal_places=4)
ZERO = Value(Decimal('0'), output_field=MONEY)


class Query(serializers.Serializer):
    country_id = serializers.IntegerField(min_value=1, required=False)
    section = serializers.ChoiceField(choices=('operations', 'costs', 'inventory'), default='operations')
    queue = serializers.ChoiceField(choices=('purchases', 'collection', 'loading', 'batches', 'inbounds', 'supplier', 'carrier'), required=False)
    limit = serializers.IntegerField(min_value=1, max_value=50, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)


def scope(actor, country_id=None):
    orders = internal_orders(actor, PurchaseOrder.objects.all())
    demands = operating.procurement_orders_for(actor)
    # Countries are an available-data filter, never an additional permission grant.
    countries = CountrySiteMaster.objects.filter(tenant_id=actor.tenant_id).filter(
        Q(pk__in=orders.values('country_id')) | Q(pk__in=demands.values('country_id'))).order_by('country_code', 'pk')
    if country_id:
        if not countries.filter(pk=country_id).exists():
            raise NotFound('该国家没有可访问的供应链数据。')
        orders = orders.filter(country_id=country_id)
        demands = demands.filter(country_id=country_id)
    batches = batches_for(actor).filter(status='active')
    if country_id:
        batches = batches.filter(country_id=country_id)
    # A batch with no accessible source never invents a country data grant.
    batches = batches.filter(country_id__in=countries.values('pk'))
    orders = orders.filter(status='confirmed')
    shipments = SupplierShipment.objects.filter(tenant_id=actor.tenant_id, order__in=orders, status='submitted')
    inbounds = InboundOrder.objects.filter(tenant_id=actor.tenant_id, batch__in=batches)
    return countries, orders, demands, shipments, batches, inbounds


def _lines(orders):
    shipped = ShipmentLine.objects.filter(purchase_line_id=OuterRef('pk'), is_active=True,
        shipment__status='submitted').order_by().values('purchase_line_id').annotate(n=Sum('quantity')).values('n')
    return PurchaseLine.objects.filter(order__in=orders, is_active=True).annotate(
        shipped=Coalesce(Subquery(shipped, output_field=IntegerField()), 0)).annotate(
        remaining=Greatest(F('quantity') - F('shipped'), Value(0)))


def _shipment_lines(shipments):
    used = DispatchAllocation.objects.filter(shipment_line_id=OuterRef('pk'), membership__active_guard=True,
        membership__batch__status='active').order_by().values('shipment_line_id').annotate(n=Sum('quantity')).values('n')
    return ShipmentLine.objects.filter(shipment__in=shipments, is_active=True).annotate(
        allocated=Coalesce(Subquery(used, output_field=IntegerField()), 0)).annotate(
        remaining=Greatest(F('quantity') - F('allocated'), Value(0)))


def _country_group(query, path, **metrics):
    return query.order_by().values(path).annotate(**metrics)


def operations_data(actor, scoped):
    countries, orders, demands, shipments, batches, inbounds = scoped
    fields = ('purchase_orders', 'purchase_quantity', 'unshipped_quantity', 'submitted_shipments',
        'waiting_collection', 'waiting_factory_loading', 'unallocated_quantity', 'awaiting_departure_quantity',
        'in_transit_quantity', 'at_port_quantity', 'at_warehouse_quantity', 'pending_inbounds',
        'inbound_difference_lines', 'overdue_batches', 'undated_batches', 'open_demand_quantity')
    rows = {c.pk: {'country_id': c.pk, 'country_code': c.country_code, 'country_name': c.name,
        **{field: 0 for field in fields}} for c in countries}

    def merge(query, path, **metrics):
        for data in _country_group(query, path, **metrics):
            row = rows.get(data[path])
            if row is not None:
                row.update({k: int(data[k] or 0) for k in metrics})

    merge(orders, 'country_id', purchase_orders=Count('pk'))
    merge(_lines(orders), 'order__country_id', purchase_quantity=Sum('quantity'), unshipped_quantity=Sum('remaining'))
    merge(shipments, 'order__country_id', submitted_shipments=Count('pk'),
        waiting_collection=Count('pk', filter=Q(delivery_mode='collection_center', collection_arrived=False)))
    lines = _shipment_lines(shipments)
    merge(lines, 'shipment__order__country_id', unallocated_quantity=Sum('remaining'))
    # Factory loading has no collection arrival state; use unallocated lines instead.
    merge(shipments.filter(delivery_mode='factory_loading', pk__in=lines.filter(remaining__gt=0).values('shipment_id')),
        'order__country_id', waiting_factory_loading=Count('pk'))
    allocations = DispatchAllocation.objects.filter(membership__batch__in=batches,
        membership__active_guard=True, shipment_line__is_active=True, shipment_line__shipment__status='submitted')
    merge(allocations, 'membership__batch__country_id',
        awaiting_departure_quantity=Sum('quantity', filter=Q(membership__batch__stage='unmarked')),
        in_transit_quantity=Sum('quantity', filter=Q(membership__batch__stage='departed')),
        at_port_quantity=Sum('quantity', filter=Q(membership__batch__stage='arrived_port')),
        at_warehouse_quantity=Sum('quantity', filter=Q(membership__batch__stage='arrived_warehouse') &
            (Q(membership__batch__inbound_order__isnull=True) | Q(membership__batch__inbound_order__status='draft'))))
    merge(inbounds.filter(status='draft'), 'batch__country_id', pending_inbounds=Count('pk'))
    merge(InboundLine.objects.filter(inbound__in=inbounds, received_quantity__isnull=False).exclude(
        received_quantity=F('expected_quantity')), 'inbound__batch__country_id', inbound_difference_lines=Count('pk'))
    travelling = batches.exclude(stage='arrived_warehouse')
    merge(travelling, 'country_id', overdue_batches=Count('pk', filter=Q(expected_warehouse_date__lt=business_date())),
        undated_batches=Count('pk', filter=Q(expected_warehouse_date__isnull=True)))
    # Use the canonical operating-line link and all reservations, including drafts.
    reserved = OperatingAllocation.objects.filter(operating_line_id=OuterRef('pk'), purchase_line__is_active=True).exclude(
        purchase_line__order__status='cancelled').order_by().values('operating_line_id').annotate(
        n=Sum('allocated_quantity')).values('n')
    demand_lines = OperatingOrderLine.objects.filter(order__in=demands, is_active=True).annotate(
        reserved=Coalesce(Subquery(reserved, output_field=IntegerField()), 0)).annotate(
        remaining=Greatest(F('quantity') - F('reserved'), Value(0)))
    merge(demand_lines, 'order__country_id', open_demand_quantity=Sum('remaining'))
    totals = {field: sum(row[field] for row in rows.values()) for field in fields}
    return {'totals': totals, 'countries': list(rows.values()),
        'inventory': {'status': 'not_included', 'quantity': None, 'value': None,
            'notice': '本页展示供应链单据进度；第三方仓可用库存请切换库存页签按需读取。入库流水不计作当前库存，库存货值待统一成本口径。'},
        'notices': ['仅统计当前账号可访问的已下单采购、已提交发货和有效发运批次；取消单据不计入。',
            '未发货按采购行减已提交发货量；未分配按发货行减有效批次数量，支持多次发货与分批集货。',
            '未发运、运输中、到港、到仓待核对为互斥批次阶段；不得与采购/发货累计数量相加。',
            '待拆采购包含有效采购草稿预留；有差异的入库行不等同于未处理异常。']}


def _money_targets(kind, scoped):
    _, _, _, shipments, batches, _ = scoped
    if kind == 'supplier':
        goods = ShipmentLine.objects.filter(shipment_id=OuterRef('pk'), is_active=True).order_by().values('shipment_id')
        totals = goods.annotate(n=Sum(ExpressionWrapper(F('quantity') * F('unit_price'), output_field=MONEY))).values('n')
        missing = goods.annotate(n=Count('pk', filter=Q(unit_price__isnull=True))).values('n')
        query = shipments.annotate(known_amount=Subquery(totals, output_field=MONEY),
            missing=Subquery(missing, output_field=IntegerField()))
        query = query.annotate(due=Case(When(missing=0, then=F('known_amount')), default=Value(None), output_field=MONEY))
        records = SettlementRecord.objects.filter(shipment_id=OuterRef('pk'))
    else:
        fees = FeeRecord.objects.filter(batch_id=OuterRef('pk'), current_revision__state='confirmed')
        query = batches.annotate(due=Subquery(fees.values('current_revision__amount')[:1], output_field=MONEY))
        records = SettlementRecord.objects.filter(batch_id=OuterRef('pk'))
    query = query.annotate(recorded=Coalesce(Subquery(records.values('current_revision__recorded_amount')[:1], output_field=MONEY), ZERO))
    return query.annotate(unsettled=Case(When(due__isnull=True, then=Value(None)),
        default=Greatest(F('due') - F('recorded'), ZERO), output_field=MONEY),
        over_recorded=Case(When(due__isnull=True, then=Value(None)),
        default=Greatest(F('recorded') - F('due'), ZERO), output_field=MONEY))


def costs_data(actor, scoped):
    groups = {}
    for kind in ('supplier', 'carrier'):
        query = _money_targets(kind, scoped)
        data = query.aggregate(documents=Count('pk'), unknown_documents=Count('pk', filter=Q(due__isnull=True)),
            total_amount=Sum('due'), total_recorded=Sum('recorded'), total_unsettled=Sum('unsettled'), total_over_recorded=Sum('over_recorded'))
        for key in ('amount', 'recorded', 'unsettled', 'over_recorded'):
            data[key] = str(data.pop('total_' + key) or Decimal('0'))
        path = 'order__supplier' if kind == 'supplier' else 'freight_company'
        ranking = list(query.order_by().values(f'{path}__id', f'{path}__name').annotate(
            amount=Sum('due'), unsettled=Sum('unsettled'), unknown_documents=Count('pk', filter=Q(due__isnull=True)))
            .order_by('-unsettled', f'{path}__id')[:10])
        data['ranking'] = [{'id': r[f'{path}__id'], 'name': r[f'{path}__name'],
            'amount': str(r['amount'] or Decimal('0')), 'unsettled': str(r['unsettled'] or Decimal('0')),
            'unknown_documents': r['unknown_documents']} for r in ranking]
        groups[kind] = data
    return {'groups': groups, 'amount_basis': '系统单据金额，未作汇率换算；供应商货款与货运费用分别统计。',
        'notices': ['供应商应结额来自已提交发货单有效行价格；货运应结额只采用当前已确认费用版本。',
            '已登记金额只取每张单据的当前累计登记，历史修订不重复求和。',
            '未定价/未确认费用单据不计入已知应结及未结金额，须结合待核对单据数查看；登记金额不代表银行核验。']}


class Dashboard(InternalAPI):
    http_method_names = ['get', 'head', 'options']

    def get(self, request):
        query = Query(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        scoped = scope(request.user, values.get('country_id'))
        countries = [{'id': c.pk, 'country_code': c.country_code, 'name': c.name} for c in scoped[0]]
        if values['section'] == 'inventory':
            from .dashboard_inventory import inventory_data
            data = inventory_data(request.user, scoped, country_id=values.get('country_id'))
        else:
            data = (costs_data if values['section'] == 'costs' else operations_data)(request.user, scoped)
        if values.get('country_id') and 'countries' in data:
            data['countries'] = [row for row in data['countries'] if row['country_id'] == values['country_id']]
        return Response({'data': {**data, 'country_options': countries, 'country_id': values.get('country_id'),
            'generated_at': timezone.now().isoformat(), 'section': values['section']}})


class DashboardQueue(InternalAPI):
    http_method_names = ['get', 'head', 'options']

    def get(self, request):
        query = Query(data=request.query_params)
        query.is_valid(raise_exception=True)
        v = query.validated_data
        kind = v.get('queue', 'purchases')
        scoped = scope(request.user, v.get('country_id'))
        _, orders, _, shipments, batches, inbounds = scoped
        if kind == 'purchases':
            records = orders.filter(pk__in=_lines(orders).filter(remaining__gt=0).values('order_id')).select_related('country', 'supplier')
        elif kind in ('collection', 'loading'):
            records = shipments.filter(delivery_mode='collection_center', collection_arrived=False) if kind == 'collection' else shipments.filter(
                delivery_mode='factory_loading', pk__in=_shipment_lines(shipments).filter(remaining__gt=0).values('shipment_id'))
            records = records.select_related('order__country', 'order__supplier')
        elif kind == 'batches':
            records = batches.exclude(stage='arrived_warehouse').select_related('country', 'freight_company')
        elif kind == 'inbounds':
            records = inbounds.filter(status='draft').select_related('batch__country', 'batch__freight_company')
        else:
            records = _money_targets(kind, scoped).filter(Q(due__isnull=True) | Q(unsettled__gt=0) | Q(over_recorded__gt=0))
            records = records.select_related('order__country', 'order__supplier') if kind == 'supplier' else records.select_related('country', 'freight_company')
        total = records.count()
        rows = []
        for obj in records.order_by('-pk')[v['offset']:v['offset'] + v['limit']]:
            if kind == 'purchases':
                country, party = obj.country, obj.supplier.name
                link = f'/supply-chain/supplier-shipments?order_id={obj.pk}'
            elif kind in ('collection', 'loading', 'supplier'):
                country, party = obj.order.country, obj.order.supplier.name
                link = f'/supply-chain/costs?kind=shipment&id={obj.pk}' if kind == 'supplier' else f'/supply-chain/supplier-shipments?order_id={obj.order_id}'
            elif kind == 'inbounds':
                country, party = obj.batch.country, obj.batch.freight_company.name
                link = f'/supply-chain/logistics?inbound_id={obj.pk}'
            else:
                country, party = obj.country, obj.freight_company.name
                link = f'/supply-chain/costs?kind=batch&id={obj.pk}' if kind == 'carrier' else f'/supply-chain/logistics?batch_id={obj.pk}'
            rows.append({'id': obj.pk, 'number': obj.number, 'country_code': country.country_code,
                'country_name': country.name, 'party_name': party, 'href': link,
                'unsettled': None if kind not in ('supplier', 'carrier') or obj.unsettled is None else str(obj.unsettled)})
        return Response({'data': rows, 'count': total, 'limit': v['limit'], 'offset': v['offset']})
