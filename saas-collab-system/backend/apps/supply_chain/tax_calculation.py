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
    """One batch read of tax-bearing contracts and source lines; split each tax exactly once."""
    from .models import PurchaseContract, ShipmentLine
    from decimal import localcontext, ROUND_FLOOR
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
    with localcontext() as context:
        context.prec = 60
        for contract in contracts:
            lines = grouped.get(contract.shipment_id, [])
            if not lines or any(line.unit_price is None for line in lines):
                raise ValidationError('免税合同税费分摊需要完整的发货单商品及未税单价。')
            weights = {line.pk: line.unit_price * line.quantity for line in lines}
            if not sum(weights.values()):
                weights = {line.pk: Decimal(line.quantity) for line in lines}
            total = sum(weights.values())
            units = int(contract.cost_tax_amount * 10000)
            raw = {pk: Decimal(units) * weight / total for pk, weight in weights.items()}
            allocated = {pk: int(value.to_integral_value(rounding=ROUND_FLOOR)) for pk,value in raw.items()}
            for pk in sorted(raw, key=lambda key: (-(raw[key]-allocated[key]),key))[:units-sum(allocated.values())]:
                allocated[pk] += 1
            result.append({'contract_id':contract.pk,'shipment_id':contract.shipment_id,'amount':str(contract.cost_tax_amount),
                'allocations':[{'shipment_line_id':line.pk,'quantity':line.quantity,'amount':str(Decimal(allocated[line.pk])/10000)} for line in lines]})
    return result
