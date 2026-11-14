from decimal import Decimal
import pytest
from apps.finance.warehouse_bill_contract import audit_file, difference_state, settlement_facts


@pytest.mark.parametrize('value,state', [('0','no_fee'), ('0.004999','no_fee'),
    ('0.005000','confirmation_required'), ('-0.004999','manual_review'), ('-0.005000','manual_review')])
def test_difference_boundary_uses_original_precision(value, state):
    assert difference_state(value) == state


def test_file_difference_does_not_use_registered_amount_or_selection():
    fact = dict(kind='order', amount='4628.400000', external_order_id='ORDER001', raw_warehouse='WH',
                issues=[], sheet='出库', row=2, reference='row2')
    summary = {'settlement': {'total':'4634.400000', 'order_total':'4628.400000', 'line_difference':'0'},
               'registered_total': '0', 'selected_total':'0'}
    other = {**fact, 'kind':'other', 'amount':'6.000000', 'external_order_id':''}
    _, result = audit_file([fact, other], summary)
    assert result['net_difference'] == '0.000000'
    assert not result['validation']['blocking']
    assert result['file_other_total'] == '6.000000'


def test_other_fees_use_only_invoice_projects():
    source = {'kind':'order', 'raw_warehouse':'SA_01'}
    facts = [source] + [{'kind':'other','raw_warehouse':'SA_01','amount':'1.5'} for _ in range(28)]
    summary = dict(country='MY',bill_month='2026-10',bill_number='bill',settlement={'lines':[
        {'kind':'order','item':'出库','amount':'4628.400000','sheet':'费用账单','row':9},
        {'kind':'other','item':'入库','amount':'6.000000','sheet':'费用账单','row':10}]})
    result = settlement_facts(facts, summary)
    assert len(result) == 2 and result[1]['amount'] == '6.000000'
    assert result[1]['sheet'] == '费用账单' and result[1]['fee_item'] == '入库'


def test_processing_difference_uses_detail_instead_of_invoice_subtotal():
    fact = dict(kind='order', amount='6766.600000', external_order_id='ORDER001',
                raw_warehouse='WH', issues=[], sheet='orders', row=2, reference='row2')
    other = {**fact, 'kind':'other', 'amount':'3234.636984', 'external_order_id':''}
    summary = {'settlement': {'total':'10073.236984', 'order_total':'6838.600000', 'line_difference':'0'}}
    for _ in range(2):
        facts, result = audit_file([fact, other], summary)
        assert len(facts) == 2  # Preview never creates duplicate synthetic source rows.
        assert result['processing_difference'] == '72.000000'
        assert result['net_difference'] == '72.000000'
        assert not result['validation']['blocking']
