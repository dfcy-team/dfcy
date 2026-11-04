from decimal import Decimal
from datetime import datetime, timezone
from types import SimpleNamespace
import json
import re

import pytest

from apps.finance.summary_database import collect, cost_on, convert_costs, final_lines, item_price, split_amount, _sku_members
from apps.finance.summary_database_document import render, compact_browser_inputs
from apps.finance.summary_models import FinanceSummaryInput
from tests.test_finance_summary import context
from tests.test_sales_management import create_scope, create_run, grant, user_for


def posted_settlement(user, store, run, order, amount, match_status='matched', day='2026-09-05'):
    from apps.finance.models import PlatformFinanceTransaction
    from apps.integrations.store_authorization_service import create_store_authorization
    platform = store.platform.platform_type
    auth = create_store_authorization(tenant=user.tenant, integration_config=run.sync_job.integration_config,
        store=store, platform=platform, region='PH', platform_store_id='123', merchant_subject_id='123',
        shop_cipher='', credential_id='custody-test-settlement-credential', token_id='custody-test-settlement-token',
        allow_live_references=True, scopes=[], actor=user)
    return PlatformFinanceTransaction.objects.create(tenant=user.tenant, platform=platform, store=store,
        authorization=auth, source_run=run, source_key='settlement', external_order_id=order.external_order_id,
        raw_fee_name='escrow_amount' if platform == 'shopee' else 'Item Price Credit', fee_code='settlement',
        fee_category='income', raw_amount=amount, signed_amount=amount, currency=store.currency,
        occurred_at_utc=datetime.fromisoformat(day).replace(tzinfo=timezone.utc), business_date=day,
        match_status=match_status, normalization_version='test', payload_hash='d'*64)


def test_quantity_changes_keep_added_items_and_remove_reduced_cost():
    result = final_lines([{'sku_id': 1, 'quantity': 3, 'source_sku': 'old'}], [
        {'action': 'replace', 'old_sku_id': 1, 'new_sku_id': 2, 'reduce_quantity': 2, 'add_quantity': 1},
        {'action': 'add', 'sku_id': 3, 'add_quantity': 2},
        {'action': 'reduce', 'sku_id': 1, 'reduce_quantity': 1}])
    assert [(x['sku_id'], x['quantity']) for x in result] == [(2, 1), (3, 2)]


def test_amount_rounding_conserves_signed_total_and_does_not_give_zero_weight_a_share():
    for amount in ['-10.01', '10.01', '-0.000001']:
        result = split_amount(amount, [('a', 1), ('b', 2), ('added', 0)])
        assert sum(result.values()) == Decimal(amount)
        assert 'added' not in result


def test_missing_price_is_not_read_as_a_real_zero():
    line = SimpleNamespace(source_details={}, quantity=2)
    assert item_price(line) is None
    line.source_details = {'api_price_source': 'shopee_escrow', 'reported_line_amount': '0'}
    assert item_price(line) == '0.000000'
    line.source_details['api_price_unverified_zero'] = True
    assert item_price(line) is None


def cost_version(start, end=None, status='confirmed'):
    return SimpleNamespace(effective_from=datetime.fromisoformat(start).replace(tzinfo=timezone.utc),
        effective_to=datetime.fromisoformat(end).replace(tzinfo=timezone.utc) if end else None,
        status=status, confirmed_cost=Decimal('10'))


def test_cost_matches_historical_interval_instead_of_current_version():
    old = cost_version('2026-08-01', '2026-10-01')
    current = cost_version('2026-10-01')
    assert cost_on([current, old], '2026-09-30', 'Asia/Manila') is old
    assert cost_on([current, old], '2026-10-01', 'Asia/Manila') is current
    assert cost_on([current], '2026-09-30', 'Asia/Manila') is None
    assert cost_on([cost_version('2026-08-01', status='pending')], '2026-09-30', 'Asia/Manila') is None
    assert cost_on([old, old], '2026-09-30', 'Asia/Manila') is None


