import pytest

from apps.commerce.models import SalesOrderItem
from apps.products.models import ProductSKU, ProductSPU
from tests.test_sales_realtime_board import DAY, _fixture, _grant, _order


@pytest.mark.django_db
def test_board_order_identity_excludes_source_code_collision_and_honors_authorized_store():
    user, tenant, platform, store, run, client = _fixture('board-exact-id')
    _grant(user, 'sales_management.orders.view')
    spu = ProductSPU.objects.create(tenant=tenant, spu_code='SPU-X', product_name='X')
    first_sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code='X', product_name='X')
    second_sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code='Y', product_name='Y')
    first = _order(tenant, platform, store, run, 'canonical-x')
    collision = _order(tenant, platform, store, run, 'source-x')
    SalesOrderItem.objects.filter(sales_order=first).update(internal_sku=first_sku)
    SalesOrderItem.objects.filter(sales_order=collision).update(internal_sku=second_sku, seller_sku='X')
    response = client.get('/api/internal/commerce/orders/', {
        'date_from': DAY, 'date_to': DAY, 'internal_sku_id': first_sku.id, 'include_summary': 'false',
    })
    assert response.status_code == 200
    assert [row['id'] for row in response.json()['data']['results']] == [first.id]
    # A valid but nonmatching identity never broadens the authorized order set.
    response = client.get('/api/internal/commerce/orders/', {'internal_sku_id': 9223372036854775807})
    assert response.status_code == 200
    assert response.json()['data']['results'] == []


@pytest.mark.django_db
@pytest.mark.parametrize('value', ['0', '-1', 'x', '9223372036854775808', '1,2'])
def test_board_order_identity_rejects_invalid_id(value):
    user, tenant, platform, store, run, client = _fixture('board-invalid-id')
    _grant(user, 'sales_management.orders.view')
    response = client.get('/api/internal/commerce/orders/', {'internal_sku_id': value})
    assert response.status_code == 400
