"""Deterministic fee allocation and append-only cost observations.

The procurement amount basis is shared by prices and fees. Settlement references
do not execute a payment and cost adjustments do not change receipt quantities.
"""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP, localcontext

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, F, IntegerField, Sum, When
from rest_framework.exceptions import NotFound, PermissionDenied

from . import logistics, services, shipments, dispatch_allocations
from .models import (CostAdjustment, CostEntry, CostVersion, FeeRecord, FeeRevision,
                     InboundOrder, InternalStockReceiptLine, PurchaseOrder, SettlementRecord,
                     SettlementRevision, ShipmentLine, SupplierShipment, BusinessEvent, PayeeAccount, domain_write)
from .cost_models import FeeRevisionItem, PaymentRecord, PaymentApplication
from .payment_item_models import PaymentItem
from .permissions import MANAGE, VIEW, internal_orders
from .supplier_products import safe_image_url, shipment_line_product_details

ZERO = Decimal('0')
MONEY = Decimal('0.0001')
MEASURE = Decimal('0.000001')
UNIT = Decimal('0.00000001')
FEE_LABELS = {'shipment': '国内发货费用（集货或装柜）', 'batch': '货运费用', 'inbound': '清货费用'}


def decimal(value, *, places=4, nullable=False):
    if value is None and nullable:
        return None
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result != result.quantize(Decimal(1).scaleb(-places)):
            raise ValueError()
        return result
    except Exception as exc:
        raise ValidationError('金额或计量必须是精度范围内的非负数。') from exc


def money(value):
    return None if value is None else value.quantize(MONEY, rounding=ROUND_HALF_UP)


def text_number(value, quantum=MONEY):
    with localcontext() as ctx:
        ctx.prec = 60
        return None if value is None else format(value.quantize(quantum, rounding=ROUND_HALF_UP), 'f')


def target_for(actor, kind, pk, permission=VIEW):
    # This internal-only check must precede shipment_for's supplier-aware helper.
    internal_orders(actor, PurchaseOrder.objects.none(), permission)
    if kind == 'shipment':
        return shipments.shipment_for(actor, pk, permission)
    if kind == 'batch':
        return logistics.batch_for(actor, pk, permission)
    if kind == 'inbound':
        return logistics.inbound_for(actor, pk, permission)
    raise NotFound('费用单据类型不存在。')


def _payee_owner(kind, obj):
    if kind == 'domestic_freight':
        if not obj.domestic_carrier_id:
            raise ValidationError('请先指定国内承运商。')
        return {'freight_company_id': obj.domestic_carrier_id}
    if kind == 'supplier':
        return {'supplier_id': obj.pk}
    if kind == 'purchase':
        return {'supplier_id': obj.supplier_id}
    if kind == 'freight_company':
        return {'freight_company_id': obj.pk}
    if kind == 'shipment':
        if not obj.order.supplier_id:
            raise ValidationError('该发货单未绑定供应商，无法维护收款账户。')
        return {'supplier_id': obj.order.supplier_id}
    if kind == 'batch':
        if not obj.freight_company_id:
            raise ValidationError('该发运批次未绑定货运公司，无法维护收款账户。')
        return {'freight_company_id': obj.freight_company_id}
    if kind == 'inbound':
        if not obj.batch.freight_company_id:
            raise ValidationError('该入库单所属批次未绑定货运公司，无法维护收款账户。')
        return {'freight_company_id': obj.batch.freight_company_id}
    raise ValidationError('该单据类型不支持收款账户。')


def _payee_context(actor, kind, pk, permission=VIEW):
    if kind == 'purchase':
        obj = _payment_owner(actor, 'purchase', pk, permission)
    elif kind in ('shipment', 'batch', 'inbound', 'domestic_freight'):
        obj = target_for(actor, 'shipment' if kind == 'domestic_freight' else kind, pk, permission)
    elif kind == 'supplier':
        from .archives import allowed_suppliers
        obj = allowed_suppliers(actor, permission).filter(pk=pk).first()
        if obj is None:
            raise NotFound('供应商账户档案不存在或无权访问。')
    elif kind == 'freight_company':
        from .archives import freight_scope
        obj = freight_scope(actor, permission).filter(pk=pk).first()
        if obj is None:
            raise NotFound('货运公司账户档案不存在或无权访问。')
    else:
        raise NotFound('收款账户上下文不存在。')
    return obj, _payee_owner(kind, obj)


def _payee_data(row):
    return {'id': row.pk, 'nature': row.nature, 'account_name': row.account_name,
        'account_holder': row.account_holder, 'bank_name': row.bank_name,
        'account_number': row.account_number, 'active': row.active, 'version': row.version}


def _mask_account_number(value):
    value = str(value or '')
    return ('*' * max(0, len(value) - 4)) + value[-4:] if value else ''


def _settlement_allocation_data(revision):
    allocations = revision.payee_allocations or []
    allocated = sum((Decimal(str(item['amount'])) for item in allocations), ZERO)
    unclassified = max(revision.recorded_amount - allocated, ZERO)
    natures = {item.get('account_snapshot', {}).get('nature') for item in allocations
        if Decimal(str(item['amount'])) > ZERO}
    nature = ('unclassified' if not allocations or not natures else
        next(iter(natures)) if len(natures) == 1 and unclassified == ZERO else 'mixed')
    return allocations, nature, unclassified


def _visible_settlement_allocations(revision):
    allocations, _, _ = _settlement_allocation_data(revision)
    return [{**item, 'account_snapshot': {**item.get('account_snapshot', {}),
        'account_number': _mask_account_number(item.get('account_snapshot', {}).get('account_number'))}}
        for item in allocations]


def payee_accounts(actor, kind, pk):
    obj, owner = _payee_context(actor, kind, pk, VIEW)
    rows = list(PayeeAccount.objects.filter(tenant_id=actor.tenant_id,
        **owner).order_by('id')[:101])
    if len(rows) > 100:
        raise ValidationError('该业务对象收款账户超过100个，请先整理账户档案。')
    try:
        _payee_context(actor, kind, pk, MANAGE)
        can_manage = True
    except (PermissionDenied, NotFound):
        can_manage = False
    data = [_payee_data(row) for row in rows]
    if not can_manage:
        for item in data:
            item['account_number'] = _mask_account_number(item['account_number'])
    return data


@transaction.atomic
def create_payee_account(actor, kind, pk, payload, request_key):
    services._internal(actor)
    services._tenant_lock(actor)
    obj, owner = _payee_context(actor, kind, pk, MANAGE)
    fingerprint = {**payload, 'owner_kind': kind, 'owner_id': next(iter(owner.values()))}
    replay = BusinessEvent.objects.filter(tenant_id=actor.tenant_id, aggregate_type='payeeaccount',
        action='payee_account_created', request_key=services._key(request_key)).first()
    if replay:
        services._matching_replay(replay, services.request_hash(fingerprint))
        row = PayeeAccount.objects.filter(pk=replay.aggregate_id, tenant_id=actor.tenant_id, **owner).first()
        if not row:
            raise ValidationError('幂等记录对应账户不属于当前业务对象。')
        return _payee_data(row)
    if PayeeAccount.objects.filter(tenant_id=actor.tenant_id, **owner).count() >= 100:
        raise ValidationError('每个业务对象最多维护100个收款账户。')
    with domain_write():
        row = PayeeAccount.objects.create(tenant=actor.tenant, created_by=actor, **owner,
            nature=payload['nature'], account_name=payload['account_name'].strip(),
            account_holder=payload['account_holder'].strip(), bank_name=payload['bank_name'].strip(),
            account_number=payload['account_number'].strip(), active=payload.get('active', True))
        services._event(actor, row, 'payee_account_created', request_key, fingerprint,
            audit={'account_snapshot': _payee_data(row)})
    return _payee_data(row)


@transaction.atomic
def update_payee_account(actor, kind, pk, account_id, payload, request_key):
    services._internal(actor)
    services._tenant_lock(actor)
    obj, owner = _payee_context(actor, kind, pk, MANAGE)
    row = PayeeAccount.objects.select_for_update().filter(tenant_id=actor.tenant_id,
        pk=account_id, **owner).first()
    if not row:
        raise NotFound('收款账户不可访问。')
    fingerprint = {**payload, 'owner_kind': kind, 'owner_id': next(iter(owner.values())), 'account_id': row.pk}
    if services._prior_event(actor, row, 'payee_account_updated', request_key, fingerprint):
        return _payee_data(row)
    if payload.get('expected_version') != row.version:
        raise ValidationError('收款账户已变化，请重新加载。')
    with domain_write():
        for field in ('nature', 'account_name', 'account_holder', 'bank_name', 'account_number', 'active'):
            value = payload.get(field, getattr(row, field))
            setattr(row, field, value.strip() if isinstance(value, str) else value)
        row.version += 1
        row.save()
        services._event(actor, row, 'payee_account_updated', request_key, fingerprint,
            audit={'account_snapshot': _payee_data(row)})
    return _payee_data(row)


