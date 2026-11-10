"""Stable links between payment plan lines and requests, with derived balances."""
from decimal import Decimal

from rest_framework.exceptions import ValidationError

from .cost_models import PaymentPlanRecord, PaymentRecord
from .payment_request_models import SupplyPaymentRequest


ACTIVE_RESERVATION_STATUSES = ('submitted',)


def line_balances(record, exclude_request_id=None, *, linked_requests=None):
    """Return exact Decimal reserved/paid/remaining/available values by line id."""
    balances = {}
    if not record:
        return balances
    lines = record.lines or []
    line_ids = [str(line.get('line_id') or f'legacy-{record.pk}-{i}') for i, line in enumerate(lines)]
    if linked_requests is None:
        requests = SupplyPaymentRequest.objects.filter(tenant_id=record.tenant_id, plan=record,
            plan_line_id__in=line_ids).select_related('payment').prefetch_related('payment__reversal', 'approval', 'batch__approval')
        if exclude_request_id is not None:
            requests = requests.exclude(pk=exclude_request_id)
    else:
        requests = [req for req in linked_requests if req.tenant_id == record.tenant_id and
                    req.plan_id == record.pk and req.plan_line_id in line_ids and req.pk != exclude_request_id]
    by_line = {line_id: [] for line_id in line_ids}
    for req in requests:
        by_line.setdefault(req.plan_line_id, []).append(req)
    for index, line in enumerate(lines):
        line_id = line_ids[index]
        linked = by_line.get(line_id, [])
        reserved = Decimal(0)
        paid = Decimal(0)
        for request in linked:
            if request.payment_id:
                payment = request.payment
                if payment.reverses_id:
                    continue
                reversed_amount = sum((Decimal(str(item.amount)) for item in payment.reversal.all()), Decimal(0))
                paid += max(Decimal(0), Decimal(str(payment.amount)) - reversed_amount)
            elif request.status == 'submitted':
                rejected = (request.approval_id and request.approval.status in ('rejected', 'withdrawn')) or (
                    request.batch_id and request.batch.approval_id and request.batch.approval.status in ('rejected', 'withdrawn'))
                if not rejected:
                    reserved += Decimal(str(request.amount))
        total = Decimal(str(line.get('amount', '0')))
        remaining = max(Decimal(0), total - paid)
        balances[str(line_id)] = {'line_id': str(line_id), 'has_references': bool(linked), 'reserved_amount': reserved,
            'paid_amount': paid, 'remaining_amount': remaining,
            'available_amount': max(Decimal(0), remaining - reserved)}
    return balances


def has_references(record):
    return SupplyPaymentRequest.objects.filter(plan=record).exists()


def enriched_lines(record):
    balances = line_balances(record)
    result = []
    for index, source in enumerate(record.lines or []):
        line = dict(source)
        line_id = str(line.get('line_id') or f'legacy-{record.pk}-{index}')
        line['line_id'] = line_id
        line.update({key: (value if isinstance(value, bool) else str(value))
                     for key, value in balances.get(line_id, {}).items() if key != 'line_id'})
        result.append(line)
    return result


def find_plan_line(actor, kind, source_id, line_id, plan_version, *, exclude_request_id=None):
    """Validate ownership, version and line identity/currency for request creation."""
    owner = {'shipment': source_id} if kind in ('shipment', 'domestic_freight') else {'batch': source_id}
    plan = PaymentPlanRecord.objects.filter(tenant_id=actor.tenant_id, kind=kind, **owner).first()
    if plan is None:
        raise ValidationError({'plan_line_id': '来源单据尚无付款计划。'})
    if plan.version != plan_version:
        raise ValidationError({'plan_version': '付款计划已变化，请刷新后重试。'})
    line = next((row for index, row in enumerate(plan.lines or [])
                 if str(row.get('line_id') or f'legacy-{plan.pk}-{index}') == str(line_id)), None)
    if line is None:
        raise ValidationError({'plan_line_id': '付款计划明细不存在。'})
    balance = line_balances(plan, exclude_request_id).get(str(line_id))
    return plan, line, balance


def validate_request_link(actor, request, obj, *, exclude_request_id=None):
    """Revalidate immutable line identity and capacity when submitting or posting."""
    if not request.plan_id:
        return None
    plan = PaymentPlanRecord.objects.filter(tenant_id=actor.tenant_id, pk=request.plan_id).first()
    if plan is None or plan.kind != request.kind:
        raise ValidationError('付款计划来源已变化。')
    from .payment_plans import _party
    if plan.party_snapshot != _party(request.kind, obj):
        raise ValidationError('付款计划往来单位已变化。')
    plan, line, balance = find_plan_line(actor, request.kind, request.source_id,
        request.plan_line_id, plan.version)
    identity = (line.get('nature'), line.get('currency') or plan.currency,
                str(line.get('fee_item_id') or ''))
    request_identity = (request.item_snapshot.get('nature') or request.account_snapshot.get('nature'),
        request.currency, str(request.fee_item_id or ''))
    if identity != request_identity:
        raise ValidationError('付款计划明细的性质、币种或费用项目已变化。')
    other = line_balances(plan, exclude_request_id=request.pk)[request.plan_line_id]
    if request.amount > other['available_amount']:
        raise ValidationError('付款计划明细可用金额不足。')
    return line
