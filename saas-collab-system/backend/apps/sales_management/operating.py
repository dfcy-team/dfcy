"""Upstream operating demand and transactionally bounded procurement allocation."""
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_CEILING
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied
from apps.masterdata.models import CountrySiteMaster
from apps.products.models import ProductSKU
from apps.permissions.models import DataScope
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.supply_chain import services
from apps.supply_chain.dates import business_date
from apps.supply_chain.models import OperatingAllocation, domain_write
from apps.supply_chain.supplier_products import product_details
from apps.supply_chain.permissions import VIEW as SUPPLY_VIEW, MANAGE as SUPPLY_MANAGE
from apps.purchasing.supply_permissions import require_internal_supply_permission
from .operating_models import OperatingOrder, OperatingOrderLine, OperatingSuggestion

VIEW = 'sales_management.operating_orders.view'
MANAGE = 'sales_management.operating_orders.manage'


def country_ids(scope):
    values = (scope.get('config') or {}).get('site_ids', [])
    if not isinstance(values, list):
        return []
    return [int(value) for value in values if not isinstance(value, bool) and str(value).isdigit()]


def _require(actor, permission):
    if not actor.is_active or actor.user_type != 'internal' or not check_user_permission(actor, permission):
        raise PermissionDenied('请使用具备运营订货权限的内部账号。')
    scopes = get_permission_data_scopes(actor, permission)
    if not scopes:
        raise PermissionDenied('缺少运营订货的数据范围授权。')
    return scopes


def orders_for(actor, permission=VIEW):
    scopes = _require(actor, permission)
    rows = OperatingOrder.objects.filter(tenant=actor.tenant)
    if any(s['scope_type'] == DataScope.ScopeType.ALL for s in scopes):
        return rows
    allowed = Q(pk__in=[])
    for scope in scopes:
        if scope['scope_type'] == DataScope.ScopeType.OWN:
            allowed |= Q(created_by=actor)
        elif scope['scope_type'] == DataScope.ScopeType.CUSTOM:
            allowed |= Q(country_id__in=country_ids(scope))
    return rows.filter(allowed).distinct()


def procurement_orders_for(actor, permission=SUPPLY_VIEW):
    """An unassigned demand needs its own country/creator authorization."""
    if not actor.is_active:
        raise PermissionDenied('请使用有效的采购账号。')
    require_internal_supply_permission(actor, permission)
    scopes = get_permission_data_scopes(actor, permission)
    rows = OperatingOrder.objects.filter(tenant=actor.tenant, status='submitted')
    if any(s['scope_type'] == DataScope.ScopeType.ALL for s in scopes):
        return rows
    allowed = Q(pk__in=[])
    for scope in scopes:
        if scope['scope_type'] == DataScope.ScopeType.OWN:
            allowed |= Q(created_by=actor)
        elif scope['scope_type'] == DataScope.ScopeType.CUSTOM:
            allowed |= Q(country_id__in=country_ids(scope))
    return rows.filter(allowed).distinct()


def order_for(actor, pk, *, procurement=False, permission=None):
    if procurement:
        rows = procurement_orders_for(actor, permission or SUPPLY_VIEW)
    else:
        rows = orders_for(actor, permission or MANAGE)
    obj = rows.filter(pk=pk).select_related('country').first()
    if not obj:
        raise NotFound('运营订货单不存在或不在授权范围。')
    return obj


def _country(actor, pk):
    scopes = _require(actor, MANAGE)
    obj = services._master(CountrySiteMaster, actor, pk, status='active')
    if any(s['scope_type'] in [DataScope.ScopeType.ALL, DataScope.ScopeType.OWN] for s in scopes):
        return obj
    if any(obj.pk in country_ids(s)
           for s in scopes if s['scope_type'] == DataScope.ScopeType.CUSTOM):
        return obj
    raise PermissionDenied('国家不在运营订货授权范围内。')


def allocated(line):
    return line.purchase_allocations.filter(purchase_line__is_active=True).exclude(
        purchase_line__order__status='cancelled').aggregate(total=Sum('allocated_quantity'))['total'] or 0


def visible_calculation(actor, calculation):
    if actor and calculation:
        from apps.commerce.country_decisions import permission_signature
        if calculation.get('permission_signature') != permission_signature(actor):
            return {'restricted': True, 'notice': '当前账号数据授权已变化，历史计算依据不可读取；单据数量仍按原单保存。'}
    return calculation


