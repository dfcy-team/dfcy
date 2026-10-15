from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.supply_chain import services, shipments, costs
from apps.supply_chain.models import SupplierShipment, domain_write
from tests.test_supply_chain_v2_foundation import world, internal_user, confirmed_order, supplier_user
from tests.test_supply_chain_v2_logistics import client, create, setup, BASE
from tests.test_supply_chain_v2_shipments import supplier_client, EXTERNAL, upload
from tests.test_supply_chain_v2_costs import fee


def test_factory_loading_address_snapshot_and_draft_switch(world):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    supplier = world['supplier']
    supplier.loading_address = '广东测试装柜地址'
    supplier.save()
    payload = {'order_id': order.pk, 'delivery_mode': 'factory_loading', 'loading_address': '',
               'lines': [{'sku_id': world['sku'].pk, 'quantity': 4}]}
    obj = shipments.create_draft(buyer, payload, 'factory-draft')
    assert obj.loading_address_snapshot == '广东测试装柜地址'
    assert shipments.create_draft(buyer, payload, 'factory-draft').pk == obj.pk
    supplier.loading_address = '新档案地址'
    supplier.save()
    obj = shipments.update_draft(buyer, obj.pk, {'expected_version': obj.version, 'notes': '保留快照'}, 'same-mode')
    assert obj.loading_address_snapshot == '广东测试装柜地址'
    obj = shipments.update_draft(buyer, obj.pk, {'expected_version': obj.version, 'delivery_mode': 'collection_center'}, 'switch-collection')
    assert obj.delivery_mode == 'collection_center' and obj.loading_address_snapshot == ''
    obj = shipments.update_draft(buyer, obj.pk, {'expected_version': obj.version, 'delivery_mode': 'factory_loading',
                                               'loading_address': '本次实际装柜地址'}, 'switch-factory')
    assert obj.loading_address_snapshot == '本次实际装柜地址'
    assert shipments.snapshot(obj)['collection_arrival_applicable'] is False
    with pytest.raises(ValidationError):
        shipments.update_draft(buyer, obj.pk, {'expected_version': obj.version, 'delivery_mode': 'invalid'}, 'invalid')


def test_supplier_can_submit_factory_loading_with_private_box_file(world):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    supplier = supplier_user(world, world['supplier'], 'factory-supplier')
    api = supplier_client(supplier)
    body = {'order_id': order.pk, 'delivery_mode': 'factory_loading', 'loading_address': '本次上门地址',
            'lines': [{'sku_id': world['sku'].pk, 'quantity': 3}]}
    response = api.post(EXTERNAL + 'shipments/', body, format='json', HTTP_IDEMPOTENCY_KEY='supplier-factory')
    assert response.status_code == 201, response.data
    obj = response.data['data']
    assert obj['delivery_mode'] == 'factory_loading' and obj['loading_address'] == '本次上门地址'
    obj = upload(api, EXTERNAL + 'shipments/', obj, key='factory-box')
    response = api.post(EXTERNAL + f"shipments/{obj['id']}/submit/", {'expected_version': obj['version']},
                        format='json', HTTP_IDEMPOTENCY_KEY='factory-submit')
    assert response.status_code == 200, response.data
    assert response.data['data']['collection_arrival_applicable'] is False
    assert all('unit_price' not in row for row in response.data['data']['lines'])
    response = api.patch(EXTERNAL + f"shipments/{obj['id']}/", {'expected_version': response.data['data']['version'],
                          'delivery_mode': 'collection_center'}, format='json', HTTP_IDEMPOTENCY_KEY='after-submit')
    assert response.status_code == 422
    assert api.post(EXTERNAL + 'shipments/', {**body, 'delivery_mode': 'invalid'}, format='json', HTTP_IDEMPOTENCY_KEY='bad-mode').status_code == 400


def test_factory_loading_skips_arrival_but_supports_explicit_fee_and_same_batch(world):
    buyer, first, second, carrier, _ = setup(world)
    with domain_write():
        first.delivery_mode = SupplierShipment.DeliveryMode.FACTORY_LOADING
        first.loading_address_snapshot = '工厂上门装载地址'
        first.save()


    api = client(buyer)
    assert costs.context(buyer, 'shipment', first.pk)['target']['fee_editable'] is True
    assert costs.context(buyer, 'shipment', second.pk)['target']['fee_editable'] is False
    assert costs.context(buyer, 'shipment', first.pk)['fee'] is None
    with pytest.raises(ValidationError, match='无需标记集货到仓'):
        services.mark_collection_arrival(buyer, first.pk, expected_version=first.version,
            occurred_at=datetime.now(timezone.utc), idempotency_key='invalid-factory-arrival')
    world['sku'].package_volume = Decimal('0.1')
    world['sku'].save()
    result, _ = fee(api, 'shipment', first, '0', key='factory-zero')
    assert Decimal(result['fee']['amount']) == 0
    first.refresh_from_db()
    candidates = api.get(BASE + 'dispatch-candidates/').data['data']
    assert {row['id'] for row in candidates} == {first.pk, second.pk}
    assert next(row for row in candidates if row['id'] == first.pk)['delivery_mode'] == 'factory_loading'
    batch, _ = create(api, [first, second], carrier)
    assert len(batch['shipments']) == 2
    first.refresh_from_db()
    assert first.collection_arrived is False
    with domain_write(), pytest.raises(ValidationError):
        first.collection_arrived = True
        first.collection_arrived_at = datetime.now(timezone.utc)
        first.collection_arrived_by = buyer
        first.save()


def test_factory_loading_requires_address_at_submission_but_keeps_incomplete_drafts(world):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    supplier = world['supplier']
    supplier.loading_address = ''
    supplier.factory_address = ''
    supplier.save()
    api = client(buyer)
    body = {'order_id': order.pk, 'delivery_mode': 'factory_loading',
            'lines': [{'sku_id': world['sku'].pk, 'quantity': 2}]}
    response = api.post(BASE + 'supplier-shipments/', body, format='json', HTTP_IDEMPOTENCY_KEY='empty-address')
    assert response.status_code == 201, response.data
    obj = upload(api, BASE + 'supplier-shipments/', response.data['data'], key='empty-address-box')
    response = api.post(BASE + f"supplier-shipments/{obj['id']}/submit/", {'expected_version': obj['version']},
                        format='json', HTTP_IDEMPOTENCY_KEY='empty-address-submit')
    assert response.status_code == 422 and '装柜地址' in str(response.data)
    draft = SupplierShipment.objects.get(pk=obj['id'])
    assert draft.status == 'draft' and draft.version == obj['version']
    draft = shipments.update_draft(buyer, draft.pk, {'expected_version': draft.version,
                                  'loading_address': '补充的装柜地址'}, 'address-added')
    draft = shipments.update_draft(buyer, draft.pk, {'expected_version': draft.version,
                                  'loading_address': '  '}, 'address-cleared')
    with pytest.raises(ValidationError, match='装柜地址'):
        shipments.action(buyer, draft.pk, {'expected_version': draft.version}, 'cleared-submit', 'submitted')
    draft = shipments.update_draft(buyer, draft.pk, {'expected_version': draft.version,
                                  'loading_address': '最终装柜地址'}, 'address-restored')
    draft = shipments.action(buyer, draft.pk, {'expected_version': draft.version}, 'address-final-submit', 'submitted')
    assert draft.status == 'submitted' and draft.loading_address_snapshot == '最终装柜地址'
