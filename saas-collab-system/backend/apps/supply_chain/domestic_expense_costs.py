"""Allocate shipment domestic expense lines once, before batch quantity splitting."""
from decimal import Decimal
from django.core.exceptions import ValidationError


def snapshots(tenant_id, shipment_ids):
    from .domestic_expense_models import DomesticExpenseGroup
    return list(DomesticExpenseGroup.objects.filter(
        tenant_id=tenant_id, shipment_id__in=shipment_ids, is_active=True,
    ).order_by('pk').values('id', 'shipment_id', 'version', 'currency', 'lines'))


def amounts(shipment, groups, issues):
    from . import costs, fee_cost_exchange
    result = {line.pk: costs.ZERO for line in costs.source_lines('shipment', shipment)}
    measures = costs.measurements('shipment', shipment)
    for group in groups:
        if group['shipment_id'] != shipment.pk:
            continue
        for line in group['lines']:
            if not line['include_in_cost']:
                continue
            try:
                exchange = line.get('cost_exchange') or {}
                if not exchange and group['currency'] != 'CNY':
                    raise ValidationError('费用缺少已冻结汇率，请重新保存费用。')
                amount = costs.money(fee_cost_exchange.to_cny(Decimal(line['amount']), exchange))
                rows = measures
                method = line['method']
                if method == 'quantity':
                    rows = [{**row, 'volume_cbm': str(row['quantity'])} for row in measures]
                    method = 'volume'
                allocated = costs.allocate(amount, rows, method, 0)
                for row in allocated:
                    pk = row['shipment_line_id']
                    if result[pk] is not None:
                        result[pk] += Decimal(row['amount'])
            except ValidationError as exc:
                issues.append(f"{shipment.number} / {line['name']}：{exc}")
                result = {pk: None for pk in result}
    return result
