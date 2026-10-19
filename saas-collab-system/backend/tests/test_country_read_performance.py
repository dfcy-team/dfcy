from django.db import connection
from django.test.utils import CaptureQueriesContext
from tests.test_country_inventory_decisions import facts, clock
from apps.commerce.country_decisions import decision_rows

def test_country_read_query_profile(facts):
    with CaptureQueriesContext(connection) as queries:
        rows = decision_rows(facts['actor'], facts['country'], [facts['sku']])
    assert len(rows) == 1
    assert sum('integrations_historysyncsegment' in q['sql'] for q in queries) == 1
    assert sum('ROW_NUMBER' in q['sql'] for q in queries) == 2


def test_full_page_reuses_authorization_branches(facts):
    from apps.products.models import ProductSKU
    skus = [facts['sku']] + [ProductSKU.objects.create(
        tenant=facts['tenant'], spu=facts['spu'], sku_code=f'PAGE-{i}') for i in range(19)]
    with CaptureQueriesContext(connection) as queries:
        rows = decision_rows(facts['actor'], facts['country'], skus)
    assert len(rows) == 20
    # Includes the per-SKU product detail contract; catches per-SKU scope lookups.
    assert len(queries) <= 160


import pytest
from types import SimpleNamespace
from apps.commerce.country_decisions import _country_inventory_source
from apps.integrations.models import SyncRun
from apps.masterdata.models import WarehouseMaster
from django.utils import timezone


@pytest.mark.parametrize('run_count,warehouse_count,joined', [(2000,1000,False),(2001,1,True),(1,1001,True)])
def test_country_dimension_thresholds_never_truncate(facts, monkeypatch, run_count, warehouse_count, joined):
    runs = list(range(1, run_count + 1))
    warehouses = list(range(1, warehouse_count + 1))
    monkeypatch.setattr(SyncRun.objects, 'filter', lambda **kw: SimpleNamespace(values_list=lambda *a, **k: runs))
    monkeypatch.setattr(WarehouseMaster.objects, 'filter', lambda **kw: SimpleNamespace(values_list=lambda *a, **k: warehouses))
    qs = _country_inventory_source(facts['actor'], facts['country'], timezone.now())
    sql, params = qs.query.sql_with_params()
    assert (' JOIN ' in sql) is joined
    if not joined:
        assert len(params) == 2 + run_count + warehouse_count
    else:
        assert 'platformintegrationconfig' in sql and 'country_code' in sql


def test_empty_country_source_ids_do_not_read_inventory(facts, monkeypatch):
    monkeypatch.setattr(SyncRun.objects, 'filter', lambda **kw: SimpleNamespace(values_list=lambda *a, **k: []))
    with CaptureQueriesContext(connection) as queries:
        qs = _country_inventory_source(facts['actor'], facts['country'], timezone.now())
        assert not qs.exists()
    assert not any('inventory_snapshot' in q['sql'] for q in queries)


def test_country_source_matches_joined_filters_with_foreign_dimensions(facts):
    from apps.commerce.models import InventorySnapshot
    from apps.products.models import ProductSPU, ProductSKU
    from tests.test_sales_management import create_scope
    from tests.test_country_inventory_decisions import stock
    tenant, platform, store, warehouse = create_scope('v257-foreign')
    spu = ProductSPU.objects.create(tenant=tenant, spu_code='FOREIGN', product_name='Foreign')
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code='FOREIGN')
    foreign = stock(tenant, warehouse, sku, suffix='foreign-country')
    original = InventorySnapshot.objects.filter(tenant_id=facts['actor'].tenant_id,
        warehouse__country_code__iexact=facts['country'].country_code, snapshot_at_utc__lte=timezone.now(),
        source_run__sync_job__integration_config__platform='jifeng_wms',
        source_run__sync_job__resource_type='inventory_snapshot')
    expected = set(original.values_list('pk', flat=True))
    actual = set(_country_inventory_source(facts['actor'], facts['country'], timezone.now()).values_list('pk', flat=True))
    assert actual == expected == {facts['snapshot'].pk}
    assert foreign.pk not in actual
