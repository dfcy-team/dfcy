from io import BytesIO

from openpyxl import load_workbook

from apps.supply_chain.documents import purchase_workbook
from apps.supply_chain.supplier_products import enrich_snapshot
from apps.supply_chain import costs, services
from tests.test_supply_chain_v2_foundation import (confirmed_order, internal_user, supplier_user,
    shipment_payload, world)
from tests.test_supply_chain_v2_shipments import EXTERNAL, INTERNAL, supplier_client, buyer_client


def test_legacy_sku_enrichment_uses_related_sku_and_preserves_frozen_blank(world):
    world['sku'].legacy_sku_code = 'OLD-42'
    world['sku'].save(update_fields=['legacy_sku_code'])
    original = {'lines': [
        {'id': 1, 'sku_id': world['sku'].pk, 'product_details': {'image_url': ''}},
        {'id': 2, 'sku_id': world['sku'].pk, 'legacy_sku_code': '', 'product_details': {'image_url': ''}},
    ]}
    enriched = enrich_snapshot(original, world['tenant'].pk)
    assert [line['legacy_sku_code'] for line in enriched['lines']] == ['OLD-42', '']


def test_purchase_workbook_adds_legacy_sku_without_shifting_quantity_inputs():
    content = purchase_workbook({
        'number': 'PO-1', 'supplier_name': '供方', 'country_name': '美国', 'reference_number': '',
        'order_date': '2026-10-14', 'total_quantity': 3, 'total_amount': None, 'notes': '',
        'lines': [{'sku_id': 1, 'sku': 'SKU-1', 'legacy_sku_code': 'OLD-1', 'name': '商品',
                   'quantity': 3, 'unit_price': None, 'product_details': {}}],
    })
    workbook = load_workbook(BytesIO(content))
    purchase = workbook['采购单']
    quantity = workbook['发货数量填写']
    assert purchase.cell(7, purchase.max_column).value == '旧SKU'
    assert purchase.cell(8, purchase.max_column).value == 'OLD-1'
    assert [quantity.cell(5, col).value for col in range(1, 7)] == [
        '商品SKU', '商品名称', '采购数量', '本批发货数量', '备注', '旧SKU']
    assert [quantity.cell(6, col).value for col in range(1, 7)] == ['SKU-1', '商品', 3, None, None, 'OLD-1']


def test_shipment_image_route_allows_document_extra_inactive_sku_and_isolates_supplier(world, monkeypatch):
    from apps.supply_chain import internal_product_images

    buyer = internal_user(world, 'image-buyer')
    order = confirmed_order(world, buyer)
    world['sku_b'].image_url = f"/media/product-images/tenant-{world['tenant'].pk}/extra.png"
    world['sku_b'].save(update_fields=['image_url'])
    shipment = services.create_supplier_shipment(buyer, shipment_payload(world, order, 'image-extra',
        lines=[{'sku_id': world['sku_b'].pk, 'quantity': 1}]), idempotency_key='image-extra')
    monkeypatch.setattr(internal_product_images, 'load_product_images',
        lambda snapshot, tenant_id: {world['sku_b'].pk: {'body': b'image', 'status': 'available'}})
    path = f"{INTERNAL}supplier-shipments/{shipment.pk}/skus/{world['sku_b'].pk}/image/"
    from apps.supply_chain.shipments import snapshot as shipment_snapshot
    line = shipment_snapshot(shipment, internal=True)['lines'][0]
    assert line['product_details']['image_url'] == world['sku_b'].image_url
    assert line['image_preview_url'] == path
    assert buyer_client(buyer).get(path).status_code == 200
    supplier = supplier_user(world, world['supplier'], 'image-supplier')
    option = supplier_client(supplier).get(f"{EXTERNAL}shipment-options/").data['data']['skus']
    sku_option = next(item for item in option if item['id'] == world['sku_b'].pk)
    assert sku_option['legacy_sku_code'] == '' and sku_option['image_preview_url'].endswith(
        f"/shipment-options/skus/{world['sku_b'].pk}/image/")
    assert supplier_client(supplier).get(sku_option['image_preview_url']).status_code == 200
    supplier_path = f"{EXTERNAL}shipments/{shipment.pk}/skus/{world['sku_b'].pk}/image/"
    response = supplier_client(supplier).get(supplier_path)
    assert response.status_code == 200 and response['Cache-Control'] == 'private, no-store'
    assert supplier_client(supplier_user(world, world['supplier_b'], 'other-image-supplier')).get(supplier_path).status_code == 404
    world['sku_b'].is_active = False
    world['sku_b'].save(update_fields=['is_active'])
    assert buyer_client(buyer).get(path).status_code == 200


def test_display_only_sku_edits_do_not_change_cost_input_fingerprint(world):
    buyer = internal_user(world, 'fingerprint-buyer')
    order = confirmed_order(world, buyer)
    shipment = services.create_supplier_shipment(buyer, shipment_payload(world, order, 'fingerprint'),
        idempotency_key='fingerprint')
    before = costs.inputs('shipment', shipment)[1]
    world['sku'].legacy_sku_code = 'OLD-FINGERPRINT'
    world['sku'].image_url = '/media/product-images/tenant-display-only/image.png'
    world['sku'].save(update_fields=['legacy_sku_code', 'image_url'])
    after = costs.inputs('shipment', shipment)[1]
    assert before == after


def test_batch_and_inbound_image_routes_enforce_document_and_actor_scope(world, monkeypatch):
    from apps.supply_chain import internal_product_images
    from tests.test_supply_chain_v2_logistics import BASE, arrive, client, create, generate, setup

    world['sku'].image_url = f"/media/product-images/tenant-{world['tenant'].pk}/document.png"
    world['sku'].save(update_fields=['image_url'])
    buyer, shipment, _other, carrier, warehouse = setup(world)
    monkeypatch.setattr(internal_product_images, 'load_product_images',
        lambda snapshot, tenant_id: {world['sku'].pk: {'body': b'image', 'status': 'available'}})
    api = client(buyer)
    batch, _ = create(api, [shipment], carrier, 'image-batch')
    batch_path = f"{BASE}dispatch-batches/{batch['id']}/skus/{world['sku'].pk}/image/"
    response = api.get(batch_path)
    assert response.status_code == 200 and response['Cache-Control'] == 'private, no-store'
    assert api.get(f"{BASE}dispatch-batches/{batch['id']}/skus/{world['sku_b'].pk}/image/").status_code == 404

    batch = arrive(api, batch)
    inbound = generate(api, batch, warehouse)
    inbound_path = f"{BASE}inbound-orders/{inbound['id']}/skus/{world['sku'].pk}/image/"
    response = api.get(inbound_path)
    assert response.status_code == 200 and response['Cache-Control'] == 'private, no-store'
    assert api.get(f"{BASE}inbound-orders/{inbound['id']}/skus/{world['sku_b'].pk}/image/").status_code == 404

    denied = client(internal_user(world, 'image-scope-denied', scope='own'))
    assert denied.get(batch_path).status_code == 404
    assert denied.get(inbound_path).status_code == 404
