import pytest
from rest_framework.test import APIClient
from apps.products.models import ProductSKU, ProductSPU, ProductLegacyItem
from apps.tenants.models import Tenant


@pytest.mark.django_db
@pytest.mark.parametrize('kind', ['skus', 'legacy-items'])
def test_optional_inventory_type_patch_and_clear(kind):
    tenant = Tenant.objects.create(name='Inventory type', code='inventory-type')
    from apps.permissions.models import Permission
    from tests.test_product_detail_fields import _user
    for code in ('products.master.view', 'products.master.manage'):
        Permission.objects.get_or_create(code=code, defaults={'name': code})
    user = _user(tenant, 'inventory-type-user')
    spu = ProductSPU.objects.create(tenant=tenant, spu_code='TEST-SPU', product_name='Test')
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code='TEST-SKU')
    legacy = ProductLegacyItem.objects.create(tenant=tenant, legacy_sku_code='OLD-SKU', product_name='Test',
        generated_spu=spu, generated_sku=sku, status='generated')
    item = sku if kind == 'skus' else legacy
    assert item.inventory_type is None
    client = APIClient()
    client.force_authenticate(user)
    url = f'/api/internal/products/{kind}/{item.id}/'
    for value in ['virtual', 'physical']:
        response = client.patch(url, {'inventory_type': value}, format='json')
        assert response.status_code == 200
        item.refresh_from_db()
        sku.refresh_from_db()
        assert item.inventory_type == sku.inventory_type == value
    for payload in [{}, {'inventory_type': ''}, {'inventory_type': None}]:
        assert client.patch(url, payload, format='json').status_code == 200
        item.refresh_from_db()
        assert item.inventory_type == 'physical'
    assert client.patch(url, {'inventory_type': 'invalid'}, format='json').status_code == 400
    assert client.patch(url, {'clear_fields': ['inventory_type']}, format='json').status_code == 200
    item.refresh_from_db()
    sku.refresh_from_db()
    assert item.inventory_type is None and sku.inventory_type is None
    other = Tenant.objects.create(name='Other', code='other-inventory')
    client.force_authenticate(_user(other, 'other-inventory-user'))
    assert client.patch(url, {'inventory_type': 'virtual'}, format='json').status_code == 404
