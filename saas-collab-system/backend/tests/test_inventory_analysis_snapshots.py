from datetime import timedelta

import pytest

from apps.commerce.models import InventorySnapshot
from tests.test_sales_management import NOW, create_scope, create_run, user_for, grant, client_for

pytestmark = pytest.mark.django_db


@pytest.fixture
def inventory():
    tenant, _, _, warehouse = create_scope('inventory-analysis')
    run = create_run(tenant, 'inventory_snapshot', 'inventory-analysis', platform='jifeng_wms')
    user = user_for(tenant, 'inventory-analysis-viewer')
    grant(user, 'analytics.view')
    def snapshot(sku, at, qty):
        return InventorySnapshot.objects.create(tenant=tenant, warehouse=warehouse, source_run=run,
            site_code='PH', source_sku=sku, snapshot_at_utc=at, on_hand_qty=qty,
            available_qty=qty, payload_hash='f' * 64)
    snapshot('FAKE-SKU', NOW, 8)
    snapshot('FAKE-SKU', NOW + timedelta(hours=1), 12)
    snapshot('FAKE-SKU', NOW + timedelta(days=1), 3)
    return client_for(user), warehouse, snapshot


def test_latest_snapshot_and_daily_trend_do_not_sum_repeat_syncs(inventory):
    client, warehouse, _ = inventory
    data = client.get('/api/internal/analytics/inventory/').json()['data']
    assert data['count'] == 1
    assert data['results'][0]['on_hand_qty'] == 3
    assert [point['total'] for point in data['trend']] == [12, 3]
    assert data['quality']['mapped_count'] == 0
    assert data['quality']['total_count'] == 1
    assert data['quality']['unmapped_count'] == 1
    assert data['risk_summary']['low_stock'] == 1
    assert data['risk_summary']['data_insufficient'] == 1
    assert data['trend_status'] == 'ready'
    assert data['freshness']['status'] in ('fresh', 'delayed', 'stale')
    assert data['warehouse_options'] == [{'value': warehouse.id, 'label': f'{warehouse.name}（{warehouse.code}）'}]


def test_latest_snapshot_excludes_other_sources_and_combines_quality_counts(inventory):
    from django.db import connection
    from apps.products.models import ProductSKU, ProductSPU

    client, warehouse, snapshot = inventory
    tenant = warehouse.tenant
    spu = ProductSPU.objects.create(tenant=tenant, spu_code='COUNT-SPU', product_name='Count test')
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code='COUNT-SKU')
    mapped = snapshot('MAPPED-OUT', NOW, 0)
    mapped.internal_sku = sku
    mapped.save()
    snapshot('LOW', NOW, 4)

    other_run = create_run(tenant, 'inventory_snapshot', 'other-source', platform='amazon')
    # Simulate a legacy/imported source mismatch without invoking model validation.
    other_source = snapshot('OTHER-SOURCE', NOW + timedelta(days=2), 999)
    with connection.cursor() as cursor:
        cursor.execute(
            'UPDATE inventory_snapshot SET source_run_id = %s, source_sku = %s WHERE id = %s',
            [other_run.id, 'FAKE-SKU', other_source.pk],
        )

    data = client.get('/api/internal/analytics/inventory/').json()['data']
    assert data['count'] == 3
    assert data['quality']['total_count'] == 3
    assert data['quality']['mapped_count'] == 1
    assert data['quality']['unmapped_count'] == 2
    assert data['quality']['mapping_rate'] == 33.3
    assert data['summary_metrics'][-1]['value'] == 3
    assert data['summary_metrics'][-1]['change'] == '缺货 1 · 低库存 2'
    assert data['metrics'][0]['value'] == '7'


def test_date_range_selects_latest_snapshot_within_range(inventory):
    client, _, _ = inventory
    data = client.get('/api/internal/analytics/inventory/', {'period_start': '2026-08-17', 'period_end': '2026-08-17'}).json()['data']
    assert data['count'] == 1
    assert data['results'][0]['on_hand_qty'] == 12
    assert len(data['trend']) == 1


