from decimal import Decimal
import pytest
from django.core.exceptions import ValidationError
from rest_framework.exceptions import NotFound
from apps.permissions.models import DataScope
from apps.supply_chain import services, shipments, fulfillment
from apps.supply_chain.models import SupplierShipment, domain_write
from apps.supply_chain.shipment_sources import accessible_shipments
from apps.supply_chain.permissions import internal_orders
from apps.supply_chain.models import PurchaseOrder
from tests.test_supply_chain_v2_foundation import world, internal_user, confirmed_order, po_payload, supplier_user
from tests.test_supply_chain_v2_shipments import buyer_client, write, upload, INTERNAL


def pair(world, buyer, second_buyer=None, **overrides):
    a = confirmed_order(world, buyer, key='multi-a', payload=po_payload(world, number='MULTI-A'))
    b = confirmed_order(world, second_buyer or buyer, key='multi-b', payload=po_payload(world,
        number='MULTI-B', lines=[{'sku_id': world['sku'].pk, 'quantity': 10, 'unit_price': '3.1234'}], **overrides))
    return a, b


def body(world, a, b):
    return {'order_id': a.pk, 'lines': [
        {'sku_id': world['sku'].pk, 'purchase_line_id': a.lines.get().pk, 'quantity': 3},
        {'sku_id': world['sku'].pk, 'purchase_line_id': b.lines.get().pk, 'quantity': 4}]}


def test_multi_po_draft_submit_source_filter_and_progress(world):
    buyer = internal_user(world)
    a, b = pair(world, buyer)
    api = buyer_client(buyer)
    path = INTERNAL + 'supplier-shipments/'
    payload = body(world, a, b)
    response = write(api, path, payload, 'multi-draft')
    assert response.status_code == 201, response.data
    result = response.data['data']
    assert set(result['order_ids']) == {a.pk, b.pk}
    assert [r['purchase_order_number'] for r in result['lines']] == ['MULTI-A', 'MULTI-B']
    assert [Decimal(r['unit_price']) for r in result['lines']] == [Decimal('2.5'), Decimal('3.1234')]
    assert write(api, path, payload, 'multi-draft').data['data']['id'] == result['id']
    result = upload(api, path, result)
    response = write(api, path + str(result['id']) + '/submit/', {'expected_version': result['version']}, 'multi-submit')
    assert response.status_code == 200, response.data
    for order, quantity in [(a, 3), (b, 4)]:
        listed = api.get(path, {'order_id': order.pk})
        assert listed.data['count'] == 1
        fulfillment.prepare_orders([order])
        assert order._read_fulfillment['shipped_quantity'] == quantity
        assert order._read_fulfillment['shipment_count'] == 1
        assert order._read_flow_relations['shipments'][0]['quantity'] == quantity


@pytest.mark.parametrize('dimension', ['supplier', 'country', 'draft'])
def test_incompatible_source_rejected_atomically(world, dimension):
    buyer = internal_user(world)
    overrides = {'supplier': world['supplier_b']} if dimension == 'supplier' else {'country': world['country_ca']} if dimension == 'country' else {}
    a, b = pair(world, buyer, **overrides)
    if dimension in ('terms', 'draft'):
        with domain_write():
            if dimension == 'terms':
                b.supplier_terms_snapshot = {**b.supplier_terms_snapshot, 'days': 999}
            else:
                b.status = 'draft'
            b.save()
    with pytest.raises(ValidationError):
        shipments.create_draft(buyer, body(world, a, b), 'bad-multi')
    assert SupplierShipment.objects.count() == 0


def test_multi_po_sources_may_have_different_legacy_term_snapshots(world):
    buyer = internal_user(world)
    a, b = pair(world, buyer)
    with domain_write():
        a.supplier_terms_snapshot = {'days': 30, 'start': 'shipment_date', 'reminder_days': 7}
        b.supplier_terms_snapshot = {'days': 90, 'start': 'collection_arrival', 'reminder_days': 3}
        a.save(update_fields=['supplier_terms_snapshot'])
        b.save(update_fields=['supplier_terms_snapshot'])
    shipment = shipments.create_draft(buyer, body(world, a, b), 'multi-different-po-terms')
    assert shipment.lines.filter(is_active=True).count() == 2


