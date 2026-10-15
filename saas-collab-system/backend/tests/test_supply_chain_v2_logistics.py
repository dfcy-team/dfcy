from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.test import APIClient
from apps.accounts.external_auth import issue_supplier_web_tokens
from apps.commerce.models import InventorySnapshot, InboundRecord
from apps.masterdata.models import WarehouseMaster
from apps.permissions.models import DataScope
from apps.supply_chain import services, logistics
from apps.supply_chain.models import (BusinessEvent, DispatchBatch, DispatchMembership, InboundOrder,
    InternalStockReceipt, InternalStockReceiptLine, domain_write)
from tests.test_supply_chain_v2_foundation import (world, internal_user, supplier_user, confirmed_order,
    po_payload, shipment_payload, freight)
from tests.test_supply_chain_v2_shipments import draft, upload, supplier_client, EXTERNAL

BASE = '/api/internal/supply-chain/v2/'


def client(user):
    api = APIClient(); api.force_authenticate(user=user)
    return api


def write(api, path, body, key, method='post'):
    return getattr(api, method)(BASE + path, body, format='json', HTTP_IDEMPOTENCY_KEY=key)


def setup(world, *, mixed_suppliers=False):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    first = services.create_supplier_shipment(buyer, shipment_payload(world, order, 'one'), idempotency_key='one')
    other = confirmed_order(world, buyer, key='other', payload=po_payload(world, number='PO-OTHER', supplier=world['supplier_b'])) if mixed_suppliers else order
    second = services.create_supplier_shipment(buyer, shipment_payload(world, other, 'two', number='SH-2'), idempotency_key='two')
    carrier = freight(world)
    warehouse = WarehouseMaster.objects.create(tenant=world['tenant'], code='us-1', name='US warehouse', country_code='US')
    return buyer, first, second, carrier, warehouse


def create(api, rows, carrier, key='batch'):
    body = {'shipment_ids': [r.pk for r in rows], 'shipment_versions': [{'id': r.pk, 'version': r.version} for r in rows],
            'freight_company_id': carrier.pk, 'freight_number': 'FREIGHT-001', 'notes': '整批发运'}
    response = write(api, 'dispatch-batches/', body, key)
    assert response.status_code == 201, response.data
    return response.data['data'], body


def arrive(api, batch):
    for index, stage in enumerate(['departed', 'arrived_port', 'arrived_warehouse']):
        response = write(api, f"dispatch-batches/{batch['id']}/stage/", {'expected_version': batch['version'], 'stage': stage,
            'occurred_at': f'2026-10-12T0{index+1}:00:00+08:00'}, stage)
        assert response.status_code == 200, response.data
        batch = response.data['data']
    return batch


def generate(api, batch, warehouse):
    response = write(api, f"dispatch-batches/{batch['id']}/inbound/", {'expected_version': batch['version'], 'warehouse_id': warehouse.pk}, 'generate')
    assert response.status_code == 200, response.data
    return response.data['data']


def checked(api, inbound, *, quantities=None):
    quantities = quantities or [l['expected_quantity'] for l in inbound['lines']]
    body = {'expected_version': inbound['version'], 'notes': '已逐行核对', 'lines': [
        {'id': l['id'], 'received_quantity': qty, 'difference_note': '清点差异' if qty != l['expected_quantity'] else ''}
        for l, qty in zip(inbound['lines'], quantities)]}
    response = write(api, f"inbound-orders/{inbound['id']}/", body, 'checked', 'patch')
    assert response.status_code == 200, response.data
    return response.data['data'], body


def test_batch_accepts_arrived_and_unarrived_idempotence_and_no_duplicate_dispatch(world):
    buyer, one, two, carrier, warehouse = setup(world)
    api = client(buyer)
    one = services.mark_collection_arrival(buyer, one.pk, expected_version=one.version,
        occurred_at=datetime(2026, 10, 12, tzinfo=timezone.utc), idempotency_key='arrival')
    assert api.get(BASE + 'dispatch-candidates/').data['count'] == 2
    batch, body = create(api, [one, two], carrier)
    assert {s['id']: s['collection_arrived'] for s in batch['shipments']} == {one.pk: True, two.pk: False}
    assert write(api, 'dispatch-batches/', body, 'batch').data['data']['id'] == batch['id']
    assert DispatchMembership.objects.count() == 2 and not InboundOrder.objects.exists()
    assert api.get(BASE + 'dispatch-candidates/').data['count'] == 0
    one.refresh_from_db()
    bad = {**body, 'shipment_ids': [one.pk], 'shipment_versions': [{'id': one.pk, 'version': one.version}]}
    assert write(api, 'dispatch-batches/', bad, 'duplicate').status_code == 422
    assert write(api, 'dispatch-batches/', {**body, 'freight_number': 'changed'}, 'batch').status_code == 422
    assert write(api, f"dispatch-batches/{batch['id']}/", {'expected_version': batch['version'], 'notes': '只改备注'}, 'notes', 'patch').status_code == 200
    current = api.get(BASE + f"dispatch-batches/{batch['id']}/").data['data']
    assert current['freight_number'] == 'FREIGHT-001' and current['shipping_marks'] == 'MARK'


