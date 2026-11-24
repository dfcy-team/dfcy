"""Precisely revise historical difference settlement; never mutate cash payments."""
from decimal import Decimal
from types import SimpleNamespace
from django.db import transaction
from rest_framework.exceptions import ValidationError
from .models import SettlementRecord, SettlementRevision
from . import services

PREFIX = 'HIST-PH-COUNT-20261106'


@transaction.atomic
def bind_history(actor, selected_rows, revision_id, allocations, reason, request_key):
    """Explicit human attribution; caller supplies freshly authorized source rows."""
    services._tenant_lock(actor)
    if not reason.strip():
        raise ValidationError('请填写原历史凭证差额归属确认依据。')
    record = SettlementRecord.objects.select_for_update().filter(tenant_id=actor.tenant_id, current_revision_id=revision_id).first()
    if not record or not record.current_revision.notes.startswith(PREFIX):
        raise ValidationError('原历史结清凭证不存在或已变化，请刷新。')
    prior = record.current_revision
    eligible = {r['key']: min(Decimal(str(r['amount'])), Decimal(str(r.get('payable_increment', r['amount'])))) for r in selected_rows
                if r['shipment_id'] == record.shipment_id and r['type'] == 'over'}
    snapshot = dict(prior.source_snapshot)
    mapping = dict(snapshot.get('receipt_difference_allocations', {}))
    for key, value in allocations.items():
        amount = Decimal(str(value))
        if key not in eligible or not amount.is_finite() or amount <= 0 or amount > eligible[key]:
            raise ValidationError('归属金额必须属于本发货单多到明细且不超过差额。')
        if key in mapping and Decimal(str(mapping[key])) != amount:
            raise ValidationError('该差额已登记不同归属金额，请核实原记录。')
        mapping[key] = str(amount)
    if not allocations or sum((Decimal(v) for v in mapping.values()), Decimal(0)) > prior.recorded_amount:
        raise ValidationError('确认归属合计不能超过原历史结清余额。')
    snapshot.update(receipt_difference_allocations=mapping, attribution_prior_revision_id=prior.pk,
                    attribution_request_key=request_key, attribution_reason=reason)
    with services.domain_write():
        record.version += 1
        revision = SettlementRevision.objects.create(tenant_id=actor.tenant_id, created_by=actor,
            settlement=record, sequence=record.version, recorded_amount=prior.recorded_amount,
            reference_number=prior.reference_number, date=prior.date, notes=prior.notes,
            reason=reason, source_snapshot=snapshot, payee_allocations=prior.payee_allocations)
        record.current_revision = revision
        record.save()
    return revision.pk


def allocation_plan(snapshot, selected_keys, recorded_amount):
    allocations = snapshot.get('receipt_difference_allocations', {})
    if not isinstance(allocations, dict) or not set(selected_keys).issubset(allocations):
        raise ValidationError('历史结清凭证缺少对应商品差额明细，请先核实原结清归属，不能按整笔金额自动撤销。')
    amounts = {key: Decimal(str(value)) for key, value in allocations.items()}
    if any(not value.is_finite() or value < 0 for value in amounts.values()):
        raise ValidationError('历史结清明细金额无效。')
    total = Decimal(str(recorded_amount))
    if sum(amounts.values(), Decimal(0)) > total:
        raise ValidationError('历史结清明细超过原凭证金额。')
    reduction = sum((amounts[key] for key in set(selected_keys)), Decimal(0))
    return reduction, {key: str(value) for key, value in amounts.items() if key not in selected_keys}


def _restore_projection(actor, record, decision, prior):
    """Shared read-only plan for preview and the eventual append-only restore."""
    applied = decision.source_snapshot.get('history_applied')
    if not applied:
        return dict(prior.source_snapshot), prior.recorded_amount
    if decision.tenant_id != actor.tenant_id or decision.shipment_id != record.shipment_id:
        raise ValidationError('原历史结清归属不匹配。')
    token = str(decision.pk)
    source = SettlementRevision.objects.filter(pk=applied['revision_id'], settlement=record, tenant_id=actor.tenant_id).first()
    key = decision.source_key
    amount = Decimal(str(applied['amount']))
    source_map = source.source_snapshot.get('receipt_difference_allocations', {}) if source else {}
    if not source or not source.notes.startswith(PREFIX) or not amount.is_finite() or amount <= 0 or Decimal(str(source_map.get(key, 0))) != amount:
        raise ValidationError('原历史结清扣减依据不完整，不能恢复。')
    snapshot = dict(prior.source_snapshot)
    restored = list(snapshot.get('restored_receipt_decisions', []))
    if token in restored:
        raise ValidationError('该历史结清扣减已恢复，请刷新。')
    mapping = dict(snapshot.get('receipt_difference_allocations', {}))
    if key in mapping:
        raise ValidationError('该差额已有新的历史归属，请核实后调整。')
    if prior.payee_allocations or not prior.notes.startswith(PREFIX):
        raise ValidationError('原历史结清已发生其他处理，请核实后调整。')
    mapping[key] = str(amount)
    snapshot.update(receipt_difference_allocations=mapping, restored_receipt_decisions=restored+[token],
                    restores_decision_id=decision.pk)
    return snapshot, prior.recorded_amount + amount


