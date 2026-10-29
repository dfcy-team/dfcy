import pytest
from rest_framework.test import APIClient

from apps.supply_chain import services
from apps.supply_chain.models import FreightCompany, domain_write
from tests.test_supply_chain_v2_foundation import (
    world, internal_user, supplier_user, confirmed_order, po_payload, shipment_payload, freight,
)
from tests.test_supply_chain_v2_shipments import supplier_client

INTERNAL = '/api/internal/supply-chain/v2/'
EXTERNAL = '/api/external/supplier/supply-chain/v2/'


@pytest.mark.django_db
def test_domestic_carrier_options_transport_permissions_and_scope(world):
    buyer = internal_user(world, 'domestic-buyer')
    order = confirmed_order(world, buyer, payload=po_payload(world, number='PO-DOMESTIC'))
    shipment = services.create_supplier_shipment(buyer,
        shipment_payload(world, order, 'domestic-shipment'), idempotency_key='domestic-shipment')
    domestic = freight(world)
    domestic.service_scopes = ['international', 'domestic']
    with domain_write():
        domestic.save(update_fields=['service_scopes'])
        international_only = FreightCompany.objects.create(tenant=world['tenant'], created_by=buyer,
            code='INT-ONLY', name='International only', service_scopes=['international'])

    internal = APIClient()
    internal.force_authenticate(user=buyer)
    options = internal.get(INTERNAL + f'supplier-shipments/{shipment.pk}/domestic-carrier-options/')
    assert options.status_code == 200
    assert {item['id'] for item in options.data['data']} == {domestic.pk}

    saved = internal.put(INTERNAL + f'supplier-shipments/{shipment.pk}/domestic-transport/', {
        'domestic_carrier_id': domestic.pk, 'domestic_tracking_number': 'CN-123',
        'expected_version': shipment.version,
    }, format='json', HTTP_IDEMPOTENCY_KEY='domestic-transport')
    assert saved.status_code == 200, saved.data
    assert saved.data['data'] == {
        'domestic_carrier_id': domestic.pk, 'domestic_carrier_name': domestic.name,
        'domestic_tracking_number': 'CN-123', 'version': shipment.version + 1,
    }
    target = internal.get(INTERNAL + f'costs/shipment/{shipment.pk}/')
    assert target.status_code == 200
    assert target.data['data']['target']['domestic_carrier_id'] == domestic.pk
    assert target.data['data']['target']['domestic_carrier_name'] == domestic.name
    assert target.data['data']['target']['domestic_tracking_number'] == 'CN-123'
    targets = internal.get(INTERNAL + 'cost-targets/?kind=shipment')
    assert targets.status_code == 200
    listed = next(item for item in targets.data['data'] if item['id'] == shipment.pk)
    assert listed['domestic_carrier_id'] == domestic.pk

    supplier = supplier_user(world, world['supplier'], 'domestic-supplier')
    external = supplier_client(supplier)
    visible = external.get(EXTERNAL + f'shipments/{shipment.pk}/domestic-carrier-options/')
    assert visible.status_code == 200
    assert {item['id'] for item in visible.data['data']} == {domestic.pk}
    forbidden = external.put(EXTERNAL + f'shipments/{shipment.pk}/domestic-transport/', {
        'domestic_carrier_id': international_only.pk, 'domestic_tracking_number': '',
        'expected_version': shipment.version + 1,
    }, format='json', HTTP_IDEMPOTENCY_KEY='domestic-invalid-carrier')
    assert forbidden.status_code == 422


