import gzip
from unittest.mock import Mock

import pytest
from django.core.cache import cache

from apps.finance.summary_jobs import run_calculation
from apps.finance.summary_models import FinanceSummaryCalculation, FinanceSummaryDataset, FinanceSummaryInput
from apps.finance.summary_read_query import execute, query_scope, launch_source_worker as launch_process
from tests.test_finance_summary import context, URL

pytestmark = pytest.mark.django_db(transaction=True)


def test_raw_payload_queries_are_sql_bounded_and_preserve_scope_and_all_rows(context):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from apps.integrations.models import SyncRawEnvelope
    from apps.finance.summary_database import bounded_raw_envelopes
    from tests.test_sales_management import create_run
    _, user, dataset, _ = context
    run = create_run(user.tenant, 'sales_order', 'memory-bounded-raw')
    expected = []
    for index in range(41):
        row = SyncRawEnvelope.objects.create(tenant=user.tenant, sync_run=run,
            store_id=dataset.metadata['store_ids'][0], platform='shopee', endpoint='product',
            sequence=index, payload={'records': [{'item_name': 'synthetic-'+str(index)}]}, payload_hash='a'*64)
        expected.append(row.pk)
    queryset = SyncRawEnvelope.objects.filter(tenant=user.tenant, sync_run=run)
    with CaptureQueriesContext(connection) as captured:
        result = list(bounded_raw_envelopes(queryset))
    assert [row.pk for row in result] == expected
    assert 'LIMIT 1' in captured[0]['sql'] and 'payload' not in captured[0]['sql']
    assert all('LIMIT 20' in query['sql'] and 'OFFSET' not in query['sql'] for query in captured[1:])
    assert len(captured) == 5
    assert list(bounded_raw_envelopes(queryset.filter(pk__in=expected[::2]))) == result[::2]


@pytest.fixture(autouse=True)
def broker(monkeypatch):
    cache.clear()
    monkeypatch.setattr(run_calculation, 'apply_async', Mock())
    # SQLite fixture databases stay in this test process; cloud tests use the real child.
    def materialize(request):
        from types import SimpleNamespace
        from django.contrib.auth import get_user_model
        from apps.finance.summary_read_query import materialize_source
        from apps.finance.summary_service import private_root
        user = get_user_model().objects.get(pk=request['user'], tenant_id=request['tenant'])
        materialize_source(user, SimpleNamespace(document_file=request['document_file']),
            {'scope': request['scope']}, private_root()/request['filename'], request['token'])
    monkeypatch.setattr('apps.finance.summary_read_query.launch_source_worker', materialize)


def test_read_only_user_can_query_without_publishing_and_duplicate_work_is_shared(context, monkeypatch):
    client, user, dataset, _ = context
    dataset.active = False
    dataset.save()
    calculate = Mock(return_value={'rows': [], 'total': 0, 'page': 1})
    monkeypatch.setattr('apps.finance.summary_read_query.execute', calculate)
    catalog = client.get(URL, {'direct': 1}).data['data']
    assert catalog['direct_query'] and not catalog['can_edit'] and catalog['dataset'] is None
    args = {'filter_month': '2026-10'}
    first = client.get(URL + 'query/', args)
    assert first.status_code == 202
    assert client.get(URL + 'query/', args).data['data']['job']['id'] == first.data['data']['job']['id']
    run_calculation(first.data['data']['job']['id'])
    ready = client.get(URL + 'query/', args)
    assert ready.status_code == 200 and ready.data['data']['query_context'] == first.data['data']['job']['id']
    assert calculate.call_count == 1
    assert not FinanceSummaryDataset.objects.filter(active=True).exists()
    assert not FinanceSummaryInput.objects.exists()
    assert not FinanceSummaryCalculation.objects.filter(kind='rebuild').exists()


def test_scope_is_server_owned_and_cross_month_week_reads_both_complete_months(context):
    client, user, dataset, _ = context
    sid = dataset.metadata['store_ids'][0]
    scope = query_scope(user, {'month': '2026-09', 'period_type': 'week', 'period': '2026-09-28'})
    assert scope == {'from': '2026-09-01', 'to': '2026-10-31', 'stores': [sid]}
    from rest_framework.exceptions import PermissionDenied
    with pytest.raises(PermissionDenied):
        query_scope(user, {'month': '2026-10', 'store': '9999999'})


