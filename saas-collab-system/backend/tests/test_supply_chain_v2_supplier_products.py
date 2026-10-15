from io import BytesIO
from decimal import Decimal
import pytest
from apps.supply_chain import services
from apps.supply_chain.models import BusinessEvent
from tests.test_supply_chain_v2_foundation import world, internal_user, supplier_user, confirmed_order, po_payload
from tests.test_supply_chain_v2_shipments import supplier_client, buyer_client, EXTERNAL


def product_order(world):
    sku = world['sku']
    sku.image_url = f'/media/product-images/tenant-{world["tenant"].pk}/item.png'
    sku.specification, sku.material, sku.size, sku.color_code = '15L', 'PP', 'M', '蓝'
    sku.spec_values = {'容量': '15L', '用途': '收纳'}
    sku.package_weight = Decimal('500'); sku.product_description = '<script>literal</script>'
    sku.package_length_cm = Decimal('20'); sku.unit = '个'; sku.hs_code = '392490'
    sku.save()
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    supplier = supplier_user(world, world['supplier'], 'supplier-product')
    return buyer, order, supplier


def test_supplier_detail_exposes_frozen_descriptions_but_no_internal_price_fields(world):
    buyer, order, supplier = product_order(world)
    world['sku'].material = 'changed'; world['sku'].spec_values = {'changed': 'new'}; world['sku'].save()
    api = supplier_client(supplier)
    response = api.get(EXTERNAL + f'purchase-orders/{order.pk}/')
    assert response.status_code == 200
    line = response.data['data']['lines'][0]
    assert line['product_details']['material'] == 'PP'
    assert line['product_details']['spec_values']['容量'] == '15L'
    assert line['product_details']['package_weight_g'] == '500.000'
    assert line['product_details']['image_url'].endswith('/item.png')
    assert line['product_details_source'] == 'confirmation'
    assert 'purchase_price' not in line['product_details']
    assert 'product_reference_price' not in line and 'supplier_reference_price' not in line
    assert line['label_pdf_url'] == EXTERNAL + f'purchase-orders/{order.pk}/skus/{world["sku"].pk}/labels/'


def test_product_pdf_is_order_bound_and_contains_one_sku(world):
    fitz = pytest.importorskip('fitz')
    _, order, supplier = product_order(world)
    api = supplier_client(supplier)
    url = EXTERNAL + f'purchase-orders/{order.pk}/skus/{world["sku"].pk}/labels/'
    response = api.get(url)
    assert response.status_code == 200
    content = b''.join(response.streaming_content)
    pdf = fitz.open(stream=content, filetype='pdf')
    assert len(pdf) == 1 and world['sku'].sku_code in pdf[0].get_text()
    assert response['Cache-Control'] == 'private, no-store'
    assert api.get(EXTERNAL + f'purchase-orders/{order.pk}/skus/{world["sku_b"].pk}/labels/').status_code == 404
    other = supplier_user(world, world['supplier_b'], 'other-product-supplier')
    assert supplier_client(other).get(url).status_code == 404
    assert buyer_client(internal_user(world, 'internal-other')).get(url).status_code in (401, 403)


def test_legacy_detail_uses_current_archive_without_rewriting_confirmation_event(world):
    buyer = internal_user(world)
    # Legacy events legitimately lack the newly added descriptive snapshot.
    from unittest.mock import patch
    with patch('apps.supply_chain.supplier_products.enrich_snapshot', side_effect=lambda snapshot, *a, **kw: snapshot):
        order = confirmed_order(world, buyer)
    event = BusinessEvent.objects.get(aggregate_id=order.pk, aggregate_type='purchaseorder', action='confirmed')
    original = event.payload.copy()
    supplier = supplier_user(world, world['supplier'], 'legacy-product')
    result = supplier_client(supplier).get(EXTERNAL + f'purchase-orders/{order.pk}/').data['data']
    assert result['lines'][0]['product_details_source'] == 'current_archive'
    event.refresh_from_db(); assert event.payload == original


def test_supplier_image_endpoint_requires_order_and_product_ownership(world):
    from unittest.mock import patch
    from rest_framework.test import APIClient
    _, order, supplier = product_order(world)
    url = EXTERNAL + f'purchase-orders/{order.pk}/skus/{world["sku"].pk}/image/'
    with patch('apps.supply_chain.supplier_product_images.load_product_images', return_value={world['sku'].pk:{'body':b'test-thumbnail'}}) as loader:
        response = supplier_client(supplier).get(url)
        assert response.status_code == 200 and response['Content-Type'] == 'image/jpeg'
        assert b''.join(response.streaming_content) == b'test-thumbnail'
        assert response['Cache-Control'] == 'private, no-store'
        loader.reset_mock()
        other = supplier_user(world, world['supplier_b'], 'image-other-supplier')
        assert supplier_client(other).get(url).status_code == 404
        assert APIClient().get(url).status_code == 401
        assert supplier_client(supplier).get(EXTERNAL + f'purchase-orders/{order.pk}/skus/{world["sku_b"].pk}/image/').status_code == 404
        loader.assert_not_called()


def test_supplier_image_missing_file_returns_no_content(world):
    _, order, supplier = product_order(world)
    url = EXTERNAL + f'purchase-orders/{order.pk}/skus/{world["sku"].pk}/image/'
    assert supplier_client(supplier).get(url).status_code == 404