def targets(actor, kind):
    orders = internal_orders(actor, PurchaseOrder.objects.all())
    if kind == 'shipment':
        return SupplierShipment.objects.filter(tenant=actor.tenant, order__in=orders, status='submitted').select_related('order__country', 'order__supplier', 'domestic_carrier')
    if kind == 'batch':
        return logistics.batches_for(actor).filter(status='active').select_related('country', 'freight_company')
    if kind == 'inbound':
        return InboundOrder.objects.filter(tenant=actor.tenant, batch__in=logistics.batches_for(actor)).select_related('batch__country', 'batch__freight_company')
    raise NotFound('费用单据类型不存在。')


def prepare_target_parties(kind, rows):
    """Only page-local parties; no line/product hydration or per-row queries."""
    from collections import defaultdict
    from .models import DispatchMembership
    for tenant_id in {row.tenant_id for row in rows}:
        scoped = [row for row in rows if row.tenant_id == tenant_id]
        ids = [row.pk if kind != 'inbound' else row.batch_id for row in scoped]
        lookup = 'shipment_id__in' if kind == 'shipment' else 'batch_id__in'
        members = DispatchMembership.objects.filter(tenant_id=tenant_id, active_guard=True,
            **{lookup: ids}).values_list('shipment_id', 'batch_id',
                'shipment__order__supplier__name', 'batch__freight_company__name').order_by('pk')
        suppliers, carriers = defaultdict(dict), defaultdict(dict)
        for shipment_id, batch_id, supplier, carrier in members:
            identity = shipment_id if kind == 'shipment' else batch_id
            if supplier:
                suppliers[identity][supplier] = None
            if carrier:
                carriers[identity][carrier] = None
        for row in scoped:
            identity = row.batch_id if kind == 'inbound' else row.pk
            names = [row.order.supplier.name] if kind == 'shipment' else list(suppliers[identity])
            company = list(carriers[identity]) if kind == 'shipment' else [
                (row.batch if kind == 'inbound' else row).freight_company.name]
            row._cost_parties = {'supplier_names': ', '.join(sorted(names)),
                'freight_company_names': ', '.join(sorted(company))}


def target_data(kind, obj):
    if not hasattr(obj, '_cost_parties'):
        prepare_target_parties(kind, [obj])
    country = obj.order.country_code_snapshot if kind == 'shipment' else (
        obj.batch.country_code_snapshot if kind == 'inbound' else obj.country_code_snapshot)
    country_master = obj.order.country if kind == 'shipment' else (
        obj.batch.country if kind == 'inbound' else obj.country)
    domestic = ({'domestic_carrier_id': obj.domestic_carrier_id,
        'domestic_carrier_name': obj.domestic_carrier.name if obj.domestic_carrier_id else '',
        'domestic_tracking_number': obj.domestic_tracking_number} if kind == 'shipment' else {})
    from .payment_process import source_links
    return {'source_links': source_links(kind, obj), 'kind': kind, 'id': obj.pk, 'number': obj.number, 'country_code': country, **domestic, **obj._cost_parties,
            'country_name': country_master.name,
            'version': obj.version, 'stage': obj.stage if kind == 'batch' else obj.status,
            **getattr(obj, '_payment_projection', {})}


def prepare_target_financials(kind, rows):
    if kind not in ('shipment', 'batch', 'inbound') or not rows:
        return
    ids = [row.pk for row in rows]
    owner_field = f'{kind}_id'
    payments = {item[owner_field]: item['total'] or ZERO for item in PaymentRecord.objects.filter(
        tenant_id=rows[0].tenant_id, **{f'{kind}__in': rows}, purpose='goods', reverses__isnull=True,
        reversal__isnull=True).values(owner_field).annotate(total=Sum('amount'))}
    opening_rows = (SettlementRecord.objects.filter(tenant_id=rows[0].tenant_id,
        **{f'{kind}__in': rows}).select_related('current_revision') if kind in ('shipment', 'batch') else [])
    opening = {getattr(item, f'{kind}_id'): item.current_revision.recorded_amount
        for item in opening_rows if item.current_revision_id}
    applied = {item['shipment_id']: item['total'] or ZERO for item in PaymentApplication.objects.filter(
        tenant_id=rows[0].tenant_id, shipment_id__in=ids, reverses__isnull=True,
        reversal__isnull=True).values('shipment_id').annotate(total=Sum('amount'))} if kind == 'shipment' else {}
    due = {}
    if kind == 'shipment':
        valid_shipments = {row.pk for row in rows if row.status == 'submitted'}
        line_data = ShipmentLine.objects.filter(tenant_id=rows[0].tenant_id, shipment_id__in=ids,
            is_active=True).values('shipment_id').annotate(total=Sum(F('unit_price') * F('quantity')),
                missing=Sum(Case(When(unit_price__isnull=True, then=1), default=0, output_field=IntegerField())))
        for item in line_data:
            if item['shipment_id'] in valid_shipments:
                due[item['shipment_id']] = None if item['missing'] else item['total'] or ZERO
    elif kind == 'batch':
        active_batches = {row.pk for row in rows if row.status == 'active'}
        for item in FeeRecord.objects.filter(tenant_id=rows[0].tenant_id, batch_id__in=ids).select_related('current_revision'):
            revision = item.current_revision
            if item.batch_id in active_batches and revision and revision.state == 'confirmed':
                due[item.batch_id] = revision.amount
    else:
        active_inbounds = {row.pk for row in rows if row.batch.status == 'active'}
        for item in FeeRecord.objects.filter(tenant_id=rows[0].tenant_id, inbound_id__in=ids).select_related('current_revision'):
            revision = item.current_revision
            if item.inbound_id in active_inbounds and revision and revision.state == 'confirmed':
                due[item.inbound_id] = revision.amount
    from .models import PurchaseContract
    taxes = dict(PurchaseContract.objects.filter(tenant_id=rows[0].tenant_id, shipment_id__in=ids, status='issued').values_list('shipment_id', 'settlement_tax_amount')) if kind == 'shipment' else {}
    for row in rows:
        oid = row.pk
        d = due.get(oid)
        if d is not None: d += taxes.get(oid, ZERO)
        opening_amount = opening.get(oid, ZERO)
        paid = opening_amount + payments.get(oid, ZERO)
        use = applied.get(oid, ZERO)
        row._payment_projection = {'due_amount': text_number(d), 'opening_amount': text_number(opening_amount),
            'paid_amount': text_number(paid), 'applied_amount': text_number(use),
            'remaining_amount': None if d is None else text_number(max(d-paid-use, ZERO))}


def fee_gate(kind, obj):
    if kind == 'shipment':
        return (obj.status == 'submitted' and (obj.collection_arrived or obj.delivery_mode == 'factory_loading'),
                '送集货中心须提交并标记集货到仓；货柜上门装载须先提交发货单。')
    if kind == 'batch':
        return (obj.status == 'active' and obj.stage != 'unmarked', '请先标记有效批次开船。')
    checked = obj.lines.exists() and not obj.lines.filter(received_quantity__isnull=True).exists()
    return (checked and obj.batch.status == 'active', '请先逐行填写实收数量，再维护清货费用。')


def source_lines(kind, obj):
    query = ShipmentLine.objects.filter(tenant=obj.tenant, is_active=True)
    if kind == 'shipment':
        query = query.filter(shipment=obj)
    elif kind == 'batch':
        query = query.filter(pk__in=dispatch_allocations.batch_quantities(obj))
    else:
        query = query.filter(inbound_lines__inbound=obj)
    return list(query.select_related('sku', 'shipment').order_by('pk'))


def measurements(kind, obj, overrides=None):
    lines = source_lines(kind, obj)
    details_by_line = shipment_line_product_details(lines)
    received = dict(obj.lines.values_list('shipment_line_id', 'received_quantity')) if kind == 'inbound' else {}
    batch_qty = dispatch_allocations.batch_quantities(obj) if kind == 'batch' else {}
    overrides = overrides or []
    ids = [row['shipment_line_id'] for row in overrides]
    if len(set(ids)) != len(ids) or not set(ids).issubset({line.pk for line in lines}):
        raise ValidationError('分摊计量行重复或不属于本单据。')
    by_id = {row['shipment_line_id']: row for row in overrides}
    result = []
    for line in lines:
        qty = received.get(line.pk) if kind == 'inbound' else batch_qty.get(line.pk, line.quantity)
        sku = line.sku
        unit_volume, volume_source = sku.package_volume, 'sku_volume'
        if unit_volume is None:
            dimensions = [sku.package_length_cm, sku.package_width_cm, sku.package_height_cm]
            if all(value is not None and value > 0 for value in dimensions):
                unit_volume = dimensions[0] * dimensions[1] * dimensions[2] / Decimal('1000000')
                volume_source = 'sku_dimensions'
        unit_weight = None if sku.package_weight is None else sku.package_weight / Decimal('1000')
        volume = None if unit_volume is None or qty is None else unit_volume * qty
        weight = None if unit_weight is None or qty is None else unit_weight * qty
        override = by_id.get(line.pk, {})
        weight_source = 'sku_weight'
        if override.get('volume_cbm') is not None:
            volume = decimal(override['volume_cbm'], places=6)
            volume_source = 'manual_total'
        if override.get('weight_kg') is not None:
            weight = decimal(override['weight_kg'], places=6)
            weight_source = 'manual_total'
        details = details_by_line.get(line.pk, {})
        result.append({'shipment_line_id': line.pk, 'sku': line.sku_code_snapshot,
            'legacy_sku_code': line.sku.legacy_sku_code or '',
            'product_details': {'image_url': details.get('image_url', '')},
            'image_preview_url': (f'/api/internal/supply-chain/v2/supplier-shipments/{line.shipment_id}/skus/{line.sku_id}/image/'
                if details.get('image_url') else ''),
            'product_name': line.product_name_snapshot, 'quantity': qty,
            'volume_cbm': text_number(volume, MEASURE), 'weight_kg': text_number(weight, MEASURE),
            'volume_source': volume_source, 'weight_source': weight_source,
            'sku_unit_volume_cbm': text_number(unit_volume, MEASURE),
            'sku_unit_weight_kg': text_number(unit_weight, MEASURE)})
    return result


