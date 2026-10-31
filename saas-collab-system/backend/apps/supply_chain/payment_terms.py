"""Supplier terms are frozen at confirmation, not inferred from archive creation."""
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from rest_framework.exceptions import ValidationError, NotFound
from .models import PaymentTermsRecord, PaymentTermsRevision, domain_write

START_LABELS = {'unspecified': '未约定', 'shipment_date': '供应商发货日', 'collection_arrival': '集货到仓日',
                'warehouse_arrival': '目的仓到仓日', 'reconciliation_date': '对账确认日'}


def supplier_terms(supplier):
    return {'days': supplier.payment_term_days, 'start': supplier.payment_term_start,
            'reminder_days': supplier.payment_reminder_days, 'start_label': START_LABELS.get(supplier.payment_term_start, '未约定')}


def order_terms(order):
    if order.status == 'draft':
        return {**supplier_terms(order.supplier), 'state': 'draft_reference'}
    return {**order.supplier_terms_snapshot, 'state': 'frozen' if order.supplier_terms_snapshot else 'unrecorded'}


def _local_date(value):
    if not value:
        return None
    return timezone.localdate(value, timezone=ZoneInfo(getattr(settings, 'SUPPLY_CHAIN_TIME_ZONE', 'Asia/Shanghai')))


def shipment_payment_reference(shipment):
    terms = order_terms(shipment.order)
    result = {**terms, 'anchor_date': None, 'due_date': None, 'message': '历史采购单未记录账期约定。'}
    if terms['state'] == 'unrecorded':
        return result
    if terms.get('days') is None or terms.get('start') == 'unspecified':
        result['message'] = '账期或起算方式尚未约定。'
        return result
    anchor = None
    start = terms['start']
    if start == 'shipment_date':
        anchor = shipment.shipment_date if shipment.status == 'submitted' else None
    elif start == 'collection_arrival':
        anchor = _local_date(shipment.collection_arrived_at)
    elif start == 'warehouse_arrival':
        from .dispatch_allocations import distribution
        groups = distribution(shipment)
        total = sum(line.quantity for line in shipment.lines.filter(is_active=True))
        dates = [g['logistics_dates']['arrived_warehouse_at'] for g in groups]
        if groups and sum(g['quantity'] for g in groups) == total and all(dates):
            anchor = _local_date(max(dates))
    if anchor:
        result.update(anchor_date=anchor.isoformat(), due_date=(anchor + timedelta(days=terms['days'])).isoformat(), message='按采购确认时的账期约定计算。')
    else:
        result['message'] = '待确认对账日期，暂不推算到期日。' if start == 'reconciliation_date' else '起算业务节点尚未发生，暂不推算到期日。'
    return result


@transaction.atomic
def save_terms(actor, kind, pk, data, idempotency_key):
    from . import costs, services
    from .permissions import MANAGE
    obj = costs._payment_owner(actor, kind, pk, MANAGE)
    services._tenant_lock(actor)
    owner_kind = 'shipment' if kind == 'domestic_freight' else kind
    field = {'shipment': 'shipment', 'batch': 'batch', 'inbound': 'inbound'}.get(owner_kind)
    if field is None:
        raise ValidationError('不支持该账期单据类型。')
    record = PaymentTermsRecord.objects.select_for_update().filter(tenant=actor.tenant, kind=kind, **{field: obj}).first()
    payload = {**data, 'kind': kind, 'owner_id': obj.pk}
    digest = services.request_hash(payload)
    replay = services.BusinessEvent.objects.filter(tenant=actor.tenant, aggregate_type=obj._meta.model_name,
        aggregate_id=obj.pk, action='payment_terms_adjusted', request_key=idempotency_key).first()
    if replay:
        services._matching_replay(replay, digest)
        return record
    if record is None:
        if data['expected_version'] != 0:
            raise ValidationError('账期版本已变化，请刷新后重试。')
        record = PaymentTermsRecord(tenant=actor.tenant, created_by=actor, kind=kind, version=0, **{field: obj})
    elif data['expected_version'] != record.version:
        raise ValidationError('账期版本已变化，请刷新后重试。')
    prior = PaymentTermsRevision.objects.filter(tenant=actor.tenant, idempotency_key=idempotency_key).first()
    if prior:
        services._matching_replay(prior, digest)
        return prior.terms
    reason = data['reason'].strip()
    if not reason:
        raise ValidationError({'reason': '调整原因必填。'})
    with domain_write():
        record.reconciliation_date = data.get('reconciliation_date')
        record.due_date_override = data.get('due_date_override')
        record.version += 1
        record.save()
        revision = PaymentTermsRevision.objects.create(tenant=actor.tenant, created_by=actor, terms=record,
            sequence=record.revisions.count() + 1, days=data['days'], start=data['start'],
            reminder_days=data['reminder_days'], reconciliation_date=record.reconciliation_date,
            due_date_override=record.due_date_override, reason=reason, idempotency_key=idempotency_key,
            request_hash=digest)
        record.current_revision = revision
        record.save(update_fields=['current_revision', 'updated_at'])
        services._event(actor, obj, 'payment_terms_adjusted', idempotency_key, payload,
            audit={'terms_revision_id': revision.pk, 'reason': reason})
    return record


