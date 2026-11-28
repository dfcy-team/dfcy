"""Real MySQL native-source pagination; synthetic records, no provider calls."""
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from django.db import connection
from rest_framework.exceptions import ValidationError

from apps.finance.models import PlatformFinanceTransaction
from apps.finance.summary_database import collect
from tests.test_sales_management import create_scope, create_run, user_for
from tests.test_finance_summary import context


@pytest.fixture(autouse=True)
def native_page_test_budget(db):
    # A broken key can otherwise loop forever; bound only the synthetic test.
    pages = []
    def guard(execute, sql, params, many, context):
        if finance_page(sql):
            pages.append(1)
            assert len(pages) <= 8, 'Native cursor repeated pages instead of completing'
        return execute(sql, params, many, context)
    with connection.execute_wrapper(guard):
        yield


@pytest.fixture
def native_rows(db):
    if connection.vendor != 'mysql':
        pytest.skip('Requires actual MySQL BINARY ordering')
    from apps.integrations.store_authorization_service import create_store_authorization
    from apps.masterdata.models import StoreMaster
    tenant, platform, store, _ = create_scope('native-page')
    platform.platform_type = 'lazada'
    platform.save(update_fields=['platform_type'])
    user = user_for(tenant, 'native-page')
    run = create_run(tenant, 'finance_transaction', 'native-page', platform='lazada')
    auth = create_store_authorization(tenant=tenant, integration_config=run.sync_job.integration_config,
        store=store, platform='lazada', region='PH', platform_store_id='123', merchant_subject_id='123',
        shop_cipher='', credential_id='custody-test-pagination-credential', token_id='custody-test-pagination-token',
        allow_live_references=True, scopes=[], actor=user)
    def row(order, i, currency='PHP', day=date(2026,10,5), **extra):
        return PlatformFinanceTransaction(tenant=tenant, platform='lazada', store=store,
            authorization=auth, source_run=run, source_key=f'synthetic-{i}', external_order_id=order,
            raw_fee_name='Item Price Credit', fee_code='sale', fee_category='income', raw_amount=1,
            signed_amount=1, currency=currency, occurred_at_utc=datetime(2026,10,5,tzinfo=timezone.utc),
            business_date=day, match_status='matched', normalization_version='test', payload_hash='a'*64,
            **extra)
    specs=[('A',503,'PHP'),('a',2,'PHP'),('a ',2,'PHP'),('á',2,'PHP'),('b',500,'PHP'),('b',3,'php'),('z',200,'PHP')]
    rows=[]
    for order,n,currency in specs:
        rows.extend([row(order,len(rows)+i,currency) for i in range(n)])
    rows.append(row('A',len(rows),day=date(2026,10,6)))
    PlatformFinanceTransaction.objects.bulk_create(rows,batch_size=200)
    expected=list(PlatformFinanceTransaction.objects.filter(store=store).values_list('pk',flat=True))
    hidden=StoreMaster.objects.create(tenant=tenant, platform=platform, code='hidden-native', name='hidden',
        country_code='PH',currency='PHP',timezone='Asia/Manila')
    other, other_platform, other_store, _=create_scope('native-other')
    # Hidden-store and other-tenant rows are not part of the selected source scope.
    hidden_auth=create_store_authorization(tenant=tenant, integration_config=run.sync_job.integration_config,
        store=hidden, platform='lazada', region='PH', platform_store_id='456', merchant_subject_id='456',
        shop_cipher='', credential_id='custody-test-hidden-credential', token_id='custody-test-hidden-token',
        allow_live_references=True, scopes=[], actor=user)
    other_platform.platform_type='lazada';other_platform.save(update_fields=['platform_type'])
    other_user=user_for(other,'native-other-actor')
    other_run=create_run(other,'finance_transaction','native-other',platform='lazada')
    other_auth=create_store_authorization(tenant=other, integration_config=other_run.sync_job.integration_config,
        store=other_store, platform='lazada', region='PH', platform_store_id='789', merchant_subject_id='789',
        shop_cipher='', credential_id='custody-test-other-credential', token_id='custody-test-other-token',
        allow_live_references=True, scopes=[], actor=other_user)
    hidden_row=row('hidden',10000);hidden_row.store=hidden;hidden_row.authorization=hidden_auth
    other_row=row('other',10001);other_row.tenant=other;other_row.store=other_store
    other_row.authorization=other_auth;other_row.source_run=other_run
    outside=row('outside-month',10003,day=date(2026,9,30))
    PlatformFinanceTransaction.objects.bulk_create([hidden_row,other_row,outside])
    scope={'stores':[store.pk],'from':'2026-10-01','to':'2026-10-31'}
    return user,store,scope,expected,row