def allocate(amount, rows, method, volume_percent):
    """Allocate integer money units; largest remainders then stable source ID."""
    amount = decimal(amount)
    percent = decimal(volume_percent, places=2)
    if method not in ('volume', 'weight', 'mixed') or percent > 100:
        raise ValidationError('请选择体积、重量或混合方式；体积占比须为 0–100。')
    if any(row['quantity'] is None for row in rows):
        raise ValidationError('未核对数量不能作为分摊依据。')
    participating = [row for row in rows if row['quantity'] > 0]
    if not participating and amount > 0:
        raise ValidationError('没有实收商品，不能分摊正数清货费用。')
    if amount == 0:
        return [{**row, 'amount': '0.0000'} for row in rows]
    with localcontext() as ctx:
        ctx.prec = 60
        volume_ratio = Decimal(1) if method == 'volume' else (ZERO if method == 'weight' else percent / 100)
        weight_ratio = 1 - volume_ratio
        for dimension, ratio, label in [('volume_cbm', volume_ratio, '体积'), ('weight_kg', weight_ratio, '重量')]:
            if ratio and any(row[dimension] is None or Decimal(row[dimension]) <= 0 for row in participating):
                raise ValidationError(f'分摊需要每个参与商品的正数{label}；请完善商品档案或填写本次实测总量。')
        volume_total = sum((Decimal(row['volume_cbm']) for row in participating), ZERO) if volume_ratio else ZERO
        weight_total = sum((Decimal(row['weight_kg']) for row in participating), ZERO) if weight_ratio else ZERO
        units = int(amount / MONEY)
        raw = {}
        for row in participating:
            share = ((volume_ratio * Decimal(row['volume_cbm']) / volume_total if volume_ratio else ZERO)
                     + (weight_ratio * Decimal(row['weight_kg']) / weight_total if weight_ratio else ZERO))
            raw[row['shipment_line_id']] = units * share
        assigned = {pk: int(value.to_integral_value(rounding=ROUND_FLOOR)) for pk, value in raw.items()}
        remainder = units - sum(assigned.values())
        ranking = sorted(raw, key=lambda pk: (-(raw[pk] - assigned[pk]), pk))
        for pk in ranking[:remainder]:
            assigned[pk] += 1
        return [{**row, 'amount': text_number(Decimal(assigned.get(row['shipment_line_id'], 0)) * MONEY)} for row in rows]


def fee_record(kind, obj):
    return FeeRecord.objects.filter(tenant=obj.tenant, **{kind: obj}).select_related('current_revision').first()


def fee_data(revision):
    if not revision:
        return None
    return {'id': revision.fee_id, 'revision_id': revision.pk, 'version': revision.sequence,
            'amount': text_number(revision.amount), 'state': revision.state, 'method': revision.method,
            'volume_percent': text_number(revision.volume_percent, Decimal('.01')),
            'billed_cbm': text_number(revision.billed_cbm, MEASURE), 'notes': revision.notes,
            'reason': revision.reason, 'allocations': revision.allocations,
            'item_breakdown': revision.item_breakdown, 'created_at': revision.created_at}


@transaction.atomic
def save_fee(actor, kind, pk, payload, key):
    services._internal(actor)
    services._tenant_lock(actor)
    obj = target_for(actor, kind, pk, MANAGE)
    if services._prior_event(actor, obj, 'fee_revised', key, payload):
        return obj
    services._version(obj, payload['expected_source_version'])
    allowed, explanation = fee_gate(kind, obj)
    if not allowed:
        raise ValidationError(explanation)
    if not payload['reason'].strip():
        raise ValidationError('请填写本次费用维护或更正原因。')
    record = fee_record(kind, obj)
    if payload['expected_version'] != (record.version if record else 0):
        raise ValidationError('费用版本已变化，请重新加载。')
    item_breakdown = None
    if kind in ('batch', 'inbound'):
        prior_breakdown = record.current_revision.item_breakdown if record and record.current_revision else []
        # Older clients may update the ordinary amount fields. Preserve the
        # existing mode and reject any amount that no longer matches its items.
        item_breakdown = payload.get('item_breakdown', prior_breakdown)
        if item_breakdown:
            if not prior_breakdown and (PaymentRecord.objects.filter(tenant_id=actor.tenant_id, **{kind: obj}, purpose='goods', fee_item__isnull=True, reverses__isnull=True, reversal__isnull=True).exists() or (kind == 'batch' and SettlementRecord.objects.filter(
                tenant_id=actor.tenant_id, batch=obj, current_revision__recorded_amount__gt=0).exists())):
                raise ValidationError('存在历史总费用或未归属项目的付款，需完成历史分配后才能启用分项费用。')
            seen, total, normalized = set(), ZERO, []
            for item in item_breakdown:
                item_id = int(item.get('fee_item_id') or 0)
                profile = PaymentItem.objects.filter(tenant_id=actor.tenant_id, pk=item_id).first()
                old = next((r for r in prior_breakdown if r.get('fee_item_id') == item_id), None)
                if profile and not old and (not profile.is_active or profile.party_type not in ['carrier', 'both']):
                    profile = None
                if not profile or item_id in seen:
                    raise ValidationError('费用分项必须选择不重复的启用中承运商项目。')
                seen.add(item_id)
                amount_item = decimal(item.get('amount'))
                nature = item.get('nature')
                if nature not in ('corporate', 'personal'):
                    raise ValidationError('请选择分项对公或对私性质。')
                paid_item = sum((p.amount for p in PaymentRecord.objects.filter(tenant_id=actor.tenant_id, **{kind: obj},
                    fee_item_id=item_id, reverses__isnull=True, reversal__isnull=True)), ZERO)
                if paid_item and (not old or old.get('nature') != nature or amount_item < paid_item):
                    raise ValidationError(f'{profile.name}已有付款，不可删除、改性质或调低至已付以下。')
                from .tax_calculation import rate_value, inclusive_tax
                # Existing fee amounts are payable gross amounts. Split tax; never add it again.
                if nature == 'personal':
                    rate = Decimal(0)
                elif 'tax_rate' in item:
                    rate = rate_value(item['tax_rate'])
                    if rate is None and payload['state'] == 'confirmed' and 'item_breakdown' in payload:
                        raise ValidationError(f'{profile.name}请明确填写税点，免税请填0。')
                elif old:
                    rate = rate_value(old.get('tax_rate'))
                else:
                    rate = profile.default_tax_rate
                tax_fields = inclusive_tax(amount_item, rate)
                total += amount_item
                frozen_name = old.get('name') if old else profile.name
                normalized.append({'fee_item_id': item_id, 'name': frozen_name, 'amount': text_number(amount_item),
                    'nature': nature, 'counts_as_cost': old.get('counts_as_cost', True) if old else profile.counts_as_cost, **tax_fields})
            paid_item_ids = set(PaymentRecord.objects.filter(tenant_id=actor.tenant_id, **{kind: obj},
                fee_item__isnull=False, reverses__isnull=True, reversal__isnull=True).values_list('fee_item_id', flat=True).distinct())
            if paid_item_ids - seen:
                raise ValidationError('已有有效付款的费用项目不能删除。')
            if decimal(payload['amount']) != total:
                raise ValidationError('费用总额必须等于所有分项金额之和。')
            item_breakdown = normalized
        elif prior_breakdown:
            if PaymentRecord.objects.filter(tenant_id=actor.tenant_id, **{kind: obj}, fee_item__isnull=False,
                reverses__isnull=True, reversal__isnull=True).exists():
                raise ValidationError('已有有效分项付款，不能切回总费用模式。')
    if kind == 'shipment':
        active_domestic = PaymentRecord.objects.filter(tenant_id=actor.tenant_id, shipment=obj,
            purpose='domestic_freight', reverses__isnull=True, reversal__isnull=True)
        paid_domestic = sum((row.amount for row in active_domestic), ZERO)
        if paid_domestic and (payload['state'] != 'confirmed' or decimal(payload['amount']) < paid_domestic):
            raise ValidationError('已有国内运费付款，费用不能改为暂估或调低至已付金额以下；请先冲销付款。')
    rows = measurements(kind, obj, payload.get('measurements'))
    allocation_amount = payload['amount']
    if item_breakdown:
        # All item amounts remain payable; only cost-marked items enter goods cost.
        allocation_amount = sum((decimal(item['amount']) for item in item_breakdown
            if item.get('counts_as_cost', True)), ZERO)
    allocations = allocate(allocation_amount, rows, payload['method'], payload['volume_percent'])
    cbm = decimal(payload.get('billed_cbm'), places=6, nullable=True)
    if kind == 'shipment' and cbm is not None:
        raise ValidationError('到集货点费用不设置货运或清货计费方数。')
    with domain_write():
        if record is None:
            record = FeeRecord.objects.create(tenant=actor.tenant, created_by=actor, **{kind: obj})
        else:
            record.version += 1
        revision = FeeRevision.objects.create(tenant=actor.tenant, created_by=actor, fee=record,
            sequence=record.version, amount=decimal(payload['amount']), state=payload['state'],
            method=payload['method'], volume_percent=decimal(payload['volume_percent'], places=2),
            billed_cbm=cbm, notes=payload.get('notes', ''), reason=payload['reason'], allocations=allocations,
            item_breakdown=(item_breakdown if item_breakdown is not None else (record.current_revision.item_breakdown if record.current_revision else [])))
        FeeRevisionItem.objects.bulk_create([
            FeeRevisionItem(revision=revision, fee_item_id=int(item['fee_item_id']),
                name=item['name'], amount=decimal(item['amount']))
            for item in revision.item_breakdown])
        record.current_revision = revision
        record.save()
        if kind == 'batch':
            obj.billed_cbm = cbm
        elif kind == 'inbound':
            obj.clearance_cbm = cbm
        obj.version += 1
        obj.save()
        services._event(actor, obj, 'fee_revised', key, payload,
                        audit={'fee_id': record.pk, 'fee_revision_id': revision.pk, 'allocations': allocations})
    return obj


