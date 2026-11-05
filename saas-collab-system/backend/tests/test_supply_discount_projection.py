from decimal import Decimal

import pytest

from apps.supply_chain import costs
from apps.supply_chain.models import ShipmentDiscountAdjustment, SupplierShipment
from tests.test_supply_chain_purchase_contracts import submitted_shipment
from tests.test_supply_chain_v2_foundation import world as foundation_world

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(foundation_world):
    return foundation_world


def test_contract_tax_and_discount_are_each_counted_once_in_payment_projection(submitted_shipment):
    user, api, shipment = submitted_shipment
    base = f"/api/internal/supply-chain/v2/supplier-shipments/{shipment['id']}/purchase-contract/"
    defaults = api.get(base).data['data']['defaults']
    defaults['buyer']['name'] = '买方有限公司'
    defaults['contract_date'] = '2026-10-30'
    defaults['lines'][0]['tax_rate'] = '10.000'
    defaults['pricing_basis'] = 'net_plus_tax'
    defaults['tax_treatment'] = 'refund'
    saved = api.put(base, {'expected_version': 0, 'expected_source_version': shipment['version'],
        'nature': 'corporate', 'payload': defaults, 'reason': '应付投影回归'}, format='json')
    assert saved.status_code == 200, saved.data
    contract = saved.data['data']['contract']
    issued = api.post(base + 'issue/', {'expected_version': contract['version'],
        'expected_source_version': shipment['version'], 'confirmed': True}, format='json')
    assert issued.status_code == 200, issued.data
    contract = issued.data['data']['contract']

    discount = api.post(f"/api/internal/supply-chain/v2/costs/shipment/{shipment['id']}/discount-adjustments/",
        {'amount': '5.0000', 'source_reference': 'DISC-PROJ-1', 'reason': '合同折让'}, format='json',
        HTTP_IDEMPOTENCY_KEY='discount-projection-regression')
    assert discount.status_code == 201, discount.data

    summary = costs.payment_summary(user, 'shipment', shipment['id'])['summary']
    assert ShipmentDiscountAdjustment.objects.filter(shipment_id=shipment['id'], amount='5.0000').exists()
    expected_due = Decimal(contract['payload']['lines'][0]['net_total']) + Decimal(contract['settlement_tax_amount']) - Decimal('5.00')
    assert Decimal(summary['due_amount']) == expected_due
    assert Decimal(summary['remaining_amount']) == expected_due
    source = SupplierShipment.objects.get(pk=shipment['id'])
    costs.prepare_target_financials('shipment', [source])
    assert Decimal(source._payment_projection['due_amount']) == expected_due
