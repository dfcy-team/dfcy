from decimal import Decimal

import pytest

from apps.supply_chain import services
from apps.supply_chain.models import PaymentRecord, CostVersion
from tests.test_supply_chain_v2_costs import pilot, get, mark, fee, calculate
from tests.test_supply_chain_v2_logistics import BASE, write
from tests.test_supply_chain_v2_foundation import world, confirmed_order, po_payload, shipment_payload
from tests.test_supply_chain_v2_foundation import freight


def account(api, kind, obj, *, owner_supplier_id=None):
    pk = obj.pk if hasattr(obj, 'pk') else obj
    data = {'nature': 'corporate', 'account_name': 'Supplier account', 'account_holder': 'Supplier',
            'bank_name': 'Bank', 'account_number': '9988776655', 'active': True}
    response = write(api, f'costs/{kind}/{pk}/payee-accounts/', data, f'account-{kind}-{pk}')
    assert response.status_code == 201, response.data
    return response.data['data']['account']['id']


@pytest.mark.django_db(transaction=True)
def test_payment_replay_partial_prepayment_reversal_and_cost_is_unchanged(world):
    buyer, api, shipment = pilot(world)
    order = shipment.order
    account_id = account(api, 'purchase', order)
    before_costs = (shipment.lines.count(), PaymentRecord.objects.count())
    url = f'costs/purchase/{order.pk}/payments/'
    body = {'amount': '1.0000', 'date': '2026-10-14', 'payee_account_id': account_id,
            'expected_version': 0, 'notes': '预付款'}
    first = write(api, url, body, 'purchase-prepay')
    assert first.status_code == 201, first.data
    replay = write(api, url, body, 'purchase-prepay')
    assert replay.status_code == 201 and replay.data['data']['version'] == 1
    assert PaymentRecord.objects.filter(purchase_order=order).count() == 1
    prepayment_id = first.data['data']['entries'][0]['id']
    assert first.data['data']['entries'][0]['account_snapshot']['account_number'].endswith('6655')

    shipment = mark(buyer, shipment)
    # A partial application reduces the remaining available amount and can be reversed immutably.
    apply_url = f'costs/shipment/{shipment.pk}/prepayment-applications/'
    application = write(api, apply_url, {'payment_id': prepayment_id, 'amount': '0.4000',
        'date': '2026-10-15', 'expected_version': 0}, 'apply-part')
    assert application.status_code == 201, application.data
    assert application.data['data']['summary']['applied_amount'] == '0.4000'
    app_row = next(row for row in application.data['data']['entries'] if row['entry_type'] == 'application')
    assert app_row['related_href'] == ''  # shipment view retains source purchase link
    assert app_row['source_kind'] == 'purchase'
    assert app_row['source_id'] == order.pk
    assert app_row['cash_change'] == '0.0000'
    purchase_process = api.get(BASE + url).data['data']
    purchase_app = next(row for row in purchase_process['entries'] if row['entry_type'] == 'application')
    assert purchase_app['related_href'] == f'/supply-chain/costs?kind=shipment&id={shipment.pk}'
    assert purchase_app['available_after'] == '0.6000'
    purchase_summary = api.get(BASE + url).data['data']['summary']
    assert purchase_summary['applied_amount'] == '0.4000'
    assert purchase_summary['paid_amount'] == '1.0000'
    assert purchase_summary['available_prepayment'] == '0.6000'
    current_context = get(api, 'shipment', shipment)
    legacy_after_application = write(api, f'costs/shipment/{shipment.pk}/settlement/', {
        'expected_source_version': current_context['target']['version'], 'expected_version': 0,
        'recorded_amount': '0.4000', 'reference_number': 'DUPLICATE-APPLY', 'date': '2026-10-15',
        'reason': '不得重复登记抵扣'}, 'legacy-after-application')
    assert legacy_after_application.status_code == 422
    assert application.data['data']['available_prepayments'][0]['available_amount'] == '0.6000'
    app_id = next(row['id'] for row in application.data['data']['entries'] if row['entry_type'] == 'application')
    blocked = write(api, f'costs/purchase/{order.pk}/payments/{prepayment_id}/reverse/',
        {'reason': '误登', 'expected_version': 1}, 'reverse-prepay-blocked')
    assert blocked.status_code == 422
    app_reverse = write(api, f'costs/shipment/{shipment.pk}/prepayment-applications/{app_id}/reverse/',
        {'reason': '撤销错误抵扣', 'expected_version': 1}, 'reverse-app')
    assert app_reverse.status_code == 200, app_reverse.data
    assert app_reverse.data['data']['summary']['applied_amount'] == '0.0000'
    reversed_payment = write(api, f'costs/purchase/{order.pk}/payments/{prepayment_id}/reverse/',
        {'reason': '冲销错误预付款', 'expected_version': 1}, 'reverse-prepay')
    assert reversed_payment.status_code == 200, reversed_payment.data
    assert reversed_payment.data['data']['summary']['paid_amount'] == '0.0000'
    assert reversed_payment.data['data']['summary']['available_prepayment'] == '0.0000'
    spent_again = write(api, apply_url, {'payment_id': prepayment_id, 'amount': '0.1000',
        'date': '2026-10-16', 'expected_version': 2}, 'apply-reversed-prepay')
    assert spent_again.status_code == 422
    assert before_costs[0] == shipment.lines.count()