def test_monthly_cost_conversion_is_frozen_and_sku_sum_is_exact():
    facts = [{'kind': 'product_cost', 'platform': 'lazada', 'country': 'PH', 'currency': 'CNY',
        'store_id': 1, 'store_code': 'LZ', 'date': '2026-09-10', 'amount': '-0.000003',
        'external_order_id': 'order', 'source_id': 'cost', 'cost_calculation': {'reasons': [], 'state': 'calculated',
        'components': [dict(sku_id=i, sku_code=str(i), legacy_sku_code='', source_sku='', currency='CNY',
                            quantity=1, net_cost='0.000001', reasons=[]) for i in range(3)]}}]
    rates = {'monthly': {'2026-09|PH|CNY|PHP': {'rate': '9.55', 'input_id': 42}},
             'historical': {'2026-09-10|CNY|PHP': {'rate': '10.00'}}}
    convert_costs(facts, {1: SimpleNamespace(currency='PHP')}, rates)
    parent = facts[0]['cost_conversion']
    assert parent['local_amount'] == '-0.000029'
    assert parent['quote']['input_id'] == 42
    members = _sku_members(facts, rates)
    assert sum(Decimal(m['amounts']['product_cost']) for m in members) == Decimal(parent['local_amount'])
    rates['monthly']['2026-09|PH|CNY|PHP']['rate'] = '99'
    assert parent['local_amount'] == '-0.000029'
    assert parent['quote']['rate'] == '9.55'


def test_missing_monthly_rate_does_not_silently_use_daily_rate_or_zero():
    f = {'kind': 'product_cost', 'country': 'PH', 'currency': 'CNY', 'store_id': 1,
         'date': '2026-09-10', 'amount': '-20', 'cost_calculation': {'reasons': [], 'components': [
             {'net_cost': '20', 'reasons': []}]}}
    convert_costs([f], {1: SimpleNamespace(currency='PHP')},
                  {'monthly': {}, 'historical': {'2026-09-10|CNY|PHP': {'rate': '10'}}})
    assert f['cost_conversion']['local_amount'] is None
    assert f['cost_calculation']['components'][0]['local_amount'] is None
    assert f['status'] == 'pending'


def test_legacy_values_are_discarded_and_second_rebuild_reads_new_inputs():
    template = '''<script type="application/json" id="snapshot">{"amount":"POISON_OLD_MONEY"}</script>
<script>
const SNAPSHOT = {};
// Only the reconciled legacy inputs
const sp6thAdvertisingRows=['POISON_OLD_MONEY'];
const KINDS={};
const HISTORICAL_FX={"old":"POISON_OLD_MONEY"};function displayCurrency(){}
const WAREHOUSE_MONTHLY_FX={"old":"POISON_OLD_MONEY"};function warehouseKind(){}
const WAREHOUSE_COUNTRY_BASIS={"old":"POISON_OLD_MONEY"};const warehouseTrial=null;
function localFact(f){return 'POISON_OLD_MONEY';}
function fxDescription(){}
const FACTS=buildFacts();const WAREHOUSE_SHARES=buildWarehouseShares();
const FILE_TREE=['POISON_OLD_MONEY'];
</script>
<script id="html2-sp6th-fees-data">globalThis.HTML2_SP6TH_FEES={"old":"POISON_OLD_MONEY"};</script>
<script id="html2-store-hierarchy">globalThis.HTML2_SKU_ORDER_SALES={"old":"POISON_OLD_MONEY"};</script>
<script id="html2-product-links">globalThis.HTML2_PRODUCT_LINK_DATA={"old":"POISON_OLD_MONEY"};globalThis.HTML2_PRODUCT_LINK_PROVENANCE={"old":"POISON_OLD_MONEY"};</script>'''
    source = {'read_at': '2026-11-01', 'facts': [{'amount': '-20'}], 'raw': [], 'shopee_income': [],
        'sku_members': [], 'rates': {'monthly': {}, 'historical': {}}, 'shares': {},
        'sku_sales': {'orders': {}}, 'products': {'rows': [], 'products': []}, 'cycles': {}, 'recharge': {}}
    first = render(template, source)
    assert 'POISON_OLD_MONEY' not in first
    source['facts'] = [{'amount': '-30'}]
    second = render(first, source)
    snapshot = json.loads(re.search(r'id="snapshot">([\s\S]*?)</script>', second)[1])
    assert snapshot['database']['facts'] == [{'amount': '-30'}]
    assert second.count('// SAAS_DATABASE_ENTRIES') == 1


