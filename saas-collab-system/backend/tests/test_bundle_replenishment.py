from datetime import timedelta

import pytest
from django.utils import timezone
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.commerce import country_decisions
from apps.commerce.models import SalesOrderBundleSnapshot
from apps.products.models import ProductBundleVersion, ProductBundleVersionComponent, ProductSKU, ProductSPU
from tests.test_country_inventory_decisions import NOW, facts as decision_facts, sale, historical_ratio_preview
from tests.test_operating_orders_v2 import OPS, client, write


@pytest.fixture
def bundle_facts(db, monkeypatch):
    monkeypatch.setattr(timezone, 'now', lambda: NOW)
    facts = decision_facts.__wrapped__(db)
    tenant, store, actor = facts['tenant'], facts['store'], facts['actor']
    bundle_spu = ProductSPU.objects.create(tenant=tenant, spu_code='BUNDLE-SPU',
        product_name='Bundle', product_type='bundle')
    bundle = ProductSKU.objects.create(tenant=tenant, spu=bundle_spu, sku_code='BUNDLE-1', product_name='Bundle')
    other_spu = ProductSPU.objects.create(tenant=tenant, spu_code='OTHER-SPU', product_name='Other')
    other = ProductSKU.objects.create(tenant=tenant, spu=other_spu, sku_code='OTHER-1', product_name='Other')

    def bundle_sale(suffix, quantity=2, *, snapshot='valid'):
        order = sale(tenant, store, bundle, suffix, 2, quantity)
        item = order.items.get()
        version = ProductBundleVersion.objects.create(tenant=tenant, bundle_sku=bundle,
            version=ProductBundleVersion.objects.filter(bundle_sku=bundle).count() + 1,
            effective_at=order.created_at_utc - timedelta(days=1), created_by=actor)
        ProductBundleVersionComponent.objects.create(version=version, component_sku=facts['sku'],
            component_sku_code=facts['sku'].sku_code, component_name='Test product', quantity=3)
        ProductBundleVersionComponent.objects.create(version=version, component_sku=other,
            component_sku_code=other.sku_code, component_name='Other', quantity=1)
        payload = [{'component_sku_id': facts['sku'].pk, 'component_sku_code': facts['sku'].sku_code,
                    'component_name': 'Test product', 'quantity': 3},
                   {'component_sku_id': other.pk, 'component_sku_code': other.sku_code,
                    'component_name': 'Other', 'quantity': 1}]
        if snapshot == 'valid':
            SalesOrderBundleSnapshot.objects.create(tenant=tenant, order_item=item, bundle_version=version,
                components_payload=payload)
        elif snapshot == 'invalid':
            payload.append(payload[0])
            SalesOrderBundleSnapshot.objects.create(tenant=tenant, order_item=item, bundle_version=version,
                components_payload=payload)
        return order

    return {**facts, 'bundle': bundle, 'other': other, 'bundle_sale': bundle_sale}


def test_bundle_demand_uses_immutable_order_snapshot_and_keeps_money_direct_only(bundle_facts):
    f = bundle_facts
    f['bundle_sale']('snapshot', quantity=2)
    # A later recipe version must not change demand for an existing order.
    later = ProductBundleVersion.objects.create(tenant=f['tenant'], bundle_sku=f['bundle'], version=2,
        effective_at=NOW, created_by=f['actor'])
    ProductBundleVersionComponent.objects.create(version=later, component_sku=f['other'],
        component_sku_code=f['other'].sku_code, component_name='Other', quantity=50)

    row = country_decisions.decision_rows(f['actor'], f['country'], [f['sku']])[0]
    window = next(item for item in row['sales_windows'] if item['days'] == 30)
    assert window['direct_sales_quantity'] == 61
    assert window['bundle_sales_quantity'] == 6
    assert window['total_demand_quantity'] == window['units'] == 67
    assert window['amount_by_currency'] == {'PHP': '120.0000', 'USD': '2.0000'}
    assert row['suggested_quantity'] == 94
    assert row['available_stock'] == '40'  # Bundle components do not create component inventory.
    other_row = country_decisions.decision_rows(f['actor'], f['country'], [f['other']])[0]
    other_window = next(item for item in other_row['sales_windows'] if item['days'] == 30)
    assert other_window['direct_sales_quantity'] == 0
    assert other_window['bundle_sales_quantity'] == other_window['total_demand_quantity'] == 2


