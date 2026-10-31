"""Contractual tax arithmetic; rates are explicitly maintained, never inferred."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django.core.exceptions import ValidationError


def rate_value(value):
    if value is None or value == '':
        return None
    try:
        rate = Decimal(str(value))
        if not rate.is_finite() or not 0 <= rate <= 100 or rate != rate.quantize(Decimal('.001')):
            raise ValueError
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError('税点须为0至100的数字，最多3位小数；未维护不能当作0。')
    return rate


def inclusive_tax(amount, rate):
    if rate is None:
        return {'pricing_basis': 'gross_inclusive', 'tax_rate': None, 'tax_amount': None, 'net_amount': None}
    rate = rate_value(rate)
    tax = (amount - amount / (Decimal(1) + rate / 100)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    return {'pricing_basis': 'gross_inclusive', 'tax_rate': str(rate), 'tax_amount': str(tax), 'net_amount': str(amount - tax)}


def contract_cost_allocations(shipments):
    """Use the issued contract's per-source-line tax snapshot without flattening rates."""
    from .models import PurchaseContract, ShipmentLine
    ids = list(shipments)
    if not ids:
        return []
    contracts = list(PurchaseContract.objects.filter(shipment_id__in=ids, status='issued', cost_tax_amount__gt=0).order_by('shipment_id'))
    if not contracts:
        return []
    grouped = {}
    for line in ShipmentLine.objects.filter(shipment_id__in=[c.shipment_id for c in contracts], is_active=True).order_by('pk'):
        grouped.setdefault(line.shipment_id, []).append(line)
    result = []
    for contract in contracts:
        source_lines = {line.pk: line for line in grouped.get(contract.shipment_id, [])}
        line_taxes = {}
        for row in (contract.payload or {}).get('lines', []):
            source_id = row.get('source_line_id')
            if source_id is None or source_id not in source_lines or source_id in line_taxes or row.get('tax_amount') is None:
                raise ValidationError('免税合同税费快照与发货单商品不匹配。')
            line_taxes[source_id] = Decimal(str(row['tax_amount']))
        if set(line_taxes) != set(source_lines) or sum(line_taxes.values(), Decimal(0)) != contract.cost_tax_amount:
            raise ValidationError('免税合同逐行税费合计与合同成本税额不一致。')
        lines = sorted(source_lines.values(), key=lambda line: line.pk)
        result.append({'contract_id':contract.pk,'shipment_id':contract.shipment_id,'amount':str(contract.cost_tax_amount),
            'allocations':[{'shipment_line_id':line.pk,'quantity':line.quantity,'amount':str(line_taxes[line.pk])} for line in lines]})
    return result