def test_browser_compaction_keeps_canonical_money_and_supplies_empty_ui_metadata():
    facts = [{'amount': '-20', 'kind': 'order_fee'}]
    snapshot = {'database': {'schema': 'saas-finance-database.v1', 'raw': [], 'facts': facts, 'shares': {}, 'rates': {}},
                'local_expenses': {'facts': facts}, 'allocations': {'views': {}}}
    html = '<script type="application/json" id="snapshot">'+json.dumps(snapshot)+'</script><script>const FACTS=SNAPSHOT.database.facts;\n// SAAS_DATABASE_ENTRIES</script>'
    compact = compact_browser_inputs(html)
    data = json.loads(re.search(r'id="snapshot">([\s\S]*?)</script>', compact)[1])
    assert data['database']['facts'] == facts
    assert 'raw' not in data['database']
    assert data['local_expenses']['facts'] == []
    assert data['allocations']['unallocated']['store'] == []
    assert 'SNAPSHOT.local_expenses.facts=FACTS;' in compact


@pytest.mark.django_db
def test_database_collection_reflects_source_changes_and_excludes_other_tenant(tmp_path):
    tenant, _, store, _ = create_scope('summary-source')
    user = user_for(tenant, 'summary-source')
    other, _, other_store, _ = create_scope('summary-other-source')
    other_user = user_for(other, 'other-source')
    row = FinanceSummaryInput.objects.create(tenant=tenant, store=store, kind='adjustment', source_key='source',
        period='2026-09', payload={'amount': '-20'}, source_hash='a'*64, source_description='source', created_by=user)
    FinanceSummaryInput.objects.create(tenant=other, store=other_store, kind='adjustment', source_key='other',
        period='2026-09', payload={'amount': '-999'}, source_hash='b'*64, source_description='source', created_by=other_user)
    scope = {'stores': [store.pk], 'from': '2026-09-01', 'to': '2026-09-30'}
    before = collect(user, scope)
    assert [f['amount'] for f in before['facts'] if f['kind'] == 'adjustment'] == ['-20.000000']
    row.payload = {'amount': '-30'};row.save()
    after = collect(user, scope)
    assert [f['amount'] for f in after['facts'] if f['kind'] == 'adjustment'] == ['-30.000000']
    assert all(f.get('store_id') == store.pk for f in after['facts'])


def test_rebuild_enforces_write_access_before_collecting(context, monkeypatch):
    client, _, dataset, _ = context
    monkeypatch.setattr('apps.finance.summary_rebuild.collect', lambda *args: pytest.fail('Unauthorized source read'))
    assert client.post(f'/api/finance/summary/{dataset.pk}/rebuild/', {'revision': 0}, format='json').status_code == 403


def test_rebuild_rejects_stale_revision_without_source_reads(context, monkeypatch):
    client, user, dataset, _ = context
    grant(user, 'finance.import')
    dataset.metadata['database_scope'] = {'stores': [], 'from': '2026-09-01', 'to': '2026-09-30'}
    dataset.save()
    monkeypatch.setattr('apps.finance.summary_rebuild.collect', lambda *args: pytest.fail('Stale source read'))
    assert client.post(f'/api/finance/summary/{dataset.pk}/rebuild/', {'revision': 9}, format='json').status_code == 409