def test_supplier_logistics_projection_and_inbound_source_preserving_receipt(world):
    buyer, one, two, carrier, warehouse = setup(world)
    api = client(buyer)
    supplier = supplier_user(world, world['supplier'], 'contact')
    external = supplier_client(supplier)
    batch, _ = create(api, [one, two], carrier)
    assert write(api, f"dispatch-batches/{batch['id']}/inbound/", {'expected_version': batch['version'], 'warehouse_id': warehouse.pk}, 'early').status_code == 422
    batch = arrive(api, batch)
    assert not InboundOrder.objects.exists() and not InternalStockReceipt.objects.exists()
    snapshot = api.get(BASE + f'supplier-shipments/{one.pk}/').data['data']
    assert snapshot['price_editable'] is True and snapshot['price_adjustment_requires_reason'] is True
    for shipment in [one, two]:
        data = external.get(EXTERNAL + f'shipments/{shipment.pk}/').data['data']
        assert data['logistics_stage'] == 'arrived_warehouse'
        assert data['logistics_dates'] == batch['logistics_dates']
        assert 'shipments' not in data and all('unit_price' not in l for l in data['lines'])
        assert 'price_editable' not in data
    inbound = generate(api, batch, warehouse)
    assert len(inbound['lines']) == 2 and all(l['received_quantity'] is None for l in inbound['lines'])
    assert not InternalStockReceipt.objects.exists()
    assert write(api, f"dispatch-batches/{batch['id']}/inbound/", {'expected_version': batch['version'], 'warehouse_id': warehouse.pk}, 'generate').data['data']['id'] == inbound['id']
    new_batch = api.get(BASE + f"dispatch-batches/{batch['id']}/").data['data']
    assert new_batch['inbound_id'] == inbound['id']
    assert write(api, f"dispatch-batches/{batch['id']}/inbound/", {'expected_version': new_batch['version'], 'warehouse_id': warehouse.pk}, 'duplicate-generate').status_code == 422
    assert write(api, f"inbound-orders/{inbound['id']}/confirm/", {'expected_version': inbound['version']}, 'unchecked').status_code == 422
    inbound, body = checked(api, inbound, quantities=[3, 5])
    assert not InternalStockReceipt.objects.exists()
    before = (InventorySnapshot.objects.count(), InboundRecord.objects.count())
    confirm = {'expected_version': inbound['version']}
    response = write(api, f"inbound-orders/{inbound['id']}/confirm/", confirm, 'confirmed')
    assert response.status_code == 200, response.data
    data = response.data['data']
    assert data['status'] == 'confirmed' and data['stock_receipt_ref'].startswith('SC2-RECEIPT-') and data['confirmed_at']
    assert InternalStockReceipt.objects.count() == 1
    entries = InternalStockReceiptLine.objects.order_by('inbound_line_id')
    assert list(entries.values_list('received_quantity', flat=True)) == [3, 5]
    assert len(set(entries.values_list('inbound_line_id', flat=True))) == 2
    assert len(set(entries.values_list('sku_id', flat=True))) == 1, 'same SKU sources must retain distinct entries'
    assert (InventorySnapshot.objects.count(), InboundRecord.objects.count()) == before
    assert write(api, f"inbound-orders/{inbound['id']}/confirm/", confirm, 'confirmed').data['data']['stock_receipt_ref'] == data['stock_receipt_ref']
    assert write(api, f"inbound-orders/{inbound['id']}/confirm/", {'expected_version': data['version']}, 'again').status_code == 422
    assert write(api, f"inbound-orders/{inbound['id']}/", {**body, 'expected_version': data['version']}, 'late', 'patch').status_code == 422
    assert InternalStockReceipt.objects.count() == 1 and InternalStockReceiptLine.objects.count() == 2
    with domain_write(), pytest.raises(DjangoValidationError):
        entries.first().save()


@pytest.mark.parametrize('timestamp,stage', [('2026-10-12T01:00:00', 'departed'), ('invalid', 'departed'), ('2026-10-12T01:00:00Z', 'arrived_port')])
def test_logistics_timezone_and_order_guards(world, timestamp, stage):
    buyer, one, two, carrier, warehouse = setup(world)
    api = client(buyer); batch, _ = create(api, [one], carrier)
    assert write(api, f"dispatch-batches/{batch['id']}/stage/", {'expected_version': batch['version'], 'stage': stage, 'occurred_at': timestamp}, 'bad').status_code in (400, 422)
    assert DispatchBatch.objects.get(pk=batch['id']).stage == 'unmarked'
    assert not InboundOrder.objects.exists()


