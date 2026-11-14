from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from . import logistics, services
from .cost_models import PaymentRecord, PaymentCurrencyConfirmation
from .models import BusinessEvent, domain_write
from .permissions import MANAGE

ACTION = 'batch_cash_classified'


def payment_groups(tenant_id, payments):
    groups = defaultdict(list)
    confirmations = dict(PaymentCurrencyConfirmation.objects.filter(
        tenant_id=tenant_id, payment_id__in=[p.pk for p in payments],
    ).values_list('payment_id', 'currency'))
    for p in payments:
        if p.reverses_id:
            continue
        currency = (p.account_snapshot or {}).get('currency') or confirmations.get(p.pk)
        groups[p.batch_id, p.date.isoformat()[:7], currency].append(p)
    return groups


def fingerprint(payments):
    return services.request_hash(sorted((p.pk, str(p.amount), p.date.isoformat()) for p in payments))


@transaction.atomic
def confirm(actor, batch_id, month, currency, corporate, personal, key):
    services._internal(actor)
    services._tenant_lock(actor)
    batch = logistics.batch_for(actor, batch_id, MANAGE)
    if batch.status != 'active':
        raise ValidationError('只能确认有效发运批次的付款性质。')
    rows = list(PaymentRecord.objects.filter(tenant_id=actor.tenant_id, batch=batch,
        date__year=int(month[:4]), date__month=int(month[5:]), purpose='goods',
        reverses__isnull=True, reversal__isnull=True))
    rows = payment_groups(actor.tenant_id, rows).get((batch_id, month, currency), [])
    total = sum((p.amount for p in rows), Decimal(0))
    if not rows or min(corporate, personal) < 0 or corporate + personal != total:
        raise ValidationError('对公与对私合计必须等于该批次当月同币种有效付款。')
    payload = dict(month=month, currency=currency, corporate=str(corporate), personal=str(personal),
                   fingerprint=fingerprint(rows))
    with domain_write():
        return services._prior_event(actor, batch, ACTION, key, payload) or services._event(
            actor, batch, ACTION, key, payload)


def confirmed_groups(tenant_id, payments):
    groups = payment_groups(tenant_id, payments)
    if not groups:
        return {}
    reversed_ids = set(PaymentRecord.objects.filter(
        tenant_id=tenant_id, reverses_id__in=[p.pk for rows in groups.values() for p in rows],
    ).values_list('reverses_id', flat=True))
    result = {}
    seen = set()
    events = BusinessEvent.objects.filter(tenant_id=tenant_id, aggregate_type='dispatchbatch',
        aggregate_id__in={k[0] for k in groups}, action=ACTION).order_by('-pk')
    for event in events:
        data = event.payload
        key = event.aggregate_id, data['month'], data['currency']
        if key in seen:
            continue
        seen.add(key)
        rows = groups.get(key, [])
        if not rows or any(p.pk in reversed_ids for p in rows) or fingerprint(rows) != data['fingerprint']:
            continue
        result[key] = (rows, {n: Decimal(data[n]) for n in ('corporate', 'personal')})
    return result
