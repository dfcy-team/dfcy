"""Small CNY registration contract; legacy bill facts keep their original policy."""
from decimal import Decimal

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from .warehouse_bill_matching import LocalOrderLookup

MODE = 'cny_simple'
FIELDS = {'kind', 'country', 'warehouse_id', 'external_order_id', 'fee_item',
          'amount', 'bill_month', 'reference', 'note'}


def simple_source(source):
    return (source or {}).get('registration_mode') == MODE


def resolve_number(user, data, source, lookup=None):
    number = source.get('original_order_id', data.get('external_order_id', ''))
    probe = {**data, 'external_order_id': number}
    evidence = {'original_order_id': number, 'lookup_numbers': True}
    result = (lookup or LocalOrderLookup(user, [(probe, evidence)])).resolve(probe, evidence)
    source['matching'] = result
    if result['status'] in {'matched', 'booking_matched', 'reservation_matched'}:
        data.update(store_id=result['store_id'], external_order_id=result['external_order_id'])
        return result['order_id'], 'matched'
    data.update(store_id=None, external_order_id=number)
    return None, 'ambiguous' if result['status'] == 'ambiguous' else 'unmatched'


def prepare_registration(user, supplied, source=None, lookup=None):
    if not isinstance(supplied, dict) or set(supplied) - FIELDS:
        raise ValidationError('简化登记仅支持仓库、国家、单号或费用名称、金额、来源月份及备注。')
    data = dict(supplied)
    if isinstance(data.get('country'), str):
        data['country'] = data['country'].strip()
    number = data.get('external_order_id', '')
    if not isinstance(number, str):
        raise ValidationError('订单号／预约单号／包裹号必须为文本。')
    number = number.strip()
    kind = serializers.ChoiceField(choices=['order', 'other']).run_validation(data.get('kind'))
    if kind == 'order' and not number:
        raise ValidationError('请填写订单号、预约单号、包裹号或完整运单号。')
    if kind == 'other' and number:
        raise ValidationError('其他处理费不填写订单号。')
    reference = serializers.CharField(max_length=191).run_validation(data.get('reference'))
    amount = serializers.DecimalField(max_digits=20, decimal_places=6, min_value=Decimal('0.000001')).run_validation(data.get('amount'))
    data.update(external_order_id=number, store_id=None, currency='CNY',
                reference=reference, bill_number=f"CNY-{data.get('bill_month', '')}", amount=str(amount))
    if kind == 'order':
        data['fee_item'] = '订单处理费'
    source = {**(source or {'type': 'manual'}), 'registration_mode': MODE,
              'original_order_id': number, 'registration_original_amount': str(amount), 'lookup_numbers': True}
    if kind == 'order':
        resolve_number(user, data, source, lookup)
    return data, source
