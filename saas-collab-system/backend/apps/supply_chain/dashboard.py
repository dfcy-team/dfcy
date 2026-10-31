"""Read-only, actor-scoped supply cockpit. Aggregate facts before joining owners.

No warehouse balance is inferred from local receipts. Settlement revisions are
cumulative observations: only the current revision is counted.
"""
from decimal import Decimal

from django.db.models import (Case, Count, DecimalField, ExpressionWrapper, Exists, F,
    IntegerField, OuterRef, Q, Subquery, Sum, Value, When)
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.commerce.country_decisions import INVENTORY as INVENTORY_PERMISSION, _config_countries
from apps.masterdata.models import CountrySiteMaster
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.sales_management import operating
from apps.sales_management.scopes import _custom_scope_configs
from apps.sales_management.operating_models import OperatingOrderLine
from .cost_models import FeeRevisionItem, FeeRecord, SettlementRecord, PaymentRecord, PaymentApplication
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
    queue = serializers.ChoiceField(choices=('purchases', 'collection', 'loading', 'batches', 'inbounds', 'supplier', 'carrier', 'domestic', 'deposit', 'clearance'), required=False)
    payment_nature = serializers.ChoiceField(choices=('corporate', 'personal', 'mixed', 'unknown'), required=False)
    payment_item = serializers.CharField(required=False, allow_blank=True, max_length=100)
    item_status = serializers.ChoiceField(choices=('all','unpaid','partial','settled'), required=False)
    status = serializers.ChoiceField(choices=('pending', 'settled', 'all'), default='pending', required=False)
    party_id = serializers.IntegerField(min_value=1, required=False)
    search = serializers.CharField(required=False, allow_blank=True, max_length=100)
    limit = serializers.IntegerField(min_value=1, max_value=50, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)