def canonical(actor, kind, obj, permission=VIEW):
    if kind == 'inbound':
        return 'batch', logistics.batch_for(actor, obj.batch_id, permission)
    if kind == 'shipment':
        memberships = list(obj.dispatch_memberships.filter(active_guard=True))
        membership = memberships[0] if len(memberships) == 1 else None
        if membership:
            return 'batch', logistics.batch_for(actor, membership.batch_id, permission)
    return kind, obj


def inputs(kind, obj):
    lines = source_lines(kind, obj)
    inbound = InboundOrder.objects.filter(batch=obj).first() if kind == 'batch' else None
    inbound_rows = list(inbound.lines.order_by('shipment_line_id')) if inbound else []
    batch_qty = dispatch_allocations.batch_quantities(obj) if kind == 'batch' else {}
    source = {'kind': kind, 'id': obj.pk, 'status': obj.status,
        'lines': [{'id': line.pk, 'shipment_id': line.shipment_id, 'sku': line.sku_code_snapshot,
                   'quantity': batch_qty.get(line.pk, line.quantity), 'unit_price': text_number(line.unit_price),
                   'collection_arrived': line.shipment.collection_arrived} for line in lines],
        'inbound': None if not inbound else {'id': inbound.pk, 'status': inbound.status,
                   'receipt_ref': inbound.stock_receipt_ref,
                   'lines': [{'id': row.pk, 'shipment_line_id': row.shipment_line_id,
                              'received_quantity': row.received_quantity} for row in inbound_rows]}, 'fees': []}
    owners = [('shipment', shipment) for shipment in {line.shipment_id: line.shipment for line in lines}.values()]
    if kind == 'batch':
        owners.append(('batch', obj))
    if inbound:
        owners.append(('inbound', inbound))
    revisions = {}
    for owner_kind, owner in owners:
        record = fee_record(owner_kind, owner)
        revision = record.current_revision if record else None
        revisions[(owner_kind, owner.pk)] = revision
        source['fees'].append({'kind': owner_kind, 'id': owner.pk,
                              'revision_id': revision.pk if revision else None})
    source['dispatch_distribution'] = list(dispatch_allocations.active().filter(shipment_line_id__in=[line.pk for line in lines]).order_by('membership__batch_id', 'shipment_line_id').values('membership__batch_id', 'shipment_line_id', 'quantity'))
    from .tax_calculation import contract_cost_allocations
    contract_taxes = contract_cost_allocations({line.shipment_id for line in lines})
    if contract_taxes: source['contract_cost_taxes'] = contract_taxes
    source['fees'].sort(key=lambda row: (row['kind'], row['id']))
    return source, services.request_hash(source), lines, inbound, inbound_rows, revisions


def fee_amounts(kind, owner, revision, issues):
    if revision is None:
        issues.append(f'{owner.number}：{FEE_LABELS[kind]}未维护；无费用时也需确认零。')
        return {line.pk: None for line in source_lines(kind, owner)}
    current = {row['shipment_line_id']: row['quantity'] for row in measurements(kind, owner)}
    frozen = {row['shipment_line_id']: row['quantity'] for row in revision.allocations}
    if current != frozen:
        raise ValidationError(f'{owner.number}：分摊数量已变化，请重新维护{FEE_LABELS[kind]}。')
    if revision.state != 'confirmed':
        issues.append(f'{owner.number}：{FEE_LABELS[kind]}仍为暂估。')
    return {row['shipment_line_id']: Decimal(row['amount']) for row in revision.allocations}


def entry_data(entry, details=None):
    details = details or {'image_url': safe_image_url(entry.shipment_line.sku.image_url, entry.tenant_id)}
    image_url = details.get('image_url', '')
    result = {'shipment_line_id': entry.shipment_line_id, 'receipt_line_id': entry.receipt_line_id,
              'sku': entry.shipment_line.sku_code_snapshot,
              'legacy_sku_code': entry.shipment_line.sku.legacy_sku_code or '', 'quantity': entry.quantity,
              'product_details': {'image_url': image_url},
              'image_preview_url': (f'/api/internal/supply-chain/v2/supplier-shipments/{entry.shipment_line.shipment_id}/skus/{entry.shipment_line.sku_id}/image/'
                  if image_url else ''),
              'received_quantity': entry.received_quantity}
    for name in ('goods_amount', 'goods_tax_amount', 'collection_fee', 'freight_fee', 'clearance_fee', 'received_goods_amount',
                 'received_collection_fee', 'received_freight_fee', 'shipped_total', 'received_total', 'pending_total'):
        result[name] = text_number(getattr(entry, name))
    for name in ('shipped_unit_cost', 'received_unit_cost'):
        result[name] = text_number(getattr(entry, name), UNIT)
    return result


def cost_data(obj, fingerprint=None, *, detail=True):
    result = {'id': obj.pk, 'sequence': obj.sequence,
        'status': 'recalculation_required' if fingerprint and obj.input_fingerprint != fingerprint else obj.state,
        'calculated_status': obj.state, 'stage': obj.stage, 'issues': obj.issues,
        'summary': obj.summary, 'created_at': obj.created_at}
    if detail:
        entries = list(obj.entries.select_related('shipment_line__sku__spu__category_node',
            'shipment_line__shipment__order'))
        details_by_line = shipment_line_product_details([entry.shipment_line for entry in entries])
        result['entries'] = [entry_data(entry, details_by_line.get(entry.shipment_line_id, {})) for entry in entries]
        result['adjustments'] = [{'receipt_line_id': row.receipt_line_id,
            'previous_amount': text_number(row.previous_amount), 'current_amount': text_number(row.current_amount),
            'delta': text_number(row.delta)} for row in obj.adjustments.order_by('receipt_line_id')]
    return result