def snapshot(obj, actor=None):
    rows = list(obj.lines.filter(is_active=True).select_related('sku__spu__category_node'))
    quantities = dict(OperatingAllocation.objects.filter(operating_line__in=rows, purchase_line__is_active=True)
        .exclude(purchase_line__order__status='cancelled').values('operating_line_id')
        .annotate(total=Sum('allocated_quantity')).values_list('operating_line_id', 'total'))
    calculation = visible_calculation(actor, obj.calculation_snapshot)
    return {'id': obj.pk, 'number': obj.number, 'country_id': obj.country_id,
            'country_code': obj.country_code_snapshot, 'country_name': obj.country.name,
            'source_kind': obj.source_kind, 'status': obj.status, 'notes': obj.notes,
            'campaign': obj.campaign, 'demand_start': str(obj.demand_start) if obj.demand_start else None,
            'demand_end': str(obj.demand_end) if obj.demand_end else None, 'plan_revision': obj.plan_revision,
            'order_date': str(obj.order_date), 'version': obj.version, 'total_quantity': sum(r.quantity for r in rows),
            'calculation_snapshot': calculation,
            'lines': [{'id': r.pk, 'sku_id': r.sku_id, 'sku': r.sku_code_snapshot,
                       'legacy_sku_code': r.sku.legacy_sku_code or '',
                       'product_name': r.product_name_snapshot,
                       'product_details': product_details(r.sku),
                       'quantity': r.quantity,
                       'allocated_quantity': quantities.get(r.pk, 0), 'remaining_quantity': r.quantity - quantities.get(r.pk, 0)} for r in rows]}


def _rows(actor, obj, rows):
    ids = [r['sku_id'] for r in rows]
    if not rows or len(set(ids)) != len(ids):
        raise ValidationError('运营订货单须有商品明细，每个 SKU 只填写一行。')
    for row in rows:
        sku = services.require_orderable_sku(services._master(ProductSKU, actor, row['sku_id'], is_active=True))
        OperatingOrderLine.objects.create(tenant=actor.tenant, created_by=actor, order=obj, sku=sku,
            sku_code_snapshot=sku.sku_code, product_name_snapshot=sku.product_name,
            quantity=services._positive_int(row['quantity']))


def _calculation(actor, payload, current=None):
    if payload['source_kind'] == 'new_goods':
        return {}
    preview = OperatingSuggestion.objects.filter(tenant=actor.tenant, created_by=actor,
        token=payload.get('preview_token', ''), country_id=payload['country_id'], expires_at__gt=timezone.now()).first()
    if not preview:
        raise ValidationError('周期或季节订货须先生成当前账号的有效建议，并核对数量。')
    _require_current_demand_basis(preview.snapshot)
    edited_id = preview.snapshot.get('edited_order_id')
    if edited_id and (current is None or current.pk != edited_id):
        raise ValidationError('这份建议仅用于修改原草稿，不能用于另建或修改其他单据。')
    if current is None or current.calculation_snapshot.get('preview_token') != preview.token:
        # Tenant serialization makes preview consumption and demand reservation atomic.
        if OperatingOrder.objects.filter(tenant_id=actor.tenant_id).exclude(status='cancelled').exclude(
                pk=current.pk if current else None).filter(calculation_snapshot__preview_token=preview.token).exists():
            raise ValidationError('此建议已生成有效运营订货单，请查看原单或重新计算，避免重复订货。')
        from apps.commerce.supply_pipeline import open_demand
        _, signature = open_demand(actor, preview.country, [r['sku_id'] for r in preview.snapshot['lines']],
                                   exclude_order_id=edited_id)
        if signature != preview.snapshot.get('open_demand_signature'):
            raise ValidationError('开放运营需求已变化，请刷新建议后复核，避免重复订货。')
    from apps.commerce.country_decisions import permission_signature
    if preview.snapshot.get('permission_signature') != permission_signature(actor):
        raise PermissionDenied('计算依据的数据授权已变化，请重新生成建议。')
    eligible = {r['sku_id'] for r in preview.snapshot['lines'] if r['suggested_quantity'] is not None}
    if any(r['sku_id'] not in eligible for r in payload['lines']):
        raise ValidationError('选中商品缺少有效库存/销量依据；新货请采用手工订货。')
    return {**preview.snapshot, 'operator_reviewed_quantities': payload['lines'], 'preview_token': preview.token}


def _require_current_demand_basis(snapshot):
    if snapshot.get('demand_basis') != 'direct_and_bundle_snapshot_v1':
        raise ValidationError('补货已纳入组合销量折算，请重新生成建议并保存草稿。')