def scope(actor, country_id=None):
    orders = internal_orders(actor, PurchaseOrder.objects.all())
    demands = operating.procurement_orders_for(actor)
    # Countries are an available-data filter, never an additional permission grant.
    supply_countries = Q(pk__in=orders.values('country_id')) | Q(pk__in=demands.values('country_id'))
    inventory_countries = CountrySiteMaster.objects.none()
    permission_cache = getattr(actor, '_permission_resolution_cache', None)
    if (check_user_permission(actor, INVENTORY_PERMISSION, cache=permission_cache)
            and get_permission_data_scopes(actor, INVENTORY_PERMISSION,
                resource_code='commerce.inventory', cache=permission_cache)):
        inventory_countries = CountrySiteMaster.objects.filter(tenant_id=actor.tenant_id, status='active')
        configs = _custom_scope_configs(actor, INVENTORY_PERMISSION, permission_cache,
            resource_code='commerce.inventory')
        if configs is not None:
            country_codes = set()
            include_all_countries = False
            for config in configs:
                allowed_codes = _config_countries(actor, config)
                if allowed_codes is None:
                    # SKU/SPU-only restrictions authorize the same country set
                    # as the shared inventory country resolver.
                    include_all_countries = True
                    break
                country_codes.update(allowed_codes)
            if not include_all_countries:
                inventory_countries = inventory_countries.filter(country_code__in=country_codes)
    countries = CountrySiteMaster.objects.filter(tenant_id=actor.tenant_id).filter(
        supply_countries | Q(pk__in=inventory_countries.values('pk'))).order_by('country_code', 'pk')
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
    if kind in ('supplier', 'domestic'):
        goods = ShipmentLine.objects.filter(shipment_id=OuterRef('pk'), is_active=True).order_by().values('shipment_id')
        totals = goods.annotate(n=Sum(ExpressionWrapper(F('quantity') * F('unit_price'), output_field=MONEY))).values('n')
        missing = goods.annotate(n=Count('pk', filter=Q(unit_price__isnull=True))).values('n')
        query = shipments.annotate(known_amount=Subquery(totals, output_field=MONEY),
            missing=Subquery(missing, output_field=IntegerField()))
        if kind == 'supplier':
            query = query.annotate(due=Case(When(missing=0, then=F('known_amount') + Case(When(purchase_contract__status='issued', then=F('purchase_contract__settlement_tax_amount')), default=ZERO, output_field=MONEY)), default=Value(None), output_field=MONEY))
            records = SettlementRecord.objects.filter(shipment_id=OuterRef('pk'))
            payment_owner, purpose = 'shipment_id', 'goods'
        else:
            fees = FeeRecord.objects.filter(shipment_id=OuterRef('pk'), current_revision__state='confirmed')
            query = query.annotate(due=Subquery(fees.values('current_revision__amount')[:1], output_field=MONEY))
            records = SettlementRecord.objects.none()
            payment_owner, purpose = 'shipment_id', 'domestic_freight'
        party_path = 'domestic_carrier' if kind == 'domestic' else 'order__supplier'
        country_path = 'order__country'
        owner = 'shipment_id'
    elif kind == 'deposit':
        lines = PurchaseLine.objects.filter(order_id=OuterRef('pk'), is_active=True).order_by().values('order_id')
        totals = lines.annotate(n=Sum(ExpressionWrapper(F('quantity') * F('unit_price'), output_field=MONEY))).values('n')
        missing = lines.annotate(n=Count('pk', filter=Q(unit_price__isnull=True))).values('n')
        query = scoped[1].annotate(known_amount=Subquery(totals, output_field=MONEY),
            missing=Subquery(missing, output_field=IntegerField())).annotate(
            due=Case(When(missing=0, then=F('known_amount')), default=Value(None), output_field=MONEY))
        records = SettlementRecord.objects.none()
        payment_owner, purpose, owner = 'purchase_order_id', 'goods', 'purchase_order_id'
        party_path, country_path = 'supplier', 'country'
    elif kind == 'clearance':
        fees = FeeRecord.objects.filter(inbound_id=OuterRef('pk'), current_revision__state='confirmed')
        query = scoped[5].annotate(due=Subquery(fees.values('current_revision__amount')[:1], output_field=MONEY))
        records = SettlementRecord.objects.none()
        payment_owner, purpose, owner = 'inbound_id', 'goods', 'inbound_id'
        party_path, country_path = 'batch__freight_company', 'batch__country'
    else:
        fees = FeeRecord.objects.filter(batch_id=OuterRef('pk'), current_revision__state='confirmed')
        query = batches.annotate(due=Subquery(fees.values('current_revision__amount')[:1], output_field=MONEY))
        records = SettlementRecord.objects.filter(batch_id=OuterRef('pk'))
        payment_owner, purpose, owner = 'batch_id', 'goods', 'batch_id'
        party_path, country_path = 'freight_company', 'country'
    effective_payments = PaymentRecord.objects.filter(**{payment_owner: OuterRef('pk')}, purpose=purpose,
        reverses__isnull=True, reversal__isnull=True)
    payments = effective_payments.order_by().values(owner).annotate(total=Sum('amount')).values('total')
    paid = Coalesce(Subquery(payments, output_field=MONEY), ZERO)
    nature_totals = {}
    for nature in ('corporate', 'personal'):
        totals = effective_payments.filter(account_snapshot__nature=nature).order_by().values(owner).annotate(total=Sum('amount')).values('total')
        nature_totals[f'{nature}_paid'] = Coalesce(Subquery(totals, output_field=MONEY), ZERO)
    query = query.annotate(**nature_totals)
    applied = ZERO
    available = ZERO
    if kind == 'supplier':
        applications = PaymentApplication.objects.filter(shipment_id=OuterRef('pk'), reverses__isnull=True,
            reversal__isnull=True).order_by().values('shipment_id').annotate(total=Sum('amount')).values('total')
        applied = Coalesce(Subquery(applications, output_field=MONEY), ZERO)
    if kind == 'deposit':
        apps = PaymentApplication.objects.filter(prepayment__purchase_order_id=OuterRef('pk'), reverses__isnull=True, reversal__isnull=True,
            prepayment__reverses__isnull=True, prepayment__reversal__isnull=True).order_by().values('prepayment__purchase_order_id').annotate(total=Sum('amount')).values('total')
        applied = Coalesce(Subquery(apps, output_field=MONEY), ZERO)
        available = Greatest(paid - applied, ZERO)
    opening = Coalesce(Subquery(records.values('current_revision__recorded_amount')[:1], output_field=MONEY), ZERO)
    paid_total = opening + paid
    recorded = paid_total if kind == 'deposit' else paid_total + applied
    query = query.annotate(opening_amount=opening, paid_amount=paid_total, applied_amount=applied,
        available_prepayment=available, recorded=recorded,
        unknown_paid=paid_total-F('corporate_paid')-F('personal_paid'))
    return query.annotate(unsettled=Case(When(due__isnull=True, then=Value(None)),
        default=Greatest(F('due') - F('recorded'), ZERO), output_field=MONEY),
        over_recorded=Case(When(due__isnull=True, then=Value(None)),
        default=Greatest(F('recorded') - F('due'), ZERO), output_field=MONEY),
        remaining_amount=Case(When(due__isnull=True, then=Value(None)), default=Greatest(F('due') - paid_total - (ZERO if kind == 'deposit' else applied), ZERO), output_field=MONEY),
        **{'_party_id': F(f'{party_path}__id'), '_party_name': F(f'{party_path}__name'), '_country_code': F(f'{country_path}__country_code'), '_country_name': F(f'{country_path}__name')})