@pytest.mark.django_db
@pytest.mark.parametrize('occurred_on', [None, '2026-09-03'])
def test_warehouse_fee_inherits_shipment_day_without_changing_bill_month(occurred_on):
    from apps.finance.warehouse_fee_models import WarehouseFee
    tenant, platform, store, warehouse = create_scope('fee-statistics-date')
    platform.platform_type = 'lazada'; platform.save()
    user = user_for(tenant, 'fee-statistics-date')
    from apps.commerce.models import SalesOrder, ShipmentRecord
    run = create_run(tenant, 'sales_order', 'fee-statistics-date', platform='lazada')
    order = SalesOrder.objects.create(tenant=tenant,platform=platform,store=store,
        authorization=run.sync_job.integration_config,source_run=run,external_order_id='fee-order',
        raw_status='completed',normalized_status='completed',status_mapping_version='test',
        created_at_utc=datetime(2026,8,17,tzinfo=timezone.utc),updated_at_utc=datetime(2026,8,17,tzinfo=timezone.utc),
        business_date='2026-08-17',currency='PHP',payload_hash='c'*64)
    shipment_run = create_run(tenant, 'shipment', 'fee-shipment-date', platform='lazada')
    ShipmentRecord.objects.create(tenant=tenant,platform=platform,store=store,sales_order=order,
        source_run=shipment_run,external_shipment_id='shipment',external_line_id='line',
        shipment_type='sale',source_sku='sku',quantity=1,status='shipped',
        shipped_at_utc=datetime(2026,9,10,18,tzinfo=timezone.utc),
        updated_at_utc=datetime(2026,9,10,18,tzinfo=timezone.utc))
    fee = WarehouseFee.objects.create(tenant=tenant, store=store, warehouse=warehouse, order=order,
        external_order_id=order.external_order_id, country='PH', kind='order', bill_month='2026-09',
        bill_number='synthetic', fee_item='出库处理费', reference='synthetic', amount='3.100001',
        currency='CNY', occurred_on=occurred_on, status='registered', business_key='a'*64,
        content_hash='b'*64, created_by=user)
    posted_settlement(user, store, run, order, '0')
    source = collect(user, {'stores':[store.pk], 'from':'2026-08-01','to':'2026-09-30'})
    fact = next(row for row in source['facts'] if row['source_id']=='warehouse:'+str(fee.pk))
    assert fact['date'] == fact['warehouse_settlement_date'] == '2026-09-05'
    assert fact['statistics_date'] == '2026-09-11'
    assert fact['statistics_date_basis'] == 'order_shipped_at_utc:Asia/Shanghai'
    assert fact['statistics_order_id'] == order.pk
    assert fact['source_bill_month'] == '2026-09' and fact['amount'] == '-3.100001'
    assert source['order_dates'][str(store.pk)+'|'+order.external_order_id]['date'] == '2026-09-11'
    fee.refresh_from_db()
    assert str(fee.occurred_on) == str(occurred_on)


@pytest.mark.django_db
@pytest.mark.parametrize('platform_type', ['shopee', 'lazada'])
@pytest.mark.parametrize('status', ['completed', 'cancelled'])
@pytest.mark.parametrize('settlement', [None, '0', '-1', '10', 'conflict', 'outside-month'])
def test_registered_warehouse_fee_needs_valid_settlement_not_positive_sales(platform_type, status, settlement):
    from apps.commerce.models import SalesOrder
    from apps.finance.warehouse_fee_models import WarehouseFee
    tenant, platform, store, warehouse = create_scope('warehouse-without-sales')
    platform.platform_type = platform_type; platform.save()
    user = user_for(tenant, 'warehouse-without-sales')
    run = create_run(tenant, 'sales_order', 'warehouse-without-sales', platform=platform_type)
    order = SalesOrder.objects.create(tenant=tenant, platform=platform, store=store,
        authorization=run.sync_job.integration_config, source_run=run, external_order_id='no-sale',
        raw_status=status, normalized_status=status, status_mapping_version='test',
        created_at_utc=datetime(2026,7,17,tzinfo=timezone.utc), updated_at_utc=datetime(2026,9,1,tzinfo=timezone.utc),
        business_date='2026-07-17', currency='PHP', payload_hash='c'*64,
        source_details={'platform_pickup_at_utc':'2026-08-31T18:00:00Z'})
    def fee(key, **extra):
        return WarehouseFee.objects.create(tenant=tenant, store=store, warehouse=warehouse,
            country='PH', kind='order', bill_month='2026-09', bill_number='test', fee_item='出库处理费',
            reference=key, amount='3.100001', currency='CNY', business_key=key.ljust(64,'x'),
            content_hash='b'*64, created_by=user, **extra)
    included = fee('registered', order=order, external_order_id=order.external_order_id,
        occurred_on='2026-09-29', status='registered')
    excluded = [fee('draft', order=order, external_order_id=order.external_order_id, status='draft'),
                fee('unmatched', external_order_id='missing', status='registered')]
    if settlement is not None:
        posted_settlement(user, store, run, order, '0' if settlement in ('conflict','outside-month') else settlement,
                          'conflict' if settlement == 'conflict' else 'matched',
                          '2026-08-31' if settlement == 'outside-month' else '2026-09-05')
    WarehouseFee.objects.create(tenant=tenant, kind='other', country='PH', bill_month='2026-09',
        bill_number='test', fee_item='其他费', reference='pool', amount='5', currency='CNY', status='registered',
        business_key='pool'.ljust(64,'x'), content_hash='b'*64, created_by=user)
    from apps.finance.warehouse_fee_models import WarehouseBillUpload
    WarehouseBillUpload.objects.create(tenant=tenant, uploaded_by=user, file_name='test.xlsx', file_hash='a'*64,
        summary={'country':'PH','bill_month':'2026-09','currency':'CNY','order_detail_sum':'3.100001'})
    source = collect(user, {'stores':[store.pk], 'from':'2026-09-01','to':'2026-09-30'})
    facts = {row['source_id']:row for row in source['facts']}
    if settlement in (None, 'conflict', 'outside-month'):
        assert 'warehouse:'+str(included.pk) not in facts
        assert source['shares']['order'] == []
    else:
        row = facts['warehouse:'+str(included.pk)]
        assert row['source_bill_month'] == '2026-09' and row['amount'] == '-3.100001'
        assert row['date'] == row['warehouse_settlement_date'] == '2026-09-05'
        if platform_type == 'lazada' and settlement == '10':
            assert 'statistics_date' not in row  # Existing positive-sale weekly dates are unchanged.
        else:
            assert row['statistics_date'] == '2026-09-01'
            assert row['statistics_date_basis'] == 'order_platform_pickup_at_utc:Asia/Shanghai'
        assert source['shares']['order'][0]['warehouse_settlement_date'] == '2026-09-05'
        assert source['shares']['order'][0]['amount'] == '-5.000000'
    assert all('warehouse:'+str(f.pk) not in facts for f in excluded)
    included.refresh_from_db()
    assert included.status == 'registered' and included.amount == Decimal('3.100001')