def test_source_permissions_required_for_whole_shipment(world):
    owner = internal_user(world, 'owner', scope=DataScope.ScopeType.OWN)
    other = internal_user(world, 'other')
    a, b = pair(world, owner, other)
    with pytest.raises(NotFound):
        shipments.create_draft(owner, body(world, a, b), 'forbidden-multi')
    obj = services.create_supplier_shipment(other, body(world, a, b), idempotency_key='allowed-multi')
    assert not accessible_shipments(internal_orders(owner, PurchaseOrder.objects.all())).filter(pk=obj.pk).exists()
    with pytest.raises(NotFound):
        shipments.shipment_for(owner, obj.pk)
    assert buyer_client(owner).get(INTERNAL + 'supplier-shipments/').data['count'] == 0


def test_supplier_can_combine_own_orders_without_price_override(world):
    buyer = internal_user(world)
    a, b = pair(world, buyer)
    actor = supplier_user(world, world['supplier'], 'multi-supplier')
    obj = shipments.create_draft(actor, body(world, a, b), 'supplier-multi')
    data = shipments.snapshot(obj)
    assert set(data['order_ids']) == {a.pk, b.pk}
    assert all('unit_price' not in row for row in data['lines'])
    assert obj.lines.get(purchase_line__order=b).unit_price == Decimal('3.1234')


def test_multi_po_dispatch_inbound_provenance(world):
    from apps.masterdata.models import WarehouseMaster
    from tests.test_supply_chain_v2_foundation import freight
    from tests.test_supply_chain_v2_logistics import create, arrive, generate, checked, write as logistics_write
    from apps.supply_chain import logistics
    buyer = internal_user(world)
    a, b = pair(world, buyer)
    obj = services.create_supplier_shipment(buyer, body(world, a, b), idempotency_key='multi-logistics')
    api = buyer_client(buyer)
    batch, _ = create(api, [obj], freight(world))
    batch = arrive(api, batch)
    warehouse = WarehouseMaster.objects.create(tenant=world['tenant'], code='multi-wh', name='Multi warehouse', country_code='US')
    inbound = generate(api, batch, warehouse)
    assert {r['order_number'] for r in inbound['lines']} == {'MULTI-A', 'MULTI-B'}
    inbound, _ = checked(api, inbound)
    response = logistics_write(api, f"inbound-orders/{inbound['id']}/confirm/", {'expected_version': inbound['version']}, 'multi-confirm')
    assert response.status_code == 200, response.data
    for order, qty in [(a, 3), (b, 4)]:
        fulfillment.prepare_orders([order])
        assert order._read_fulfillment['received_quantity'] == qty
        assert order._read_fulfillment['dispatched_quantity'] == qty
        assert order._read_flow_relations['inbounds'][0]['quantity'] == qty
    restricted = internal_user(world, 'logistics-own', scope=DataScope.ScopeType.OWN)
    assert not logistics.batches_for(restricted).exists()


def test_image_request_uses_exact_source_line(world, monkeypatch):
    from apps.supply_chain.internal_product_images import _shipment_sku_image
    buyer = internal_user(world)
    a, b = pair(world, buyer)
    obj = services.create_supplier_shipment(buyer, body(world, a, b), idempotency_key='multi-image')
    rows = list(obj.lines.order_by('id'))
    monkeypatch.setattr('apps.supply_chain.internal_product_images.shipment_line_product_details',
        lambda lines: {line.pk: {'image_url': str(line.purchase_line.order_id)} for line in lines})
    assert _shipment_sku_image(obj, world['sku'].pk, str(rows[0].pk))['image_url'] == str(a.pk)
    assert _shipment_sku_image(obj, world['sku'].pk, str(rows[1].pk))['image_url'] == str(b.pk)
    with pytest.raises(NotFound):
        _shipment_sku_image(obj, world['sku'].pk, '999999999')


def test_inactive_source_line_cannot_reveal_previous_purchase_image(world):
    from apps.supply_chain.internal_product_images import _shipment_sku_image
    owner = internal_user(world, 'image-owner', scope=DataScope.ScopeType.OWN)
    other = internal_user(world, 'image-other')
    a, b = pair(world, owner, other)
    obj = services.create_supplier_shipment(other, body(world, a, b), idempotency_key='image-history')
    historical = obj.lines.get(purchase_line__order=b)
    with domain_write():
        historical.is_active = False
        historical.save(update_fields=['is_active'])
    assert accessible_shipments(internal_orders(owner, PurchaseOrder.objects.all())).filter(pk=obj.pk).exists()
    response = buyer_client(owner).get(
        f'{INTERNAL}supplier-shipments/{obj.pk}/skus/{world["sku"].pk}/image/',
        {'shipment_line_id': historical.pk})
    assert response.status_code == 404
    with pytest.raises(NotFound):
        _shipment_sku_image(obj, world['sku'].pk, str(historical.pk))
