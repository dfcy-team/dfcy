from decimal import Decimal
import pytest
from django.core.exceptions import ValidationError
from apps.supply_chain import costs, domestic_expenses
from apps.supply_chain.models import PayeeAccount, PaymentRecord, domain_write
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_v2_costs import pilot, mark


@pytest.mark.django_db(transaction=True)
def test_domestic_expense_group_payment_and_replay(world):
    buyer, api, shipment = pilot(world)
    shipment = mark(buyer, shipment)
    body = {'expected_version': shipment.version, 'lines': [
        {'name': '装卸费', 'amount': '500', 'currency': 'CNY',
         'payee_type': 'supplier', 'payee_id': world['supplier_b'].pk,
         'include_in_cost': True, 'method': 'quantity', 'notes': '成本归本单'},
    ]}
    first = domestic_expenses.save(buyer, shipment.pk, body, 'expense-create')
    replay = domestic_expenses.save(buyer, shipment.pk, body, 'expense-create')
    assert first['groups'][0]['id'] == replay['groups'][0]['id']
    group = first['groups'][0]
    summary = costs.payment_summary(buyer, 'domestic_expense', group['id'])
    assert Decimal(summary['summary']['due_amount']) == 500
    with domain_write():
        account = PayeeAccount.objects.create(tenant=buyer.tenant, created_by=buyer,
            supplier=world['supplier_b'], nature='corporate', account_name='B',
            account_holder='B', bank_name='Bank', account_number='123')
    payment = {'expected_version': 0, 'amount': '100', 'date': '2026-11-23',
               'payee_account_id': account.pk, 'currency': 'CNY'}
    paid = costs.create_payment(buyer, 'domestic_expense', group['id'], payment, 'expense-pay')
    assert Decimal(paid['summary']['remaining_amount']) == 400
    row = PaymentRecord.objects.get(domestic_expense_group_id=group['id'])
    assert row.shipment_id == shipment.pk
    assert row.payee_account.supplier_id == world['supplier_b'].pk
    legacy = costs.payment_summary(buyer, 'domestic_freight', shipment.pk)
    assert Decimal(legacy['summary']['paid_amount']) == 0
    shipment.refresh_from_db()
    with pytest.raises(ValidationError, match='付款记录'):
        domestic_expenses.save(buyer, shipment.pk, {**body, 'expected_version': shipment.version}, 'expense-edit')
    reversed_state = costs.reverse_payment(buyer, 'domestic_expense', group['id'], row.pk,
        {'expected_version': paid['version'], 'reason': '退回'}, 'expense-reverse')
    assert Decimal(reversed_state['summary']['paid_amount']) == 0
@pytest.mark.django_db(transaction=True)
def test_domestic_expense_request_list_and_cost(world):
    from tests.test_supply_chain_v2_logistics import BASE, write
    from apps.supply_chain.domestic_expense_costs import amounts, snapshots
    buyer, api, shipment = pilot(world)
    shipment = mark(buyer, shipment)
    payload = {'expected_version': shipment.version, 'lines': [
        {'name': '提货费', 'amount': '60', 'currency': 'CNY', 'payee_type': 'supplier',
         'payee_id': world['supplier_b'].pk, 'include_in_cost': True, 'method': 'quantity'},
        {'name': '其他费用', 'amount': '40', 'currency': 'CNY', 'payee_type': 'supplier',
         'payee_id': world['supplier_b'].pk, 'include_in_cost': False, 'method': 'quantity'},
    ]}
    result = write(api, f'supplier-shipments/{shipment.pk}/domestic-expenses/', payload, 'expense-api', 'put')
    assert result.status_code == 200, result.data
    group_id = result.data['data']['groups'][0]['id']
    issues = []
    allocated = amounts(shipment, snapshots(buyer.tenant_id, [shipment.pk]), issues)
    assert not issues
    assert sum(allocated.values()) == 60
    listed = api.get(BASE + 'cost-targets/', {'kind': 'domestic_expense'})
    assert listed.status_code == 200, listed.data
    assert listed.data['count'] == 1
    account = write(api, f'costs/domestic_expense/{group_id}/payee-accounts/', {
        'nature': 'corporate', 'account_name': 'B account', 'account_holder': 'B',
        'bank_name': 'Bank', 'account_number': '622111', 'active': True,
    }, 'expense-account')
    assert account.status_code == 201, account.data
    req_payload = {'amount': '10', 'currency': 'CNY', 'payee_account_id': account.data['data']['account']['id'], 'reason': '装卸费'}
    endpoint = f'costs/domestic_expense/{group_id}/payment-requests/'
    created = write(api, endpoint, req_payload, 'expense-request')
    assert created.status_code == 201, created.data
    replay = write(api, endpoint, req_payload, 'expense-request')
    assert replay.status_code == 200
    assert replay.data['data']['id'] == created.data['data']['id']
    assert api.get(BASE + endpoint).data['count'] == 1