def finance_page(sql):
    return sql.lstrip().upper().startswith('SELECT') and 'raw_fee_name' in sql.split('FROM',1)[0]


def test_native_pages_preserve_all_rows_groups_and_binary_keys(native_rows):
    user,store,scope,expected,_=native_rows
    source=collect(user,scope,native=True,allow_legacy_zero=False)
    members=[r['id'] for f in source['facts'] if f['kind']=='sales' for r in f['rows']]
    assert sorted(members)==sorted(expected)
    assert len(members)==len(set(members))
    assert source['source_counts']['platform_finance']==len(expected)>1000
    groups={(f['external_order_id'],f['currency']) for f in source['facts'] if f['kind']=='sales'}
    assert groups=={('A','PHP'),('a','PHP'),('a ','PHP'),('á','PHP'),('b','PHP'),('b','php'),('z','PHP')}
    assert {f['date'] for f in source['facts'] if f['kind']=='sales'}=={'2026-10-05','2026-10-06'}
    assert sum(Decimal(f['amount']) for f in source['facts'] if f['kind']=='sales')==len(expected)
    assert all(f['store_id']==store.pk for f in source['facts'])


def test_new_rows_after_upper_are_not_included(native_rows):
    user,store,scope,expected,row=native_rows
    inserted=[]
    def execute(execute,sql,params,many,context):
        if finance_page(sql) and not inserted:
            inserted.append(True)
            created=row('late',10002);created.save();inserted.append(created.pk)
        return execute(sql,params,many,context)
    with connection.execute_wrapper(execute):
        source=collect(user,scope,native=True,allow_legacy_zero=False)
    assert inserted
    assert source['source_counts']['platform_finance']==len(expected)
    assert not any(f['external_order_id']=='late' for f in source['facts'])


def test_unexpected_empty_page_fails_instead_of_publishing_partial_source(native_rows):
    user,_,scope,_,_=native_rows
    pages=[]
    def execute(execute,sql,params,many,context):
        result=execute(sql,params,many,context)
        if finance_page(sql):
            original=context['cursor'].fetchmany
            def fetchmany(size):
                pages.append(1)
                return [] if len(pages)==2 else original(size)
            context['cursor'].fetchmany=fetchmany
        return result
    with connection.execute_wrapper(execute), pytest.raises(ValidationError,match='来源'):
        collect(user,scope,native=True,allow_legacy_zero=False)


def test_collector_code_changes_invalidate_both_result_and_source_keys(context,monkeypatch):
    from apps.finance import summary_jobs as jobs
    _,_,dataset,_=context
    original=Path.read_bytes
    revision=[b'legacy-pagination']
    def read(path):
        return revision[0] if path.name=='summary_database.py' else original(path)
    monkeypatch.setattr(Path,'read_bytes',read)
    payload={'action':'table','_database_query':{'scope':{'stores':[41],'from':'2026-10-01','to':'2026-10-31'}}}
    jobs.rules_fingerprint.cache_clear()
    old_result=jobs.calculation_key(dataset,'query',payload)
    old_source=jobs.calculation_key(dataset,'query',{'_database_query':payload['_database_query']})
    revision[0]=b'complete-pagination'
    jobs.rules_fingerprint.cache_clear()
    assert jobs.calculation_key(dataset,'query',payload)!=old_result
    assert jobs.calculation_key(dataset,'query',{'_database_query':payload['_database_query']})!=old_source
    jobs.rules_fingerprint.cache_clear()


