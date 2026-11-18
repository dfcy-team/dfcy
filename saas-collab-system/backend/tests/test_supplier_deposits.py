from decimal import Decimal

from apps.supply_chain.models import PaymentRecord, SupplierDepositEntry
from tests.test_supply_chain_v2_foundation import confirmed_order, internal_user, world
from tests.test_supply_chain_v2_logistics import BASE, client, write


def test_supplier_deposit_refund_transfer_and_cash_separation(world):
    actor = internal_user(world)
    order = confirmed_order(world, actor)
    api = client(actor)
    route = 'supplier-deposits/'
    body = {'kind': 'deposit', 'supplier_id': order.supplier_id, 'currency': 'USD',
            'amount': '20', 'date': '2026-10-12', 'reference': 'BANK-001'}
    result = write(api, route, body, 'record')
    assert result.status_code == 200, result.data
    deposit_id = result.data['data']['id']
    assert write(api, route, body, 'record').data['data']['id'] == deposit_id
    assert write(api, route, body, 'different-key').status_code == 400
    refund = {**body, 'kind': 'refund', 'deposit_id': deposit_id, 'amount': '5', 'reference': 'REFUND-001'}
    assert write(api, route, refund, 'refund').status_code == 200
    transfer = {**body, 'kind': 'transfer', 'deposit_id': deposit_id, 'amount': '8',
                'reference': 'TRANSFER-001', 'purchase_order_number': order.number}
    result = write(api, route, transfer, 'transfer')
    assert result.status_code == 200, result.data
    assert write(api, route, {**transfer, 'amount': '8'}, 'transfer-again').status_code == 400
    assert SupplierDepositEntry.objects.count() == 3
    payment = PaymentRecord.objects.get()
    assert payment.purchase_order_id == order.pk and payment.amount == Decimal('8')
    group = api.get(BASE + route).data['data']['groups'][0]
    assert tuple(Decimal(group[key]) for key in ('paid', 'refunded', 'transferred', 'balance')) == (20, 5, 8, 7)
    dashboard = api.get(BASE + 'dashboard/?section=costs').data['data']['groups']
    assert Decimal(dashboard['deposit']['available_prepayment']) == 8
    assert Decimal(dashboard['supplier']['cash_paid_amount']) == 0
    monthly = api.get(BASE + 'dashboard/monthly/', {'queue': 'deposit', 'month': '2026-10'})
    assert monthly.status_code == 200, monthly.data
    summary = monthly.data['data']['summary']
    assert Decimal(summary['paid_amount']) == 0
    assert Decimal(summary['transferred_prepayment_amount']) == 8
    denied = client(internal_user(world, 'own-order-only', scope='own'))
    assert denied.get(BASE + route).data['data']['entries'] == []
    assert write(denied, route, body, 'denied').status_code == 404
