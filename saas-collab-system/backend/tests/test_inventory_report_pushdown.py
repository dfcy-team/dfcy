from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from apps.reports import datasets
from apps.sales_management.models import InventorySnapshot
from tests.test_sales_management import NOW, create_scope, create_run, user_for, grant
from tests.test_inventory_workbench import _snapshot
from tests.test_report_revision import _config

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('code', ['Exact-A', 'Exact-A ', 'exact-a'])
def test_source_filter_reaches_window_preserving_exact_identity(code):
    tenant, _, _, warehouse = create_scope('pushdown')
    run = create_run(tenant, 'inventory_snapshot', 'pushdown', platform='jifeng_wms')
    _snapshot(tenant, warehouse, run, code, NOW-timedelta(days=1), 9)
    _snapshot(tenant, warehouse, run, code, NOW, 2)
    user = user_for(tenant, 'pushdown'); grant(user, 'reports.view'); grant(user, 'sales_management.view')
    original = datasets._inventory_latest
    observed = []
    def capture(qs):
        observed.append(set(qs.values_list('source_sku', flat=True)))
        return original(qs)
    with patch.object(datasets, '_inventory_latest', side_effect=capture):
        result = datasets.query_dataset(SimpleNamespace(user=user), _config('inventory', ['warehouse_id', 'sku'], ['available'], {'warehouse_id':str(warehouse.pk), 'sku':code, 'sku_mode':'source'}), use_cache=False)
    assert observed == [{code}]
    assert result['rows'] == [{'warehouse_id':warehouse.pk, 'sku':code, 'available':2}]


@pytest.mark.parametrize(('older_code', 'newer_code'), [
    ('Exact-A', 'exact-a'),
    ('café', 'cafe\u0301'),
    ('pad', 'pad '),
])
def test_source_pushdown_preserves_database_collation_partitions(older_code, newer_code):
    tenant, _, _, warehouse = create_scope('pushdown-collation')
    run = create_run(tenant, 'inventory_snapshot', 'pushdown-collation', platform='jifeng_wms')
    _snapshot(tenant, warehouse, run, older_code, NOW-timedelta(days=1), 7)
    _snapshot(tenant, warehouse, run, newer_code, NOW, 0)
    user = user_for(tenant, 'pushdown-collation'); grant(user, 'reports.view'); grant(user, 'sales_management.view')
    all_rows = InventorySnapshot.objects.filter(tenant=tenant, warehouse=warehouse)
    same_partition = all_rows.filter(source_sku=older_code).filter(source_sku=newer_code).exists()
    original = datasets._inventory_latest
    observed = []
    def capture(qs):
        observed.append(set(qs.values_list('source_sku', flat=True)))
        return original(qs)
    with patch.object(datasets, '_inventory_latest', side_effect=capture):
        result = datasets.query_dataset(SimpleNamespace(user=user), _config('inventory', ['sku'], ['available'], {'sku':older_code, 'sku_mode':'source'}), use_cache=False)
    assert observed == [set(all_rows.filter(source_sku=older_code).values_list('source_sku', flat=True))]
    # When the database collation merges the identifiers, the newer row wins
    # the complete partition and the later exact predicate must return nothing.
    assert result['rows'] == ([] if same_partition else [{'sku':older_code, 'available':7}])


def test_cutoff_keeps_last_snapshot_before_date():
    tenant, _, _, warehouse = create_scope('pushdown-cutoff')
    run = create_run(tenant, 'inventory_snapshot', 'cutoff', platform='jifeng_wms')
    _snapshot(tenant, warehouse, run, 'cutoff', NOW-timedelta(days=2), 7)
    _snapshot(tenant, warehouse, run, 'cutoff', NOW+timedelta(days=2), 0)
    user = user_for(tenant, 'cutoff'); grant(user, 'reports.view'); grant(user, 'sales_management.view')
    result = datasets.query_dataset(SimpleNamespace(user=user), _config('inventory', ['sku'], ['available'], {'date_to':NOW.date().isoformat(), 'sku':'cutoff', 'sku_mode':'source'}), use_cache=False)
    assert result['rows'] == [{'sku':'cutoff', 'available':7}]