def test_warehouse_recognition_adapter_preserves_existing_dates_and_cost_gate():
    import shutil
    import subprocess
    from pathlib import Path
    from django.conf import settings
    node = getattr(settings,'FINANCE_SUMMARY_NODE',None) or shutil.which('node')
    if not node:pytest.skip('Node runtime is required for the financial calculator')
    original = """function recognize(input){const first=new Map(input.filter(f=>f.kind==='sales'&&Number(f.amount)>0).map(f=>[identity(f),f.date])),out=[],warnings=[];
for(let f of input){if(outside.has(f.kind)&&f.external_order_id&&f.cost_event!=='return'){
 const date=first.get(identity(f));
 if(!date){warnings.push({source_id:f.source_id,reason:'未找到有效销售结算；成本费用不提前扣除'});continue;}
 f={...f,source_date:f.source_date||f.date,source_bill_month:f.source_bill_month||f.warehouse_allocation?.month||f.date.slice(0,7),date,month:date.slice(0,7),accounting_basis:'首次有效销售结算（已载入历史）'};
}out.push(f);}return{rows:out,warnings};}"""
    from apps.finance.summary_database_document import warehouse_profit_rules
    adapted = warehouse_profit_rules(original)
    assert warehouse_profit_rules(adapted) == adapted
    legacy = original.replace("if(!date){warnings.push(", "if(!date&&!['warehouse_order','warehouse_other'].includes(f.kind)){warnings.push(")
    legacy = legacy.replace("f={...f,source_date:", "if(date)f={...f,source_date:").replace(
        "accounting_basis:'首次有效销售结算（已载入历史）'};",
        "accounting_basis:'首次有效销售结算（已载入历史）'};\n   else{const month=f.source_bill_month||f.warehouse_allocation?.month||f.date.slice(0,7);f={...f,source_date:f.source_date||f.date,source_bill_month:month,date:month,month,accounting_basis:'已登记关联订单仓库费用；无正向销售结算时按原账单月计入'};}")
    assert warehouse_profit_rules(legacy) == adapted
    source = dict(read_at='2026-11-03',facts=[],raw=[],shopee_income=[],sku_members=[],rates={},shares={},
        sku_sales={},products={},cycles={},recharge={})
    document = render('<script id="html2-profit-rules">'+original+'</script>',source)
    assert re.search(r'<script id="html2-profit-rules">([\s\S]*?)</script>',document)[1] == adapted
    assert render(document,source) == document
    engine = str(Path(__file__).parents[1]/'apps/finance/summary_engine.cjs')
    script = """const assert=require('node:assert/strict'),vm=require('node:vm');
const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const adapted=require(input.engine).warehouseProfitRules(input.original);
assert.equal(adapted,input.adapted);
assert.equal(require(input.engine).warehouseProfitRules(input.legacy),input.adapted);
const c={outside:new Set(['warehouse_order','warehouse_other','product_cost','gcash','promotion']),identity:f=>f.external_order_id};
vm.createContext(c);vm.runInContext(adapted,c);
const fee=(id,kind='warehouse_order')=>({source_id:id,kind,external_order_id:id,amount:'-3',date:'2026-09-29',source_bill_month:'2026-09',statistics_date:'2026-08-31'});
const result=c.recognize([fee('missing'),{...fee('zero'),warehouse_settlement_date:'2026-09-05'},{kind:'sales',external_order_id:'zero',amount:'0',date:'2026-09-03'},
 {...fee('negative'),warehouse_settlement_date:'2026-09-05'},{kind:'sales',external_order_id:'negative',amount:'-1',date:'2026-09-03'},
 {...fee('other','warehouse_other'),warehouse_settlement_date:'2026-09-05'},
 fee('cost','product_cost'),fee('gcash','gcash'),fee('promo','promotion'),
 {...fee('existing'),source_bill_month:'2026-08',warehouse_settlement_date:'2026-09-12'}, {kind:'sales',external_order_id:'existing',amount:'10',date:'2026-09-15'}]);
assert(!result.rows.some(f=>f.source_id==='missing'));
for(const id of ['zero','negative','other']){const f=result.rows.find(f=>f.source_id===id);assert.equal(f.month,'2026-09');assert.equal(f.date,'2026-09-05');assert.equal(f.statistics_date,'2026-08-31');assert.match(f.accounting_basis,/有效结算日/);}
assert.equal(result.rows.find(f=>f.source_id==='existing').date,'2026-09-12');
assert.equal(result.rows.find(f=>f.source_id==='existing').source_bill_month,'2026-08');
for(const id of ['cost','gcash','promo'])assert(!result.rows.some(f=>f.source_id===id));
assert.equal(result.warnings.length,3);
"""
    result = subprocess.run([node,'-e',script],input=json.dumps(dict(engine=engine,original=original,legacy=legacy,adapted=adapted)),
        capture_output=True,text=True,timeout=10)
    assert result.returncode == 0, result.stderr