@pytest.mark.django_db(transaction=True)
def test_cross_purchase_and_foreign_tenant_payments_are_rejected(world):
    buyer, api, shipment = pilot(world)
    foreign_id = account(api, 'purchase', shipment.order)
    order2 = confirmed_order(world, buyer, key='payment-other-order',
        payload=po_payload(world, number='PO-OTHER-PAYMENT'))
    # A prepayment attached to one order cannot be applied to a different order's shipment.
    body = {'amount': '1.0000', 'date': '2026-10-14', 'payee_account_id': foreign_id, 'expected_version': 0}
    prepayment = write(api, f'costs/purchase/{shipment.order_id}/payments/', body, 'source-prepayment')
    assert prepayment.status_code == 201
    target_shipment = services.create_supplier_shipment(buyer,
        shipment_payload(world, order2, 'other-payment-shipment', number='SH-OTHER-PAYMENT'),
        idempotency_key='other-payment-shipment')
    # Ownership is rejected before payment amount semantics are evaluated.
    rejected = write(api, f'costs/shipment/{target_shipment.pk}/prepayment-applications/', {
        'payment_id': prepayment.data['data']['entries'][0]['id'], 'amount': '0.5000',
        'date': '2026-10-15', 'expected_version': 0}, 'cross-order-apply')
    assert rejected.status_code == 422
    foreign_tenant = world['tenant'].__class__.objects.create(name='Other tenant', code='other-payment-tenant')
    from apps.accounts.models import CustomUser
    user = CustomUser.objects.create_user(username='foreign-payment', tenant=foreign_tenant,
        user_type=CustomUser.UserType.INTERNAL)
    # The target is not visible through the other tenant's cost route.
    foreign_api = api.__class__()
    foreign_api.force_authenticate(user)
    assert foreign_api.get(BASE + f'costs/purchase/{shipment.order_id}/payments/').status_code in (403, 404)


@pytest.mark.django_db(transaction=True)
def test_supplier_and_freight_company_payee_archive_contexts(world):
    buyer, api, shipment = pilot(world)
    supplier_url = f'costs/supplier/{world["supplier"].pk}/payee-accounts/'
    freight_company = freight(world)
    freight_url = f'costs/freight_company/{freight_company.pk}/payee-accounts/'
    body = {'nature': 'corporate', 'account_name': 'Archive account', 'account_holder': 'Holder',
            'bank_name': 'Bank', 'account_number': '1234567890', 'active': True}
    supplier_result = write(api, supplier_url, body, 'supplier-archive-account')
    freight_result = write(api, freight_url, body, 'freight-archive-account')
    assert supplier_result.status_code == freight_result.status_code == 201
    assert api.get(BASE + supplier_url).data['data']['accounts'][0]['account_number'].endswith('7890')
    assert api.get(BASE + freight_url).data['data']['accounts'][0]['account_number'].endswith('7890')


