from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from django.db import close_old_connections, connection, connections
from django.db.models import Sum
from rest_framework.test import APIClient

from apps.supply_chain.cost_models import PaymentRecord
from apps.supply_chain.payment_request_models import SupplyPaymentRequest
from tests.test_supply_payment_request_evidence import (
    _confirm,
    _setup_request,
    _upload,
    world,
    write,
)
from tests.test_supply_chain_v2_logistics import BASE

pytestmark = pytest.mark.django_db(transaction=True)


def _mysql_only():
    if connection.vendor != 'mysql':
        pytest.skip('Requires isolated MySQL/InnoDB tenant row locks.')


def _race(user, actions):
    barrier = Barrier(len(actions))

    def invoke(action):
        close_old_connections()
        try:
            from apps.accounts.models import CustomUser

            actor = CustomUser.objects.get(pk=user.pk)
            client = APIClient()
            client.force_authenticate(user=actor)
            barrier.wait(timeout=10)
            return action(client)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(actions)) as executor:
        futures = [executor.submit(invoke, action) for action in actions]
        return [future.result(timeout=30) for future in futures]


def test_mysql_direct_payment_racing_request_confirmation_keeps_balance_bounded(world, monkeypatch):
    _mysql_only()
    from apps.supply_chain.costs import payment_summary

    buyer, api, shipment, account, row, _approver, _reviewer = _setup_request(world, monkeypatch)
    uploaded = _upload(api, shipment, row)
    assert uploaded.status_code == 201, uploaded.data
    request_row = uploaded.data['data']
    state = payment_summary(buyer, 'shipment', shipment.pk)
    direct_payload = {
        'amount': state['summary']['remaining_amount'],
        'payee_account_id': account['id'],
        'date': '2026-10-14',
        'expected_version': state['version'],
        'reference_number': 'DIRECT-RACE',
    }

    confirm = lambda client: _confirm(client, shipment, request_row, key='race-confirm')
    direct = lambda client: write(
        client,
        f'costs/shipment/{shipment.pk}/payments/',
        direct_payload,
        'race-direct',
    )
    confirmed, direct_result = _race(buyer, [confirm, direct])

    # The submitted request reserves its amount even if direct posting wins the
    # tenant-lock race; only confirmation may consume that reservation.
    assert confirmed.status_code == 200, confirmed.data
    assert direct_result.status_code in (409, 422), direct_result.data
    request_row_db = SupplyPaymentRequest.objects.get(pk=request_row['id'])
    assert request_row_db.payment_id == confirmed.data['data']['payment_id']
    assert PaymentRecord.objects.filter(shipment_id=shipment.pk).count() == 1
    final = payment_summary(buyer, 'shipment', shipment.pk)['summary']
    due = Decimal(final['due_amount'])
    paid = Decimal(final['paid_amount'])
    reserved = SupplyPaymentRequest.objects.filter(
        tenant_id=buyer.tenant_id,
        kind='shipment',
        source_id=shipment.pk,
        status='submitted',
        payment__isnull=True,
    ).aggregate(value=Sum('amount'))['value'] or Decimal('0')
    assert paid + Decimal(final['applied_amount']) + reserved <= due
    replay = _confirm(api, shipment, request_row, key='race-confirm-retry')
    assert replay.status_code == 200 and replay.data['data']['payment_id'] == request_row_db.payment_id
    assert PaymentRecord.objects.filter(shipment_id=shipment.pk).count() == 1


def test_mysql_prepayment_application_racing_request_confirmation_keeps_balance_bounded(world, monkeypatch):
    _mysql_only()
    from apps.supply_chain import costs
    from apps.supply_chain.models import PaymentApplication

    buyer, api, shipment, _account, row, _approver, _reviewer = _setup_request(
        world, monkeypatch, request_amount=None)
    uploaded = _upload(api, shipment, row)
    assert uploaded.status_code == 201, uploaded.data
    request_row = uploaded.data['data']

    order_account = write(api, f'costs/purchase/{shipment.order_id}/payee-accounts/', {
        'nature': 'corporate', 'account_name': '并发定金账户', 'account_holder': '供应商',
        'bank_name': '测试银行', 'account_number': '6222000000003333', 'active': True,
    }, 'deposit-confirm-race-account')
    assert order_account.status_code == 201, order_account.data
    deposit = write(api, f'costs/purchase/{shipment.order_id}/payments/', {
        'amount': '1.0000', 'payee_account_id': order_account.data['data']['account']['id'],
        'date': '2026-10-14', 'expected_version': 0,
    }, 'deposit-confirm-race-payment')
    assert deposit.status_code == 201, deposit.data
    payment_id = deposit.data['data']['entries'][0]['id']
    state = costs.payment_summary(buyer, 'shipment', shipment.pk)
    application_payload = {
        'payment_id': payment_id,
        'amount': '1.0000',
        'date': '2026-10-14',
        'expected_version': state['version'],
    }

    confirm = lambda client: _confirm(client, shipment, request_row, key='deposit-confirm-race')
    apply_deposit = lambda client: client.post(
        f'{BASE}costs/shipment/{shipment.pk}/prepayment-applications/',
        application_payload,
        format='json',
        HTTP_IDEMPOTENCY_KEY='deposit-application-race',
    )
    confirm_result, application_result = _race(buyer, [confirm, apply_deposit])

    assert confirm_result.status_code == 200, confirm_result.data
    assert application_result.status_code in (409, 422), application_result.data
    assert PaymentRecord.objects.filter(shipment_id=shipment.pk).count() == 1
    assert PaymentApplication.objects.filter(shipment_id=shipment.pk).count() == 0

    final = costs.payment_summary(buyer, 'shipment', shipment.pk)['summary']
    due = Decimal(final['due_amount'])
    paid = Decimal(final['paid_amount'])
    applied = Decimal(final['applied_amount'])
    reserved = SupplyPaymentRequest.objects.filter(
        tenant_id=buyer.tenant_id,
        kind='shipment',
        source_id=shipment.pk,
        status='submitted',
        payment__isnull=True,
    ).aggregate(value=Sum('amount'))['value'] or Decimal('0')
    assert paid + applied + reserved <= due