def test_repeated_page_fails_instead_of_looping(native_rows):
    user,_,scope,_,_=native_rows
    first=[]
    def execute(execute,sql,params,many,context):
        result=execute(sql,params,many,context)
        if finance_page(sql):
            first.extend(context['cursor'].fetchmany(500))
            context['cursor'].fetchmany=lambda size: tuple(first)
        return result
    with connection.execute_wrapper(execute), pytest.raises(ValidationError,match='来源'):
        collect(user,scope,native=True,allow_legacy_zero=False)


def test_requested_foreign_store_is_rejected_before_financial_reads(native_rows):
    from apps.masterdata.models import StoreMaster
    user,_,scope,_,_=native_rows
    other=StoreMaster.objects.exclude(tenant=user.tenant).first()
    with pytest.raises(ValidationError):
        collect(user,{**scope,'stores':[other.pk]},native=True,allow_legacy_zero=False)


def test_native_finance_sorts_once_with_unbuffered_bounded_reads(native_rows):
    user,_,scope,expected,_=native_rows
    reads=[];sizes=[]
    def execute(execute,sql,params,many,context):
        result=execute(sql,params,many,context)
        if finance_page(sql):
            reads.append(sql)
            assert context['cursor'].cursor.cursor.__class__.__name__=='SSCursor'
            original=context['cursor'].fetchmany
            def fetchmany(size):
                sizes.append(size)
                return original(size)
            context['cursor'].fetchmany=fetchmany
        return result
    with connection.execute_wrapper(execute):
        source=collect(user,scope,native=True,allow_legacy_zero=False)
    assert source['source_counts']['platform_finance']==len(expected)
    assert len(reads)==1
    assert 'BINARY' in reads[0] and 'ORDER BY' in reads[0]
    assert len(sizes)>2 and set(sizes)=={500}


def test_referenced_envelopes_use_small_id_batches_and_preserve_provider_evidence(db):
    from apps.integrations.models import SyncRawEnvelope
    from apps.integrations.store_authorization_service import create_store_authorization
    from apps.finance.summary_database import INCOME_FIELDS
    tenant,_,store,_=create_scope('small-envelope-batches')
    user=user_for(tenant,'small-envelope-actor')
    run=create_run(tenant,'finance_transaction','small-envelope',platform='shopee')
    auth=create_store_authorization(tenant=tenant,integration_config=run.sync_job.integration_config,
        store=store,platform='shopee',region='PH',platform_store_id='123',merchant_subject_id='123',
        shop_cipher='',credential_id='custody-test-batch-credential',token_id='custody-test-batch-token',
        allow_live_references=True,scopes=[],actor=user)
    for index in range(45):
        order='synthetic-envelope-'+str(index)
        income={key:0 for key in INCOME_FIELDS if key!='currency'}
        envelope=SyncRawEnvelope.objects.create(tenant=tenant,sync_run=run,store=store,
            platform='shopee',endpoint='get_escrow_detail',sequence=index,
            payload={'responses':[{'payload':{'response':{'order_sn':order,'order_income':income}}}]},payload_hash='c'*64)
        PlatformFinanceTransaction.objects.create(tenant=tenant,platform='shopee',store=store,
            authorization=auth,source_run=run,raw_envelope=envelope,source_key=order,
            external_order_id=order,raw_fee_name='escrow_amount',fee_code='escrow',fee_category='income',
            raw_amount=0,signed_amount=0,currency='PHP',occurred_at_utc=datetime(2026,10,5,tzinfo=timezone.utc),
            business_date='2026-10-05',match_status='matched',normalization_version='test',payload_hash='b'*64)
    reads=[]
    def execute(execute,sql,params,many,context):
        if 'integrations_syncrawenvelope' in sql and connection.ops.quote_name('id')+' IN (' in sql:
            reads.append(len(params))
        return execute(sql,params,many,context)
    with connection.execute_wrapper(execute):
        source=collect(user,{'stores':[store.pk],'from':'2026-10-01','to':'2026-10-31'},native=True,allow_legacy_zero=False)
    assert len(source['shopee_income'])==45
    assert all(row['response_index']==0 for row in source['shopee_income'])
    assert source['source_counts']['platform_finance']==45
    assert reads==[21,21,6]


