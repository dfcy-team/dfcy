"""Versioned domestic expense maintenance on a supplier shipment."""
from collections import defaultdict
from decimal import Decimal
import re

from django.core.exceptions import ValidationError
from django.db import transaction

from . import archives, services, shipments
from .domestic_expense_models import DomesticExpenseGroup
from .models import domain_write
from .permissions import VIEW, MANAGE


def data(actor, shipment):
    from .costs import text_number
    from . import costs
    groups = DomesticExpenseGroup.objects.filter(
        tenant_id=actor.tenant_id, shipment=shipment, is_active=True,
    ).select_related('supplier', 'carrier').order_by('pk')
    groups = list(groups)
    from .payment_request_models import SupplyPaymentRequest
    from django.db.models import Sum
    balances = {}
    reservations = {}
    for group in groups:
        reservations[group.pk] = SupplyPaymentRequest.objects.filter(
            tenant_id=actor.tenant_id, kind='domestic_expense', source_id=group.pk,
            status='submitted', payment__isnull=True,
        ).exclude(approval__status__in=['rejected', 'withdrawn']).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        balances[group.pk] = costs.payment_summary(actor, 'domestic_expense', group.pk)['summary']
    return {
        'version': shipment.version,
        'suppliers': list(archives.allowed_suppliers(actor, VIEW).values('id', 'name')),
        'carriers': list(archives.freight_scope(actor, VIEW).values('id', 'name')),
        'lines': [dict(line, payee_type='supplier' if group.supplier_id else 'carrier', payee_id=group.supplier_id or group.carrier_id, currency=group.currency) for group in groups for line in group.lines],
        'groups': [{
            'id': group.pk, 'version': group.version,
            'payee_type': 'supplier' if group.supplier_id else 'carrier',
            'payee_id': group.supplier_id or group.carrier_id,
            'payee_name': (group.supplier or group.carrier).name,
            'currency': group.currency, 'amount': text_number(group.amount),
            'paid_amount': balances[group.pk]['paid_amount'],
            'requested_amount': text_number(reservations[group.pk]),
            'remaining_amount': balances[group.pk]['remaining_amount'],
            'lines': group.lines,
        } for group in groups],
    }


def read(actor, pk):
    return data(actor, shipments.shipment_for(actor, pk, VIEW))


@transaction.atomic
def save(actor, pk, payload, key):
    services._internal(actor)
    services._tenant_lock(actor)
    shipment = shipments.shipment_for(actor, pk, MANAGE)
    event = services._prior_event(actor, shipment, 'domestic_expenses_saved', key, payload)
    if event:
        return data(actor, shipment)
    services._version(shipment, payload.get('expected_version'))
    if shipment.status == 'cancelled':
        raise ValidationError('已作废发货单不能维护费用。')
    rows = payload.get('lines')
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValidationError('费用明细最多 100 行。')
    grouped = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict):
            raise ValidationError('费用明细格式不正确。')
        name = str(row.get('name') or '').strip()
        currency = str(row.get('currency') or '').strip().upper()
        kind = row.get('payee_type')
        pk = row.get('payee_id')
        if not name or len(name) > 100 or not re.fullmatch('[A-Z]{3}', currency):
            raise ValidationError('请填写费用名称及三位币种编码。')
        if type(pk) is not int or pk <= 0 or kind not in ('supplier', 'carrier'):
            raise ValidationError('请选择费用收款单位。')
        query = archives.allowed_suppliers(actor, MANAGE) if kind == 'supplier' else archives.freight_scope(actor, MANAGE)
        if not query.filter(pk=pk).exists():
            raise ValidationError('收款单位不存在或不在授权范围。')
        amount = services._price(row.get('amount'))
        method = row.get('method', 'quantity')
        if method not in ('quantity', 'volume', 'weight'):
            raise ValidationError('费用分摊方式无效。')
        include = row.get('include_in_cost', True)
        if type(include) is not bool:
            raise ValidationError('是否计入成本须为布尔值。')
        notes = str(row.get('notes') or '').strip()
        if len(notes) > 10000:
            raise ValidationError('费用备注不能超过 10000 字。')
        from .fee_cost_exchange import resolve
        cost_exchange = resolve(actor.tenant, {'currency': currency}, {}) if include else {}
        grouped[kind, pk, currency].append({
            'name': name, 'amount': format(amount, '.4f'), 'method': method,
            'include_in_cost': include, 'notes': notes, 'cost_exchange': cost_exchange,
        })
    existing = list(DomesticExpenseGroup.objects.filter(tenant_id=actor.tenant_id, shipment=shipment, is_active=True))
    # A submitted payment request must reserve the exact group snapshot.
    from .payment_request_models import SupplyPaymentRequest
    if SupplyPaymentRequest.objects.filter(tenant_id=actor.tenant_id, kind='domestic_expense',
            source_id__in=[group.pk for group in existing]).exclude(status='cancelled').exists():
        raise ValidationError('国内运输费用已有付款申请，请先处理申请后再调整。')
    from .cost_models import PaymentRecord
    if hasattr(PaymentRecord, 'domestic_expense_group'):
        if PaymentRecord.objects.filter(domestic_expense_group__in=existing).exists():
            raise ValidationError('国内运输费用已有付款记录，请通过费用更正处理。')
    with domain_write():
        by_key = {('supplier' if group.supplier_id else 'carrier',
                   group.supplier_id or group.carrier_id, group.currency): group for group in existing}
        for group_key, lines in grouped.items():
            kind, payee, currency = group_key
            group = by_key.pop(group_key, None)
            if group is None:
                group = DomesticExpenseGroup(
                    tenant=actor.tenant, created_by=actor, shipment=shipment,
                    supplier_id=payee if kind == 'supplier' else None,
                    carrier_id=payee if kind == 'carrier' else None, currency=currency,
                )
            group.lines = lines
            group.amount = sum((Decimal(row['amount']) for row in lines), Decimal('0'))
            group.version = (group.version or 0) + 1
            group.save()
        for group in by_key.values():
            group.is_active = False
            group.version += 1
            group.save()
        shipment.version += 1
        shipment.save()
        services._event(actor, shipment, 'domestic_expenses_saved', key, payload)
    return data(actor, shipment)
