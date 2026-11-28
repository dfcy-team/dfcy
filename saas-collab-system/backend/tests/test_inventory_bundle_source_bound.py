from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from apps.commerce.inventory_sales import _bundle_product_source
from apps.commerce.models import SalesOrderItem
from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant
from tests.test_country_inventory_decisions import facts, sale


@pytest.mark.parametrize('ids, expected_filter, expected_value', [
    ([], 'internal_sku_id__in', []),
    (list(range(2000)), 'internal_sku_id__in', list(range(2000))),
    (list(range(2001)), 'internal_sku__product_type', 'bundle'),
])
def test_bundle_source_is_bounded_and_falls_back_without_truncation(monkeypatch, ids, expected_filter, expected_value):
    products = MagicMock()
    products.order_by.return_value.values_list.return_value.__getitem__.return_value = ids
    monkeypatch.setattr('apps.commerce.inventory_sales.ProductSKU.objects.filter', lambda **kwargs: products)
    source = MagicMock()

    _bundle_product_source(source)

    products.order_by.assert_called_once_with()
    products.order_by.return_value.values_list.assert_called_once_with('pk', flat=True)
    if expected_filter == 'internal_sku_id__in':
        source.filter.assert_called_once_with(internal_sku_id__in=expected_value)
    else:
        source.filter.assert_called_once_with(internal_sku__product_type=expected_value)


def test_bundle_source_matches_fk_predicate_across_catalog_edges(facts):
    f = facts
    bundle = ProductSKU.objects.create(tenant=f['tenant'], spu=f['spu'], sku_code='BUNDLE',
                                       product_type='bundle')
    inactive = ProductSKU.objects.create(tenant=f['tenant'], spu=f['spu'], sku_code='INACTIVE-BUNDLE',
                                         product_type='bundle', is_active=False)
    other_tenant = Tenant.objects.create(name='Foreign bundle tenant', code='foreign-bundle-tenant')
    foreign_spu = ProductSPU.objects.create(tenant=other_tenant, spu_code='FOREIGN-BUNDLE',
                                             product_name='Foreign bundle')
    foreign_bundle = ProductSKU.objects.create(tenant=other_tenant, spu=foreign_spu,
                                                sku_code='FOREIGN-BUNDLE-SKU', product_type='bundle')

    ordinary_order = sale(f['tenant'], f['store'], f['sku'], 'ordinary-bound', 1, 1)
    null_order = sale(f['tenant'], f['store'], f['sku'], 'null-bound', 1, 1)
    null_order.items.update(internal_sku=None)
    bundle_order = sale(f['tenant'], f['store'], bundle, 'bundle-bound', 1, 1)
    inactive_order = sale(f['tenant'], f['store'], inactive, 'inactive-bundle-bound', 1, 1)
    foreign_order = sale(f['tenant'], f['store'], f['sku'], 'foreign-bundle-bound', 1, 1)
    # Reproduce a legacy/anomalous FK row that the old relation predicate still sees.
    with patch.object(SalesOrderItem, 'clean', lambda self: None):
        foreign_order.items.update(internal_sku_id=foreign_bundle.pk)

    source = SalesOrderItem.objects.filter(sales_order_id__in=[ordinary_order.pk, null_order.pk,
        bundle_order.pk, inactive_order.pk, foreign_order.pk])
    expected = set(source.filter(internal_sku__product_type='bundle').values_list('pk', flat=True))
    actual = set(_bundle_product_source(source).values_list('pk', flat=True))
    assert actual == expected
    assert actual == {bundle_order.items.get().pk, inactive_order.items.get().pk, foreign_order.items.get().pk}