@pytest.mark.parametrize('snapshot', ['missing', 'invalid'])
def test_unknown_bundle_snapshot_blocks_suggestion_and_nulls_total(bundle_facts, snapshot):
    f = bundle_facts
    f['bundle_sale']('bad-' + snapshot, snapshot=snapshot)
    row = country_decisions.decision_rows(f['actor'], f['country'], [f['sku']])[0]
    window = next(item for item in row['sales_windows'] if item['days'] == 30)
    assert 'bundle_composition_unverified' in row['issues']
    assert row['suggested_quantity'] is None
    assert row['direct_sales_quantity'] == 61
    assert row['bundle_sales_quantity'] is None
    assert row['total_demand_quantity'] is None
    assert window['bundle_sales_quantity'] is None and window['total_demand_quantity'] is None


@pytest.mark.parametrize('change', ['remapped', 'future_recipe', 'nested_component'])
def test_invalid_historical_relationship_does_not_become_direct_sales(bundle_facts, change):
    f = bundle_facts
    order = f['bundle_sale']('bad-relation-' + change)
    item = order.items.get()
    snapshot = SalesOrderBundleSnapshot.objects.get(order_item=item)
    if change == 'remapped':
        item.internal_sku = f['sku']
        item.save()
    elif change == 'future_recipe':
        version = snapshot.bundle_version
        version.effective_at = NOW
        version.save()
    else:
        snapshot.components_payload = [{'component_sku_id': f['bundle'].pk, 'quantity': 1}]
        snapshot.save()
    row = country_decisions.decision_rows(f['actor'], f['country'], [f['sku']])[0]
    assert row['direct_sales_quantity'] == 61
    assert row['total_demand_quantity'] is None
    assert row['suggested_quantity'] is None
    assert 'bundle_composition_unverified' in row['issues']


def test_platform_and_operating_reference_expose_same_bundle_demand(bundle_facts):
    f = bundle_facts
    f['bundle_sale']('platform', quantity=2)
    selected = country_decisions.sales_windows(f['actor'], f['country'], [f['sku'].pk], (30,),
        platform_type='shopee')[30]
    assert selected['direct_sales_by_sku'][f['sku'].pk] == 61
    assert selected['bundle_sales_by_sku'][f['sku'].pk] == 6
    assert selected['units_by_sku'][f['sku'].pk] == 67

    response = write(client(f['actor']), OPS + 'references/', {
        'country_id': f['country'].pk, 'source_kind': 'cycle', 'analysis_mode': 'platform',
        'platform_type': 'shopee', 'sales_start': '2026-09-15', 'sales_end': '2026-10-14',
        'target_stock_sales_ratio': '2', 'include_in_transit': True, 'search': f['sku'].sku_code,
    }, 'bundle-reference')
    assert response.status_code == 200, response.data
    line = next(line for line in response.data['data']['lines'] if line['sku_id'] == f['sku'].pk)
    assert line['direct_sales_quantity'] == 61
    assert line['bundle_sales_quantity'] == 6
    assert line['total_demand_quantity'] == 67
    assert line['platform_analysis']['direct_sales_quantity'] == 61
    assert line['platform_analysis']['bundle_sales_quantity'] == 6
    assert line['platform_analysis']['total_demand_quantity'] == 67

    preview = historical_ratio_preview(f['actor'], {
        'country_id': f['country'].pk, 'sku_ids': [f['sku'].pk],
        'sales_start': '2026-09-15', 'sales_end': '2026-10-14', 'sales_window_days': 30,
        'target_days': 60, 'target_stock_sales_ratio': '2', 'include_in_transit': True,
    }, 'bundle-preview')
    preview_line = preview['lines'][0]
    assert preview_line['direct_sales_quantity'] == 61
    assert preview_line['bundle_sales_quantity'] == 6
    assert preview_line['total_demand_quantity'] == 67
    assert preview_line['suggested_quantity'] == 94


def test_bundle_orders_are_batch_scanned_with_constant_queries_per_chunk(bundle_facts):
    f = bundle_facts
    f['bundle_sale']('query-one')
    with CaptureQueriesContext(connection) as one_order:
        country_decisions.sales_windows(f['actor'], f['country'], [f['sku'].pk], (30,))
    for index in range(9):
        f['bundle_sale'](f'query-extra-{index}')
    with CaptureQueriesContext(connection) as ten_orders:
        country_decisions.sales_windows(f['actor'], f['country'], [f['sku'].pk], (30,))
    assert len(ten_orders.captured_queries) == len(one_order.captured_queries)