def test_details_reuse_original_scope_and_settings_change_invalidates_result(context, monkeypatch):
    client, user, dataset, state = context
    calculate = Mock(return_value={'rows': [], 'total': 0, 'page': 1})
    monkeypatch.setattr('apps.finance.summary_read_query.execute', calculate)
    first = client.get(URL + 'query/', {'filter_month': '2026-10'})
    job = first.data['data']['job']['id']
    run_calculation(job)
    response = client.get(URL + 'query-detail/', {'query_context': job, 'row_key': 'test', 'kind': 'sales',
                                                'filter_store': '9999999', 'filter_month': '2025-01'})
    assert response.status_code == 202
    detail = FinanceSummaryCalculation.objects.get(pk=response.data['data']['job']['id'])
    assert detail.request['filters']['month'] == '2026-10'
    assert detail.request['filters']['_stores'] == list(map(str, dataset.metadata['store_ids']))
    state.revision += 1
    state.save()
    run_calculation(detail.pk)
    detail.refresh_from_db()
    assert detail.status == 'superseded'


def test_view_switch_preserves_the_explicit_refresh_snapshot(context, monkeypatch):
    client, _, _, _ = context
    monkeypatch.setattr('apps.finance.summary_read_query.execute', lambda *a: {'rows': [], 'total': 0})
    first = client.get(URL + 'query/', {'filter_month': '2026-10', 'refresh': 1})
    job = first.data['data']['job']['id']
    run_calculation(job)
    from datetime import timedelta
    from django.utils import timezone
    # A slow cold query is still a fresh snapshot when it has just completed.
    FinanceSummaryCalculation.objects.filter(pk=job).update(created_at=timezone.now()-timedelta(minutes=6))
    next_view = client.get(URL + 'query/', {'filter_month': '2026-10', 'query_context': job, 'view': 'order'})
    other = FinanceSummaryCalculation.objects.get(pk=next_view.data['data']['job']['id'])
    parent = FinanceSummaryCalculation.objects.get(pk=job)
    assert other.request['_database_query'] == parent.request['_database_query']


def test_switching_views_cannot_keep_an_old_source_generation_alive(context, monkeypatch):
    from apps.finance.summary_jobs import current_dataset
    client, _, _, _ = context
    monkeypatch.setattr('apps.finance.summary_read_query.execute', lambda *a: {'rows': []})
    response = client.get(URL + 'query/', {'filter_month': '2026-10'})
    job = FinanceSummaryCalculation.objects.get(pk=response.data['data']['job']['id'])
    job.request['_database_query']['generation'] -= 20
    job.save(update_fields=['request'])
    assert current_dataset(job) is None


def test_source_materialization_is_reused_across_views_and_pages(context, monkeypatch):
    from apps.finance.summary_read_query import seed_for
    from apps.finance.summary_service import private_root
    _, user, dataset, _ = context
    seed = seed_for(user)
    source = {'read_at': 'synthetic'}
    collect = Mock(return_value=source)
    monkeypatch.setattr('apps.finance.summary_database.collect', collect)
    monkeypatch.setattr('apps.finance.summary_database_document.render', lambda template, source, **kwargs: '<html>synthetic</html>')
    native = Mock(return_value={'rows': []})
    monkeypatch.setattr('apps.finance.summary_native.query', native)
    spec = {'scope': {'from': '2026-10-01', 'to': '2026-10-31', 'stores': dataset.metadata['store_ids']},
            'settings': None, 'generation': 1, 'refresh': False, 'accounting_history_version': 1}
    execute(seed, user, {'_database_query': spec, 'view': 'store'})
    execute(seed, user, {'_database_query': spec, 'view': 'order', 'page': 2})
    assert collect.call_count == 1 and native.call_count == 2
    assert gzip.decompress(next(private_root().glob('read-query-*.html.gz')).read_bytes()) == b'<html>synthetic</html>'


def test_real_template_and_database_sources_work_without_an_active_batch(context):
    client, _, dataset, _ = context
    dataset.active = False
    dataset.save()
    response = client.get(URL + 'query/', {'filter_month': '2026-10'})
    job = response.data['data']['job']['id']
    run_calculation(job)
    row = FinanceSummaryCalculation.objects.get(pk=job)
    assert row.status == 'ready', row.error_code
    data = client.get(URL + f'jobs/{job}/').data['data']['result']
    assert data['direct_query'] and isinstance(data['rows'], list)
    assert not FinanceSummaryDataset.objects.filter(active=True).exists()