@transaction.atomic
def calculate(actor, kind, pk, payload, key):
    services._internal(actor)
    services._tenant_lock(actor)
    obj = target_for(actor, kind, pk, MANAGE)
    if kind == 'shipment' and obj.dispatch_memberships.filter(active_guard=True).exists():
        raise ValidationError('已集货的成本请按具体集货批次计算。')
    canonical_kind, canonical_obj = canonical(actor, kind, obj, MANAGE)
    if canonical_kind != kind or canonical_obj.pk != obj.pk:
        raise ValidationError('已集货的成本请按集货批次计算，避免重复形成入库成本调整。')
    digest, key = services.request_hash({'kind': kind, 'id': pk, **payload}), services._key(key)
    replay = CostVersion.objects.filter(tenant=actor.tenant, creation_key=key).first()
    if replay:
        services._matching_replay(replay, digest)
        return replay
    services._version(obj, payload['expected_source_version'])
    if obj.status != ('submitted' if kind == 'shipment' else 'active'):
        raise ValidationError('请对已提交发货单或有效集货批次计算成本。')
    source, fingerprint, lines, inbound, inbound_rows, revisions = inputs(kind, obj)
    if payload['expected_input_fingerprint'] != fingerprint:
        raise ValidationError('价格、费用或入库数量已变化，请重新加载后计算。')
    if not lines:
        raise ValidationError('没有商品，不能计算成本。')
    issues, collection = [], {}
    goods_taxes = {row['shipment_line_id']: Decimal(row['amount']) for contract in source.get('contract_cost_taxes', []) for row in contract['allocations']}
    for shipment in {line.shipment_id: line.shipment for line in lines}.values():
        collection.update(fee_amounts('shipment', shipment, revisions[('shipment', shipment.pk)], issues))
    batch_qty = dispatch_allocations.batch_quantities(obj) if kind == 'batch' else {}
    if kind == 'batch':
        # Cumulative rounding assigns each source fee exactly once, including the unallocated remainder.
        before = {}
        for allocation in source['dispatch_distribution']:
            if allocation['membership__batch_id'] < obj.pk:
                pk = allocation['shipment_line_id']
                before[pk] = before.get(pk, 0) + allocation['quantity']
        for line in lines:
            amount = collection.get(line.pk)
            if amount is not None:
                start = before.get(line.pk, 0)
                collection[line.pk] = money(amount * Decimal(start + batch_qty[line.pk]) / line.quantity) - money(amount * Decimal(start) / line.quantity)
    if kind == 'batch':
        for line in lines:
            tax = goods_taxes.get(line.pk, ZERO)
            start = before.get(line.pk, 0)
            goods_taxes[line.pk] = money(tax * Decimal(start + batch_qty[line.pk]) / line.quantity) - money(tax * Decimal(start) / line.quantity)
    freight = fee_amounts('batch', obj, revisions[('batch', obj.pk)], issues) if kind == 'batch' else {}
    clearance = fee_amounts('inbound', inbound, revisions[('inbound', inbound.pk)], issues) if inbound else {}
    checked = bool(inbound_rows) and all(row.received_quantity is not None for row in inbound_rows)
    if inbound and (not checked or inbound.status != 'confirmed'):
        issues.append('入库数量尚未核对并确认，入库成本仅为暂估。')
    if not inbound:
        issues.append('尚未生成并确认入库，本次为发货阶段成本。')
    quantities = {row.shipment_line_id: row.received_quantity for row in inbound_rows}
    receipts = {row.inbound_line.shipment_line_id: row for row in
        InternalStockReceiptLine.objects.filter(receipt__inbound=inbound).select_related('inbound_line')} if inbound else {}
    entries = []
    with localcontext() as ctx:
        ctx.prec = 60
        for line in lines:
            qty, received = batch_qty.get(line.pk, line.quantity), quantities.get(line.pk) if checked else None
            goods_tax = goods_taxes.get(line.pk, ZERO)
            goods = None if line.unit_price is None else money(line.unit_price * qty) + goods_tax
            if goods is None:
                issues.append(f'{line.shipment.number} / {line.sku_code_snapshot}：实际采购价格未填写。')
            collect, transport, clear = collection.get(line.pk, ZERO), freight.get(line.pk, ZERO), clearance.get(line.pk, ZERO)
            shipped_total = None if any(value is None for value in (goods, collect, transport)) else goods + collect + transport
            proportion = None if received is None else Decimal(min(received, qty)) / qty
            released_goods = None if proportion is None or goods is None else money(goods * proportion)
            released_collect = None if proportion is None or collect is None else money(collect * proportion)
            released_transport = None if proportion is None or transport is None else money(transport * proportion)
            if received == 0:
                released_goods = released_collect = released_transport = ZERO
            received_total = (None if received is None or any(value is None for value in (
                              released_goods, released_collect, released_transport, clear)) else
                              released_goods + released_collect + released_transport + clear)
            pending = None if shipped_total is None else (shipped_total if received is None else
                      shipped_total - (released_goods or ZERO) - released_collect - released_transport)
            if received is not None and received > qty:
                issues.append(f'{line.sku_code_snapshot}：实收超发货；额外货值尚需采购核对，成本仍为暂估。')
            entries.append({'shipment_line': line, 'receipt_line': receipts.get(line.pk),
                'quantity': qty, 'received_quantity': received, 'goods_amount': goods, 'goods_tax_amount': goods_tax,
                'collection_fee': collect, 'freight_fee': transport, 'clearance_fee': clear,
                'received_goods_amount': released_goods, 'received_collection_fee': released_collect,
                'received_freight_fee': released_transport, 'shipped_total': shipped_total,
                'received_total': received_total, 'pending_total': pending,
                'shipped_unit_cost': None if shipped_total is None else (shipped_total / qty).quantize(UNIT, rounding=ROUND_HALF_UP),
                'received_unit_cost': None if not received or received_total is None else (received_total / received).quantize(UNIT, rounding=ROUND_HALF_UP)})
    def total(name):
        with localcontext() as ctx:
            ctx.prec = 60
            return None if any(row[name] is None for row in entries) else text_number(sum((row[name] for row in entries), ZERO))
    summary = {'shipped_quantity': sum(row['quantity'] for row in entries),
        'received_quantity': sum(row['received_quantity'] for row in entries) if checked else None,
        'shipped_total': total('shipped_total'), 'received_total': total('received_total'), 'pending_total': total('pending_total')}
    prior = CostVersion.objects.filter(tenant=actor.tenant, **{kind: obj}).order_by('-sequence').first()
    prior_entries = {row.receipt_line_id: row for row in prior.entries.all() if row.receipt_line_id} if prior else {}
    with domain_write():
        version = CostVersion.objects.create(tenant=actor.tenant, created_by=actor, **{kind: obj},
            sequence=prior.sequence + 1 if prior else 1, state='estimated' if issues else 'confirmed',
            stage='received' if checked else 'shipped', input_fingerprint=fingerprint, source_snapshot=source,
            summary=summary, issues=list(dict.fromkeys(issues)), creation_key=key, request_hash=digest)
        for row in entries:
            entry = CostEntry.objects.create(tenant=actor.tenant, created_by=actor, cost_version=version, **row)
            old = prior_entries.get(entry.receipt_line_id)
            if (old and old.received_total is not None and entry.received_total is not None
                    and old.received_total != entry.received_total):
                CostAdjustment.objects.create(tenant=actor.tenant, created_by=actor, previous_version=prior,
                    current_version=version, receipt_line=entry.receipt_line, previous_amount=old.received_total,
                    current_amount=entry.received_total, delta=entry.received_total - old.received_total)
        services._event(actor, obj, 'cost_calculated', key, payload, audit={'cost_version_id': version.pk,
                       'cost_sequence': version.sequence, 'input_fingerprint': fingerprint, 'summary': summary})
    return version


def contract_payable_tax(obj, field='settlement_tax_amount'):
    from .models import PurchaseContract
    return PurchaseContract.objects.filter(tenant_id=obj.tenant_id, shipment_id=obj.pk, status='issued').values_list(field, flat=True).first() or ZERO


def settlement_amount(kind, obj):
    if kind == 'domestic_freight':
        if obj.status != 'submitted':
            return None
        record = fee_record('shipment', obj)
        revision = record.current_revision if record else None
        return revision.amount if revision and revision.state == 'confirmed' else None
    if kind == 'shipment':
        lines = source_lines(kind, obj)
        if obj.status != 'submitted' or not lines or any(line.unit_price is None for line in lines):
            return None
        with localcontext() as ctx:
            ctx.prec = 60
            return sum((money(line.unit_price * line.quantity) for line in lines), ZERO) + contract_payable_tax(obj)
    if kind == 'batch':
        record = fee_record(kind, obj)
        revision = record.current_revision if record else None
        return revision.amount if obj.status == 'active' and revision and revision.state == 'confirmed' else None
    if kind == 'inbound':
        record = fee_record(kind, obj)
        revision = record.current_revision if record else None
        return revision.amount if obj.batch.status == 'active' and revision and revision.state == 'confirmed' else None
    return None


def settlement_data(kind, obj):
    if kind not in ('shipment', 'batch'):
        return None, []
    current = settlement_amount(kind, obj)
    record = SettlementRecord.objects.filter(tenant=obj.tenant, **{kind: obj}).select_related('current_revision').first()
    revision = record.current_revision if record else None
    history_rows = list(record.revisions.order_by('-sequence')) if record else []
    attachments_by_revision = {}
    if history_rows:
        from .models import PaymentVoucher
        for voucher in PaymentVoucher.objects.filter(tenant_id=obj.tenant_id,
                settlement_revision_id__in=[row.pk for row in history_rows]).select_related('created_by').defer('content'):
            attachments_by_revision.setdefault(voucher.settlement_revision_id, []).append({
                'id': voucher.pk, 'file_name': voucher.file_name, 'media_type': voucher.media_type,
                'byte_size': voucher.byte_size, 'sha256': voucher.sha256, 'created_at': voucher.created_at,
                'uploaded_by': voucher.created_by.full_name or voucher.created_by.username})
    history = [] if not record else [{'id': row.pk, 'version': row.sequence, 'recorded_amount': text_number(row.recorded_amount),
        'reference_number': row.reference_number, 'date': row.date, 'notes': row.notes, 'reason': row.reason,
        'allocations': _visible_settlement_allocations(row), 'settlement_nature': _settlement_allocation_data(row)[1],
        'unclassified_amount': text_number(_settlement_allocation_data(row)[2]),
        'source_amount': row.source_snapshot.get('amount'), 'created_at': row.created_at,
        'attachments': attachments_by_revision.get(row.pk, [])}
        for row in history_rows]
    recorded = revision.recorded_amount if revision else ZERO
    if revision and current is not None:
        due = current - Decimal(revision.source_snapshot['amount'])
    else:
        due = None
    terms = None
    if kind == 'shipment':
        from .payment_terms import shipment_payment_reference
        terms = shipment_payment_reference(obj)
    allocations, nature, unclassified = _settlement_allocation_data(revision) if revision else ([], 'unclassified', ZERO)
    return {'version': record.version if record else 0, 'recorded_amount': text_number(recorded),
        'allocations': _visible_settlement_allocations(revision) if revision else allocations,
        'settlement_nature': nature, 'unclassified_amount': text_number(unclassified), 'payment_terms': terms,
        'reference_number': revision.reference_number if revision else '', 'date': revision.date if revision else None,
        'notes': revision.notes if revision else '', 'current_amount': text_number(current),
        'unsettled_amount': None if current is None else text_number(max(current - recorded, ZERO)),
        'over_recorded_amount': None if current is None else text_number(max(recorded - current, ZERO)),
        'status': ('unsettled' if not revision or current is None or (recorded == 0 and current > 0) else
                   'partially_settled' if recorded < current else 'settled'),
        'adjustment_due': text_number(due), 'supported': True}, history


