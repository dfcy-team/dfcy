import pytest
from rest_framework.test import APIClient

from apps.permissions.models import DataScope
from apps.supply_chain.cost_models import ShipmentDiscountAdjustment
from apps.supply_chain.models import SupplierShipment
from apps.tenants.models import Tenant
from tests.test_supply_chain_purchase_contracts import submitted_shipment
from tests.test_supply_chain_v2_foundation import internal_user, world
from tests.test_supply_chain_v2_logistics import BASE

pytestmark = pytest.mark.django_db


def test_discount_api_precision_replay_and_source_uniqueness(world, submitted_shipment):
    buyer, api, data = submitted_shipment
    shipment = SupplierShipment.objects.get(pk=data['id'])
    path = BASE + f'costs/shipment/{shipment.pk}/discount-adjustments/'
    readonly = internal_user(world, 'discount-viewer', codes=('supply.v2.view',))
    readonly_api = APIClient(); readonly_api.force_authenticate(user=readonly)
    payload = {'amount': '0.1234', 'source_reference': 'REBATE-001', 'reason': '四位精度优惠'}
    denied = readonly_api.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='discount-view-denied')
    assert denied.status_code in (403, 404)
    foreign_world = {**world, 'tenant': Tenant.objects.create(code='discount-foreign', name='Other tenant')}
    foreign = internal_user(foreign_world, 'discount-foreign-user')
    foreign_api = APIClient(); foreign_api.force_authenticate(user=foreign)
    assert foreign_api.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='discount-foreign').status_code == 404

    first = api.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='discount-one')
    assert first.status_code == 201, first.data
    row = ShipmentDiscountAdjustment.objects.get(shipment=shipment)
    assert str(row.amount) == '0.1234'
    replay = api.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='discount-one')
    assert replay.status_code == 201, replay.data
    assert ShipmentDiscountAdjustment.objects.filter(shipment=shipment).count() == 1
    precision = api.post(path, {**payload, 'amount': '0.12345'}, format='json', HTTP_IDEMPOTENCY_KEY='discount-overprecision')
    assert precision.status_code == 400

    key_conflict = api.post(path, {**payload, 'amount': '0.1200'}, format='json',
                            HTTP_IDEMPOTENCY_KEY='discount-one')
    assert key_conflict.status_code == 422
    source_conflict = api.post(path, {**payload, 'reason': '重复来源换原因'}, format='json',
                               HTTP_IDEMPOTENCY_KEY='discount-two')
    assert source_conflict.status_code == 422
    assert ShipmentDiscountAdjustment.objects.filter(shipment=shipment).count() == 1