def test_source_timeout_has_a_clear_failed_result_without_publishing(context, monkeypatch):
    from apps.finance.summary_read_query import SourceReadTimeout
    client, _, _, _ = context
    monkeypatch.setattr('apps.finance.summary_read_query.execute', Mock(side_effect=SourceReadTimeout()))
    response = client.get(URL + 'query/', {'filter_month': '2026-10'})
    pk = response.data['data']['job']['id']
    run_calculation(pk)
    job = FinanceSummaryCalculation.objects.get(pk=pk)
    assert job.status == 'failed' and job.error_code == 'SOURCE_READ_TIMEOUT' and job.result is None


@pytest.mark.parametrize('previous,expected', [(0,15000),(500,500),(30000,15000)])
def test_source_budget_keeps_stricter_limits_and_restores_after_failure(monkeypatch, previous, expected):
    from unittest.mock import MagicMock
    from django.db import DatabaseError
    from apps.finance.summary_read_query import source_budget, SourceReadTimeout
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchone.return_value = (previous,)
    connection = Mock(vendor='mysql')
    connection.cursor.return_value = cursor
    monkeypatch.setattr('django.db.connection', connection)
    with pytest.raises(SourceReadTimeout):
        with source_budget():
            raise DatabaseError(3024, 'synthetic timeout')
    calls = cursor.execute.call_args_list
    assert calls[1].args == ('SET SESSION MAX_EXECUTION_TIME=%s', [expected])
    assert calls[-1].args == ('SET SESSION MAX_EXECUTION_TIME=%s', [previous])


def test_expired_read_cache_cannot_recalculate_old_details_and_preserves_accepted_files(context, monkeypatch):
    from datetime import timedelta
    import os
    from django.utils import timezone
    from apps.finance.summary_jobs import current_dataset, prune_expired_results
    from apps.finance.summary_service import private_root
    client, _, dataset, _ = context
    monkeypatch.setattr('apps.finance.summary_read_query.execute', lambda *a: {'rows': []})
    response = client.get(URL + 'query/', {'filter_month': '2026-10'})
    pk = response.data['data']['job']['id']
    run_calculation(pk)
    old = timezone.now()-timedelta(hours=3)
    FinanceSummaryCalculation.objects.filter(pk=pk).update(created_at=old, finished_at=old)
    job = FinanceSummaryCalculation.objects.get(pk=pk)
    assert current_dataset(job) is None
    accepted = private_root()/dataset.document_file
    derived = private_root()/('read-query-'+'a'*64+'.html.gz')
    derived.write_bytes(b'synthetic cache')
    os.utime(derived, (old.timestamp(), old.timestamp()))
    prune_expired_results()
    job.refresh_from_db()
    assert job.status == 'expired' and job.result is None
    assert accepted.is_file() and not derived.exists()