@transaction.atomic
def save_settlement(actor, kind, pk, payload, key):
    services._internal(actor)
    services._tenant_lock(actor)
    obj = target_for(actor, kind, pk, MANAGE)
    if kind not in ('shipment', 'batch'):
        raise ValidationError('结算登记仅适用于供应商发货货值与集货货运费用。')
    if services._prior_event(actor, obj, 'settlement_registered', key, payload):
        return obj
    if (PaymentRecord.objects.filter(tenant_id=actor.tenant_id, **{kind: obj}, purpose='goods').exists() or
            (kind == 'shipment' and PaymentApplication.objects.filter(tenant_id=actor.tenant_id, shipment=obj).exists())):
        raise ValidationError('本单据已启用逐笔付款或定金抵扣，请通过付款记录登记。')
    services._version(obj, payload['expected_source_version'])
    current = settlement_amount(kind, obj)
    if current is None:
        raise ValidationError('请先补齐有效发货价格，或将货运费用标记为已确认。')
    if not payload['reference_number'].strip() or not payload['reason'].strip():
        raise ValidationError('请填写结算来源单号和登记原因。')
    record = SettlementRecord.objects.filter(tenant=obj.tenant, **{kind: obj}).first()
    if payload['expected_version'] != (record.version if record else 0):
        raise ValidationError('结算登记已变化，请重新加载。')
    prior_revision = record.current_revision if record else None
    if 'payee_allocations' not in payload and prior_revision and prior_revision.payee_allocations:
        raise ValidationError('本结算已有收款账户分配，请提交payee_allocations避免丢失。')
    allocation_inputs = payload.get('payee_allocations', [])
    if len({item['account_id'] for item in allocation_inputs}) != len(allocation_inputs):
        raise ValidationError('同一结算不可重复选择收款账户。')
    allocated_amount = sum((decimal(item['amount']) for item in allocation_inputs), ZERO)
    recorded_amount = decimal(payload['recorded_amount'])
    if allocation_inputs and allocated_amount != recorded_amount:
        raise ValidationError('收款账户分配金额合计必须等于登记累计金额。')
    if allocation_inputs and not recorded_amount:
        raise ValidationError('登记金额为0时不能选择收款账户。')
    owner = _payee_owner(kind, obj) if allocation_inputs else {}
    previous_allocations = {item['account_id']: item for item in (prior_revision.payee_allocations or [])} if prior_revision else {}
    accounts = {row.pk: row for row in PayeeAccount.objects.filter(tenant_id=actor.tenant_id,
        pk__in=[item['account_id'] for item in allocation_inputs], **owner)}
    if len(accounts) != len(allocation_inputs):
        raise ValidationError('收款账户不可用或不属于当前业务对象。')
    snapshots = []
    for item in allocation_inputs:
        account = accounts[item['account_id']]
        amount = decimal(item['amount'])
        previous = previous_allocations.get(account.pk)
        previous_amount = decimal(previous['amount']) if previous else ZERO
        if not account.active and (not previous or amount > previous_amount):
            raise ValidationError('已停用收款账户只能保留或减少原有累计分配。')
        # An account's classification and banking details are frozen at its first
        # allocation. Later cumulative revisions reuse that historical snapshot.
        snapshot = previous.get('account_snapshot') if previous else _payee_data(account)
        snapshots.append({'account_id': account.pk, 'amount': text_number(amount), 'account_snapshot': snapshot})
    with domain_write():
        if record is None:
            record = SettlementRecord.objects.create(tenant=actor.tenant, created_by=actor, **{kind: obj})
        else:
            record.version += 1
        revision = SettlementRevision.objects.create(tenant=actor.tenant, created_by=actor, settlement=record,
            sequence=record.version, recorded_amount=recorded_amount, payee_allocations=snapshots,
            reference_number=payload['reference_number'], date=services._date(payload['date']),
            notes=payload.get('notes', ''), reason=payload['reason'],
            source_snapshot={'kind': kind, 'id': obj.pk, 'source_version': obj.version, 'amount': text_number(current)})
        record.current_revision = revision
        record.save()
        services._event(actor, obj, 'settlement_registered', key, payload, audit={'settlement_revision_id': revision.pk,
            'source_amount': text_number(current), 'registered_cumulative_amount': text_number(revision.recorded_amount)})
    return obj


def _payment_owner(actor, kind, pk, permission=VIEW):
    if kind == 'purchase':
        rows = internal_orders(actor, PurchaseOrder.objects.all(), permission)
        obj = rows.filter(pk=pk).first()
        if obj is None:
            raise NotFound('采购单不存在或无权访问。')
        return obj
    if kind in ('shipment', 'batch', 'inbound', 'domestic_freight'):
        obj = target_for(actor, 'shipment' if kind == 'domestic_freight' else kind, pk, permission)
        if kind == 'domestic_freight' and not obj.domestic_carrier_id:
            raise ValidationError('请先指定国内承运商。')
        return obj
    raise NotFound('付款单据类型不存在。')


