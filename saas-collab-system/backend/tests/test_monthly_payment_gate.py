from types import SimpleNamespace
from unittest.mock import patch

from apps.supply_chain.monthly_payment_gate import payment_state


def _summary(due, paid, remaining):
    return {'summary': {'due_amount': due, 'paid_amount': paid,
                        'remaining_amount': remaining}}


def test_gate_distinguishes_goods_and_recorded_fee_payment_and_ignores_unrecorded():
    inbound = SimpleNamespace(pk=12)
    member = SimpleNamespace(shipment_id=9)
    batch = SimpleNamespace(pk=4, memberships=SimpleNamespace(
        filter=lambda **kwargs: SimpleNamespace(select_related=lambda *args: SimpleNamespace(order_by=lambda field: [member]))), inbound_orders=SimpleNamespace(
        filter=lambda **kwargs: SimpleNamespace(order_by=lambda field: [inbound])))
    batch_state = {**_summary('100', '100', '0'), 'fee_items': [
        {'fee_item_id': 1, 'name': 'freight', 'amount': '10', 'paid_amount': '5', 'remaining_amount': '5'}]}
    inbound_state = {**_summary('20', '0', '20'), 'fee_items': [
        {'fee_item_id': 2, 'name': 'clearance', 'amount': '8', 'paid_amount': '8', 'remaining_amount': '0'}]}
    with patch('apps.supply_chain.monthly_payment_gate.costs.payment_summary',
               side_effect=[_summary('100', '100', '0'), batch_state, inbound_state]), \
             patch('apps.supply_chain.domestic_expense_models.DomesticExpenseGroup.objects.filter',
                   return_value=SimpleNamespace(order_by=lambda field: [])):
        state = payment_state(SimpleNamespace(tenant_id=1), batch)
    assert state['goods']['state'] == 'paid'
    assert state['recorded_fees_state'] == 'unpaid'
    assert state['recorded_fees'][1]['state'] == 'paid'
    assert state['ready'] is False
    assert len(state['recorded_fees']) == 2


def test_unknown_goods_amount_is_not_treated_as_paid():
    batch = SimpleNamespace(pk=5, memberships=SimpleNamespace(
        filter=lambda **kwargs: SimpleNamespace(select_related=lambda *args: SimpleNamespace(order_by=lambda field: []))), inbound_orders=SimpleNamespace(
        filter=lambda **kwargs: SimpleNamespace(order_by=lambda field: [])))
    with patch('apps.supply_chain.monthly_payment_gate.costs.payment_summary',
               return_value=_summary(None, '0', None)), \
             patch('apps.supply_chain.domestic_expense_models.DomesticExpenseGroup.objects.filter',
                   return_value=SimpleNamespace(order_by=lambda field: [])):
        state = payment_state(SimpleNamespace(tenant_id=1), batch)
    assert state['goods']['state'] == 'unknown'
    assert state['ready'] is False
