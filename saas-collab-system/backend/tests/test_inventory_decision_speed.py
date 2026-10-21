"""Reproducible menu/calculation benchmarks; only generated fixture data."""
import json
import os
import hashlib
from datetime import timedelta
from collections import Counter
from pathlib import Path
from statistics import median
from time import perf_counter
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from apps.alerts.models import InventoryDecisionRow, InventoryDecisionView, InventoryAlert
from apps.commerce.country_decisions import decision_rows
from apps.products.models import ProductSKU
from tests.test_country_inventory_decisions import facts, clock, NOW
from tests.test_inventory_decision_workflow import query, build_all, evaluator, rule, evaluate
from tests.test_supply_chain_v2_logistics import client


@contextmanager
def uncached_calculation_permissions():
    """Paired pre-change path on the same fixture/process, never a runtime flag."""
    from apps.commerce import country_decisions, supply_pipeline
    from apps.sales_management import scopes
    def without_cache(function):
        def call(*args, **kwargs):
            kwargs['cache'] = None
            return function(*args, **kwargs)
        return call
    with ExitStack() as stack:
        for module in (country_decisions, supply_pipeline, scopes):
            for name in ('check_user_permission', 'get_permission_data_scopes'):
                function = getattr(module, name, None)
                if function:
                    stack.enter_context(patch.object(module, name, without_cache(function)))
        yield


def test_inventory_menu_and_calculation_benchmark(facts):
    f = facts
    ProductSKU.objects.bulk_create([ProductSKU(tenant=f['tenant'], spu=f['spu'], sku_code=f'SPEED-{i:05d}')
                                   for i in range(999)])
    skus = list(ProductSKU.objects.filter(tenant=f['tenant']).select_related('spu__category_node').order_by('pk')[:100])
    if connection.vendor == 'sqlite':
        with connection.cursor() as cursor:
            cursor.execute('ANALYZE')
    timings, counts, calculation_queries = [], [], []
    baseline_timings, baseline_counts = [], []
    for _ in range(5):
        started = perf_counter()
        with uncached_calculation_permissions(), CaptureQueriesContext(connection) as baseline_queries:
            baseline_rows = decision_rows(f['actor'], f['country'], skus)
        baseline_timings.append(perf_counter() - started); baseline_counts.append(len(baseline_queries))
        started = perf_counter()
        with CaptureQueriesContext(connection) as queries:
            rows = decision_rows(f['actor'], f['country'], skus)
        timings.append(perf_counter() - started); counts.append(len(queries))
        calculation_queries = [q['sql'] for q in queries]
        assert len(rows) == 100 and rows[0]['suggested_quantity'] == 82
        assert rows == baseline_rows
    query(f); build_all()
    if connection.vendor == 'sqlite':
        with connection.cursor() as cursor:
            cursor.execute('ANALYZE')
    timings_page, counts_page, page_queries = [], [], []
    for _ in range(7):
        started = perf_counter()
        with CaptureQueriesContext(connection) as queries:
            page = query(f, decision_state='pending', offset=960)
        timings_page.append(perf_counter() - started); counts_page.append(len(queries))
        page_queries = [q['sql'] for q in queries]
        assert page['count'] == 999 and len(page['results']) == 20
    payload_sql = next(sql for sql in page_queries if 'SELECT' in sql and '"payload"' in sql)
    plan = []
    if connection.vendor == 'sqlite':
        with connection.cursor() as cursor:
            cursor.execute('EXPLAIN QUERY PLAN ' + payload_sql)
            plan = [list(row) for row in cursor.fetchall()]
    view = InventoryDecisionView.objects.get()
    fetch_baseline, fetch_indexed = [], []
    for _ in range(7):
        for ordering, timings_for_order in ((('sku__sku_code','sku_id'),fetch_baseline),
                                            (('sku_code_snapshot','sku_id'),fetch_indexed)):
            started = perf_counter()
            payload = list(InventoryDecisionRow.objects.filter(view=view,revision=view.revision,decision_state='pending')
                .order_by(*ordering).values_list('payload',flat=True)[960:980])
            timings_for_order.append(perf_counter()-started)
            assert len(payload)==20
    artifact = {'engine': connection.vendor, 'catalog_skus':1000, 'calculation_skus':100,
        'paired_baseline_calculation_ms':round(median(baseline_timings)*1000,3),
        'paired_baseline_calculation_sql':baseline_counts,
        'calculation_median_ms':round(median(timings)*1000,3), 'calculation_sql':counts,
        'paired_baseline_row_fetch_ms':round(median(fetch_baseline)*1000,3),
        'indexed_row_fetch_ms':round(median(fetch_indexed)*1000,3),
        'page_size':20, 'page_median_ms':round(median(timings_page)*1000,3), 'page_sql':counts_page,
        'page_plan':plan, 'calculation_query_counts': dict(Counter(
            sql.split(' FROM ')[-1].split(' ')[0] for sql in calculation_queries if ' FROM ' in sql))}
    target = os.getenv('INVENTORY_SPEED_ARTIFACT')
    if target:
        path = Path(target); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(artifact, ensure_ascii=False))
    assert all('inventory_snapshot' not in sql and 'sales_order' not in sql for sql in page_queries)
    assert max(counts) <= 52
    assert max(counts_page) <= 35
    if connection.vendor == 'sqlite':
        assert not any('TEMP B-TREE' in str(row) for row in plan)
        positive_plan = InventoryDecisionRow.objects.filter(view=view,revision=view.revision,
            has_suggestion__in=[True]).order_by('sku_code_snapshot','sku_id').explain()
        assert 'idx_inventory_row_positive' in positive_plan and 'TEMP B-TREE' not in positive_plan


