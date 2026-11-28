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



def replacement_currency(codes, exchange):
    """Use captured payment evidence; never infer an unrecorded CNY unit."""
    codes = set(codes)
    if (exchange or {}).get('currency'):
        codes.add(exchange['currency'])
    if len(codes) != 1:
        return None
    code = next(iter(codes))
    return code if isinstance(code, str) and len(code) == 3 and code.isascii() and code.isalpha() and code.isupper() else None


def legacy_fee(actor, shipment):
    from . import costs
    from .cost_models import FeeRecord
    from .payment_request_models import SupplyPaymentRequest
    record = FeeRecord.objects.filter(tenant_id=actor.tenant_id, shipment=shipment).select_related('current_revision').first()
    revision = record.current_revision if record else None
    if not revision or revision.amount <= 0:
        return None
    summary = costs.payment_summary(actor, 'domestic_freight', shipment.pk)['summary']
    requested = SupplyPaymentRequest.objects.filter(tenant_id=actor.tenant_id,
        kind='domestic_freight', source_id=shipment.pk).exclude(status='cancelled').exists()
    allowed, explanation = costs.fee_gate('shipment', shipment)
    paid = Decimal(summary['paid_amount'])
    currency = replacement_currency(costs._payment_currency_codes(actor, 'domestic_freight', shipment), revision.cost_exchange)
    return {'id': record.pk, 'version': record.version, 'revision_id': revision.pk,
            'amount': costs.text_number(revision.amount), 'state': revision.state,
            'currency': currency,
            'paid_amount': summary['paid_amount'], 'can_replace': bool(allowed and currency is not None and not paid and not requested),
            'blocked_reason': ('历史费用币种不明确或与付款口径冲突，请先核对原始币种。' if currency is None else '历史费用已有付款或付款申请，请先处理原记录，不能重复录入。' if paid or requested else '' if allowed else explanation)}


def replace_legacy(actor, shipment, payload, key, amount, currency, group_ids):
    from . import costs
    from .cost_models import FeeRecord
    legacy = legacy_fee(actor, shipment)
    if not legacy or payload.get('legacy_expected_version') != legacy['version']:
        raise ValidationError('历史费用版本已变化，请刷新后再选择替换。')
    if not legacy['can_replace']:
        raise ValidationError(legacy['blocked_reason'])
    replacement = costs.decimal(payload.get('legacy_replacement_amount'))
    if replacement != amount or replacement != Decimal(legacy['amount']) or currency != legacy['currency']:
        raise ValidationError('替换须使用同币种、同金额的人工维护记录；其他新增费用请选择另增费用。')
    record = FeeRecord.objects.select_related('current_revision').get(pk=legacy['id'], tenant_id=actor.tenant_id)
    revision = record.current_revision
    correction = {'expected_source_version': shipment.version, 'expected_version': record.version,
        'amount': '0.0000', 'state': 'confirmed',
        'method': revision.method if revision.method in ('volume', 'weight', 'mixed') else 'volume',
        'volume_percent': str(revision.volume_percent if 0 <= revision.volume_percent <= 100 else 100),
        'billed_cbm': None, 'notes': revision.notes,
        'reason': '用户明确以人工维护费用记录替换历史同笔费用；金额不变，保留付款及凭证，历史应付不重复计入。费用组：' + ','.join(map(str,group_ids))}
    costs.save_fee(actor, 'shipment', shipment.pk, correction,
                   'legacy-replace-' + services.request_hash({'key': key}))
    shipment.refresh_from_db()
    return {'historical_fee_id': legacy['id'], 'historical_revision_id': legacy['revision_id'],
            'replacement_group_ids': group_ids, 'replacement_amount': str(replacement),
            'currency': currency, 'decision': 'manual_replace'}


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
        'legacy_fee': legacy_fee(actor, shipment),
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
    # Existing manually maintained, possibly paid group: only resolve the
    # duplicate historical source. Never edit or move its payment/vouchers.
    if payload.get('legacy_action') == 'replace' and payload.get('legacy_group_id') is not None:
        group_id = payload['legacy_group_id']
        if type(group_id) is not int:
            raise ValidationError('请选择人工维护费用记录。')
        group = DomesticExpenseGroup.objects.filter(tenant_id=actor.tenant_id,
            shipment=shipment, is_active=True, pk=group_id).first()
        if group is None:
            raise ValidationError('人工维护费用记录不存在或不在当前单据。')
        audit = replace_legacy(actor, shipment, payload, key, group.amount, group.currency, [group.pk])
        with domain_write():
            services._event(actor, shipment, 'domestic_expenses_saved', key, payload, audit=audit)
        return data(actor, shipment)
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
        method = row.get('method', 'volume')
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
    legacy = legacy_fee(actor, shipment)
    action = payload.get('legacy_action')
    if action not in (None, 'replace', 'additional'):
        raise ValidationError('请选择替换历史同笔费用或另增费用。')
    if legacy and grouped and action not in ('replace', 'additional'):
        raise ValidationError('本单已有历史费用，请明确选择替换历史同笔费用或另增费用；不得重复补录。')
    if action == 'replace':
        if not legacy or len(grouped) != 1:
            raise ValidationError('替换历史同笔费用须选择一笔相同币种的人工维护记录。')
        if payload.get('legacy_expected_version') != legacy['version'] or not legacy['can_replace']:
            raise ValidationError(legacy['blocked_reason'] or '历史费用版本已变化，请刷新。')
        group_key, new_lines = next(iter(grouped.items()))
        new_amount = sum((Decimal(line['amount']) for line in new_lines), Decimal('0'))
        if (new_amount != Decimal(legacy['amount']) or group_key[2] != legacy['currency']
                or services._price(payload.get('legacy_replacement_amount')) != new_amount):
            raise ValidationError('替换须保持原金额及币种；新增装卸费等请选择另增费用。')
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
    saved_groups = []
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
            saved_groups.append(group.pk)
        for group in by_key.values():
            group.is_active = False
            group.version += 1
            group.save()
        shipment.version += 1
        shipment.save()
        audit = {}
        if action == 'replace':
            audit = replace_legacy(actor, shipment, payload, key, new_amount, group_key[2], saved_groups)
        services._event(actor, shipment, 'domestic_expenses_saved', key, payload, audit=audit)
    return data(actor, shipment)
