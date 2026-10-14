from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from apps.finance.ingestion import upsert_finance_transaction
from apps.finance.models import PlatformFinanceTransaction
from apps.integrations.models import SyncJob, SyncRun
from apps.reports.datasets import query_dataset
from tests.test_lazada_order_finance_ingestion import _lazada_scope
from tests.test_sales_management import NOW, grant

pytestmark = pytest.mark.django_db


def seed():
    tenant,user,store,config,authorization=_lazada_scope('finance-query-efficiency')
    grant(user,'reports.view');grant(user,'finance.view')
    job=SyncJob.objects.create(tenant=tenant,integration_config=config,store_authorization=authorization,resource_type='settlement_bill')
    run=SyncRun.objects.create(tenant=tenant,sync_job=job,run_id='finance-perf',idempotency_key='finance-perf')
    records=[]
    for i,currency in enumerate(('USD','EUR')):
        result=upsert_finance_transaction(tenant=tenant,store=store,authorization=authorization,source_run=run,payload={'contract_version':'finance_transaction.v1','source_key':f'perf-{i}','raw_fee_name':'Commission','raw_amount':'11.00','currency':currency,'occurred_at_utc':NOW.isoformat()})
        records.append(result.instance)
    later=records[0].updated_at+timedelta(days=1)
    PlatformFinanceTransaction.objects.filter(pk=records[1].pk).update(updated_at=later)
    return tenant,user,later


def test_finance_freshness_is_computed_in_group_query_without_second_scan():
    _,user,later=seed()
    with CaptureQueriesContext(connection) as captured:
        result=query_dataset(SimpleNamespace(user=user),{'dataset':'finance','dimensions':['currency'],'metrics':['transaction_count','signed_amount']},use_cache=False)
    assert result['count']==2 and result['refreshed_at']==later
    source_queries=[q['sql'] for q in captured.captured_queries if 'FROM "finance_platformfinancetransaction"' in q['sql'].replace('`', '"')]
    assert len(source_queries)==1
    assert 'MAX(' in source_queries[0] and 'GROUP BY' in source_queries[0]


def test_truncated_report_retains_complete_scoped_freshness():
    _,user,later=seed()
    with CaptureQueriesContext(connection) as captured:
        result=query_dataset(SimpleNamespace(user=user),{'dataset':'finance','dimensions':['currency'],'metrics':['transaction_count']},limit=1,use_cache=False)
    assert result['truncated'] is True and result['refreshed_at']==later
    source_queries=[q['sql'] for q in captured.captured_queries if 'FROM "finance_platformfinancetransaction"' in q['sql'].replace('`', '"')]
    assert len(source_queries)==2


def test_empty_scoped_finance_has_no_fabricated_freshness():
    _,user,_=seed()
    result=query_dataset(SimpleNamespace(user=user),{'dataset':'finance','filters':{'currency':'JPY'}},use_cache=False)
    assert result['rows']==[] and result['refreshed_at'] is None


def test_list_sort_and_period_filter_have_matching_indexes():
    tenant,_,_=seed()
    if connection.vendor != 'sqlite':
        pytest.skip('SQLite query plan smoke; MySQL plan is a release gate.')
    sql,params=PlatformFinanceTransaction.objects.filter(tenant=tenant).order_by('-occurred_at_utc','-id')[:50].query.sql_with_params()
    with connection.cursor() as cursor:
        cursor.execute('EXPLAIN QUERY PLAN '+sql,params);plan=' '.join(str(row) for row in cursor.fetchall())
    assert 'idx_fin_tx_tenant_time' in plan and 'TEMP B-TREE FOR ORDER BY' not in plan
    names={index.name for index in PlatformFinanceTransaction._meta.indexes}
    assert 'idx_fin_tx_tenant_date' in names