def costs_data(actor, scoped):
    groups = {}
    for kind in ('supplier', 'carrier', 'domestic', 'deposit', 'clearance'):
        query = _money_targets(kind, scoped)
        data = query.aggregate(documents=Count('pk'), unknown_documents=Count('pk', filter=Q(due__isnull=True)),
            total_amount=Sum('due'), total_opening=Sum('opening_amount'), total_paid=Sum('paid_amount'), total_applied=Sum('applied_amount'),
            total_recorded=Sum('recorded'), total_unsettled=Sum('unsettled'), total_over_recorded=Sum('over_recorded'), total_available_prepayment=Sum('available_prepayment'))
        for key in ('amount', 'opening', 'paid', 'applied', 'recorded', 'unsettled', 'over_recorded', 'available_prepayment'):
            data[key] = str(data.pop('total_' + key) or Decimal('0'))
        data['available'] = data['available_prepayment']
        ranking = list(query.order_by().values('_party_id', '_party_name').annotate(
            amount=Sum('due'), opening=Sum('opening_amount'), paid=Sum('paid_amount'), applied=Sum('applied_amount'),
            recorded=Sum('recorded'), unsettled=Sum('unsettled'), over_recorded=Sum('over_recorded'),
            available_prepayment=Sum('available_prepayment'), unknown_documents=Count('pk', filter=Q(due__isnull=True)))
            .order_by('-unsettled', '_party_id')[:10])
        data['ranking'] = [{'party_id': r['_party_id'], 'id': r['_party_id'], 'name': r['_party_name'],
            **{key: str(r[key] or Decimal('0')) for key in ('amount','opening','paid','applied','recorded','unsettled','over_recorded','available_prepayment')},
            'unknown_documents': r['unknown_documents']} for r in ranking]
        groups[kind] = data
    return {'groups': groups, 'amount_basis': '系统单据金额，未作汇率换算；供应商货款与货运费用分别统计。',
        'notices': ['供应商应结额来自已提交发货单有效行价格；国内运费和承运费用分别采用当前已确认费用版本。',
            '期初登记、有效现金支付及有效定金抵扣分列；定金抵扣不计入现金已付，历史修订不重复求和。',
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
            records = _money_targets(kind, scoped)
            nature = v.get('payment_nature')
            if nature == 'mixed':
                records = records.filter(corporate_paid__gt=0, personal_paid__gt=0)
            elif nature in ('corporate', 'personal'):
                records = records.filter(**{f'{nature}_paid__gt': 0})
            elif nature == 'unknown':
                records = records.filter(Q(unknown_paid__gt=0) | Q(paid_amount=0))
            if v.get('item_status'):
                if kind not in ('carrier', 'clearance'):
                    raise serializers.ValidationError({'item_status': '费用项目状态仅用于批次货运费及入库清关费用。'})
                owner = 'batch_id' if kind == 'carrier' else 'inbound_id'
                paid = PaymentRecord.objects.filter(tenant_id=request.user.tenant_id, **{owner: OuterRef('revision__fee__'+owner)}, fee_item_id=OuterRef('fee_item_id'), reverses__isnull=True, reversal__isnull=True).order_by().values(owner).annotate(total=Sum('amount')).values('total')
                items = FeeRevisionItem.objects.filter(revision__fee__tenant_id=request.user.tenant_id, revision_id=F('revision__fee__current_revision_id'), **{'revision__fee__'+owner: OuterRef('pk')}).annotate(item_paid=Coalesce(Subquery(paid, output_field=MONEY), ZERO))
                if v.get('payment_item'):
                    items = items.filter(name__icontains=v['payment_item'])
                if v['item_status'] == 'unpaid':
                    items = items.filter(amount__gt=0, item_paid=0)
                elif v['item_status'] == 'partial':
                    items = items.filter(item_paid__gt=0, amount__gt=F('item_paid'))
                elif v['item_status'] == 'settled':
                    items = items.filter(amount__lte=F('item_paid'))
                records = records.filter(Exists(items))
            elif v.get('payment_item'):
                owner = {'supplier': 'shipment_id', 'domestic': 'shipment_id', 'carrier': 'batch_id',
                    'deposit': 'purchase_order_id', 'clearance': 'inbound_id'}[kind]
                matching = PaymentRecord.objects.filter(**{owner: OuterRef('pk')},
                    purpose='domestic_freight' if kind == 'domestic' else 'goods',
                    reverses__isnull=True, reversal__isnull=True,
                    item_snapshot__name__icontains=v['payment_item'])
                records = records.filter(Exists(matching))
            if v.get('party_id'):
                records = records.filter(_party_id=v['party_id'])
            if v.get('search'):
                records = records.filter(Q(number__icontains=v['search']) | Q(_party_name__icontains=v['search']))
            if v['status'] == 'pending':
                records = records.filter(Q(due__isnull=True) | Q(remaining_amount__gt=0) | Q(over_recorded__gt=0))
            elif v['status'] == 'settled':
                records = records.filter(due__isnull=False, remaining_amount=0, over_recorded=0)
            if kind in ('supplier', 'domestic'):
                records = records.select_related('order__country', 'order__supplier', 'domestic_carrier')
            elif kind == 'deposit':
                records = records.select_related('country', 'supplier')
            elif kind == 'clearance':
                records = records.select_related('batch__country', 'batch__freight_company')
            else:
                records = records.select_related('country', 'freight_company')
        total = records.count()
        summary = None
        if kind in ('supplier', 'carrier', 'domestic', 'deposit', 'clearance'):
            # Avoid shadowing annotations referenced by subsequent aggregate expressions.
            values = records.aggregate(documents=Count('pk'), unknown_documents=Count('pk', filter=Q(due__isnull=True)),
                total_due=Sum('due'), total_opening=Sum('opening_amount'), total_paid=Sum('paid_amount'), total_applied=Sum('applied_amount'),
                total_remaining=Sum('remaining_amount'), total_available=Sum('available_prepayment'),
                total_corporate=Sum('corporate_paid'), total_personal=Sum('personal_paid'), total_unknown=Sum('unknown_paid'))
            summary = {'documents': values['documents'], 'unknown_documents': values['unknown_documents'],
                'due_amount': str(values['total_due'] or Decimal('0')), 'opening_amount': str(values['total_opening'] or Decimal('0')),
                'paid_amount': str(values['total_paid'] or Decimal('0')), 'applied_amount': str(values['total_applied'] or Decimal('0')),
                'remaining_amount': str(values['total_remaining'] or Decimal('0')),
                'available_prepayment': str(values['total_available'] or Decimal('0')),
                **{f'{name}_paid': str(values[f'total_{name}'] or Decimal('0')) for name in ('corporate', 'personal', 'unknown')}}
        page = list(records.order_by('-pk')[v['offset']:v['offset'] + v['limit']])
        fee_details = {}
        if kind in ('carrier', 'clearance'):
            owner = 'batch_id' if kind == 'carrier' else 'inbound_id'
            fee_details = {getattr(f, owner): f.current_revision.item_breakdown for f in FeeRecord.objects.filter(
                **{f'{owner}__in': [obj.pk for obj in page]}).select_related('current_revision') if f.current_revision}
        rows = []
        for obj in page:
            if kind == 'purchases':
                country, party = obj.country, obj.supplier.name
                link = f'/supply-chain/supplier-shipments?order_id={obj.pk}'
            elif kind in ('collection', 'loading', 'supplier'):
                country, party = obj.order.country, obj.order.supplier.name
                link = f'/supply-chain/costs?kind=shipment&id={obj.pk}' if kind == 'supplier' else f'/supply-chain/supplier-shipments?order_id={obj.order_id}'
            elif kind == 'domestic':
                country, party = obj.order.country, obj.domestic_carrier.name if obj.domestic_carrier_id else '未选择国内承运商'
                link = f'/supply-chain/costs?kind={"domestic_freight" if obj.domestic_carrier_id else "shipment"}&id={obj.pk}'
            elif kind == 'deposit':
                country, party = obj.country, obj.supplier.name
                link = f'/supply-chain/costs?kind=purchase&id={obj.pk}'
            elif kind in ('inbounds', 'clearance'):
                country, party = obj.batch.country, obj.batch.freight_company.name
                link = f'/supply-chain/costs?kind=inbound&id={obj.pk}' if kind == 'clearance' else f'/supply-chain/logistics?inbound_id={obj.pk}'
            else:
                country, party = obj.country, obj.freight_company.name
                link = f'/supply-chain/costs?kind=batch&id={obj.pk}' if kind == 'carrier' else f'/supply-chain/logistics?batch_id={obj.pk}'
            if kind in ('supplier', 'carrier', 'domestic', 'deposit', 'clearance'):
                target_kind = ('shipment' if kind == 'supplier' or (kind == 'domestic' and not obj.domestic_carrier_id)
                    else 'inbound' if kind == 'clearance' else 'batch' if kind == 'carrier' else 'purchase' if kind == 'deposit' else 'domestic_freight')
                rows.append({'id': obj.pk, 'number': obj.number, 'country_code': country.country_code,
                    'country_name': country.name, 'party_id': obj._party_id, 'party_name': party, 'href': link, 'kind': target_kind, 'queue': kind,
                    'due_amount': None if obj.due is None else str(obj.due), 'opening_amount': str(obj.opening_amount),
                    'paid_amount': str(obj.paid_amount), 'applied_amount': str(obj.applied_amount),
                    **{f'{name}_paid': str(getattr(obj, f'{name}_paid')) for name in ('corporate', 'personal', 'unknown')},
                    'fee_items': fee_details.get(obj.pk, []),
                    'remaining_amount': None if obj.remaining_amount is None else str(obj.remaining_amount),
                    'available_prepayment': str(obj.available_prepayment), 'unsettled': None if obj.unsettled is None else str(obj.unsettled)})
            else:
                rows.append({'id': obj.pk, 'number': obj.number, 'country_code': country.country_code,
                    'country_name': country.name, 'party_name': party, 'href': link})
        return Response({'data': rows, 'count': total, 'limit': v['limit'], 'offset': v['offset'], 'summary': summary})
