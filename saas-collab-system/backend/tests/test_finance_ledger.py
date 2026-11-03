from decimal import Decimal

import pytest

from apps.finance.ledger import allocate, summarize, split_amount, sales_weights
from apps.finance.warehouse_fee_services import create_fee, operate
from apps.sales_management.registration_models import OrderRegistration
from tests.test_sales_management import create_scope, create_order, grant, user_for, client_for
from tests.test_warehouse_fees import payload as fee_payload


def fact(**changes):
    return dict(dict(source_id='fee:1', kind='warehouse_other', scope='country', country='PH',
        store_id=None, store_code='', platform='', external_order_id='', currency='PHP',
        amount=Decimal('-1.000001'), date='2026-08-31', status='confirmed',
        source='仓库账单', description='仓储费', parts=[], warehouse_id=1), **changes)


def orders():
    return [dict(id=i, country='PH', store_id=s, store_code=str(s), platform='shopee',
        external_order_id=str(i), currency='PHP', weight=Decimal(w))
        for i, s, w in [(1, 10, '1'), (2, 10, '2'), (3, 20, '3')]]


@pytest.mark.parametrize('amount', ['-1.000001', '0.01', '-12345.000123'])
def test_largest_remainder_is_exact_and_deterministic(amount):
    shares = split_amount(Decimal(amount), [('a', Decimal(1)), ('b', Decimal(1)), ('c', Decimal(1))])
    assert sum(shares.values()) == Decimal(amount)
    assert shares == split_amount(Decimal(amount), [('c', Decimal(1)), ('b', Decimal(1)), ('a', Decimal(1))])


def test_country_rollup_is_direct_and_store_order_allocations_reconcile():
    source = fact()
    country, _ = allocate([source], orders(), 'country')
    assert country[0].get('allocation') is None
    stores, _ = allocate([source], orders(), 'store')
    lines, _ = allocate([source], orders(), 'order')
    assert sum(x['amount'] for x in stores) == source['amount']
    assert sum(x['amount'] for x in lines) == source['amount']
    for store in stores:
        assert store['amount'] == sum(x['amount'] for x in lines if x['store_id'] == store['store_id'])


def test_missing_denominator_stays_unallocated_and_is_not_zero():
    entries, missing = allocate([fact(currency='CNY')], orders(), 'order')
    assert not entries and missing[0]['amount'] == Decimal('-1.000001')
    assert summarize(entries, 'order') == []


def test_reference_refund_and_pending_amount_do_not_deduct_net_receipt():
    entries = [fact(kind='receipt', amount=Decimal('80')), fact(source_id='refund:1',
        kind='refund', amount=Decimal('-20'), status='reference'),
        fact(source_id='draft:1', kind='gcash', amount=Decimal('-2'), status='pending')]
    row = summarize(entries, 'country')[0]
    assert row['balance'] == Decimal('80') and row['pending_count'] == 1
    assert row['cells']['refund']['amount'] is None
    assert row['cells']['refund']['reference_amount'] == Decimal('-20')


@pytest.fixture
def context(db):
    tenant, _, store, warehouse = create_scope('ledger')
    user = user_for(tenant, 'ledger-viewer')
    for permission in ['finance.view', 'finance.warehouse_fees.view', 'finance.warehouse_fees.import',
                       'finance.warehouse_fees.register', 'finance.gcash.view',
                       'sales_management.promotion.view', 'sales_management.orders.view']:
        grant(user, permission)
    return client_for(user), user, store, warehouse