def test_warehouse_shares_inherit_statistics_day_but_keep_unallocated_amount():
    from apps.finance.summary_database import warehouse_shares
    source = {'source_id':'other:1','kind':'warehouse_other','date':'2026-09','source_bill_month':'2026-09',
              'amount':'-10.000001','currency':'CNY','country':'PH','scope':'country','status':'confirmed'}
    fee = {'source_id':'order:1','kind':'warehouse_order','source_bill_month':'2026-09','date':'2026-09',
           'statistics_date':'2026-08-17','statistics_date_basis':'order_shipped_at_utc:Asia/Shanghai','statistics_order_id':7,
           'amount':'-2','currency':'CNY','country':'PH','store_id':1,'store_code':'LZ','platform':'lazada','external_order_id':'one'}
    shares = warehouse_shares([source,fee], {'PH|2026-09|CNY':{'total':'4'}}, {'monthly':{}})
    allocated = shares['order'][0]
    assert allocated['statistics_date'] == '2026-08-17'
    assert allocated['statistics_order_id'] == 7 and allocated['date'] == '2026-09'
    assert sum(Decimal(row['amount']) for row in shares['order']+shares['unallocated']) == Decimal(source['amount'])
    assert all('statistics_date' not in row for row in shares['unallocated'])


@pytest.mark.django_db
def test_settled_order_loads_its_original_month_other_pool_outside_reporting_window():
    from apps.commerce.models import SalesOrder
    from apps.finance.models import PlatformFinanceTransaction
    from apps.finance.warehouse_fee_models import WarehouseFee, WarehouseBillUpload
    tenant,platform,store,warehouse=create_scope('prior-warehouse-pool')
    user=user_for(tenant,'prior-warehouse-pool')
    run=create_run(tenant,'sales_order','prior-warehouse-pool')
    order=SalesOrder.objects.create(tenant=tenant,platform=platform,store=store,
        authorization=run.sync_job.integration_config,source_run=run,external_order_id='prior-fee-order',
        raw_status='completed',normalized_status='completed',status_mapping_version='test',
        created_at_utc=datetime(2026,7,17,tzinfo=timezone.utc),updated_at_utc=datetime(2026,9,1,tzinfo=timezone.utc),
        business_date='2026-07-17',currency='PHP',payload_hash='c'*64)
    from apps.integrations.store_authorization_service import create_store_authorization
    auth=create_store_authorization(tenant=tenant,integration_config=run.sync_job.integration_config,store=store,
        platform='shopee',region='PH',platform_store_id='123',merchant_subject_id='123',shop_cipher='',
        credential_id='custody-test-old-credential',token_id='custody-test-old-token',allow_live_references=True,scopes=[],actor=user)
    PlatformFinanceTransaction.objects.create(tenant=tenant,platform='shopee',store=store,
        authorization=auth,source_run=run,source_key='settled',
        external_order_id=order.external_order_id,raw_fee_name='escrow_amount',fee_code='escrow',fee_category='income',
        raw_amount='10',signed_amount='10',currency='PHP',occurred_at_utc=datetime(2026,9,5,tzinfo=timezone.utc),
        business_date='2026-09-05',match_status='matched',normalization_version='test',payload_hash='d'*64)
    common=dict(tenant=tenant,country='PH',warehouse=warehouse,bill_number='July',bill_month='2026-07',
        currency='CNY',status='registered',content_hash='b'*64,created_by=user)
    fee=WarehouseFee.objects.create(**common,kind='order',store=store,order=order,
        external_order_id=order.external_order_id,fee_item='出库处理费',reference='fee',amount='2',business_key='a'*64)
    pool=WarehouseFee.objects.create(**common,kind='other',fee_item='其他费',reference='pool',amount='10',business_key='e'*64)
    WarehouseFee.objects.create(**{**common,'bill_month':'2026-06'},kind='other',fee_item='无关费用',reference='unrelated',amount='999',business_key='f'*64)
    WarehouseBillUpload.objects.create(tenant=tenant,uploaded_by=user,file_name='July.xlsx',file_hash='g'*64,
        summary={'country':'PH','bill_month':'2026-07','currency':'CNY','order_detail_sum':'4'})
    result=collect(user,{'stores':[store.pk],'from':'2026-09-01','to':'2026-09-30'})
    facts={f['source_id']:f for f in result['facts']}
    assert facts['warehouse:'+str(fee.pk)]['date']=='2026-09-05'
    assert 'warehouse:'+str(pool.pk) in facts
    assert all(f.get('source_bill_month')!='2026-06' for f in result['facts'])
    assert result['shares']['order'][0]['amount']=='-5.000000'
    assert result['shares']['order'][0]['date']=='2026-09-05'
    assert sum(Decimal(r['amount']) for r in result['shares']['order']+result['shares']['unallocated'])==Decimal('-10')


