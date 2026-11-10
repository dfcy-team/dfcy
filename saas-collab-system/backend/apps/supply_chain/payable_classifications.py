"""Classification metadata for the confirmed payable, separate from payments."""
from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import NotFound, ValidationError, PermissionDenied

from . import costs, services
from .cost_models import PayableClassificationRecord, PaymentPlanRecord
from .permissions import MANAGE, VIEW
from .payment_plans import _party, _source_currency
from .models import domain_write

KINDS = ('shipment', 'domestic_freight', 'batch')
ZERO = Decimal('0.0000')


def classification_data(actor, kind, pk):
    if kind not in KINDS:
        raise NotFound('应付分类仅支持供应商发货单、国内运费或集货发运批次。')
    obj = costs._payment_owner(actor, kind, pk, VIEW)
    owner = {'shipment': obj} if kind in ('shipment', 'domestic_freight') else {'batch': obj}
    record = PayableClassificationRecord.objects.filter(tenant_id=actor.tenant_id, kind=kind, **owner).first()
    state = costs.payment_summary(actor, kind, pk)
    raw = state['summary']['due_amount']
    payable = Decimal(str(raw)) if raw is not None else None
    party = _party(kind, obj)
    plan = PaymentPlanRecord.objects.filter(tenant_id=actor.tenant_id, kind=kind, **owner).first()
    can_manage = True
    try:
        costs._payment_owner(actor, kind, pk, MANAGE)
    except (PermissionDenied, NotFound):
        can_manage = False
    source_currency = _source_currency(kind, obj)
    stale = bool(record and (payable is None or record.payable_amount != payable or
        record.party_snapshot != party or (source_currency and record.currency != source_currency)))
    corp = record.corporate_amount if record else ZERO
    pers = record.personal_amount if record else ZERO
    reason = None
    if kind == 'batch' and state.get('itemized'):
        # Confirmed fee item nature is authoritative; manual aggregate splits are disabled.
        corp = pers = ZERO
        for item in state.get('fee_items', []):
            amount = Decimal(str(item['amount']))
            if item.get('nature') == 'corporate': corp += amount
            elif item.get('nature') == 'personal': pers += amount
        can_manage = False
        reason = '批次费用已按费用项目确认对公/对私性质，请在费用项目中维护。'
    classified = corp + pers
    return {'version': record.version if record else 0, 'source_version': obj.version,
        'payable_amount': str(payable) if payable is not None else None,
        'corporate_amount': str(corp), 'personal_amount': str(pers),
        'unclassified_amount': str(max(payable - classified, ZERO)) if payable is not None else None,
        'currency': (record.currency if record else '') or (plan.currency if plan else '') or _source_currency(kind, obj),
        'can_manage': can_manage, 'stale': stale, 'party_name': party['name'],
        'read_only_reason': reason}


@transaction.atomic
def save_classification(actor, kind, pk, payload, request_key):
    if kind not in KINDS:
        raise NotFound('应付分类仅支持供应商发货单、国内运费或集货发运批次。')
    services._internal(actor)
    services._tenant_lock(actor)
    obj = costs._payment_owner(actor, kind, pk, MANAGE)
    owner = {'shipment': obj} if kind in ('shipment', 'domestic_freight') else {'batch': obj}
    record = PayableClassificationRecord.objects.select_for_update().filter(
        tenant_id=actor.tenant_id, kind=kind, **owner).first()
    corp, pers = payload['corporate_amount'], payload['personal_amount']
    reason = payload['reason'].strip()
    if not reason:
        raise ValidationError({'reason': '调整原因必填。'})
    digest_payload = {'kind': kind, 'source_id': obj.pk, 'currency': payload['currency'],
        'corporate_amount': str(corp), 'personal_amount': str(pers), 'reason': reason,
        'expected_version': payload['expected_version'], 'expected_source_version': payload['expected_source_version'],
        'expected_payable_amount': str(payload['expected_payable_amount'])}
    key = services._key(request_key)
    prior = services.BusinessEvent.objects.filter(tenant_id=actor.tenant_id,
        aggregate_type='payableclassificationrecord', action='payable_classification_saved', request_key=key).first()
    if prior:
        services._matching_replay(prior, services.request_hash(digest_payload))
        return
    if kind == 'batch' and costs.payment_summary(actor, kind, pk).get('itemized'):
        raise ValidationError('批次费用已按费用项目确认性质，不能手工维护总额分类。')
    if (record.version if record else 0) != payload['expected_version'] or obj.version != payload['expected_source_version']:
        raise ValidationError('单据或应付分类已变化，请刷新后重试。')
    state = costs.payment_summary(actor, kind, pk)
    raw = state['summary']['due_amount']
    if raw is None:
        raise ValidationError('来源单据应付金额尚未确认，暂不能分类。')
    payable = Decimal(str(raw))
    if payable != payload['expected_payable_amount']:
        raise ValidationError('确认应付金额已变化，请刷新后重试。')
    if corp + pers > payable:
        raise ValidationError('对公与对私分类合计不能超过确认应付总额。')
    party = _party(kind, obj)
    if not party['id']:
        raise ValidationError('请先确认本单应付往来单位。')
    currency = payload['currency']
    if record and currency != record.currency:
        raise ValidationError('本单币种已确认，不能直接更改。')
    plan = PaymentPlanRecord.objects.filter(tenant_id=actor.tenant_id, kind=kind, **owner).first()
    source_currency = _source_currency(kind, obj)
    locked_currencies = [c for c in (record.currency if record else '', plan.currency if plan else '', source_currency) if c]
    if any(currency != locked for locked in locked_currencies):
        raise ValidationError('应付分类币种必须与来源单据或付款计划一致。')
    with domain_write():
        if record is None:
            record = PayableClassificationRecord.objects.create(tenant=actor.tenant, created_by=actor,
                kind=kind, currency=currency, corporate_amount=corp, personal_amount=pers,
                payable_amount=payable, party_snapshot=party, reason=reason, version=1, **owner)
        else:
            record.currency, record.corporate_amount, record.personal_amount = currency, corp, pers
            record.payable_amount, record.party_snapshot, record.reason = payable, party, reason
            record.version += 1
            record.save()
        services._event(actor, record, 'payable_classification_saved', key, digest_payload,
            audit={'payable_classification_id': record.pk, 'party_snapshot': party})
