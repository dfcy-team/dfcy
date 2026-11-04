from decimal import Decimal
from types import SimpleNamespace
import pytest

from apps.supply_chain.costs import _allocate_source_tax, _prepayment_options
from apps.supply_chain import services
from apps.supply_chain.models import PaymentApplication, PaymentRecord, domain_write
from rest_framework.test import APIClient
from tests.test_supply_chain_v2_foundation import internal_user, world
from tests.test_supply_multi_po_shipments import body, pair

BASE = '/api/internal/supply-chain/v2/'


def prepayment(payment_id, order_id, number, amount):
    return SimpleNamespace(pk=payment_id, purchase_order_id=order_id,
        purchase_order=SimpleNamespace(number=number), reference_number=f'DEP-{payment_id}',
        amount=Decimal(amount))


def test_source_deposits_use_each_po_goods_cap_and_report_source_identity():
    # Shipment lines are 3 * 2.5000 from PO-A and 4 * 3.1234 from PO-B.
    deposits = [prepayment(1, 10, 'PO-A', '20'), prepayment(2, 20, 'PO-B', '20')]
    options, total = _prepayment_options(deposits, {},
        {10: Decimal('7.5000'), 20: Decimal('12.4936')}, {})
    assert {row['purchase_order_number']: Decimal(row['available_amount']) for row in options} == {
        'PO-A': Decimal('7.5000'), 'PO-B': Decimal('12.4936')}
    assert total == Decimal('19.9936')


def test_contract_tax_is_allocated_by_goods_value_with_stable_remainder():
    caps = _allocate_source_tax({10: Decimal('7.5000'), 20: Decimal('12.4936')}, Decimal('2.0000'))
    assert caps == {10: Decimal('8.2502'), 20: Decimal('13.7434')}
    assert sum(caps.values()) == Decimal('21.9936')


def test_source_cap_does_not_depend_on_deposit_row_order():
    deposits = [prepayment(1, 10, 'PO-A', '9'), prepayment(2, 10, 'PO-A', '9')]
    cap = {10: Decimal('10')}
    forward = _prepayment_options(deposits, {}, cap, {})
    reverse = _prepayment_options(list(reversed(deposits)), {}, cap, {})
    assert {row['id']: row['available_amount'] for row in forward[0]} == {1: '9.0000', 2: '9.0000'}
    assert {row['id']: row['available_amount'] for row in reverse[0]} == {1: '9.0000', 2: '9.0000'}
    assert forward[1] == reverse[1] == Decimal('10')


def test_prior_applications_reduce_only_their_source_cap_and_reversal_restores_it():
    deposits = [prepayment(1, 10, 'PO-A', '20'), prepayment(2, 20, 'PO-B', '20')]
    caps = {10: Decimal('7.5'), 20: Decimal('12.4936')}
    applied = {10: Decimal('2.5')}
    active = _prepayment_options(deposits, {1: Decimal('2.5')}, caps, applied)
    assert {row['purchase_order_id']: Decimal(row['available_amount']) for row in active[0]} == {
        10: Decimal('5.0000'), 20: Decimal('12.4936')}
    reversed_application = _prepayment_options(deposits, {}, caps, {})
    assert reversed_application[1] == Decimal('19.9936')


def _multi_shipment(world, buyer):
    first, second = pair(world, buyer)
    shipment = services.create_supplier_shipment(buyer, body(world, first, second),
        idempotency_key='finance-multi-shipment')
    with domain_write():
        shipment.status = 'submitted'
        shipment.save(update_fields=['status'])
    api = APIClient()
    api.force_authenticate(user=buyer)
    return api, first, second, shipment


