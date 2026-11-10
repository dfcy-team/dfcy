"""Payment schedules are plans only: they do not create cash or cost entries."""
from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from rest_framework.exceptions import ValidationError, PermissionDenied, NotFound

from . import costs, services
from .cost_models import PaymentPlanRecord, PayableClassificationRecord
from .models import domain_write
from .permissions import MANAGE, VIEW
from .payment_plan_links import line_balances, has_references, enriched_lines


def _record(actor, kind, obj):
    owner = {'shipment': obj if kind in ('shipment', 'domestic_freight') else None,
             'batch': obj if kind == 'batch' else None}
    owner = {k: v for k, v in owner.items() if v is not None}
    return PaymentPlanRecord.objects.filter(tenant_id=actor.tenant_id, kind=kind, **owner).first()


def _party(kind, obj):
    if kind == 'domestic_freight':
        from .domestic_freight import payable_party
        party_type, party = payable_party(obj)
    elif kind == 'shipment':
        party_type, party = 'supplier', obj.order.supplier
    else:
        party_type, party = 'carrier', obj.freight_company if obj.freight_company_id else None
    return {'type': party_type, 'id': party.pk if party else None, 'name': party.name if party else ''}


def _source_currency(kind, obj):
    snapshot = (obj.domestic_terms_snapshot if kind == 'domestic_freight' else
                obj.freight_terms_snapshot if kind == 'batch' else {}) or {}
    value = snapshot.get('currency')
    return value if isinstance(value, str) and len(value) == 3 and value.isascii() and value.isalpha() and value.isupper() else None


def plan_data(actor, kind, pk):
    if kind not in ('shipment', 'domestic_freight', 'batch'):
        raise NotFound('付款计划仅支持供应商发货单、国内运费或集货发运批次。')
    obj = costs._payment_owner(actor, kind, pk, VIEW)
    record = _record(actor, kind, obj)
    state = costs.payment_summary(actor, kind, pk)
    party = _party(kind, obj)
    from .payment_terms import terms_data
    terms = terms_data(actor, kind, pk)
    can_manage = False
    try:
        costs._payment_owner(actor, kind, pk, MANAGE)
        can_manage = True
    except (PermissionDenied, NotFound):
        pass
    payable_classification = PayableClassificationRecord.objects.filter(tenant_id=actor.tenant_id, kind=kind,
        **({'shipment': obj} if kind in ('shipment','domestic_freight') else {'batch': obj})).first()
    currency = record.currency if record and record.currency else ((payable_classification.currency if payable_classification else '') or _source_currency(kind, obj))
    return {'version': record.version if record else 0, 'source_version': obj.version,
            'lines': enriched_lines(record) if record else [],
            'remaining_amount': state['summary']['remaining_amount'],
            'currency': currency, 'currency_requires_confirmation': not bool(currency),
            'can_manage': can_manage, 'party_name': party['name'],
            'party_changed': bool(record and record.party_snapshot != party),
            'saved_party_name': (record.party_snapshot or {}).get('name') if record else None,
            'default_due_date': terms.get('due_date'), 'fee_items': state.get('fee_items', [])}


