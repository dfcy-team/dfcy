from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from apps.reports import datasets
from tests.test_sales_management import NOW, create_scope, create_run, user_for, grant
from tests.test_inventory_workbench import _snapshot
from tests.test_report_revision import _config

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('code', ['Exact-A', 'Exact-A ', 'exact-a'])
def test_source_filter_reaches_window_preserving_exact_identity(code):
    tenant, _, _, warehouse = create_scope('pushdown')
    run = create_run(tenant, 'inventory_snapshot', 'pushdown', platform='jifeng_wms')
    for other in ['Exact-A', 'Exact-A ', 'exact-a']:
        _snapshot(tenant, warehouse, run, other, NOW-timedelta(days=1), 9)
        _snapshot(tenant, warehouse, run, other, NOW, 2)
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


def test_cutoff_keeps_last_snapshot_before_date():
    tenant, _, _, warehouse = create_scope('pushdown-cutoff')
    run = create_run(tenant, 'inventory_snapshot', 'cutoff', platform='jifeng_wms')
    _snapshot(tenant, warehouse, run, 'cutoff', NOW-timedelta(days=2), 7)
    _snapshot(tenant, warehouse, run, 'cutoff', NOW+timedelta(days=2), 0)
    user = user_for(tenant, 'cutoff'); grant(user, 'reports.view'); grant(user, 'sales_management.view')
    result = datasets.query_dataset(SimpleNamespace(user=user), _config('inventory', ['sku'], ['available'], {'date_to':NOW.date().isoformat(), 'sku':'cutoff', 'sku_mode':'source'}), use_cache=False)
    assert result['rows'] == [{'sku':'cutoff', 'available':7}]