def test_risk_filter_applies_after_latest_and_to_trend(inventory):
    client, _, _ = inventory
    data = client.get('/api/internal/analytics/inventory/', {'risk': 'healthy'}).json()['data']
    assert data['count'] == 0
    assert [point['total'] for point in data['trend']] == [12]


def test_mapping_filter_does_not_resurrect_older_snapshot(inventory):
    from apps.products.models import ProductSKU, ProductSPU

    client, warehouse, snapshot = inventory
    spu = ProductSPU.objects.create(tenant=warehouse.tenant, spu_code='MAP-SPU', product_name='Mapped')
    sku = ProductSKU.objects.create(tenant=warehouse.tenant, spu=spu, sku_code='MAP-SKU')
    older = snapshot('MAPPING-CHANGED', NOW, 8)
    older.internal_sku = sku
    older.save()
    snapshot('MAPPING-CHANGED', NOW + timedelta(days=1), 4)
    mapped = client.get('/api/internal/analytics/inventory/', {'mapping_status': 'mapped'}).json()['data']
    assert mapped['count'] == 0
    unmapped = client.get('/api/internal/analytics/inventory/', {'mapping_status': 'unmapped'}).json()['data']
    assert unmapped['count'] == 2
    assert unmapped['quality']['unmapped_count'] == 2


@pytest.mark.parametrize('query', [{'include_virtual': 'invalid'}, {'risk': 'high'}, {'mapping_status': 'broken'}, {'warehouse_id': 'demo'},
    {'period_start': 'bad'}, {'period_start': '2026-08-19', 'period_end': '2026-08-17'}])
def test_invalid_inventory_filters_fail_explicitly(inventory, query):
    client, _, _ = inventory
    assert client.get('/api/internal/analytics/inventory/', query).status_code == 400


def test_empty_period_has_no_fabricated_inventory(inventory):
    client, _, _ = inventory
    data = client.get('/api/internal/analytics/inventory/', {'period_end': '2026-08-01'}).json()['data']
    assert data['count'] == 0
    assert data['trend'] == []
    assert data['quality']['total_count'] == 0
    assert data['freshness']['status'] == 'pending'
    assert data['risk_summary']['data_insufficient'] == 0


def test_virtual_filter_controls_latest_rows_totals_trend_and_pagination(inventory):
    from apps.products.models import ProductSKU, ProductSPU

    client, warehouse, snapshot = inventory
    spu = ProductSPU.objects.create(tenant=warehouse.tenant, spu_code='TYPE-SPU', product_name='Test')
    for code, kind, qty in [('PHYSICAL', 'physical', 10), ('UNSET', None, 20), ('VIRTUAL', 'virtual', 100)]:
        sku = ProductSKU.objects.create(tenant=warehouse.tenant, spu=spu, sku_code=code, inventory_type=kind)
        # An older unlinked snapshot must not replace the latest virtual snapshot.
        snapshot(code, NOW - timedelta(hours=1), 1)
        row = snapshot(code, NOW, qty)
        row.internal_sku = sku
        row.save()
    url = '/api/internal/analytics/inventory/'
    included = client.get(url).json()['data']
    assert included['count'] == 4
    assert included['metrics'][0]['value'] == '133'
    assert client.get(url, {'include_virtual': 'true'}).json()['data']['metrics'] == included['metrics']
    query = {'include_virtual': 'false', 'page_size': 2, 'ordering': '-on_hand_qty'}
    first = client.get(url, query).json()['data']
    second = client.get(url, {**query, 'page': 2}).json()['data']
    assert first['count'] == 3
    assert [row['source_sku'] for row in first['results'] + second['results']] == ['UNSET', 'PHYSICAL', 'FAKE-SKU']
    assert first['metrics'][0]['value'] == '33'
    assert first['quality']['total_count'] == 3
    assert first['quality']['mapped_count'] == 2
    assert [point['total'] for point in first['trend']] == [42, 3]
    assert first['metrics'] == second['metrics']