@transaction.atomic
def save_order(actor, payload, key, pk=None):
    from apps.supply_chain.numbering import number_for
    _require(actor, MANAGE)
    services._tenant_lock(actor)
    obj = order_for(actor, pk) if pk else OperatingOrder.objects.filter(tenant=actor.tenant, creation_key=services._key(key)).first()
    if obj:
        order_for(actor, obj.pk)
        if pk is None:
            return services._matching_replay(obj, services.request_hash(payload))
        if services._prior_event(actor, obj, 'draft_updated', key, payload):
            return obj
        services._version(obj, payload['expected_version'])
        if obj.status != 'draft':
            raise ValidationError('已提交或已取消的运营需求不能修改。')
    country = _country(actor, payload['country_id'])
    if payload['order_date'] > business_date():
        raise ValidationError('运营订货日期不能晚于今天。')
    calculation = (_calculation(actor, payload, obj if pk else None) if pk is None or payload.get('preview_token')
                   or (obj and obj.source_kind != payload['source_kind']) else obj.calculation_snapshot)
    if payload['source_kind'] != 'new_goods':
        _require_current_demand_basis(calculation)
    if obj and not payload.get('preview_token') and payload['source_kind'] != 'new_goods':
        old_ids = set(obj.lines.filter(is_active=True).values_list('sku_id', flat=True))
        if country.pk != obj.country_id or any(r['sku_id'] not in old_ids for r in payload['lines']):
            raise ValidationError('更换国家或新增商品时，请重新生成库销比建议。')
        calculation = {**calculation, 'operator_reviewed_quantities': payload['lines']}
    with domain_write():
        if obj is None:
            obj = OperatingOrder.objects.create(tenant=actor.tenant, created_by=actor,
                number=number_for(actor, 'operating_order', f'OP-{business_date():%Y%m%d}-{uuid4().hex[:12].upper()}', country.country_code.upper()), country=country,
                country_code_snapshot=country.country_code.upper(), source_kind=payload['source_kind'],
                order_date=payload['order_date'], notes=payload['notes'], calculation_snapshot=calculation,
                campaign=payload.get('campaign', ''), demand_start=payload.get('demand_start'),
                demand_end=payload.get('demand_end'), plan_revision=payload.get('plan_revision', ''),
                creation_key=key, request_hash=services.request_hash(payload))
        else:
            for row in obj.lines.filter(is_active=True):
                row.is_active = False; row.save()
            obj.country, obj.country_code_snapshot = country, country.country_code.upper()
            obj.source_kind, obj.order_date, obj.notes = payload['source_kind'], payload['order_date'], payload['notes']
            obj.calculation_snapshot, obj.version = calculation, obj.version + 1
            for field in ('campaign', 'demand_start', 'demand_end', 'plan_revision'):
                if field in payload:
                    setattr(obj, field, payload[field])
            obj.save()
        _rows(actor, obj, payload['lines'])
        services._event(actor, obj, 'draft_updated' if pk else 'created', key, payload,
                        audit={'snapshot': snapshot(obj)})
    return obj


@transaction.atomic
def action(actor, pk, payload, key, target):
    _require(actor, MANAGE)
    services._tenant_lock(actor)
    obj = order_for(actor, pk)
    if services._prior_event(actor, obj, target, key, payload):
        return obj
    services._version(obj, payload['expected_version'])
    if (target == 'submitted' and obj.status != 'draft') or obj.status == 'cancelled':
        raise ValidationError('当前单据状态不支持此操作。')
    if target == 'cancelled' and any(allocated(r) for r in obj.lines.filter(is_active=True)):
        raise ValidationError('已有有效采购分配，不能取消运营需求；先处理采购草稿。')
    _country(actor, obj.country_id)
    if target == 'submitted' and obj.source_kind != 'new_goods':
        _require_current_demand_basis(obj.calculation_snapshot)
    for row in obj.lines.filter(is_active=True):
        sku = services._master(ProductSKU, actor, row.sku_id, is_active=True)
        if target == 'submitted':
            services.require_orderable_sku(sku)
    with domain_write():
        obj.status, obj.version = target, obj.version + 1
        obj.save()
        services._event(actor, obj, target, key, payload)
    return obj


@transaction.atomic
def split(actor, pk, payload, key):
    services._internal(actor)
    services._tenant_lock(actor)
    obj = order_for(actor, pk, procurement=True, permission=SUPPLY_MANAGE)
    previous = services._prior_event(actor, obj, 'purchase_split', key, payload)
    if previous:
        order = services._order(actor, previous.payload['purchase_order_id'])
        return obj, order
    services._version(obj, payload['expected_version'])
    ids = [r['operating_line_id'] for r in payload['lines']]
    if len(set(ids)) != len(ids):
        raise ValidationError('运营来源行不能重复。')
    lines = {r.pk: r for r in obj.lines.filter(is_active=True)}
    converted = []
    for row in payload['lines']:
        line = lines.get(row['operating_line_id'])
        if not line or row['quantity'] > line.quantity - allocated(line):
            raise ValidationError('来源行无效或拆单数量超过剩余需求。')
        converted.append({'sku_id': line.sku_id, 'quantity': row['quantity'],
            **({'unit_price': row['unit_price']} if 'unit_price' in row else {}),
            'operating_sources': [{'system': 'sales_management', 'order_id': str(obj.pk), 'line_id': str(line.pk),
                                  'quantity': row['quantity'], 'operating_line_id': line.pk}]})
    order = services.create_purchase_order(actor, {'supplier_id': payload['supplier_id'], 'country_id': obj.country_id,
        'source_kind': 'operating', 'order_date': business_date(), 'reference_number': payload['reference_number'],
        'notes': payload['notes'], 'lines': converted}, idempotency_key='op-split-' + services.request_hash({'pk': pk, 'key': key}))
    with domain_write():
        obj.version += 1
        obj.save()
        services._event(actor, obj, 'purchase_split', key, payload, audit={'purchase_order_id': order.pk,
            'lines': [{'operating_line_id': r['operating_line_id'], 'quantity': r['quantity']} for r in payload['lines']]})
    return obj, order