def payment_summary(actor, kind, pk):
    obj = _payment_owner(actor, kind, pk, VIEW)
    if kind == 'purchase':
        lines = list(obj.lines.filter(is_active=True))
        due = sum((money(line.unit_price * line.quantity) for line in lines if line.unit_price is not None), ZERO)
        if any(line.unit_price is None for line in lines):
            due = None
        related = {'purchase_order': obj}
        opening = ZERO
    else:
        due = settlement_amount(kind, obj)
        related = {'shipment': obj} if kind == 'domestic_freight' else {kind: obj}
        legacy = (SettlementRecord.objects.filter(tenant_id=actor.tenant_id, **{kind: obj}).select_related('current_revision').first()
            if kind in ('shipment', 'batch') else None)
        opening = legacy.current_revision.recorded_amount if legacy and legacy.current_revision else ZERO
    purpose = 'domestic_freight' if kind == 'domestic_freight' else 'goods'
    entries = list(PaymentRecord.objects.filter(tenant_id=actor.tenant_id, **related, purpose=purpose).select_related('payee_account').prefetch_related('reversal').order_by('date', 'id'))
    effective_entries = [row for row in entries if row.reverses_id is None and not row.reversal.all()]
    paid = opening + sum((row.amount for row in effective_entries), ZERO)
    applications = list(PaymentApplication.objects.filter(tenant_id=actor.tenant_id, **({'shipment_id': obj.pk} if kind == 'shipment' else {'prepayment__purchase_order_id': obj.pk})).select_related('prepayment', 'shipment').prefetch_related('reversal')) if kind in ('shipment', 'purchase') else []
    effective_applications = [row for row in applications if row.reverses_id is None and not row.reversal.all()]
    applied = sum((row.amount for row in effective_applications), ZERO)
    available_prepayments = []
    available = ZERO
    prepay_scope = PaymentRecord.objects.filter(tenant_id=actor.tenant_id, purchase_order=obj if kind == 'purchase' else getattr(obj, 'order', None), reverses__isnull=True).exclude(reversal__isnull=False) if kind in ('purchase', 'shipment') else PaymentRecord.objects.none()
    usage = {item['prepayment_id']: item['total'] or ZERO for item in PaymentApplication.objects.filter(
        tenant_id=actor.tenant_id, prepayment__in=prepay_scope, reverses__isnull=True, reversal__isnull=True
        ).values('prepayment_id').annotate(total=Sum('amount'))}
    if kind == 'purchase':
        applied = sum(usage.values(), ZERO)
        for prepay in prepay_scope:
            used = usage.get(prepay.pk, ZERO)
            bal = prepay.amount-used
            if bal > ZERO:
                available += bal
                available_prepayments.append({'id': prepay.pk, 'reference_number': prepay.reference_number, 'available_amount': text_number(bal)})
    elif kind == 'shipment':
        for prepay in prepay_scope:
            used = usage.get(prepay.pk, ZERO)
            bal = prepay.amount-used
            if bal > ZERO:
                available += bal
                available_prepayments.append({'id': prepay.pk, 'reference_number': prepay.reference_number, 'available_amount': text_number(bal)})
    payment_ids = [row.pk for row in entries] + [row.prepayment_id for row in applications]
    payment_ids += [item['id'] for item in available_prepayments]
    payment_ids = list(set(payment_ids))
    vouchers = {}
    if payment_ids:
        from .models import PaymentVoucher
        for voucher in PaymentVoucher.objects.filter(tenant_id=actor.tenant_id, payment_id__in=payment_ids).defer('content'):
            vouchers.setdefault(voucher.payment_id, []).append({'id': voucher.pk, 'file_name': voucher.file_name,
                'media_type': voucher.media_type, 'byte_size': voucher.byte_size, 'sha256': voucher.sha256})
    def visible_snapshot(snapshot):
        snapshot = dict(snapshot or {})
        if snapshot.get('account_number'):
            snapshot['account_number'] = _mask_account_number(snapshot['account_number'])
        return snapshot
    rendered_entries = [{'id': row.pk, 'entry_type': 'payment', 'amount': text_number(row.amount), 'date': row.date,
        'recorded_at': row.created_at, 'reference_number': row.reference_number, 'notes': row.notes, 'account_snapshot': row.account_snapshot,
        'fee_item_id': row.fee_item_id, 'item_snapshot': row.item_snapshot,
        'attachments': vouchers.get(row.pk, []), 'reversed': bool(row.reverses_id or row.reversal.all()),
        'is_reversal': bool(row.reverses_id), 'reversal_reason': row.reversal_reason} for row in entries]
    from .payment_request_models import SupplyPaymentRequest
    group_ids = dict(SupplyPaymentRequest.objects.filter(tenant_id=actor.tenant_id,
        payment_id__in=[row.pk for row in entries], batch__isnull=False).values_list('payment_id','batch_id'))
    for entry in rendered_entries:
        if entry['id'] in group_ids:
            entry['payment_batch_id']=group_ids[entry['id']]
            entry['payment_batch_href']=f"/supply-chain/costs?tab=reconciliation&payment_batch_id={group_ids[entry['id']]}"
    for item in rendered_entries:
        item['account_snapshot'] = visible_snapshot(item['account_snapshot'])
    for application in applications:
        rendered_entries.append({'id': application.pk, 'entry_type': 'application', 'amount': text_number(application.amount),
            'date': application.date, 'recorded_at': application.created_at, 'reference_number': application.prepayment.reference_number, 'notes': '定金抵扣',
            'related_number': application.shipment.number if kind == 'purchase' else '',
            'related_href': f'/supply-chain/costs?kind=shipment&id={application.shipment_id}' if kind == 'purchase' else '',
            'account_snapshot': visible_snapshot(application.prepayment.account_snapshot), 'attachments': vouchers.get(application.prepayment_id, []),
            'source_kind': 'purchase', 'source_id': application.prepayment.purchase_order_id,
            'payment_id': application.prepayment_id,
            'reversed': bool(application.reverses_id or application.reversal.all()),
            'is_reversal': bool(application.reverses_id), 'reversal_reason': application.reversal_reason})
    if opening:
        revision = legacy.current_revision
        rendered_entries.append({'id': f'opening-{revision.pk}', 'entry_type': 'opening', 'amount': text_number(opening),
            'date': revision.date, 'reference_number': revision.reference_number, 'notes': revision.notes,
            'account_snapshot': {}, 'attachments': [], 'reversed': False})
    from .payment_process import annotate_process, source_links
    rendered_entries = annotate_process(rendered_entries, due, kind)
    item_balances = []
    if kind in ('batch', 'inbound'):
        fee = fee_record(kind, obj)
        breakdown = fee.current_revision.item_breakdown if fee and fee.current_revision else []
        for item in breakdown:
            item_paid = sum((p.amount for p in PaymentRecord.objects.filter(tenant_id=actor.tenant_id, **{kind: obj},
                fee_item_id=item['fee_item_id'], reverses__isnull=True, reversal__isnull=True)), ZERO)
            item_balances.append({**item, 'paid_amount': text_number(item_paid),
                'remaining_amount': text_number(max(Decimal(item['amount'])-item_paid, ZERO))})
    return {'target': {'kind': kind, 'id': obj.pk, 'number': obj.number, 'source_links': source_links(kind, obj)},
        'process_basis': '按登记顺序展示；逐笔余额按当前应付金额重算，不代表历史时点应付。历史累计仅作期初，不能还原历史逐笔转账。',
        'summary': {'due_amount': text_number(due), 'contract_tax_amount': text_number(contract_payable_tax(obj) if kind == 'shipment' else ZERO), 'contract_cost_tax_amount': text_number(contract_payable_tax(obj, 'cost_tax_amount') if kind == 'shipment' else ZERO), 'opening_amount': text_number(opening),
            'paid_amount': text_number(paid), 'applied_amount': text_number(applied),
            'remaining_amount': None if due is None else text_number(max(due-paid-(applied if kind != 'purchase' else ZERO), ZERO)),
            'available_prepayment': text_number(available)},
        'version': len(entries)+(len(applications) if kind == 'shipment' else 0), 'entries': rendered_entries, 'available_prepayments': available_prepayments,
        'fee_items': item_balances, 'itemized': bool(item_balances)}


@transaction.atomic
def create_payment(actor, kind, pk, payload, request_key):
    services._internal(actor)
    services._tenant_lock(actor)
    obj = _payment_owner(actor, kind, pk, MANAGE)
    if kind == 'purchase' and obj.status != 'confirmed':
        raise ValidationError('采购单须先确认，才能登记定金。')
    related = {'purchase_order': obj} if kind == 'purchase' else {'shipment': obj} if kind == 'domestic_freight' else {kind: obj}
    digest_payload = {**payload, 'kind': kind, 'owner_id': obj.pk}
    event = BusinessEvent.objects.filter(tenant_id=actor.tenant_id, aggregate_type='paymentrecord',
        action='payment_created', request_key=services._key(request_key)).first()
    if event:
        services._matching_replay(event, services.request_hash(digest_payload))
        return payment_summary(actor, kind, pk)
    state = payment_summary(actor, kind, pk)
    if payload['expected_version'] != state['version']:
        raise ValidationError('付款记录已变化，请重新加载。')
    account_owner = _payee_owner(kind, obj)
    account = PayeeAccount.objects.filter(tenant_id=actor.tenant_id, active=True,
        pk=payload['payee_account_id'], **account_owner).first()
    if account is None:
        raise ValidationError('收款账户无效或不属于当前业务对象。')
    amount = decimal(payload['amount'])
    fee_item = None
    item_snapshot = {}
    if kind in ('batch', 'inbound'):
        fee = fee_record(kind, obj)
        breakdown = fee.current_revision.item_breakdown if fee and fee.current_revision else []
        if breakdown:
            selected = next((item for item in breakdown if str(item['fee_item_id']) == str(payload.get('fee_item_id'))), None)
            if not selected:
                raise ValidationError('分项费用模式下，付款必须指定费用项目。')
            if account.nature != selected['nature']:
                raise ValidationError('收款账户对公／对私性质与费用项目不一致。')
            fee_item = PaymentItem.objects.filter(tenant_id=actor.tenant_id, pk=selected['fee_item_id']).first()
            item_paid = sum((p.amount for p in PaymentRecord.objects.filter(tenant_id=actor.tenant_id, **{kind: obj},
                fee_item_id=selected['fee_item_id'], reverses__isnull=True, reversal__isnull=True)), ZERO)
            if amount > Decimal(selected['amount'])-item_paid:
                raise ValidationError('付款金额超过该费用项目剩余应付金额。')
            item_snapshot = dict(selected)
    if state['summary']['remaining_amount'] is not None and amount > Decimal(state['summary']['remaining_amount']):
        raise ValidationError('付款金额不能超过当前应付剩余金额。')
    if kind != 'purchase' and state['summary']['due_amount'] is None:
        raise ValidationError('请先确认本单应付金额，再登记付款。')
    with domain_write():
        row = PaymentRecord.objects.create(tenant=actor.tenant, created_by=actor, **related, purpose='domestic_freight' if kind == 'domestic_freight' else 'goods', amount=amount,
            date=services._date(payload['date']), reference_number=payload.get('reference_number') or f'PAY-{kind}-{obj.pk}-{services._key(request_key)[:12]}',
            notes=payload.get('notes', ''), payee_account=account, account_snapshot=_payee_data(account), fee_item=fee_item, item_snapshot=item_snapshot,
            idempotency_key=services._key(request_key))
        row.version = 1
        services._event(actor, row, 'payment_created', request_key, digest_payload, audit={'payment_id': row.pk})
    return payment_summary(actor, kind, pk)


@transaction.atomic
def apply_prepayment(actor, pk, payload, request_key):
    services._internal(actor)
    services._tenant_lock(actor)
    shipment = _payment_owner(actor, 'shipment', pk, MANAGE)
    digest = {'shipment_id': shipment.pk, **payload}
    prior = BusinessEvent.objects.filter(tenant_id=actor.tenant_id, aggregate_type='paymentapplication',
        action='prepayment_applied', request_key=services._key(request_key)).first()
    if prior:
        services._matching_replay(prior, services.request_hash(digest))
        return payment_summary(actor, 'shipment', pk)
    state = payment_summary(actor, 'shipment', pk)
    if payload['expected_version'] != state['version']:
        raise ValidationError('付款记录已变化，请重新加载。')
    prepay = PaymentRecord.objects.select_for_update().filter(tenant_id=actor.tenant_id,
        pk=payload['payment_id'], purchase_order=shipment.order, reverses__isnull=True).exclude(reversal__isnull=False).first()
    if prepay is None:
        raise ValidationError('定金不存在或不属于该发货单供应商。')
    used = sum((a.amount for a in prepay.applications.filter(reverses__isnull=True, reversal__isnull=True)), ZERO)
    amount = decimal(payload['amount'])
    if amount > prepay.amount-used:
        raise ValidationError('抵扣金额超过该笔定金剩余金额。')
    due = settlement_amount('shipment', shipment)
    if due is None:
        raise ValidationError('请先确认发货单应付金额，再抵扣定金。')
    paid = Decimal(state['summary']['paid_amount'])+Decimal(state['summary']['applied_amount'])
    if due is not None and amount > max(due-paid, ZERO):
        raise ValidationError('抵扣金额超过发货单应付剩余金额。')
    with domain_write():
        row = PaymentApplication.objects.create(tenant=actor.tenant, created_by=actor,
            prepayment=prepay, shipment=shipment, amount=amount, date=services._date(payload['date']),
            idempotency_key=services._key(request_key))
        services._event(actor, row, 'prepayment_applied', request_key, digest, audit={'application_id': row.pk})
    return payment_summary(actor, 'shipment', pk)


