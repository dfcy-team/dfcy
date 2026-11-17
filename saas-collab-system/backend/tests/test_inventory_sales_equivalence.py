import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from apps.commerce.inventory_sales import sales_windows
from tests.inventory_sales_reference import reference_sales_windows
from tests.test_country_inventory_decisions import facts, clock, sale, history_coverage
from apps.masterdata.models import StoreMaster


def normalized(value):
    if isinstance(value, dict):
        return {key: sorted(set(item)) if key == 'issues' else normalized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalized(item) for item in value]
    return value


@pytest.mark.parametrize('windows', [(7,), (7, 15, 30), (15, 30)])
def test_all_windows_match_existing_calculation(facts, windows):
    f = facts
    args = (f['actor'], f['country'], [f['sku'].pk], windows)
    assert normalized(sales_windows(*args)) == normalized(reference_sales_windows(*args))


def test_more_same_timezone_stores_do_not_add_per_store_sales_queries(facts):
    f = facts
    args = (f['actor'], f['country'], [f['sku'].pk], (7, 15, 30))
    with CaptureQueriesContext(connection) as first:
        expected = sales_windows(*args)
    for index in range(3):
        store = StoreMaster.objects.create(tenant=f['tenant'], platform=f['store'].platform,
            code=f'batch-{index}', name=f'Batch {index}', country_code=f['store'].country_code,
            timezone=f['store'].timezone, currency=f['store'].currency, status='active')
        sale(f['tenant'], store, f['sku'], f'batch-{index}', 2, index + 1)
    with CaptureQueriesContext(connection) as second:
        result = sales_windows(*args)
    assert len(first) == len(second)
    assert result[7]['units_by_sku'][f['sku'].pk] == expected[7]['units_by_sku'][f['sku'].pk] + 6
    assert normalized(result) == normalized(reference_sales_windows(*args))


def test_invalid_timezone_keeps_other_store_totals_and_coverage_flags(facts):
    f = facts
    StoreMaster.objects.create(tenant=f['tenant'], platform=f['store'].platform,
        code='invalid-zone', name='Invalid zone', country_code=f['store'].country_code,
        timezone='Invalid/Zone', currency=f['store'].currency, status='active')
    args = (f['actor'], f['country'], [f['sku'].pk], (7, 30))
    assert normalized(sales_windows(*args)) == normalized(reference_sales_windows(*args))


def test_latest_identity_keeps_timestamp_order_after_late_import(facts):
    from apps.sales_management.inventory_queries import materialized_latest_inventory
    from apps.commerce.models import InventorySnapshot
    from tests.test_country_inventory_decisions import stock
    f = facts
    tied = stock(f['tenant'], f['warehouse'], f['sku'], suffix='newer', hours=0.5)
    late_import = stock(f['tenant'], f['warehouse'], f['sku'], suffix='older-import', hours=5)
    source = InventorySnapshot.objects.filter(tenant=f['tenant'])
    assert list(materialized_latest_inventory(source).values_list('pk', flat=True)) == [tied.pk]
    tied.internal_sku = None
    tied.save()
    assert not materialized_latest_inventory(source).filter(internal_sku__isnull=False).exists()
    assert not materialized_latest_inventory(source.none()).exists()


@pytest.mark.parametrize('end', ['2026-10-15', '2026-10-16'])
def test_unfinished_store_day_does_not_produce_sales(facts, end):
    from datetime import date
    f = facts
    args = (f['actor'], f['country'], [f['sku'].pk], (7, 30))
    kwargs = {'end_date': date.fromisoformat(end)}
    assert normalized(sales_windows(*args, **kwargs)) == normalized(reference_sales_windows(*args, **kwargs))


def test_inventory_report_skips_financial_work_and_keeps_sales_classification(facts):
    f = facts
    args = (f['actor'], f['country'], [f['sku'].pk], (30,))
    reference = reference_sales_windows(*args)[30]
    with CaptureQueriesContext(connection) as queries:
        current = sales_windows(*args, inventory_only=True)[30]
    for key in ['units_by_sku', 'coverage_complete', 'unmapped', 'bundle_composition_unverified', 'stores']:
        assert current[key] == reference[key]
    assert not any('refund_return' in row['sql'] for row in queries)
    assert current['source_run_ids'] == set()


def test_read_only_database_connection_uses_a_select_only_fallback(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from apps.sales_management.inventory_queries import eligible_inventory_orders
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchone.return_value = (1,)
    connection = SimpleNamespace(vendor='mysql', cursor=lambda: cursor)
    monkeypatch.setattr('django.db.connections', {'inventory-test': connection})
    expected = object()
    orders = SimpleNamespace(db='inventory-test', values=lambda *fields: expected)
    with eligible_inventory_orders(orders) as result:
        assert result is expected
    cursor.execute.assert_called_once_with('SELECT @@transaction_read_only')


def test_private_order_selection_is_dropped_when_calculation_fails(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from apps.sales_management.inventory_queries import eligible_inventory_orders
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchone.return_value = (0,)
    connection = SimpleNamespace(vendor='mysql', cursor=lambda: cursor,
                                 ops=SimpleNamespace(quote_name=lambda name: name), close=MagicMock())
    monkeypatch.setattr('django.db.connections', {'inventory-test': connection})
    orders = MagicMock()
    orders.db = 'inventory-test'
    compiler = orders.order_by.return_value.annotate.return_value.values.return_value.query.get_compiler.return_value
    compiler.as_sql.return_value = ('SELECT 42 AS eligible_id', ())
    with pytest.raises(RuntimeError, match='calculation failed'):
        with eligible_inventory_orders(orders):
            raise RuntimeError('calculation failed')
    assert cursor.execute.call_args_list[-1].args[0].startswith('DROP TEMPORARY TABLE IF EXISTS tmp_inventory_orders_')
    connection.close.assert_not_called()