def test_reverse_dates_stale_and_metadata_freeze(world):
    buyer, one, two, carrier, warehouse = setup(world)
    api = client(buyer); batch, _ = create(api, [one], carrier)
    body = {'expected_version': 1, 'stage': 'departed', 'occurred_at': '2026-10-12T02:00:00+08:00'}
    assert write(api, f"dispatch-batches/{batch['id']}/stage/", body, 'departure').status_code == 200
    assert write(api, f"dispatch-batches/{batch['id']}/stage/", body, 'departure').status_code == 200
    assert write(api, f"dispatch-batches/{batch['id']}/stage/", {**body, 'occurred_at': '2026-10-12T03:00:00+08:00'}, 'departure').status_code == 422
    assert write(api, f"dispatch-batches/{batch['id']}/stage/", {'expected_version': 2, 'stage': 'arrived_port', 'occurred_at': '2026-10-12T01:00:00+08:00'}, 'reverse').status_code == 422
    assert write(api, f"dispatch-batches/{batch['id']}/", {'expected_version': 2, 'notes': 'late'}, 'frozen', 'patch').status_code == 422
    assert write(api, f"dispatch-batches/{batch['id']}/stage/", {'expected_version': 1, 'stage': 'arrived_port', 'occurred_at': '2026-10-12T03:00:00+08:00'}, 'stale').status_code == 422


def test_warehouse_guards_zero_actual_differences_and_partial_fields(world):
    buyer, one, two, carrier, warehouse = setup(world)
    api = client(buyer); batch, _ = create(api, [one], carrier); batch = arrive(api, batch)
    bad = WarehouseMaster.objects.create(tenant=world['tenant'], code='ca', name='CA', country_code='CA')
    assert write(api, f"dispatch-batches/{batch['id']}/inbound/", {'expected_version': batch['version'], 'warehouse_id': bad.pk}, 'wrong-country').status_code == 422
    inbound = generate(api, batch, warehouse)
    body = {'expected_version': inbound['version'], 'lines': [{'id': inbound['lines'][0]['id'], 'received_quantity': 0, 'difference_note': ''}]}
    assert write(api, f"inbound-orders/{inbound['id']}/", body, 'no-reason', 'patch').status_code == 422
    assert InboundOrder.objects.get(pk=inbound['id']).lines.get().received_quantity is None
    obj, body = checked(api, inbound, quantities=[0])
    changed = write(api, f"inbound-orders/{obj['id']}/", {'expected_version': obj['version'], 'notes': '备注保留'}, 'note', 'patch').data['data']
    assert changed['lines'][0]['received_quantity'] == 0
    warehouse.status = 'inactive'; warehouse.save()
    assert write(api, f"inbound-orders/{obj['id']}/confirm/", {'expected_version': changed['version']}, 'inactive').status_code == 422
    assert not InternalStockReceipt.objects.exists()
    warehouse.status = 'active'; warehouse.save()
    assert write(api, f"inbound-orders/{obj['id']}/confirm/", {'expected_version': changed['version']}, 'now-active').status_code == 200
    assert InternalStockReceiptLine.objects.get().received_quantity == 0


def test_entire_batch_scope_readonly_supplier_and_tenant_boundaries(world):
    buyer, one, two, carrier, warehouse = setup(world, mixed_suppliers=True)
    api = client(buyer); batch, _ = create(api, [one, two], carrier); batch = arrive(api, batch)
    inbound = generate(api, batch, warehouse)
    limited = client(internal_user(world, 'limited', scope=DataScope.ScopeType.CUSTOM, config={'supplier_ids': [world['supplier'].pk]}))
    assert limited.get(BASE + 'dispatch-batches/').data['count'] == 0
    assert limited.get(BASE + f"dispatch-batches/{batch['id']}/").status_code == 404
    assert limited.get(BASE + f"inbound-orders/{inbound['id']}/").status_code == 404
    assert write(limited, f"inbound-orders/{inbound['id']}/confirm/", {'expected_version': inbound['version']}, 'hidden').status_code == 404
    readonly = client(internal_user(world, 'readonly', codes=('supply.v2.view',)))
    assert readonly.get(BASE + 'inbound-orders/').data['count'] == 1
    assert write(readonly, f"inbound-orders/{inbound['id']}/confirm/", {'expected_version': inbound['version']}, 'readonly').status_code == 403
    external = supplier_client(supplier_user(world, world['supplier'], 'external'))
    assert external.get(BASE + 'dispatch-batches/').status_code == 401
    assert external.get(EXTERNAL + 'dispatch-batches/').status_code == 404
    anon = APIClient()
    assert anon.get(BASE + 'inbound-orders/').status_code == 401
    from apps.tenants.models import Tenant
    tenant_b = Tenant.objects.create(name='other', code='other')
    foreign = internal_user({**world, 'tenant': tenant_b}, 'foreign')
    assert client(foreign).get(BASE + f"inbound-orders/{inbound['id']}/").status_code == 404