def test_real_registration_sources_are_scoped_private_and_readonly(context):
    client, user, store, warehouse = context
    from apps.masterdata.models import CountrySiteMaster
    CountrySiteMaster.objects.create(tenant=user.tenant, code='PH', name='PH', country_code='PH', currency='PHP')
    order = create_order(user.tenant, store, 'ledger', '100')
    fee, _ = create_fee(user, fee_payload((*context, None), external_order_id=order.external_order_id,
        currency='PHP', bill_month='2026-08', occurred_on='2026-08-31'), action='import')
    operate(user, fee.pk, 'register', fee.version)
    OrderRegistration.objects.create(tenant=user.tenant, store=store, order=order, kind='gcash',
        status='registered', requested_by=user, payload={'type':'refund', 'amount':'12', 'currency':'PHP',
        'paid_at':'2026-08-31', 'phone':'PRIVATE-PHONE', 'recipient':'PRIVATE-RECIPIENT'})
    response = client.get('/api/finance/ledger/', {'all_history':1, 'view':'country'})
    assert response.status_code == 200, response.data
    body = response.json()['data']
    assert body['items'][0]['cells']['warehouse_order']['amount'] == '-2.400000'
    assert body['items'][0]['cells']['gcash']['amount'] == '-12'
    assert 'PRIVATE' not in str(response.content)
    fee.refresh_from_db()
    assert fee.version == 2 and fee.status == 'registered'
    other = user_for(user.tenant, 'ledger-finance-only')
    grant(other, 'finance.view')
    body = client_for(other).get('/api/finance/ledger/', {'all_history':1}).json()['data']
    assert body['items'] == []


def test_ledger_rejects_invalid_filters_and_anonymous(context):
    client = context[0]
    for query in [{'view':'bad'}, {'period_start':'2026-09-20', 'period_end':'2026-08-01'},
                  {'currency':'bad'}, {'unknown':'yes'}, {'page_size':1001}]:
        assert client.get('/api/finance/ledger/', query).status_code == 400
    from rest_framework.test import APIClient
    assert APIClient().get('/api/finance/ledger/').status_code in {401,403}


def test_order_filter_does_not_rebase_store_expenses(context):
    client, user, store, _ = context
    first = create_order(user.tenant, store, 'first', '100')
    create_order(user.tenant, store, 'second', '300')
    OrderRegistration.objects.create(tenant=user.tenant, store=store, kind='gcash', status='registered',
        requested_by=user, payload={'type':'other','amount':'40','currency':'PHP','paid_at':'2026-08-31'})
    query = {'all_history':1, 'view':'order', 'kind':'gcash'}
    full = client.get('/api/finance/ledger/', query).json()['data']
    assert full['totals'][0]['balance'] == '-40.000000'
    selected = client.get('/api/finance/ledger/', {**query, 'external_order_id':first.external_order_id}).json()['data']
    assert selected['items'][0]['cells']['gcash']['amount'] == '-10.000000'
    detail = client.get('/api/finance/ledger/', {**query, 'external_order_id':first.external_order_id, 'breakdown':1}).json()['data']
    assert detail['items'][0]['allocation']['store_sales'] == '400.0000'
    assert detail['items'][0]['allocation']['country_sales'] is None
    assert detail['items'][0]['allocation']['basis_currency'] == 'PHP'


def test_restricted_order_permission_never_rebases_public_cost(context):
    client, user, store, _ = context
    create_order(user.tenant, store, 'visible', '100')
    restricted = user_for(user.tenant, 'ledger-partial')
    from apps.permissions.models import DataScope
    grant(restricted, 'finance.view')
    grant(restricted, 'finance.gcash.view')
    grant(restricted, 'sales_management.orders.view', DataScope.ScopeType.CUSTOM, {'store_ids':[store.pk]})
    OrderRegistration.objects.create(tenant=user.tenant, store=store, kind='gcash', status='registered',
        requested_by=user, payload={'type':'other','amount':'40','currency':'PHP','paid_at':'2026-08-31'})
    body = client_for(restricted).get('/api/finance/ledger/', {'all_history':1,'view':'order'}).json()['data']
    assert body['items'] == [] and body['unallocated_count'] == 1
    assert '授权范围不完整' in body['unallocated'][0]['reason']


def test_sales_weight_query_count_does_not_grow_per_order(context):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    _, user, store, _ = context
    create_order(user.tenant, store, 'initial', '100')
    with CaptureQueriesContext(connection) as initial:
        first, complete = sales_weights(user, {})
    for suffix in ['a', 'b', 'c']:
        create_order(user.tenant, store, suffix, '100')
    with CaptureQueriesContext(connection) as expanded:
        rows, _ = sales_weights(user, {})
    assert complete and len(first) == 1 and len(rows) == 4
    assert len(expanded) <= len(initial) + 1