def test_only_charged_costs_are_classified_but_unsettled_outbound_is_retained(native_rows,monkeypatch):
    import weakref, gc
    from apps.commerce.models import SalesOrder, SalesOrderItem
    from apps.masterdata.models import WarehouseMaster
    from apps.sales_management.warehouse_order_models import OrderWarehouseLookup
    from apps.finance import summary_cost_classification as classification
    user,store,scope,_,factory=native_rows
    run=create_run(user.tenant,'sales_order','native-classification-orders',platform='lazada')
    def order(identity):
        return SalesOrder.objects.create(tenant=user.tenant,platform=store.platform,store=store,
            authorization=run.sync_job.integration_config,source_run=run,external_order_id=identity,
            raw_status='completed',normalized_status='completed',status_mapping_version='test',
            created_at_utc=datetime(2026,10,5,tzinfo=timezone.utc),updated_at_utc=datetime(2026,10,5,tzinfo=timezone.utc),
            business_date='2026-10-05',currency='PHP',payload_hash='d'*64)
    sale=order('A');outbound=order('no-settlement')
    for index in range(2):
        SalesOrderItem.objects.create(sales_order=sale,external_line_id=str(index),platform_product_id='synthetic-product',
            quantity=1,currency='PHP',source_details={'api_price_source':'synthetic-proof','reported_line_amount':0,
                'api_price_unverified_zero':bool(index),'unused_payload':'x'*10000})
    for index,source in enumerate([{}, {'sale_unit_price':0}, {'sale_unit_price':'2.50'}],2):
        SalesOrderItem.objects.create(sales_order=sale,external_line_id=str(index),platform_product_id='synthetic-product',
            quantity=1,currency='PHP',source_details={'api_price_source':'synthetic-proof',**source})
    SalesOrderItem.objects.bulk_create([SalesOrderItem(sales_order=sale,external_line_id=str(index),
        platform_product_id='synthetic-product',quantity=1,currency='PHP') for index in range(5,506)])
    OrderWarehouseLookup.objects.create(order=outbound,warehouse=WarehouseMaster.objects.filter(tenant=user.tenant).first(),
        status='matched',snapshot={'unused_payload':'x'*10000,'packages':[{'warehouse_order_no':'synthetic-outbound','status':'7',
            'shipped_at_utc':'2026-10-06T00:00:00Z','items':[{'sku':'synthetic-missing-sku','quantity':1}]}]})
    original=classification.collect_classifications;calls=[];order_refs=[]
    def track(user,stores,orders,facts,**kwargs):
        calls.append({o.external_order_id for o in orders})
        order_refs.extend(weakref.ref(o) for o in orders)
        return original(user,stores,orders,facts,**kwargs)
    monkeypatch.setattr(classification,'collect_classifications',track)
    from apps.finance import summary_database
    original_quotes=summary_database.product_quotes
    def check_released_models(envelopes):
        gc.collect()
        assert all(ref() is None for ref in order_refs)
        return original_quotes(envelopes)
    monkeypatch.setattr(summary_database,'product_quotes',check_released_models)
    queries=[]
    def capture(execute,sql,params,many,context):
        queries.append(sql)
        return execute(sql,params,many,context)
    with connection.execute_wrapper(capture):
        source=collect(user,scope,native=True,allow_legacy_zero=False)
    assert calls==[{'A'}]
    assert any(row['external_order_id']=='no-settlement' for row in source['cost_flows'])
    assert [row['historical_line_amount'] for row in source['sku_sales']['orders'][str(store.pk)+'|A']]==['0.000000',None,None,'0.000000','2.500000']+[None]*501
    history=[sql for sql in queries if 'MIN(' in sql and 'platform_product_id' in sql]
    assert history and all('AS BINARY' in sql for sql in history)
    projections=[sql.split(' FROM ',1)[0] for sql in queries if '_read_price_source' in sql]
    assert projections and all(sql.count('`source_details`')==5 for sql in projections)
    item_pages=[sql for sql in queries if '_read_price_source' in sql]
    assert len(item_pages)==2 and all('LIMIT 500' in sql for sql in item_pages)
    packages=[sql.split(' FROM ',1)[0] for sql in queries if '_read_packages' in sql]
    assert packages and all('JSON_EXTRACT' in sql and sql.count('`snapshot`')==1 for sql in packages)