def test_shipping_dates_require_unique_actual_day_and_keep_tenant_store_order_identity():
    from apps.finance.summary_database import shipping_dates
    orders = [SimpleNamespace(pk=i,store_id=1,platform_id=2,external_order_id=str(i)) for i in range(1,5)]
    def shipment(order,day,store=1,platform=2):
        return {'sales_order_id':order,'store_id':store,'platform_id':platform,
                'shipped_at_utc':datetime.fromisoformat(day).replace(tzinfo=timezone.utc) if day else None}
    dates = shipping_dates(orders,[shipment(1,'2026-08-31T18:00:00'),shipment(1,'2026-08-31T19:00:00'),
        shipment(2,'2026-09-01T12:00:00'),shipment(2,'2026-09-02T12:00:00'),
        shipment(3,None),shipment(4,'2026-09-03T12:00:00',store=99)])
    assert dates['1|1']['date'] == '2026-09-01'
    assert dates['1|2']['date'] is None and dates['1|2']['reason'] == '订单存在多个发货／揽收日期，待核对'
    assert dates['1|3']['date'] is None and dates['1|4']['date'] is None


def test_undated_other_fee_allocation_keeps_original_month_and_does_not_invent_a_day():
    from apps.finance.summary_database import warehouse_shares
    source = {'source_id':'other:1','kind':'warehouse_other','date':'2026-09','source_bill_month':'2026-09',
        'amount':'-10','currency':'CNY','country':'PH','scope':'country','status':'confirmed'}
    fee = {'source_id':'order:1','kind':'warehouse_order','source_bill_month':'2026-09','month':'2026-09',
        'date':'2026-09','statistics_date':None,'statistics_date_reason':'关联订单缺少发货日期',
        'amount':'-2','currency':'CNY','country':'PH','store_id':1,'store_code':'LZ','platform':'lazada','external_order_id':'one'}
    shares=warehouse_shares([source,fee],{'PH|2026-09|CNY':{'total':'2'}},{'monthly':{}})
    assert shares['order'][0]['statistics_date'] is None
    assert shares['order'][0]['statistics_date_reason'] == '关联订单缺少发货日期'
    assert shares['order'][0]['source_bill_month'] == '2026-09'
    assert shares['order'][0]['amount'] == '-10.000000'