@transaction.atomic
def reverse_payment(actor, kind, pk, payment_id, payload, request_key, *, allow_payment_batch=False):
    services._internal(actor)
    services._tenant_lock(actor)
    obj = _payment_owner(actor, kind, pk, MANAGE)
    owner_filter = {'purchase_order': obj} if kind == 'purchase' else {'shipment': obj} if kind == 'domestic_freight' else {kind: obj}
    row = PaymentRecord.objects.select_for_update().filter(tenant_id=actor.tenant_id, pk=payment_id, **owner_filter,
        purpose='domestic_freight' if kind == 'domestic_freight' else 'goods').first()
    if row is None:
        raise NotFound('付款记录不存在或无权访问。')
    request_row = getattr(row, 'payment_request', None)
    if request_row and request_row.batch_id and not allow_payment_batch:
        raise ValidationError('该付款属于付款批次，请在批次中整体冲销。')
    fingerprint = {'payment_id': row.pk, **payload}
    prior = BusinessEvent.objects.filter(tenant_id=actor.tenant_id, action='payment_reversed', request_key=services._key(request_key)).first()
    if prior:
        services._matching_replay(prior, services.request_hash(fingerprint))
        return payment_summary(actor, kind, pk)
    if row.reverses_id or row.reversal.exists():
        raise ValidationError('该付款已冲销或不能重复冲销。')
    if row.purchase_order_id and row.applications.filter(reverses__isnull=True, reversal__isnull=True).exists():
        raise ValidationError('该定金已有抵扣，请先冲销抵扣记录。')
    state = payment_summary(actor, kind, pk)
    if payload['expected_version'] != state['version']:
        raise ValidationError('付款记录已变化，请重新加载。')
    with domain_write():
        reversal = PaymentRecord.objects.create(tenant=actor.tenant, created_by=actor, **owner_filter, purpose=row.purpose,
            amount=row.amount, date=services._date(payload['date']) if payload.get('date') else row.date,
            reference_number=f'REV-{row.pk}', notes=payload['reason'], payee_account=row.payee_account,
            account_snapshot=row.account_snapshot, fee_item=row.fee_item, item_snapshot=row.item_snapshot,
            idempotency_key=services._key(request_key), reverses=row, reversal_reason=payload['reason'])
        services._event(actor, reversal, 'payment_reversed', request_key, fingerprint, audit={'reversed_payment_id': row.pk})
    return payment_summary(actor, kind, pk)


@transaction.atomic
def reverse_prepayment_application(actor, pk, application_id, payload, request_key):
    services._internal(actor)
    services._tenant_lock(actor)
    shipment = _payment_owner(actor, 'shipment', pk, MANAGE)
    row = PaymentApplication.objects.select_for_update().filter(tenant_id=actor.tenant_id,
        pk=application_id, shipment=shipment).first()
    if row is None:
        raise NotFound('定金抵扣记录不存在或无权访问。')
    fingerprint = {'application_id': row.pk, **payload}
    prior = BusinessEvent.objects.filter(tenant_id=actor.tenant_id, action='prepayment_application_reversed', request_key=services._key(request_key)).first()
    if prior:
        services._matching_replay(prior, services.request_hash(fingerprint))
        return payment_summary(actor, 'shipment', pk)
    if row.reverses_id or row.reversal.exists():
        raise ValidationError('该抵扣已冲销或不能重复冲销。')
    state = payment_summary(actor, 'shipment', pk)
    if payload['expected_version'] != state['version']:
        raise ValidationError('付款记录已变化，请重新加载。')
    with domain_write():
        reversal = PaymentApplication.objects.create(tenant=actor.tenant, created_by=actor,
            prepayment=row.prepayment, shipment=shipment, amount=row.amount, date=row.date,
            idempotency_key=services._key(request_key), reverses=row, reversal_reason=payload['reason'])
        services._event(actor, reversal, 'prepayment_application_reversed', request_key, fingerprint,
            audit={'reversed_application_id': row.pk})
    return payment_summary(actor, 'shipment', pk)


def context(actor, kind, pk):
    domestic_freight = kind == 'domestic_freight'
    owner_kind = 'shipment' if domestic_freight else kind
    obj = target_for(actor, owner_kind, pk)
    prepare_target_financials(owner_kind, [obj])
    allowed, reason = (False, '国内运费由确认的发货单费用决定。') if domestic_freight else fee_gate(kind, obj)
    try:
        target_for(actor, owner_kind, pk, MANAGE)
    except (NotFound, PermissionDenied):
        allowed, reason = False, '本单据仅有查看权限。'
    target = {**target_data(owner_kind, obj), 'fee_editable': allowed, 'fee_block_reason': '' if allowed else reason,
              'calculation_kind': owner_kind, 'calculation_id': obj.pk, 'calculation_version': obj.version,
              'calculation_allowed': False}
    latest, history, fingerprint = None, [], None
    try:
        calc_kind, calc_obj = canonical(actor, kind, obj)
        target.update(calculation_kind=calc_kind, calculation_id=calc_obj.pk, calculation_version=calc_obj.version)
        _, fingerprint, *_ = inputs(calc_kind, calc_obj)
        versions = CostVersion.objects.filter(tenant=actor.tenant, **{calc_kind: calc_obj}).order_by('-sequence')
        latest_obj = versions.first()
        latest = cost_data(latest_obj, fingerprint) if latest_obj else None
        history = [cost_data(row, detail=False) for row in versions[:100]]
        target_for(actor, calc_kind, calc_obj.pk, MANAGE)
        target['related_batches'] = dispatch_allocations.distribution(obj) if kind == 'shipment' else []
        target['calculation_allowed'] = (kind != 'shipment' or not target['related_batches']) and calc_obj.status == (
            'submitted' if calc_kind == 'shipment' else 'active')
    except (NotFound, PermissionDenied):
        # A scoped buyer may see this supplier's shipment but not the whole batch.
        target['calculation_allowed'] = False
    record = fee_record(owner_kind, obj)
    fee = fee_data(record.current_revision) if record else None
    fee_history = [fee_data(row) for row in record.revisions.order_by('-sequence')[:100]] if record else []
    settlement, settlement_history = (None, []) if domestic_freight else settlement_data(kind, obj)
    current_measurements = measurements(owner_kind, obj)
    # Retain explicitly measured totals when only amount/ratio changes; a changed
    # quantity needs new measurement and must not reuse the old total silently.
    frozen = {row['shipment_line_id']: row for row in fee['allocations']} if fee else {}
    for row in current_measurements:
        old = frozen.get(row['shipment_line_id'])
        if old and old['quantity'] == row['quantity']:
            for name, source_name in [('volume_cbm', 'volume_source'), ('weight_kg', 'weight_source')]:
                if old.get(source_name) == 'manual_total':
                    row[name], row[source_name] = old[name], 'manual_total'
    legacy_by_line = {row['shipment_line_id']: row['legacy_sku_code'] for row in current_measurements}
    image_by_line = {row['shipment_line_id']: (row['product_details'], row['image_preview_url']) for row in current_measurements}
    for fee_value in [fee, *fee_history]:
        if fee_value:
            for allocation in fee_value.get('allocations', []):
                if 'legacy_sku_code' not in allocation:
                    allocation['legacy_sku_code'] = legacy_by_line.get(allocation['shipment_line_id'], '')
                if 'product_details' not in allocation:
                    allocation['product_details'], allocation['image_preview_url'] = image_by_line.get(
                        allocation['shipment_line_id'], ({'image_url': ''}, ''))
    from .freight_channels import freight_reference
    quote_reference = freight_reference(obj, fee.get('billed_cbm') if fee else None) if kind == 'batch' else None
    fee_item_options = list(PaymentItem.objects.filter(tenant_id=actor.tenant_id, is_active=True,
        party_type__in=['carrier', 'both']).values('id', 'name', 'default_nature', 'default_tax_rate', 'default_allocation', 'counts_as_cost')) if kind in ('batch', 'inbound') else []
    return {'target': target, 'fee': fee, 'fee_history': fee_history, 'fee_item_options': fee_item_options, 'freight_quote_reference': quote_reference,
        'measurements': current_measurements, 'latest_cost': latest, 'cost_history': history,
        'input_fingerprint': fingerprint, 'settlement': settlement,
        'settlement_supported': kind in ('shipment', 'batch'), 'payment_supported': kind in ('shipment', 'batch', 'inbound'),
        'settlement_history': settlement_history}


def version_for(actor, kind, pk, sequence):
    obj = target_for(actor, kind, pk)
    calc_kind, calc_obj = canonical(actor, kind, obj)
    version = CostVersion.objects.filter(tenant=actor.tenant, sequence=sequence, **{calc_kind: calc_obj}).first()
    if version is None:
        raise NotFound('成本版本不存在。')
    return cost_data(version)
