from datetime import date
from decimal import Decimal
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from apps.finance.summary_service import READ_PERMISSIONS
from apps.finance.summary_models import FinanceSummaryDataset, FinanceSummaryInput
from apps.finance.warehouse_fee_models import WarehouseFee
from apps.sales_management.registration_models import OrderRegistration
from apps.masterdata.models import StoreMaster
from tests.test_sales_management import grant, user_for, client_for, create_scope
from tests.test_finance_ledger import platform_context, add_transaction

pytestmark=pytest.mark.django_db
URL='/api/finance/summary/source-flows/'
PERIOD={'start':'2026-08-01','end':'2026-08-31'}


@pytest.fixture
def setup():
    context=platform_context('shopee');user,store,_,_=context
    for code in READ_PERMISSIONS:
        if code!='finance.view':grant(user,code)
    return context, client_for(user)


def fee(user,store,number,day=None):
    return WarehouseFee.objects.create(tenant=user.tenant,store=store,country='PH',kind='order',bill_month='2026-08',
        bill_number=str(number),fee_item='Handling',reference=str(number),amount=Decimal('3.100001'),currency='CNY',
        business_key=str(number).zfill(64),content_hash='a'*64,created_by=user,status='registered',occurred_on=day)


def test_no_dataset_direct_page_exact_amount_and_source_detail(setup,monkeypatch):
    context,client=setup;user,store,_,_=context
    tx=add_transaction(context,'commission_fee','-1.2345');fee(user,store,1)
    monkeypatch.setattr('apps.finance.summary_database.collect',lambda *a,**k:pytest.fail('must not collect'))
    monkeypatch.setattr('apps.finance.summary_native.query',lambda *a,**k:pytest.fail('must not calculate'))
    r=client.get(URL,PERIOD);assert r.status_code==200,r.data
    data=r.data['data'];assert len(data['rows'])==2 and data['total'] is None
    assert not FinanceSummaryDataset.objects.exists()
    row=next(x for x in data['rows'] if x['key']==f'finance-transaction:{tx.pk}')
    assert row['original_amount']=='-1.2345' and row['amount'] is None
    assert row['mode_label']=='原始记录（未分摊）'
    r=client.get(URL+f'finance-transaction/{tx.pk}/');assert r.status_code==200
    assert r.data['data']['amount']=='-1.2345'


def test_cursor_interleaves_sources_without_duplicates_and_rejects_changes(setup):
    context,client=setup;user,store,_,_=context
    for i in range(7):
        add_transaction(context,f'fee-{i}','-1');fee(user,store,i+1,date(2026,8,31))
    seen=[];cursor=None
    for _ in range(10):
        r=client.get(URL,{**PERIOD,'page_size':3,**({'cursor':cursor} if cursor else {})});assert r.status_code==200,r.data
        data=r.data['data'];seen.extend(x['key'] for x in data['rows'])
        if not data['has_more']:break
        cursor=data['next_cursor']
    assert len(seen)==len(set(seen))==14
    assert client.get(URL,{**PERIOD,'page_size':3,'cursor':cursor,'currency':'USD'}).status_code==400
    assert client.get(URL,{**PERIOD,'cursor':'forged'}).status_code==400


def test_dates_month_only_and_cross_month_week_are_not_invented(setup):
    context,client=setup;user,store,_,_=context
    missing=fee(user,store,1);dated=fee(user,store,2,date(2026,9,1))
    rows=client.get(URL,PERIOD).data['data']['rows'];assert [r['key'] for r in rows]==[f'warehouse:{missing.pk}']
    assert rows[0]['date']=='2026-08' and '未推断' in rows[0]['date_basis']
    rows=client.get(URL,{'start':'2026-08-31','end':'2026-09-06','period_type':'week'}).data['data']['rows']
    assert [r['key'] for r in rows]==[f'warehouse:{dated.pk}']
    rows=client.get(URL,{**PERIOD,'undated':1}).data['data']['rows'];assert len(rows)==1
    assert not client.get(URL,{'start':'2026-08-15','end':'2026-08-31'}).data['data']['rows']


def test_latest_ad_report_only_and_unknown_amount_is_not_zero(setup):
    from apps.integrations.models import ShopeeAdvertisingRecord
    context,client=setup;user,store,_,run=context
    for key,expense in [('old','1.123456'),('new','2.123456'),('missing',None)]:
        ShopeeAdvertisingRecord.objects.create(tenant=user.tenant,store=store,kind='shop_daily',record_key=key,
            report_date='2026-08-31' if key!='missing' else '2026-08-30',currency='PHP',report_timezone='Asia/Manila',
            data={'expense':expense},source_run=run)
    r=client.get(URL,{**PERIOD,'kind':'advertising'});assert r.status_code==200,r.data
    rows=r.data['data']['rows'];assert len(rows)==2
    assert rows[0]['original_amount']=='-2.123456' and rows[1]['original_amount'] is None
    assert rows[1]['source_status']=='pending'
    assert len(client.get(URL,{**PERIOD,'status':'pending'}).data['data']['rows'])==1