@pytest.mark.django_db
def test_domestic_payment_idempotency_and_goods_purpose_isolation(world):
    buyer = internal_user(world, 'domestic-payment-buyer')
    order = confirmed_order(world, buyer, payload=po_payload(world, number='PO-DOM-PAY'))
    shipment = services.create_supplier_shipment(buyer,
        shipment_payload(world, order, 'domestic-payment-shipment'), idempotency_key='domestic-payment-shipment')
    world['sku'].package_volume = '0.1'
    world['sku'].save(update_fields=['package_volume'])
    carrier = freight(world)
    with domain_write():
        carrier.service_scopes = ['international', 'domestic']
        carrier.save(update_fields=['service_scopes'])
    api = APIClient()
    api.force_authenticate(user=buyer)
    saved = api.put(INTERNAL + f'supplier-shipments/{shipment.pk}/domestic-transport/', {
        'domestic_carrier_id': carrier.pk, 'domestic_tracking_number': '', 'expected_version': shipment.version,
    }, format='json', HTTP_IDEMPOTENCY_KEY='domestic-pay-transport')
    assert saved.status_code == 200, saved.data
    shipment.refresh_from_db()
    with domain_write():
        shipment.status = 'submitted'
        shipment.delivery_mode = 'factory_loading'
        shipment.loading_address_snapshot = '验收测试装柜地址'
        shipment.save(update_fields=['status', 'delivery_mode', 'loading_address_snapshot'])
    shipment.refresh_from_db()
    context = api.get(INTERNAL + f'costs/shipment/{shipment.pk}/').data['data']
    fee = api.put(INTERNAL + f'costs/shipment/{shipment.pk}/fee/', {
        'expected_source_version': context['target']['version'], 'expected_version': 0,
        'amount': '10.0000', 'state': 'confirmed', 'method': 'volume', 'volume_percent': '100',
        'billed_cbm': None, 'notes': '', 'reason': '国内运费验收',
    }, format='json', HTTP_IDEMPOTENCY_KEY='domestic-pay-fee')
    assert fee.status_code == 200, fee.data
    account = api.post(INTERNAL + f'costs/domestic_freight/{shipment.pk}/payee-accounts/', {
        'nature': 'corporate', 'account_name': '国内承运商账户', 'account_holder': '承运商',
        'bank_name': '测试银行', 'account_number': '6222000000001111', 'active': True,
    }, format='json', HTTP_IDEMPOTENCY_KEY='domestic-pay-account')
    assert account.status_code == 201, account.data
    payment_payload = {'amount': '10.0000', 'date': '2026-10-29',
        'payee_account_id': account.data['data']['account']['id'], 'notes': '',
        'reference_number': 'DOM-PAY-1', 'expected_version': 0}
    payment_url = INTERNAL + f'costs/domestic_freight/{shipment.pk}/payments/'
    paid = api.post(payment_url, payment_payload, format='json', HTTP_IDEMPOTENCY_KEY='domestic-pay-once')
    replay = api.post(payment_url, payment_payload, format='json', HTTP_IDEMPOTENCY_KEY='domestic-pay-once')
    assert paid.status_code == 201 and replay.status_code == 201
    assert len(paid.data['data']['entries']) == 1 == len(replay.data['data']['entries'])
    goods = api.get(INTERNAL + f'costs/shipment/{shipment.pk}/payments/')
    assert goods.status_code == 200 and goods.data['data']['entries'] == []
    payment_id = paid.data['data']['entries'][0]['id']
    with domain_write():
        other_carrier = FreightCompany.objects.create(tenant=world['tenant'], created_by=buyer,
            code='DOM-OTHER', name='Other domestic carrier', service_scopes=['domestic'])
    wrong_account = api.post(INTERNAL + f'costs/freight_company/{other_carrier.pk}/payee-accounts/', {
        'nature': 'corporate', 'account_name': '其他承运商账户', 'account_holder': '其他承运商',
        'bank_name': '测试银行', 'account_number': '6222000000002222', 'active': True,
    }, format='json', HTTP_IDEMPOTENCY_KEY='domestic-wrong-account')
    assert wrong_account.status_code == 201
    wrong_payment = api.post(payment_url, {**payment_payload,
        'expected_version': 1,
        'payee_account_id': wrong_account.data['data']['account']['id']}, format='json',
        HTTP_IDEMPOTENCY_KEY='domestic-wrong-carrier-payment')
    assert wrong_payment.status_code == 422
    goods_reverse = api.post(INTERNAL + f'costs/shipment/{shipment.pk}/payments/{payment_id}/reverse/', {
        'reason': '不得从货款路径冲销', 'expected_version': 0,
    }, format='json', HTTP_IDEMPOTENCY_KEY='goods-cannot-reverse-domestic')
    assert goods_reverse.status_code == 404
    voucher = api.get(INTERNAL + f'costs/shipment/{shipment.pk}/payments/{payment_id}/vouchers/')
    assert voucher.status_code == 404
    fee_context = api.get(INTERNAL + f'costs/shipment/{shipment.pk}/').data['data']
    estimated_fee = api.put(INTERNAL + f'costs/shipment/{shipment.pk}/fee/', {
        'expected_source_version': fee_context['target']['version'], 'expected_version': 1,
        'amount': '10.0000', 'state': 'estimated', 'method': 'volume', 'volume_percent': '100',
        'billed_cbm': None, 'notes': '', 'reason': '已付款后不能改暂估',
    }, format='json', HTTP_IDEMPOTENCY_KEY='domestic-fee-cannot-estimate')
    assert estimated_fee.status_code == 422
    lower_fee = api.put(INTERNAL + f'costs/shipment/{shipment.pk}/fee/', {
        'expected_source_version': fee_context['target']['version'], 'expected_version': 1,
        'amount': '9.0000', 'state': 'confirmed', 'method': 'volume', 'volume_percent': '100',
        'billed_cbm': None, 'notes': '', 'reason': '已付款后不得下调',
    }, format='json', HTTP_IDEMPOTENCY_KEY='domestic-fee-cannot-decrease')
    assert lower_fee.status_code == 422
    shipment.refresh_from_db()
    change_before_reversal = api.put(INTERNAL + f'supplier-shipments/{shipment.pk}/domestic-transport/', {
        'domestic_carrier_id': other_carrier.pk, 'domestic_tracking_number': '',
        'expected_version': shipment.version,
    }, format='json', HTTP_IDEMPOTENCY_KEY='domestic-carrier-locked')
    assert change_before_reversal.status_code == 422
    reversed_payment = api.post(INTERNAL + f'costs/domestic_freight/{shipment.pk}/payments/{payment_id}/reverse/', {
        'reason': '承运商付款冲销', 'expected_version': 1,
    }, format='json', HTTP_IDEMPOTENCY_KEY='domestic-pay-reversal')
    assert reversed_payment.status_code == 200, reversed_payment.data
    shipment.refresh_from_db()
    changed = api.put(INTERNAL + f'supplier-shipments/{shipment.pk}/domestic-transport/', {
        'domestic_carrier_id': other_carrier.pk, 'domestic_tracking_number': '',
        'expected_version': shipment.version,
    }, format='json', HTTP_IDEMPOTENCY_KEY='domestic-carrier-after-reversal')
    assert changed.status_code == 200, changed.data
    with domain_write():
        shipment.status = 'cancelled'
        shipment.save(update_fields=['status'])
    new_carrier_account = api.post(INTERNAL + f'costs/domestic_freight/{shipment.pk}/payee-accounts/', {
        'nature': 'corporate', 'account_name': '新承运商账户', 'account_holder': '新承运商',
        'bank_name': '测试银行', 'account_number': '6222000000003333', 'active': True,
    }, format='json', HTTP_IDEMPOTENCY_KEY='new-domestic-carrier-account')
    assert new_carrier_account.status_code == 201
    blocked = api.post(payment_url, {**payment_payload, 'expected_version': 2,
        'payee_account_id': new_carrier_account.data['data']['account']['id'],
        'reference_number': 'DOM-PAY-CANCELLED'}, format='json',
        HTTP_IDEMPOTENCY_KEY='domestic-pay-after-cancel')
    assert blocked.status_code == 422