@pytest.mark.django_db(transaction=True)
def test_legacy_cumulative_settlement_becomes_opening_and_cannot_be_overwritten(world):
    buyer, api, shipment = pilot(world)
    shipment = mark(buyer, shipment)
    context = get(api, 'shipment', shipment)
    legacy = write(api, f'costs/shipment/{shipment.pk}/settlement/', {
        'expected_source_version': context['target']['version'], 'expected_version': 0,
        'recorded_amount': '1.0000', 'reference_number': 'OLD-1', 'date': '2026-10-13',
        'reason': '旧累计期初'}, 'old-settlement')
    assert legacy.status_code == 200
    account_id = account(api, 'purchase', shipment.order)
    summary = api.get(BASE + f'costs/shipment/{shipment.pk}/payments/').data['data']
    assert summary['summary']['opening_amount'] == '1.0000'
    assert summary['summary']['paid_amount'] == '1.0000'
    assert any(row['entry_type'] == 'opening' for row in summary['entries'])
    payment = write(api, f'costs/shipment/{shipment.pk}/payments/', {
        'amount': '0.5000', 'date': '2026-10-14', 'payee_account_id': account_id,
        'expected_version': 0}, 'new-payment-after-opening')
    assert payment.status_code == 201
    refreshed = get(api, 'shipment', shipment)
    refused = write(api, f'costs/shipment/{shipment.pk}/settlement/', {
        'expected_source_version': refreshed['target']['version'], 'expected_version': 1,
        'recorded_amount': '1.5000', 'reference_number': 'OLD-2', 'date': '2026-10-14',
        'reason': '禁止覆盖期初累计'}, 'old-settlement-overwrite')
    assert refused.status_code == 422


@pytest.mark.django_db(transaction=True)
def test_payment_projection_matches_cost_target_and_cost_ledger_classification(world):
    buyer, api, shipment = pilot(world)
    shipment = mark(buyer, shipment)
    fee(api, 'shipment', shipment, '0')
    calculate(api, 'shipment', shipment)
    account_id = account(api, 'purchase', shipment.order)
    before_versions = PaymentRecord.objects.count()
    before_cost_versions = CostVersion.objects.count()
    created = write(api, f'costs/shipment/{shipment.pk}/payments/', {
        'amount': '0.5000', 'date': '2026-10-14', 'payee_account_id': account_id,
        'expected_version': 0}, 'shipment-payment-ledger')
    assert created.status_code == 201, created.data
    projection = api.get(BASE + 'cost-targets/', {'kind': 'shipment'}).data['data']
    owner = next(row for row in projection if row['id'] == shipment.pk)
    assert owner['paid_amount'] == '0.5000' and owner['remaining_amount'] is not None
    ledger = api.get(BASE + 'product-cost-ledger/').data['data']
    rows = [row for row in ledger if row['shipment_id'] == shipment.pk]
    assert rows and all(row['goods_settlement_recorded_amount'] == '0.5000' for row in rows)
    assert all(row['goods_settlement_nature'] == 'corporate' for row in rows)
    assert all(row['goods_payment_amount'] == '0.5000' for row in rows)
    assert get(api, 'shipment', shipment)['target']['paid_amount'] == '0.5000'
    groups = api.get(BASE + 'dashboard/?section=costs').data['data']['groups']
    assert Decimal(groups['supplier']['recorded']) == Decimal('0.5000')
    assert PaymentRecord.objects.count() == before_versions + 1
    assert CostVersion.objects.count() == before_cost_versions
