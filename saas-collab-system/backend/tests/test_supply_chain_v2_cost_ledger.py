"""The product ledger reads effective batch costs without widening supplier scope."""
from decimal import Decimal

from apps.masterdata.models import WarehouseMaster
from apps.permissions.models import DataScope
from apps.products.models import ProductCostVersion
from apps.supply_chain import logistics, services
from apps.supply_chain.models import CostVersion, InternalStockReceiptLine
from tests.test_supply_chain_v2_foundation import (world, internal_user, supplier_user,
    confirmed_order, po_payload, shipment_payload, freight)
from tests.test_supply_chain_v2_logistics import client, create, BASE
from tests.test_supply_chain_v2_costs import pilot, received_pilot, calculate, fee, mark

URL = BASE + 'product-cost-ledger/'


def test_received_costs_filter_by_product_country_warehouse_and_batch_without_global_price_write(world):
    buyer, api, shipment, batch_id, inbound_id = received_pilot(world)
    version, _ = calculate(api, 'batch', batch_id)
    before = InternalStockReceiptLine.objects.count()
    rows = api.get(URL).data['data']
    assert len(rows) == 2
    row = next(r for r in rows if r['sku_id'] == world['sku'].pk)
    assert row['country_code'] == 'US' and row['status'] == 'confirmed'
    assert row['received_quantity'] == 3 and row['cost_version_id'] == version['id']
    assert row['is_latest'] and row['batch_id'] == batch_id
    assert Decimal(row['received_total']) > 0 and row['received_unit_cost'] is not None
    params = {'sku_id': row['sku_id'], 'country_id': row['country_id'],
              'warehouse_id': row['warehouse_id'], 'batch_id': batch_id}
    assert api.get(URL, params).data['count'] == 1
    assert api.get(URL, {**params, 'country_id': world['country_ca'].pk}).data['count'] == 0
    assert api.get(URL, {'search': 'DOES-NOT-EXIST'}).data['count'] == 0
    assert api.get(URL, {'sku_id': 'invalid'}).status_code == 400
    assert not ProductCostVersion.objects.exists()
    assert InternalStockReceiptLine.objects.count() == before
    assert api.post(URL, {}, format='json').status_code == 405


def test_latest_and_history_never_add_both_versions_and_mark_changed_inputs(world):
    buyer, api, shipment, batch_id, _ = received_pilot(world)
    first, _ = calculate(api, 'batch', batch_id)
    fee(api, 'batch', batch_id, '40', key='new-fee')
    stale = api.get(URL).data['data']
    assert {r['status'] for r in stale} == {'recalculation_required'}
    second, _ = calculate(api, 'batch', batch_id)
    current = api.get(URL).data['data']
    assert len(current) == 2 and {r['cost_version_id'] for r in current} == {second['id']}
    history = api.get(URL, {'versions': 'all'}).data['data']
    assert len(history) == 4 and {r['cost_version_id'] for r in history} == {first['id'], second['id']}
    assert all(not r['is_latest'] for r in history if r['cost_version_id'] == first['id'])


def test_pre_collection_cost_becomes_history_once_shipment_joins_a_batch(world):
    buyer, api, shipment = pilot(world)
    shipment = mark(buyer, shipment)
    fee(api, 'shipment', shipment, '0')
    first, _ = calculate(api, 'shipment', shipment)
    assert api.get(URL).data['count'] == 2
    shipment.refresh_from_db()
    batch, _ = create(api, [shipment], freight(world))
    assert api.get(URL).data['count'] == 0
    assert all(not r['is_latest'] for r in api.get(URL, {'versions': 'all'}).data['data'])
    second, _ = calculate(api, 'batch', batch['id'])
    assert {r['cost_version_id'] for r in api.get(URL).data['data']} == {second['id']}
    assert api.get(URL, {'versions': 'all'}).data['count'] == 4


def test_ledger_and_options_cannot_leak_a_partially_authorized_batch(world):
    buyer, api, shipment = pilot(world)
    other = confirmed_order(world, buyer, key='other', payload=po_payload(world,
        number='PO-OTHER', supplier=world['supplier_b']))
    other_shipment = services.create_supplier_shipment(buyer, shipment_payload(world, other,
        'other-s', number='S-OTHER'), idempotency_key='other-s')
    shipment.refresh_from_db()
    batch, _ = create(api, [shipment, other_shipment], freight(world))
    calculate(api, 'batch', batch['id'])
    scoped = internal_user(world, 'supplier-a-only', DataScope.ScopeType.CUSTOM,
                           {'supplier_ids': [world['supplier'].pk]})
    scoped_api = client(scoped)
    assert scoped_api.get(URL).data['count'] == 0
    assert scoped_api.get(URL, {'versions': 'all'}).data['count'] == 0
    for kind in ('batches', 'countries', 'warehouses'):
        assert scoped_api.get(URL + 'options/', {'kind': kind}).data['count'] == 0
    assert client(supplier_user(world, world['supplier'], 'supplier-reader')).get(URL).status_code == 403
    assert api.get(URL + 'options/', {'kind': 'batches'}).data['count'] == 1


def test_view_scope_read_only_and_cost_owner_isolation(world):
    buyer, api, shipment, batch_id, _ = received_pilot(world)
    calculate(api, 'batch', batch_id)
    viewer = internal_user(world, 'read-only', codes=('supply.v2.view',))
    assert client(viewer).get(URL).data['count'] == 2
    assert client(viewer).get(URL+'options/', {'kind': 'warehouses'}).data['count'] == 1
    own = internal_user(world, 'own-only', DataScope.ScopeType.OWN)
    assert client(own).get(URL).data['count'] == 0
    assert api.get(URL+'options/', {'kind': 'invalid'}).status_code == 400
    assert api.get(URL, {'limit': 101}).status_code == 400
    buyer.is_active = False; buyer.save()
    assert client(buyer).get(URL).status_code in (401, 403)