def test_sorting_is_numeric_global_and_stable_across_pages(inventory):
    client, _, snapshot = inventory
    for index in range(25):
        snapshot(f'SORT-{index:02}', NOW, 100 - index)
    first = client.get('/api/internal/analytics/inventory/', {'ordering': '-on_hand_qty', 'page_size': 20}).json()['data']
    second = client.get('/api/internal/analytics/inventory/', {'ordering': '-on_hand_qty', 'page': 2, 'page_size': 20}).json()['data']
    assert [r['on_hand_qty'] for r in first['results'] + second['results']] == list(range(100, 75, -1)) + [3]
    ascending = client.get('/api/internal/analytics/inventory/', {'ordering': 'on_hand_qty'}).json()['data']
    assert ascending['results'][0]['on_hand_qty'] == 3
    assert ascending['metrics'] == first['metrics']
    assert ascending['trend'] == first['trend']
    # Equal keys keep a stable secondary order across pages.
    one = client.get('/api/internal/analytics/inventory/', {'ordering': 'in_transit_qty', 'page_size': 20}).json()['data']
    two = client.get('/api/internal/analytics/inventory/', {'ordering': 'in_transit_qty', 'page_size': 20, 'page': 2}).json()['data']
    ids = [r['id'] for r in one['results'] + two['results']]
    assert ids == sorted(set(ids))


@pytest.mark.parametrize('ordering', ['source_sku', 'internal_sku', 'warehouse_name', 'warehouse_code',
    'on_hand_qty', 'available_qty', 'reserved_qty', 'in_transit_qty', 'risk_label', 'mapping_status', 'snapshot_time'])
@pytest.mark.parametrize('prefix', ['', '-'])
def test_inventory_sort_whitelist_accepts_display_columns(inventory, ordering, prefix):
    client, _, _ = inventory
    response = client.get('/api/internal/analytics/inventory/', {'ordering': prefix + ordering, 'risk': 'low'})
    assert response.status_code == 200
    assert response.json()['data']['count'] == 1


@pytest.mark.parametrize('ordering', ['tenant_id', 'source_run__id', 'random', '--source_sku', 'source_sku,-id'])
def test_inventory_rejects_unapproved_sort_fields(inventory, ordering):
    client, _, _ = inventory
    assert client.get('/api/internal/analytics/inventory/', {'ordering': ordering}).status_code == 400


def test_sorting_risk_mapping_and_null_internal_skus(inventory):
    from apps.products.models import ProductSKU, ProductSPU
    client, warehouse, snapshot = inventory
    out = snapshot('OUT', NOW, 0)
    locked = snapshot('LOCKED', NOW, 8)
    locked.reserved_qty = 9
    locked.save()
    healthy = snapshot('HEALTHY', NOW, 100)
    spu = ProductSPU.objects.create(tenant=warehouse.tenant, spu_code='SORT-SPU', product_name='Test')
    sku = ProductSKU.objects.create(tenant=warehouse.tenant, spu=spu, sku_code='SORT-SKU')
    healthy.internal_sku = sku
    healthy.save()
    risk = client.get('/api/internal/analytics/inventory/', {'ordering': 'risk_label'}).json()['data']
    assert [r['risk_label'] for r in risk['results']] == ['缺货', '锁定偏高', '低库存', '正常']
    for ordering in ('internal_sku', '-internal_sku', '-mapping_status'):
        data = client.get('/api/internal/analytics/inventory/', {'ordering': ordering}).json()['data']
        assert data['results'][0]['id'] == healthy.id
    data = client.get('/api/internal/analytics/inventory/', {'ordering': 'mapping_status'}).json()['data']
    assert data['results'][-1]['id'] == healthy.id
    data = client.get('/api/internal/analytics/inventory/', {'ordering': '-snapshot_time'}).json()['data']
    assert data['results'][0]['source_sku'] == 'FAKE-SKU'