def preview_history(actor, selected_rows, *, restoring=()):
    grouped = {}
    caps = {}
    for row in selected_rows:
        cap = Decimal(str(row.get('payable_increment', row.get('amount') or '0')))
        if row['type'] == 'over' and cap > 0:
            grouped.setdefault(row['shipment_id'], []).append(row['key'])
            caps[row['key']] = cap
    restoring = [d for d in restoring if d.source_snapshot.get('history_applied')]
    shipment_ids = set(grouped) | {d.shipment_id for d in restoring}
    plans = []
    seen_shipments = set()
    for record in SettlementRecord.objects.filter(tenant_id=actor.tenant_id, shipment_id__in=shipment_ids).select_related('current_revision'):
        seen_shipments.add(record.shipment_id)
        revision = record.current_revision
        if not revision:
            if any(d.shipment_id == record.shipment_id for d in restoring):
                raise ValidationError('原历史结清凭证不存在或已变化，请刷新。')
            continue
        projected = SimpleNamespace(pk=revision.pk, source_snapshot=dict(revision.source_snapshot),
            recorded_amount=revision.recorded_amount, notes=revision.notes, payee_allocations=revision.payee_allocations)
        for decision in restoring:
            if decision.shipment_id == record.shipment_id:
                projected.source_snapshot, projected.recorded_amount = _restore_projection(actor, record, decision, projected)
        keys = grouped.get(record.shipment_id, [])
        if not keys or not projected.notes.startswith(PREFIX) or not projected.recorded_amount:
            continue
        if projected.payee_allocations:
            raise ValidationError('原结清已有账户分配，请先核实对应账户明细后调整。')
        reduction, remaining = allocation_plan(projected.source_snapshot, keys, projected.recorded_amount)
        allocations = {key: str(projected.source_snapshot['receipt_difference_allocations'][key]) for key in keys}
        if any(Decimal(value) > caps[key] for key, value in allocations.items()):
            raise ValidationError('历史结清归属超过实际新增应付，请核实对应明细。')
        plans.append(dict(record_id=record.pk, revision_id=revision.pk, shipment_id=record.shipment_id,
                          reduction=str(reduction), remaining_allocations=remaining, allocations=allocations))
    if {d.shipment_id for d in restoring} - seen_shipments:
        raise ValidationError('原历史结清凭证不存在或已变化，请刷新。')
    return plans


@transaction.atomic
def restore_history(actor, decision, reason):
    """Reverse only the historical deduction frozen on this decision."""
    services._tenant_lock(actor)
    applied = decision.source_snapshot.get('history_applied')
    if not applied:
        return None
    record = SettlementRecord.objects.select_for_update().get(tenant_id=actor.tenant_id, shipment_id=decision.shipment_id)
    prior = record.current_revision
    snapshot, restored_amount = _restore_projection(actor, record, decision, prior)
    snapshot['restore_reason'] = reason
    with services.domain_write():
        record.version += 1
        revision = SettlementRevision.objects.create(tenant_id=actor.tenant_id, created_by=actor,
            settlement=record, sequence=record.version, recorded_amount=restored_amount,
            reference_number=prior.reference_number, date=prior.date, notes=prior.notes,
            reason=reason, source_snapshot=snapshot, payee_allocations=[])
        record.current_revision = revision
        record.save()
    return revision.pk


@transaction.atomic
def confirm_history(actor, selected_rows, reason, request_key):
    services._tenant_lock(actor)
    plans = preview_history(actor, selected_rows)
    if plans and not reason.strip():
        raise ValidationError('请填写调整原结清凭证的依据。')
    with services.domain_write():
        for plan in plans:
            record = SettlementRecord.objects.select_for_update().get(tenant_id=actor.tenant_id, pk=plan['record_id'])
            prior = record.current_revision
            if prior.pk != plan['revision_id']:
                raise ValidationError('原结清凭证已变化，请重新预览。')
            snapshot = dict(prior.source_snapshot)
            snapshot.update(receipt_difference_allocations=plan['remaining_allocations'], adjusts_revision_id=prior.pk,
                            adjustment_request_key=request_key, adjusted_amount=plan['reduction'])
            record.version += 1
            revision = SettlementRevision.objects.create(tenant_id=actor.tenant_id, created_by=actor,
                settlement=record, sequence=record.version,
                recorded_amount=prior.recorded_amount-Decimal(plan['reduction']),
                reference_number=prior.reference_number, date=prior.date, notes=prior.notes,
                reason=reason, source_snapshot=snapshot, payee_allocations=prior.payee_allocations)
            # Account allocations cannot be reduced without identifying the original allocation.
            if prior.payee_allocations:
                raise ValidationError('原结清已有账户分配，请先核实对应账户明细后调整。')
            record.current_revision=revision
            record.save()
    return plans