def _deposit(api, order, suffix):
    account = api.post(BASE + f'costs/purchase/{order.pk}/payee-accounts/', {
        'nature': 'corporate', 'account_name': f'定金账户{suffix}', 'account_holder': '供应商',
        'bank_name': '测试银行', 'account_number': f'622200000000{suffix:04d}', 'active': True,
    }, format='json', HTTP_IDEMPOTENCY_KEY=f'finance-multi-account-{suffix}')
    assert account.status_code == 201, account.data
    payment = api.post(BASE + f'costs/purchase/{order.pk}/payments/', {
        'amount': '20.0000', 'payee_account_id': account.data['data']['account']['id'],
        'date': '2026-10-14', 'expected_version': 0,
    }, format='json', HTTP_IDEMPOTENCY_KEY=f'finance-multi-payment-{suffix}')
    assert payment.status_code == 201, payment.data
    return payment.data['data']['entries'][0]['id']


@pytest.mark.django_db
def test_multipo_apply_rejects_unrelated_source_caps_each_po_and_reversal_restores(world):
    from tests.test_supply_chain_v2_foundation import confirmed_order, po_payload

    buyer = internal_user(world, 'finance-multi')
    api, first, second, shipment = _multi_shipment(world, buyer)
    unrelated = confirmed_order(world, buyer, key='finance-unrelated',
        payload=po_payload(world, number='FINANCE-UNRELATED'))
    deposits = {first.pk: _deposit(api, first, 1001), second.pk: _deposit(api, second, 1002),
        unrelated.pk: _deposit(api, unrelated, 1003)}
    from apps.supply_chain import costs
    state = costs.payment_summary(buyer, 'shipment', shipment.pk)
    options = {row['purchase_order_id']: Decimal(row['available_amount']) for row in state['available_prepayments']}
    assert options == {first.pk: Decimal('7.5000'), second.pk: Decimal('12.4936')}
    unrelated_apply = api.post(BASE + f'costs/shipment/{shipment.pk}/prepayment-applications/', {
        'payment_id': deposits[unrelated.pk], 'amount': '1.0000', 'date': '2026-10-14',
        'expected_version': state['version'],
    }, format='json', HTTP_IDEMPOTENCY_KEY='finance-unrelated-apply')
    assert unrelated_apply.status_code == 422
    app = api.post(BASE + f'costs/shipment/{shipment.pk}/prepayment-applications/', {
        'payment_id': deposits[first.pk], 'amount': '7.5000', 'date': '2026-10-14',
        'expected_version': state['version'],
    }, format='json', HTTP_IDEMPOTENCY_KEY='finance-po-a-apply')
    assert app.status_code == 201, app.data
    state = costs.payment_summary(buyer, 'shipment', shipment.pk)
    overcap = api.post(BASE + f'costs/shipment/{shipment.pk}/prepayment-applications/', {
        'payment_id': deposits[first.pk], 'amount': '0.0001', 'date': '2026-10-14',
        'expected_version': state['version'],
    }, format='json', HTTP_IDEMPOTENCY_KEY='finance-po-a-overcap')
    assert overcap.status_code == 422
    assert PaymentApplication.objects.filter(shipment=shipment, reverses__isnull=True).count() == 1
    application = PaymentApplication.objects.get(shipment=shipment, reverses__isnull=True)
    reversed_response = api.post(BASE + f'costs/shipment/{shipment.pk}/prepayment-applications/{application.pk}/reverse/', {
        'reason': '测试冲销', 'expected_version': state['version'],
    }, format='json', HTTP_IDEMPOTENCY_KEY='finance-po-a-reverse')
    assert reversed_response.status_code == 200, reversed_response.data
    assert costs.payment_summary(buyer, 'shipment', shipment.pk)['summary']['available_prepayment'] == '19.9936'


def test_small_tax_allocation_never_assigns_negative_or_zero_goods_tax():
    from apps.supply_chain.costs import _allocate_source_tax
    goods = {1: Decimal('1'), 2: Decimal('1'), 3: Decimal('1'), 4: Decimal('1'), 5: Decimal('0')}
    caps = _allocate_source_tax(goods, Decimal('0.0002'))
    assert sum(caps.values()) == Decimal('4.0002')
    assert all(caps[key] >= value for key, value in goods.items())
    assert caps[5] == 0