def test_native_collection_keeps_money_and_evidence_while_dropping_browser_duplicates(context, monkeypatch):
    from datetime import datetime, timezone
    from apps.commerce.models import SalesOrder, SalesOrderItem
    from apps.masterdata.models import StoreMaster
    from apps.finance.summary_database import collect
    from tests.test_sales_management import create_run
    from tests.test_finance_database_summary import posted_settlement
    client, user, dataset, _ = context
    store = StoreMaster.objects.get(pk=dataset.metadata['store_ids'][0])
    platform = store.platform
    platform.platform_type = 'lazada'
    platform.save()
    run = create_run(user.tenant, 'sales_order', 'native-read-source', platform='lazada')
    stamp = datetime(2026, 9, 5, tzinfo=timezone.utc)
    order = SalesOrder.objects.create(tenant=user.tenant, platform=platform, store=store,
        authorization=run.sync_job.integration_config, source_run=run, external_order_id='synthetic-order',
        raw_status='completed', normalized_status='completed', status_mapping_version='test',
        created_at_utc=stamp, updated_at_utc=stamp, business_date='2026-09-05', currency='PHP', payload_hash='c'*64,
        source_details={'platform_pickup_at_utc': '2026-09-05T01:00:00Z',
                        'platform_logistics': {'status': 'ok', 'order_sn': 'synthetic-order', 'packages': []},
                        'unused_snapshot': 'not needed by financial calculations'})
    SalesOrderItem.objects.create(sales_order=order, external_line_id='synthetic-line', platform_product_id='1',
        quantity=2, original_unit_price='5', sale_unit_price='5', line_total_amount='10', currency='PHP',
        source_details={'api_price_source': 'official', 'reported_line_amount': '10'})
    row = posted_settlement(user, store, run, order, '10')
    row.pk = None
    row.source_key = 'synthetic-fee'
    row.raw_fee_name = 'Commission Fee'
    row.raw_amount, row.signed_amount = '1', '-1'
    row.save()
    monkeypatch.setattr('apps.finance.summary_database.timezone.now', lambda: stamp)
    scope = {'stores': [store.pk], 'from': '2026-09-01', 'to': '2026-09-30'}
    before, after = collect(user, scope), collect(user, scope, native=True)
    assert {f['source_id']: f for f in before['facts']} == {f['source_id']: f for f in after['facts']}
    # Calculated evidence uses canonical order subjects; the independent raw API retains physical rows.
    flows = {after['facts'][f['native_fact_index']]['source_id']: after['facts'][f['native_fact_index']] for f in after['raw_flows'] if 'native_fact_index' in f}
    for fact in after['facts']:
        if fact['kind'] in ('sales', 'order_fee'):
            assert flows[fact['source_id']]['amount'] == fact['amount']
    assert before['shares'] == after['shares'] and before['rates'] == after['rates']
    assert before['source_counts'] == after['source_counts']
    assert before['sku_sales'] == after['sku_sales'] and before['order_dates'] == after['order_dates']
    assert len(before['raw']) == 2 and len(after['raw']) == 1
    second = StoreMaster.objects.create(tenant=user.tenant, platform=platform, code='native-second',
        name='Synthetic second store', country_code=store.country_code, currency=store.currency)
    row.pk = None
    row.store = second
    row.source_key = 'synthetic-second-store-fee'
    row.signed_amount = '-2'
    row.save()
    multi_scope = {**scope, 'stores': [second.pk, store.pk]}
    expected, actual = collect(user, multi_scope), collect(user, multi_scope, native=True)
    assert {f['source_id']: f for f in expected['facts']} == {f['source_id']: f for f in actual['facts']}
    assert actual['source_counts']['platform_finance'] == 3
    from decimal import Decimal
    assert sum(Decimal(f['amount']) == Decimal('-2') for f in actual['facts'] if f['store_id'] == second.pk) == 1
    response = client.get(URL + 'query/', {'filter_month': '2026-09'})
    query_id = response.data['data']['job']['id']
    run_calculation(query_id)
    job = FinanceSummaryCalculation.objects.get(pk=query_id)
    assert job.status == 'ready', job.error_code
    result = client.get(URL + f'jobs/{query_id}/').data['data']['result']
    assert result['rows'][0]['values']['sales'] == '10.000000'
    assert result['rows'][0]['values']['order_fee'] == '-1.000000'


def test_streaming_multiple_shopee_stores_keeps_columns_after_component_classification(context, monkeypatch):
    from types import SimpleNamespace
    from apps.masterdata.models import StoreMaster
    from apps.finance.summary_database import collect
    from tests.test_sales_management import create_run
    from tests.test_finance_database_summary import posted_settlement
    _, user, dataset, _ = context
    first = StoreMaster.objects.get(pk=dataset.metadata['store_ids'][0])
    platform = first.platform
    platform.platform_type = 'shopee'
    platform.save()
    second = StoreMaster.objects.create(tenant=user.tenant, platform=platform, code='SP-stream-second',
        name='Synthetic Shopee second store', country_code=first.country_code, currency=first.currency)
    from apps.integrations import store_authorization_service
    create_authorization = store_authorization_service.create_store_authorization
    def authorize_store(**kwargs):
        identity = str(100000 + kwargs['store'].pk)
        return create_authorization(**{**kwargs, 'platform_store_id': identity, 'merchant_subject_id': identity})
    monkeypatch.setattr(store_authorization_service, 'create_store_authorization', authorize_store)
    for index, store in enumerate([first, second]):
        run = create_run(user.tenant, 'sales_order', 'shopee-stream-'+str(index), platform='shopee')
        posted_settlement(user, store, run, SimpleNamespace(external_order_id='same-order'), '10')
    scope = {'stores': [second.pk, first.pk], 'from': '2026-09-01', 'to': '2026-09-30'}
    expected, actual = collect(user, scope), collect(user, scope, native=True)
    assert {f['source_id']: f for f in expected['facts']} == {f['source_id']: f for f in actual['facts']}
    assert actual['source_counts']['platform_finance'] == 2
    assert {f['store_id'] for f in actual['facts']} == {first.pk, second.pk}