def platform_context(platform):
    from apps.integrations.models import (MarketplaceStoreAuthorization, PlatformIntegrationConfig,
        SyncJob, SyncRun, authorization_service_write, marketplace_identity_key, marketplace_store_binding_key)
    tenant, _, store, _ = create_scope('ledger-' + platform)
    store.platform.platform_type = platform
    store.platform.save()
    user = user_for(tenant, 'ledger-platform-' + platform)
    grant(user, 'finance.view')
    config = PlatformIntegrationConfig.objects.create(tenant=tenant, platform=platform,
        account_alias='Ledger test', created_by=user)
    identity = marketplace_identity_key(platform, 'PH', 'ledger-store')
    authorization = MarketplaceStoreAuthorization(tenant=tenant, store=store, integration_config=config,
        platform=platform, region='PH', platform_store_id='ledger-store', platform_identity_key=identity,
        active_platform_identity_key=identity, active_store_binding_key=marketplace_store_binding_key(tenant.pk,platform,store.pk),
        merchant_subject_id='test', credential_id='test-reference', token_id='test-reference', status='active',
        created_by=user, updated_by=user)
    with authorization_service_write():
        authorization.save()
    job = SyncJob.objects.create(tenant=tenant, integration_config=config, resource_type='settlement_bill')
    run = SyncRun.objects.create(tenant=tenant,sync_job=job,run_id='ledger-'+platform,idempotency_key='ledger-'+platform)
    return user, store, authorization, run


def add_transaction(context, name, amount, category='other'):
    from datetime import datetime, UTC
    from apps.finance.models import PlatformFinanceTransaction
    user, store, authorization, run = context
    return PlatformFinanceTransaction.objects.create(tenant=user.tenant, platform=store.platform.platform_type,
        store=store,authorization=authorization,source_run=run,source_key=name,
        external_order_id='LEDGER-ORDER',raw_fee_name=name,fee_category=category,raw_amount=amount,
        signed_amount=amount,currency='PHP',occurred_at_utc=datetime(2026,8,31,tzinfo=UTC),
        business_date='2026-08-31',match_status='matched',normalization_version='test',payload_hash='a'*64)


@pytest.mark.django_db
def test_shopee_components_and_refund_reference_never_double_count_settlement():
    context = platform_context('shopee')
    for name, amount in [('escrow_amount','80'), ('order_original_price','200'),
                         ('commission_fee','-5'), ('seller_return_refund','-20')]:
        add_transaction(context,name,amount)
    result = client_for(context[0]).get('/api/finance/ledger/', {'all_history':1,'view':'country'}).json()['data']
    assert result['totals'][0]['balance'] == '80.0000'
    assert result['items'][0]['cells']['refund']['reference_amount'] == '-20.0000'
    assert result['items'][0]['cells']['receipt']['amount'] == '80.0000'
    client = client_for(context[0])
    detail = client.get('/api/finance/ledger/', {'all_history':1}).json()['data']
    assert detail['pagination']['total'] == 1
    assert detail['source_count'] == 1 and detail['hidden_reference_refund_count'] == 1
    assert detail['items'][0]['kind'] == 'receipt' and detail['totals'] == result['totals']
    audit = client.get('/api/finance/ledger/', {'all_history':1,'view':'country','breakdown':1,'kind':'refund'}).json()['data']
    assert audit['items'][0]['status'] == 'reference'
    raw = client.get('/api/finance/transactions/', {'external_order_id':'LEDGER-ORDER'}).json()['data']
    assert raw['pagination']['total'] == 4
    from apps.finance.models import PlatformFinanceTransaction
    assert PlatformFinanceTransaction.objects.get(tenant=context[0].tenant,raw_fee_name='seller_return_refund').signed_amount == Decimal('-20')


