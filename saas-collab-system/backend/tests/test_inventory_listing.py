from decimal import Decimal

import pytest

from apps.commerce.inventory_listing import apply_listing_observation


@pytest.mark.parametrize('quantity', [Decimal('2'), '12'])
def test_stock_without_platform_mapping_is_visible_even_when_sales_coverage_is_unknown(quantity):
    row = {'sku_id': 1, 'on_hand_stock': quantity, 'mapped_sales_units': 0,
           'mapped_sales_complete': False, 'operations': {'sales_status': 'unknown'}}
    apply_listing_observation(row, False)
    assert row['stock_sales_status'] == 'stock_no_sales'
    assert row['operations']['sales_status'] == 'no_sales'
    assert row['platform_mapping_status'] == 'unlinked'


@pytest.mark.parametrize('linked,sales,stock', [(True, 0, 5), (False, 2, 5), (False, 0, 0), (False, 0, None)])
def test_known_sales_and_unknown_or_zero_stock_do_not_become_unlisted_stock(linked, sales, stock):
    row = {'on_hand_stock': stock, 'mapped_sales_units': sales, 'operations': {'sales_status': 'unknown'}}
    apply_listing_observation(row, linked)
    assert 'stock_sales_status' not in row


def test_last_successful_stock_is_visible_while_current_stock_is_unavailable():
    row = {'available_stock': None, 'mapped_sales_units': 0,
           'warehouses': [{'available_qty': None, 'last_synced_qty': '9'}], 'operations': {}}
    apply_listing_observation(row, False)
    assert row['stock_sales_status'] == 'stock_no_sales'
    assert row['available_stock'] is None


def test_classification_does_not_generate_purchase_quantity():
    row = {'on_hand_stock': 3, 'total_demand_quantity': None, 'suggested_quantity': None, 'operations': {}}
    apply_listing_observation(row, False)
    assert row['suggested_quantity'] is None


@pytest.mark.django_db
def test_mapping_in_another_country_or_tenant_does_not_hide_unlisted_stock():
    from apps.commerce.inventory_listing import linked_sku_ids
    from apps.listings.models import PlatformProductDetail
    from apps.products.models import ProductSPU, ProductSKU
    from tests.test_sales_management import create_scope
    tenant, platform, store, warehouse = create_scope('listing-country')
    spu = ProductSPU.objects.create(tenant=tenant, spu_code='LIST-SPU')
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code='LIST-SKU')
    PlatformProductDetail.objects.create(tenant=tenant, platform=platform, store=store,
        platform_product_id='P', platform_variant_id='V', internal_sku=sku)
    assert linked_sku_ids(tenant.pk, store.country_code, [sku.pk]) == {sku.pk}
    assert linked_sku_ids(tenant.pk, 'MY', [sku.pk]) == set()
    assert linked_sku_ids(tenant.pk + 999, store.country_code, [sku.pk]) == set()


def test_mapping_created_after_cached_unlisted_result_removes_old_reason():
    row = {'mapped_only': True, 'on_hand_stock': 2, 'available_stock': 2,
           'inventory_complete': True, 'mapped_sales_units': 0,
           'mapped_sales_complete': False, 'operations': {'sales_status': 'unknown'}}
    apply_listing_observation(row, False)
    assert row['operations']['sales_status'] == 'no_sales'
    apply_listing_observation(row, True)
    assert row['platform_mapping_status'] == 'linked'
    assert 'stock_sales_reason' not in row
    assert row['operations']['sales_status'] == 'unknown'


def test_nonmapped_decision_retains_observed_sales_when_complete_demand_is_unknown():
    row = {'on_hand_stock': 7, 'total_demand_quantity': None,
           'sales_windows': [{'days': 30, 'units': 2}], 'operations': {}}
    apply_listing_observation(row, False)
    assert 'stock_sales_status' not in row