def test_pickup_fallback_requires_actual_pickup_not_capture_deadline_or_packed_event():
    from apps.finance.summary_database import shipping_dates
    def order(i,details):return SimpleNamespace(pk=i,store_id=1,platform_id=2,external_order_id=str(i),source_details=details)
    def event(status,description):return {'status':status,'description':description,'occurred_at_utc':'2026-08-31T18:00:00Z'}
    def trace(i,events):return {'platform_logistics':{'order_sn':str(i),'collected_at_utc':'2026-11-02T00:00:00Z','packages':[{'events':events}]}}
    orders=[order(1,{'platform_pickup_at_utc':'2026-09-02T18:00:00Z'}),
        order(2,trace(2,[event('100100','Your package has been picked up by LEX PH.')])),
        order(3,trace(3,[event('1200','Your package is packed and will be handed over to our logistics partner.')])),
        order(4,trace('wrong',[event('100100','Your package has been picked up by LEX PH.')])),
        order(5,{'platform_pickup_at_utc':'not-a-date','ship_by_at_utc':'2026-09-01T00:00:00Z'})]
    dates=shipping_dates(orders,[])
    assert dates['1|1']['date']=='2026-09-03'
    assert dates['1|1']['basis']=='order_platform_pickup_at_utc:Asia/Shanghai'
    assert dates['1|2']['date']=='2026-09-01'
    assert dates['1|2']['basis']=='order_trace_pickup:Asia/Shanghai'
    assert all(dates['1|'+str(i)]['date'] is None for i in [3,4,5])
    shipped=[{'sales_order_id':1,'store_id':1,'platform_id':2,'shipped_at_utc':datetime(2026,9,1,tzinfo=timezone.utc)}]
    assert shipping_dates(orders,shipped)['1|1']['date']=='2026-09-01'


def test_flow_date_enrichment_preserves_original_fx_month_not_hierarchy_month():
    import shutil
    import subprocess
    from django.conf import settings
    from apps.finance.summary_database_document import DATABASE_LOCAL_FACT
    node=getattr(settings,'FINANCE_SUMMARY_NODE',None) or shutil.which('node')
    if not node:pytest.skip('Node runtime is required for the financial calculator')
    script=DATABASE_LOCAL_FACT+'''
const SNAPSHOT={database:{rates:{historical:{},monthly:{
 '2026-08|PH|CNY|PHP':{rate:'1'},'2026-09|PH|CNY|PHP':{rate:'2'}}}}};
const displayCurrency=()=> 'PHP',warehouseKind=()=>true,fixed=String,convertAmount=(a,r)=>Number(a)*Number(r);
const f={kind:'warehouse_order',amount:'-20',currency:'CNY',country:'PH',date:'2026-09-01',statistics_date:'2026-08-31',source_date:'2026-08',month:'2026-08'};
if(localFact(f).amount!=='-40')throw Error('Original FX month changed');
delete f.statistics_date;
if(localFact(f).amount!=='-40')throw Error('Existing conversion behavior changed');
'''
    result=subprocess.run([node,'-e',script],capture_output=True,text=True,timeout=10)
    assert result.returncode==0, 'Flow date must not alter exchange-rate attribution'