def demand_quantity(sales, ratio, stock):
    from apps.commerce.country_decisions import suggestion_quantity
    return suggestion_quantity(sales, ratio, stock)


@transaction.atomic
def preview(actor, payload, key):
    from apps.commerce.country_decisions import country_for, skus_for, decision_rows, NOTICE, permission_signature
    from apps.commerce.supply_pipeline import open_demand
    _require(actor, MANAGE)
    services._tenant_lock(actor)
    country = _country(actor, payload['country_id'])
    country_for(actor, country.pk)
    edited_id = payload.get('exclude_operating_order_id')
    if edited_id:
        edited = order_for(actor, edited_id)
        if edited.status != 'draft':
            raise ValidationError('仅编辑本人有权维护的草稿时可排除本单预留量。')
    token = services.request_hash({'actor': actor.pk, 'tenant': actor.tenant_id, 'key': services._key(key)})
    previous = OperatingSuggestion.objects.filter(token=token).first()
    digest = services.request_hash(payload)
    if previous:
        _require_current_demand_basis(previous.snapshot)
        if previous.snapshot.get('permission_signature') != permission_signature(actor):
            raise PermissionDenied('数据授权已变化，旧建议不能重放，请重新计算。')
        if previous.snapshot['request_hash'] != digest:
            raise ValidationError('建议幂等键不能用于不同输入。')
        return {'preview_token': previous.token, **previous.snapshot}
    start, end = payload['sales_start'], payload['sales_end']
    if start > end or end >= business_date() or (end - start).days > 365:
        raise ValidationError('销量周期须为已完成日期范围，最多 366 天。')
    ids = payload['sku_ids']
    if len(set(ids)) != len(ids):
        raise ValidationError('建议商品不能重复。')
    skus = list(skus_for(actor, country).filter(pk__in=ids).select_related('spu__category_node'))
    if len(skus) != len(ids):
        raise ValidationError('商品不存在或不在库存商品授权范围内。')
    days = int(payload.get('sales_window_days') or (end - start).days + 1)
    target_days = payload.get('target_days') or max(1, int((payload['target_stock_sales_ratio'] * days).to_integral_value(rounding=ROUND_CEILING)))
    ratio = None if payload.get('sales_window_days') else payload['target_stock_sales_ratio']
    rows = decision_rows(actor, country, skus, target_days=target_days, window_days=days,
        end_date=None if payload.get('sales_window_days') else end, ratio=ratio,
        include_in_transit=payload['include_in_transit'], windows=(days,), exclude_order_id=edited_id)
    result = []
    for row in rows:
        observed = row['sales_windows'][0]
        result.append({**row, 'sales_quantity': observed['units'],
            'in_transit_stock': str(row['pipeline']['effective_incoming']) if row['pipeline']['authorized'] else None,
            'issues': sorted(set(row['issues'] + ['refunds_not_deducted']))})
    _, signature = open_demand(actor, country, ids, exclude_order_id=edited_id)
    data = {'demand_basis': 'direct_and_bundle_snapshot_v1',
        'formula': 'max(0, ceil(普通商品需求件数（直接销量＋组合折算） × 目标库销比 - WMS可用库存 - 按期有效到货 - 开放运营需求))',
        'parameters': payload, 'needs_review': True, 'permission_signature': permission_signature(actor), 'edited_order_id': edited_id,
        'stock_formula': 'available_qty；WMS在途不相加、locked不重复扣减；本地入库不增加WMS库存',
        'notice': NOTICE, 'country_stock_basis': 'warehouse.country_code', 'sales_date_basis': 'store.timezone',
        'sales_start_date': str(start), 'sales_end_date_inclusive': str(end),
        'generated_at': timezone.now().isoformat(), 'open_demand_signature': signature, 'lines': result}
    import json
    data = json.loads(json.dumps({**data, 'request_hash': digest}, default=str, ensure_ascii=False))
    with domain_write():
        suggestion = OperatingSuggestion.objects.create(tenant=actor.tenant, created_by=actor, country=country,
            token=token, snapshot=data, expires_at=timezone.now() + timedelta(hours=2))
    return {'preview_token': suggestion.token, **data}