def test_atomic_stock_receipt_failure_rollback_and_immutable_source(world):
    buyer, one, two, carrier, warehouse = setup(world)
    api = client(buyer); batch, _ = create(api, [one, two], carrier); batch = arrive(api, batch)
    inbound, _ = checked(api, generate(api, batch, warehouse))
    with patch('apps.supply_chain.logistics.InternalStockReceiptLine.objects.create', side_effect=RuntimeError('simulated adapter failure')):
        with pytest.raises(RuntimeError):
            logistics.confirm_inbound(buyer, inbound['id'], {'expected_version': inbound['version']}, 'fault')
    assert not InternalStockReceipt.objects.exists() and not InternalStockReceiptLine.objects.exists()
    obj = InboundOrder.objects.get(pk=inbound['id'])
    assert obj.status == 'draft' and obj.version == inbound['version'] and not obj.stock_receipt_ref
    assert not BusinessEvent.objects.filter(action='inbound_confirmed').exists()


@pytest.mark.parametrize('invalid', ['negative', 'fractional', 'foreign-line', 'missing-line'])
def test_malformed_receipt_payload_no_partial_writes(world, invalid):
    buyer, one, two, carrier, warehouse = setup(world)
    api = client(buyer); batch, _ = create(api, [one, two], carrier); batch = arrive(api, batch)
    inbound = generate(api, batch, warehouse)
    rows = [{'id': l['id'], 'received_quantity': 4, 'difference_note': ''} for l in inbound['lines']]
    if invalid == 'negative': rows[0]['received_quantity'] = -1
    if invalid == 'fractional': rows[0]['received_quantity'] = 1.5
    if invalid == 'foreign-line': rows[0]['id'] = 999999
    if invalid == 'missing-line': rows.pop()
    response = write(api, f"inbound-orders/{inbound['id']}/", {'expected_version': inbound['version'], 'lines': rows}, invalid, 'patch')
    assert response.status_code in (400, 422), response.data
    assert InboundOrder.objects.get(pk=inbound['id']).version == 1
    assert all(q is None for q in InboundOrder.objects.get(pk=inbound['id']).lines.values_list('received_quantity', flat=True))


def test_real_supplier_submits_then_buyer_dispatches_without_arrival(world):
    buyer = internal_user(world); order = confirmed_order(world, buyer); carrier = freight(world)
    ext = supplier_client(supplier_user(world, world['supplier'], 'supplier'))
    shipment = upload(ext, EXTERNAL + 'shipments/', draft(ext, EXTERNAL, world, order, quantity=12))
    assert ext.post(EXTERNAL + f"shipments/{shipment['id']}/submit/", {'expected_version': shipment['version']}, format='json', HTTP_IDEMPOTENCY_KEY='submit').status_code == 200
    from apps.supply_chain.models import SupplierShipment
    obj = SupplierShipment.objects.get(pk=shipment['id']); api = client(buyer)
    batch, _ = create(api, [obj], carrier)
    assert batch['shipments'][0]['collection_arrived'] is False and batch['shipments'][0]['total_quantity'] == 12
    assert batch['shipments'][0]['lines'][0]['exception_type'] == 'excess'


def test_country_mix_stale_selection_and_duplicate_ids(world):
    buyer, one, two, carrier, warehouse = setup(world)
    api = client(buyer)
    other_order = confirmed_order(world, buyer, key='ca', payload=po_payload(world, number='PO-CA', country=world['country_ca']))
    other = services.create_supplier_shipment(buyer, shipment_payload(world, other_order, 'ca', number='SH-CA'), idempotency_key='ca')
    body = {'shipment_ids': [one.pk, other.pk], 'shipment_versions': [{'id': r.pk, 'version': r.version} for r in [one, other]], 'freight_company_id': carrier.pk, 'freight_number': 'mixed'}
    assert write(api, 'dispatch-batches/', body, 'mixed').status_code == 422
    assert not DispatchBatch.objects.exists()
    body['shipment_ids'] = [one.pk]; body['shipment_versions'] = [{'id': one.pk, 'version': 999}]
    assert write(api, 'dispatch-batches/', body, 'stale').status_code == 422
    body['shipment_ids'] = [one.pk, one.pk]; body['shipment_versions'] = [{'id': one.pk, 'version': 1}]
    assert write(api, 'dispatch-batches/', body, 'duplicate').status_code == 422