def test_registered_sources_and_adjustments_are_bounded_and_drafts_excluded(setup):
    context,client=setup;user,store,_,_=context
    for i,(status,day) in enumerate([('registered','2026-08-15'),('draft','2026-08-15'),('completed','2026-09-01')]):
        OrderRegistration.objects.create(tenant=user.tenant,store=store,kind='gcash',status=status,requested_by=user,
            payload={'paid_at':day,'amount':'2.123456','currency':'PHP'},idempotency_key=str(i),request_hash='a'*64)
    FinanceSummaryInput.objects.create(tenant=user.tenant,store=store,kind='adjustment',source_key='a',period='2026-08',
        payload={'amount':'5.000001','currency':'PHP'},source_hash='b'*64,created_by=user)
    r=client.get(URL,PERIOD);assert r.status_code==200,r.data
    assert {Decimal(x['original_amount']) for x in r.data['data']['rows']}=={Decimal('-2.123456'),Decimal('5.000001')}


def test_scoped_user_cannot_read_other_store_unassigned_fee_or_foreign_detail(setup):
    context,_=setup;owner,store,_,_=context
    other=StoreMaster.objects.create(tenant=owner.tenant,platform=store.platform,code='other',name='Other',country_code='PH',currency='PHP')
    own=fee(owner,store,1);foreign=fee(owner,other,2);fee(owner,None,3)
    user=user_for(owner.tenant,'limited-reader')
    for code in READ_PERMISSIONS:grant(user,code,scope_type='custom',config={'store_ids':[store.pk]})
    client=client_for(user);r=client.get(URL,PERIOD);assert r.status_code==200,r.data
    assert [x['key'] for x in r.data['data']['rows']]==[f'warehouse:{own.pk}']
    assert client.get(URL,{**PERIOD,'store':other.pk}).status_code==403
    assert client.get(URL+f'warehouse/{foreign.pk}/').status_code==404
    tenant,_,third,_=create_scope('foreign-source');foreign_user=user_for(tenant,'foreign-owner');external=fee(foreign_user,third,1)
    assert client.get(URL+f'warehouse/{external.pk}/').status_code==404


def test_queries_have_per_source_limits_no_count_offset_or_large_json(setup):
    context,client=setup
    for i in range(30):add_transaction(context,f'fee-{i}','1')
    with CaptureQueriesContext(connection) as queries:r=client.get(URL,{**PERIOD,'page_size':5})
    assert r.status_code==200,r.data
    sql=[x['sql'] for x in queries if 'flow_amount' in x['sql']]
    assert len(sql)==6 and all('LIMIT 6' in s for s in sql)
    assert all('COUNT(' not in s and 'OFFSET' not in s for s in sql)
    assert all('raw_envelope' not in s and 'snapshot' not in s for s in sql)
    assert len(r.data['data']['rows'])==5


def test_invalid_date_and_mutations_rejected(setup):
    _,client=setup
    for params in [{},{'start':'2026-09-01','end':'2026-08-01'},{'start':'2020-01-01','end':'2026-01-01'}, {**PERIOD,'page_size':101}]:
        assert client.get(URL,params).status_code==400
    assert client.post(URL,PERIOD).status_code==405


def test_unassigned_country_fees_and_cross_border_store_fees_keep_scope(setup):
    context,client=setup;user,store,_,_=context
    unassigned=fee(user,None,1);unassigned.country='SG';unassigned.save()
    assigned=fee(user,store,2);assigned.country='MY';assigned.save()
    rows=client.get(URL,PERIOD).data['data']['rows'];assert len(rows)==2
    assert client.get(URL,{**PERIOD,'country':'SG'}).data['data']['rows'][0]['key']==f'warehouse:{unassigned.pk}'
    rows=client.get(URL,{**PERIOD,'country':'PH'}).data['data']['rows'];assert [r['key'] for r in rows]==[f'warehouse:{assigned.pk}']
    assert not client.get(URL,{**PERIOD,'store':store.pk,'country':'SG'}).data['data']['rows']


def test_source_kind_skips_irrelevant_large_finance_query(setup):
    _,client=setup
    with CaptureQueriesContext(connection) as queries:r=client.get(URL,{**PERIOD,'kind':'advertising'})
    assert r.status_code==200
    assert not any('finance_platformfinancetransaction' in q['sql'] for q in queries)
    assert len([q for q in queries if 'flow_amount' in q['sql']])==2


def test_mysql_timeout_restores_previous_budget(monkeypatch):
    from unittest.mock import MagicMock
    from django.db import OperationalError
    from rest_framework.exceptions import ValidationError
    from apps.finance import source_flow_views as flows
    database=MagicMock();database.vendor='mysql';cursor=database.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value=(4500,);monkeypatch.setattr(flows,'connection',database)
    with pytest.raises(ValidationError,match='超过时限'):
        with flows.read_budget():raise OperationalError(3024,'query interrupted')
    assert cursor.execute.call_args_list[-1].args==('SET SESSION MAX_EXECUTION_TIME=%s',[4500])