@transaction.atomic
def save_plan(actor, kind, pk, payload, request_key):
    if kind not in ('shipment', 'domestic_freight', 'batch'):
        from rest_framework.exceptions import NotFound
        raise NotFound('付款计划仅支持供应商发货单、国内运费或集货发运批次。')
    services._internal(actor)
    services._tenant_lock(actor)
    obj = costs._payment_owner(actor, kind, pk, MANAGE)
    record = PaymentPlanRecord.objects.select_for_update().filter(tenant_id=actor.tenant_id,
        kind=kind, **({'shipment': obj} if kind in ('shipment','domestic_freight') else {'batch': obj})).first()
    expected = payload['expected_version']
    currency = payload['currency']
    lines = [{**row, 'amount': str(row['amount']),
              'due_date': row['due_date'].isoformat() if row.get('due_date') else None}
             for row in payload['lines']]
    reason = payload['reason'].strip()
    if not reason:
        raise ValidationError({'reason': '调整原因必填。'})
    digest_payload = {'kind': kind, 'source_id': obj.pk, 'currency': currency,
                      'lines': lines, 'reason': reason,
                      'expected_version': expected, 'expected_source_version': payload['expected_source_version']}
    key = services._key(request_key)
    prior = services.BusinessEvent.objects.filter(tenant_id=actor.tenant_id,
        aggregate_type='paymentplanrecord', action='payment_plan_saved', request_key=key).first()
    if prior:
        services._matching_replay(prior, services.request_hash(digest_payload))
        return
    if (record.version if record else 0) != expected or obj.version != payload['expected_source_version']:
        raise ValidationError('单据或付款计划已变化，请刷新后重试。')
    party = _party(kind, obj)
    if not party['id']:
        raise ValidationError('请先确认本单应付款往来单位。')
    if record and has_references(record) and ((record.party_snapshot or {}).get('type'),
            (record.party_snapshot or {}).get('id')) != (party['type'], party['id']):
        raise ValidationError('已有付款申请引用该计划，不能更换往来单位。')
    if record and record.currency and currency != record.currency:
        raise ValidationError('本单币种已确认，不能直接更改。')
    classification = PayableClassificationRecord.objects.filter(tenant_id=actor.tenant_id, kind=kind,
        **({'shipment': obj} if kind in ('shipment','domestic_freight') else {'batch': obj})).first()
    if classification and currency != classification.currency:
        raise ValidationError('付款计划币种必须与应付分类一致。')
    source_currency = _source_currency(kind, obj)
    if source_currency and source_currency != currency:
        raise ValidationError('付款计划币种必须与来源单据一致。')
    remaining = costs.payment_summary(actor, kind, pk)['summary']['remaining_amount']
    if remaining is None:
        raise ValidationError('来源单据应付金额尚未确认，暂不能维护付款计划。')
    balances = line_balances(record) if record else {}
    normalized_lines = []
    seen_ids = set()
    referenced = {}
    if record:
        from .payment_request_models import SupplyPaymentRequest
        referenced = set(SupplyPaymentRequest.objects.filter(plan=record).values_list('plan_line_id', flat=True).distinct())
    known_ids = ({item.get('line_id') or f'legacy-{record.pk}-{i}' for i, item in enumerate(record.lines or [])} if record else set())
    for index, row in enumerate(lines):
        line_id = row.get('line_id')
        supplied_id = line_id is not None
        if line_id is None:
            line_id = str(uuid4())
        line_id = str(line_id)
        if not line_id or len(line_id) > 64 or line_id in seen_ids:
            raise ValidationError({'lines': '付款计划明细编号无效或重复。'})
        seen_ids.add(line_id)
        if supplied_id and record and line_id not in known_ids:
            raise ValidationError({'lines': '付款计划明细编号未知，请刷新后重试。'})
        if supplied_id and record is None:
            raise ValidationError({'lines': '新付款计划明细无需指定编号。'})
        normalized_lines.append({**row, 'line_id': line_id})
    new_ids = {row['line_id'] for row in normalized_lines}
    if set(referenced) - new_ids:
        raise ValidationError({'lines': '已被付款申请引用的计划明细不能删除。'})
    for row in normalized_lines:
        line_id = row['line_id']
        old = next((item for i, item in enumerate(record.lines or [])
                    if (item.get('line_id') or f'legacy-{record.pk}-{i}') == line_id), None) if record else None
        if line_id in referenced and old:
            identity = (old.get('nature'), old.get('currency') or record.currency, str(old.get('fee_item_id') or ''))
            candidate = (row.get('nature'), row.get('currency') or currency, str(row.get('fee_item_id') or ''))
            if identity != candidate:
                raise ValidationError({'lines': '已被付款申请引用的计划明细不能修改性质、币种或费用项目。'})
            paid = balances.get(line_id, {}).get('paid_amount', Decimal(0))
            reserved = balances.get(line_id, {}).get('reserved_amount', Decimal(0))
            if Decimal(str(row['amount'])) < paid + reserved:
                raise ValidationError({'lines': '计划金额不能低于已入账及已占用金额。'})
    total = sum((max(Decimal(0), Decimal(str(row['amount'])) - balances.get(row['line_id'], {}).get('paid_amount', Decimal(0))) for row in normalized_lines), Decimal(0))
    if total > Decimal(str(remaining)):
        raise ValidationError('付款计划合计不能超过当前剩余应付。')
    payment_state = costs.payment_summary(actor, kind, pk)
    fee_items = {str(item['fee_item_id']): item for item in payment_state.get('fee_items', [])}
    item_totals = {}
    for row in normalized_lines:
        if row.get('currency') and row['currency'] != currency:
            raise ValidationError('单行币种必须与本单确认币种一致。')
        row['amount'] = str(row['amount'])
        row['currency'] = currency
        item_id = row.get('fee_item_id')
        if kind == 'batch' and payment_state.get('itemized') and item_id is None:
            raise ValidationError('批次费用已按项目拆分，付款计划必须选择费用项目。')
        if item_id is not None:
            item = fee_items.get(str(item_id))
            if item is None:
                raise ValidationError('所选费用项目不属于当前批次。')
            expected_nature = item.get('nature')
            if expected_nature and expected_nature != row['nature']:
                raise ValidationError('付款性质与费用项目约定不一致。')
            item_totals[str(item_id)] = item_totals.get(str(item_id), Decimal(0)) + Decimal(str(row['amount']))
    for item_id, planned in item_totals.items():
        limit = Decimal(str(fee_items[item_id]['remaining_amount']))
        paid_by_item = sum((balances.get(row['line_id'], {}).get('paid_amount', Decimal(0)) for row in normalized_lines if str(row.get('fee_item_id')) == item_id), Decimal(0))
        if max(Decimal(0), planned - paid_by_item) > limit:
            raise ValidationError('某费用项目的计划金额超过该项目剩余应付。')
    with domain_write():
        if record is None:
            record = PaymentPlanRecord.objects.create(tenant=actor.tenant, created_by=actor,
                kind=kind, currency=currency, lines=normalized_lines, party_snapshot=party, reason=reason, version=1,
                **({'shipment': obj} if kind in ('shipment','domestic_freight') else {'batch': obj}))
        else:
            record.currency = currency
            record.lines = normalized_lines
            record.party_snapshot = party
            record.reason = reason
            record.version += 1
            record.save()
        services._event(actor, record, 'payment_plan_saved', key, digest_payload,
                        audit={'payment_plan_id': record.pk, 'party_snapshot': party})