def test_native_historical_title_keeps_first_item_across_order_read_batches(context):
    from datetime import datetime, timezone
    from apps.commerce.models import SalesOrder, SalesOrderItem
    from apps.masterdata.models import StoreMaster
    from apps.finance.summary_database import collect
    from tests.test_sales_management import create_run
    _, user, dataset, _ = context
    store = StoreMaster.objects.get(pk=dataset.metadata['store_ids'][0])
    run = create_run(user.tenant, 'sales_order', 'historical-title-batches')
    stamp = datetime(2026, 8, 1, tzinfo=timezone.utc)
    SalesOrder.objects.bulk_create([SalesOrder(tenant=user.tenant, platform=store.platform, store=store,
        authorization=run.sync_job.integration_config, source_run=run, external_order_id='title-order-'+str(i),
        raw_status='completed', normalized_status='completed', status_mapping_version='test',
        created_at_utc=stamp, updated_at_utc=stamp, business_date='2026-08-01', currency=store.currency,
        payload_hash='e'*64) for i in range(501)])
    title_orders = SalesOrder.objects.filter(tenant=user.tenant, store=store, source_run=run)
    for external_id, title in [('title-order-500', 'Earlier source title'), ('title-order-0', 'Later source title')]:
        order = title_orders.get(external_order_id=external_id)
        SalesOrderItem.objects.create(sales_order=order, external_line_id='title-line', platform_product_id='missing-title-product',
            item_name_snapshot=title, quantity=1, currency=store.currency)
    scope = {'stores': [store.pk], 'from': '2026-09-01', 'to': '2026-09-30'}
    before, after = collect(user, scope), collect(user, scope, native=True)
    for source in [before, after]:
        product = next(p for p in source['products']['products'] if p['platform_product_id']=='missing-title-product')
        assert product['title'] == 'Earlier source title'


def test_chunked_query_document_matches_existing_renderer_bytes(context, tmp_path):
    import hashlib
    from apps.finance.summary_database import collect
    from apps.finance.summary_database_document import render
    from apps.finance.summary_initialization import template_bytes
    from apps.finance.summary_read_query import write_document
    _, user, dataset, _ = context
    source = collect(user, {'stores': dataset.metadata['store_ids'], 'from': '2026-09-01', 'to': '2026-09-30'}, native=True)
    source['facts'] = [{'source_id': str(i), 'amount': '1.000000', 'description': '合成 </script> 来源'} for i in range(601)]
    source['sku_sales'] = {'orders': {'test': [{'title': '合成 </script> 商品'} for _ in range(601)]}}
    source['sku_sales']['key_types'] = {1: 'numeric', None: 'null', False: 'boolean'}
    template = template_bytes()[0].decode('utf-8')
    expected = render(template, source).encode('utf-8')
    path = tmp_path/'query.html.gz'
    digest = write_document(path, template, source)
    assert gzip.decompress(path.read_bytes()) == expected
    assert digest == hashlib.sha256(expected).hexdigest()


@pytest.mark.parametrize('reply,returncode,expected', [
    ('{"ok":true}', 0, None),
    ('{"ok":false,"code":"SOURCE_READ_TIMEOUT"}', 0, 'timeout'),
    ('not a worker reply', 1, 'failed'),
    ('[]', 0, 'failed'),
])
def test_source_child_protocol_is_bounded_and_fail_closed(monkeypatch, reply, returncode, expected):
    import json
    import subprocess
    from types import SimpleNamespace
    from rest_framework.exceptions import ValidationError
    from apps.finance.summary_read_query import SourceReadTimeout
    run = Mock(return_value=SimpleNamespace(stdout=reply, returncode=returncode))
    monkeypatch.setattr('apps.finance.summary_read_query.subprocess.run', run)
    request = {'user': 1, 'tenant': 1, 'scope': {'stores': [2]}}
    if expected is None:
        launch_process(request)
    else:
        with pytest.raises(SourceReadTimeout if expected=='timeout' else ValidationError):
            launch_process(request)
    args, options = run.call_args
    assert args[0][1:] == ['-m', 'apps.finance.summary_source_worker']
    assert json.loads(options['input']) == request
    assert options['timeout'] == 600 and options['stderr'] == subprocess.DEVNULL