def test_inventory_alert_list_benchmark(facts):
    f = facts; actor = evaluator(f); configured_rule = rule(f); evaluate(f, actor)
    skus = ProductSKU.objects.bulk_create([ProductSKU(tenant=f['tenant'], spu=f['spu'], sku_code=f'ALERT-SPEED-{i:05d}')
                                         for i in range(999)])
    InventoryAlert.objects.bulk_create([InventoryAlert(tenant=f['tenant'], rule=configured_rule, sku=sku,
        spu=f['spu'], warehouse_code='COUNTRY:PH', alert_type='low_coverage', severity='high', available_stock=1,
        in_transit_stock=0, average_daily_sales=1, coverage_days=1, threshold_value=30,
        dedup_key=hashlib.sha256(sku.sku_code.encode()).hexdigest(), reason='Generated benchmark',
        source_summary={'mode':'real_observation','country_id':f['country'].pk}, evaluation_state='risk',
        data_valid_until=NOW+timedelta(hours=23), triggered_at=NOW) for sku in skus])
    if connection.vendor == 'sqlite':
        with connection.cursor() as cursor:
            cursor.execute('ANALYZE')
    elapsed, counts, last_queries = [], [], []
    api = client(actor)
    for _ in range(7):
        started = perf_counter()
        with CaptureQueriesContext(connection) as queries:
            response = api.get('/api/internal/alerts/inventory/', {'validity':'valid','source_mode':'real_observation',
                                                                 'page':40,'page_size':20})
        elapsed.append(perf_counter()-started); counts.append(len(queries))
        last_queries = [q['sql'] for q in queries]
        assert response.status_code == 200 and response.data['data']['count'] == 1000
    artifact = {'engine':connection.vendor,'alerts':1000,'page_size':20,
                'median_ms':round(median(elapsed)*1000,3), 'sql':counts}
    target = os.getenv('INVENTORY_SPEED_ARTIFACT')
    if target:
        path = Path(target).with_name(Path(target).stem+'-alerts.json')
        path.write_text(json.dumps(artifact,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(artifact,ensure_ascii=False))
    assert not any('alerts_inventoryalertevent' in sql for sql in last_queries)
    assert max(counts) <= 29


def test_builder_drains_ten_chunks_without_waiting_for_next_beat(monkeypatch):
    from apps.alerts import tasks, inventory_views
    calls = []
    monkeypatch.setattr(tasks, 'monotonic', lambda: 0)
    monkeypatch.setattr(inventory_views, 'recover_views', lambda: None)
    def build(limit):
        calls.append(limit)
        return {'processed':100, 'completed':int(len(calls)==10), 'failed':0}
    monkeypatch.setattr(inventory_views, 'build_pending_views', build)
    with override_settings(INVENTORY_DECISION_BACKGROUND_TASKS_ENABLED=True):
        result = tasks.build_inventory_decision_views.run()
    assert calls == [2]*10
    assert result == {'processed':1000,'completed':1,'failed':0}


def test_builder_yields_when_time_budget_expires(monkeypatch):
    from apps.alerts import tasks, inventory_views
    from unittest.mock import Mock
    moments = iter([0,4])
    monkeypatch.setattr(tasks, 'monotonic', lambda: next(moments))
    monkeypatch.setattr(inventory_views, 'recover_views', lambda: None)
    build = Mock(return_value={'processed':100,'completed':0,'failed':0})
    monkeypatch.setattr(inventory_views, 'build_pending_views', build)
    with override_settings(INVENTORY_DECISION_BACKGROUND_TASKS_ENABLED=True):
        result = tasks.build_inventory_decision_views.run()
    assert result['processed'] == 100
    build.assert_called_once_with(limit=2)


def test_inventory_background_tasks_skip_queued_work_when_disabled(monkeypatch):
    from apps.alerts import tasks

    monkeypatch.setattr(tasks.settings, 'INVENTORY_DECISION_BACKGROUND_TASKS_ENABLED', False)
    with patch('apps.alerts.inventory_refresh.refresh_due_decisions', side_effect=AssertionError('refresh ran')), \
         patch('apps.alerts.inventory_views.recover_views', side_effect=AssertionError('recovery ran')):
        expected = {'skipped': True, 'reason': 'inventory_decision_background_tasks_disabled'}
        assert tasks.refresh_inventory_decisions.run() == expected
        assert tasks.build_inventory_decision_views.run() == expected


def test_inventory_background_schedule_is_default_off():
    from django.conf import settings

    assert settings.INVENTORY_DECISION_BACKGROUND_SCHEDULE_ENABLED is False
    assert settings.INVENTORY_DECISION_BACKGROUND_TASKS_ENABLED is False
    assert 'build-inventory-decision-views' not in settings.CELERY_BEAT_SCHEDULE
    assert 'refresh-inventory-decisions' not in settings.CELERY_BEAT_SCHEDULE


def test_online_index_operations_use_concurrent_postgresql_ddl():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from django.db import models
    from apps.alerts.migration_operations import OnlineAddIndex, OnlineRemoveIndex
    index = models.Index(fields=['view','revision'],name='test_online_index')
    model = object()
    state = SimpleNamespace(apps=SimpleNamespace(get_model=lambda *args:model),
        models={('alerts','inventorydecisionrow'): SimpleNamespace(get_index_by_name=lambda name:index)})
    editor = SimpleNamespace(connection=SimpleNamespace(vendor='postgresql',alias='default'),
                             add_index=Mock(),remove_index=Mock())
    for operation in (OnlineAddIndex(model_name='inventorydecisionrow',index=index),
                      OnlineRemoveIndex(model_name='inventorydecisionrow',name=index.name)):
        operation.allow_migrate_model = Mock(return_value=True)
        operation.database_forwards('alerts',editor,state,state)
        operation.database_backwards('alerts',editor,state,state)
    assert editor.add_index.call_count == editor.remove_index.call_count == 2
    for method in (editor.add_index,editor.remove_index):
        for call in method.call_args_list:
            assert call.kwargs == {'concurrently':True}


def test_index_migration_invalidates_old_cache_without_deleting_facts(facts):
    from importlib import import_module
    from types import SimpleNamespace
    from django.apps import apps
    from apps.commerce.models import InventorySnapshot
    f = facts; query(f); build_all()
    view = InventoryDecisionView.objects.get()
    old_revision, old_rows, stock_rows = view.revision, view.rows.count(), InventorySnapshot.objects.count()
    migration = import_module('apps.alerts.migrations.0007_remove_inventorydecisionrow_idx_inventory_row_state_and_more')
    assert migration.Migration.atomic is False
    migration.invalidate_old_views(apps, SimpleNamespace(connection=connection))
    view.refresh_from_db()
    assert view.state == 'pending' and view.revision == old_revision+1
    assert view.rows.count() == old_rows and InventorySnapshot.objects.count() == stock_rows