def terms_data(actor, kind, pk):
    from . import costs
    if kind not in ('shipment', 'domestic_freight', 'batch', 'inbound'):
        raise NotFound('不支持该账期单据类型。')
    obj = costs._payment_owner(actor, kind, pk)
    owner_kind = 'shipment' if kind == 'domestic_freight' else kind
    field = {'shipment': 'shipment', 'batch': 'batch', 'inbound': 'inbound'}.get(owner_kind)
    record = PaymentTermsRecord.objects.filter(tenant=actor.tenant, kind=kind, **{field: obj}).select_related('current_revision').first()
    if record:
        rev = record.current_revision
        terms = {'days': rev.days, 'start': rev.start, 'reminder_days': rev.reminder_days,
                 'reconciliation_date': rev.reconciliation_date, 'due_date_override': rev.due_date_override,
                 'version': record.version}
    elif kind == 'shipment':
        snap = obj.order.supplier_terms_snapshot or {}
        terms = {'days': snap.get('days'), 'start': snap.get('start'), 'reminder_days': snap.get('reminder_days', 7),
                 'reconciliation_date': None, 'due_date_override': None, 'version': 0}
    elif kind in ('batch', 'inbound'):
        snapshot = obj.freight_terms_snapshot if kind == 'batch' else (obj.batch.freight_terms_snapshot or {})
        terms = {'days': snapshot.get('days'), 'start': snapshot.get('start', 'unspecified'), 'reminder_days': snapshot.get('reminder_days', 7),
                 'reconciliation_date': None, 'due_date_override': None, 'version': 0}
    else:
        snapshot = obj.domestic_terms_snapshot or {}
        terms = {'days': snapshot.get('days'),
                 'start': snapshot.get('start', 'unspecified'),
                 'reminder_days': snapshot.get('reminder_days', 7),
                 'reconciliation_date': None, 'due_date_override': None, 'version': 0}
    history = list(record.revisions.order_by('-sequence').values('sequence','days','start','reminder_days','reconciliation_date','due_date_override','reason','created_at')) if record else []
    from .payment_reminders import reminder_query
    reminder = reminder_query(actor, kind).filter(pk=obj.pk).first()
    anchor = reminder.terms_anchor if reminder else None
    due = reminder.terms_due if reminder else None
    status = reminder.terms_status if reminder else 'unknown'
    return {**terms, 'anchor_date': anchor.isoformat() if hasattr(anchor, 'isoformat') else anchor,
            'due_date': due.isoformat() if hasattr(due, 'isoformat') else due,
            'status': status, 'message': ('按本单约定到期日提醒。' if terms.get('due_date_override') else '按起算日期加账期天数计算。' if due else '账期未约定或起算节点未发生，到期日待确认。'), 'history': history}