@pytest.mark.django_db
def test_lazada_net_receipt_keeps_fees_and_refund_separate_without_legacy_double_count():
    from apps.finance.models import PlatformStatement
    context = platform_context('lazada')
    for name, amount in [('Item Price Credit','100'),('Commission','-10'),('Payment Fee','-3'),('Reversal Item Price','-20')]:
        add_transaction(context,name,amount)
    PlatformStatement.objects.create(tenant=context[0].tenant,platform='lazada',statement_no='legacy',
        period_start='2026-08-01',period_end='2026-08-31',currency='PHP',gross_amount='999',net_amount='999')
    result = client_for(context[0]).get('/api/finance/ledger/', {'all_history':1,'view':'country'}).json()['data']
    assert result['totals'][0]['balance'] == '67.0000'
    assert result['items'][0]['cells']['receipt']['amount'] == '87.0000'
    assert result['items'][0]['cells']['refund']['amount'] == '-20.0000'
    detail = client_for(context[0]).get('/api/finance/ledger/', {'all_history':1}).json()['data']
    assert any(row['kind'] == 'refund' and row['status'] == 'confirmed' for row in detail['items'])
    assert detail['hidden_reference_refund_count'] == 0


def test_reference_refunds_are_hidden_before_pagination_only(monkeypatch):
    from types import SimpleNamespace
    from apps.finance import ledger
    facts = [fact(source_id='receipt',kind='receipt',amount=Decimal('80'),date='2026-08-05'),
        fact(source_id='reference-refund-1',kind='refund',status='reference',date='2026-08-04'),
        fact(source_id='actual-refund',kind='refund',amount=Decimal('-10'),date='2026-08-03'),
        fact(source_id='other-reference',kind='gcash',status='reference',date='2026-08-02'),
        fact(source_id='reference-refund-2',kind='refund',status='reference',date='2026-08-01')]
    monkeypatch.setattr(ledger,'collect_records',lambda *_: (facts,[]))
    monkeypatch.setattr(ledger,'sales_weights',lambda *_: ([],True))
    monkeypatch.setattr(ledger,'check_user_permission',lambda *_: False)
    query = {'view':'detail','page':1,'page_size':2}
    first = ledger.report(SimpleNamespace(),query)
    second = ledger.report(SimpleNamespace(),{**query,'page':2})
    assert [row['source_id'] for row in first['items']] == ['receipt','actual-refund']
    assert [row['source_id'] for row in second['items']] == ['other-reference']
    assert first['pagination']['total'] == 3 and first['source_count'] == 3
    assert first['hidden_reference_refund_count'] == 2
    assert first['totals'][0]['balance'] == Decimal('70')
    filtered = ledger.report(SimpleNamespace(),{**query,'kind':'refund','status':'reference'})
    assert filtered['items'] == [] and filtered['pagination']['total'] == 0
    assert filtered['hidden_reference_refund_count'] == 2
    breakdown = ledger.report(SimpleNamespace(),{**query,'breakdown':True,'page_size':20})
    assert breakdown['pagination']['total'] == 5 and breakdown['hidden_reference_refund_count'] == 0
    assert len(facts) == 5 and facts[1]['status'] == 'reference'


def test_tenant_and_currency_bounds_are_retained(context):
    client, user, store, _ = context
    other, _, other_store, _ = create_scope('ledger-hidden')
    other_user = user_for(other, 'ledger-other')
    for tenant, registrar, shop, currency, amount in [(user.tenant,user,store,'PHP','10'),
            (user.tenant,user,store,'CNY','20'),(other,other_user,other_store,'PHP','99')]:
        OrderRegistration.objects.create(tenant=tenant,store=shop,kind='gcash',status='registered',requested_by=registrar,idempotency_key=currency+amount,
            payload={'type':'other','amount':amount,'currency':currency,'paid_at':'2026-08-31'})
    assert client.get('/api/finance/ledger/',{'all_history':1}).json()['data']['source_count'] == 2
    from apps.permissions.models import DataScope
    viewer = user_for(user.tenant, 'ledger-cny')
    grant(viewer,'finance.view',DataScope.ScopeType.CUSTOM,{'currencies':['CNY']})
    grant(viewer,'finance.gcash.view')
    data = client_for(viewer).get('/api/finance/ledger/',{'all_history':1}).json()['data']
    assert data['source_count'] == 1 and data['totals'][0]['currency'] == 'CNY'
