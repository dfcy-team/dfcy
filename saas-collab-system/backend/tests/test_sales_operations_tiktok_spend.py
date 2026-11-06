from datetime import date, datetime, UTC
from decimal import Decimal
from hashlib import sha256
from unittest.mock import patch

import pytest
from apps.commerce.models import SalesOrder
from apps.integrations.models import PlatformIntegrationConfig, TikTokAdsAdvertiserMapping, TikTokAdsDailySpend, SharedAdvertisingRawPayload
from apps.integrations.gmv_max_sync import REPORT_PATH
from apps.masterdata.models import CountrySiteMaster
from tests.test_sales_realtime_board import _fixture, _order, DAY

pytestmark = pytest.mark.django_db
URL = '/api/internal/commerce/sales-operations/'


@pytest.fixture
def fixture():
    user, tenant, platform, store, run, client = _fixture('tk-sales')
    user.is_superuser = True
    user.save(update_fields=['is_superuser'])
    platform.platform_type = 'tiktok'
    platform.save(update_fields=['platform_type'])
    order_config = run.sync_job.integration_config
    order_config.platform = 'tiktok'
    order_config.save(update_fields=['platform'])
    config = PlatformIntegrationConfig.objects.create(tenant=tenant, platform='tiktok', account_alias='tkads',
        environment='pilot', created_by=user, platform_config={'api_type': 'advertising'})
    mapping = TikTokAdsAdvertiserMapping.objects.create(tenant=tenant, store=store, integration_config=config,
        advertiser_id='1234', token_id='tok_' + '1' * 32, currency='USD', timezone='Asia/Manila')
    _order(tenant, platform, store, run, 'today', amount='1200')
    for code, rate in [('USD', '0.1'), ('PHP', '6')]:
        CountrySiteMaster.objects.create(tenant=tenant, code=code.lower(), name=code, country_code=code[:2],
            currency=code, cny_exchange_rate=rate, exchange_rate_date=DAY)
    return client, mapping, run


def verified(payload):
    return {**payload, 'report_scope': 'GMV_MAX_CAMPAIGN', 'store_evidence': {
        'is_gmv_max_available': True, 'store_id': payload['platform_store_id'],
        'exclusive_authorized_advertiser_info': {'advertiser_id': payload['advertiser_id']}}}


def snapshot(mapping, cost='10', day=DAY, suffix='1', *, identity=True):
    payload = {'schema': 'gmv-max-day-v1', 'advertiser_id': mapping.advertiser_id,
        'date': day, 'platform_store_id': '99', 'currency': 'USD', 'timezone': 'Asia/Manila',
        'pages': [{'page_info': {'page': 1, 'page_size': 100, 'total_page': 1, 'total_number': 1},
            'list': [{'dimensions': {'campaign_id': '1'}, 'metrics': {'cost': cost, 'gross_revenue': '100', 'orders': '1'}}]}]}
    return SharedAdvertisingRawPayload.objects.create(tenant=mapping.tenant, store=mapping.store,
        platform='tiktok', endpoint=REPORT_PATH, payload_hash=sha256((day+cost+suffix).encode()).hexdigest(), payload=verified(payload) if identity else payload)


def get(client, **params):
    response = client.get(URL, {'date_from': DAY, 'date_to': DAY, **params})
    assert response.status_code == 200, response.content
    return response.json()['data']


def test_api_fx_dedup_and_previous_period(fixture):
    client, m, run = fixture
    snapshot(m, '99', suffix='old')
    snapshot(m, '10', suffix='new')
    snapshot(m, '5', day='2026-08-16')
    _order(m.tenant, m.store.platform, m.store, run, 'previous', amount='600')
    SalesOrder.objects.filter(tenant=m.tenant, external_order_id='previous').update(
        created_at_utc=datetime(2026, 8, 16, 8, tzinfo=UTC))
    TikTokAdsDailySpend.objects.create(tenant=m.tenant, mapping=m, date=DAY, spend='2', currency='USD')
    data = get(client, currency='PHP')
    row = data['rows'][0]
    assert Decimal(row['ad_spend']) == 600  # GMV Max 10 / .1 * 6; ordinary bidding spend is excluded
    assert Decimal(row['roi']) == Decimal('1200') / 600
    assert abs(Decimal(row['roi_delta']) - (Decimal('1200') / 600 - 2)) < Decimal('.000001')
    assert 'GMV Max 10' in row['ad_basis'] and '前期：GMV Max 5' in row['ad_basis']
    assert '2026-08-17' in row['ad_basis']
    assert Decimal(data['currency_groups'][0]['ad_spend']) == 600
    assert Decimal(data['cny_summary']['ad_spend']) == 100


def test_missing_rate_does_not_turn_gmv_into_basic_zero(fixture):
    client, m, _ = fixture
    snapshot(m)
    TikTokAdsDailySpend.objects.create(tenant=m.tenant, mapping=m, date=DAY, spend='0', currency='PHP')
    CountrySiteMaster.objects.filter(tenant=m.tenant, currency='USD').delete()
    row = get(client)['rows'][0]
    assert row['ad_spend'] is None and row['roi'] is None
    assert '参考汇率' in row['ad_reason'] and '10' in row['ad_basis']


def test_no_data_and_explicit_zero_are_distinct(fixture):
    client, m, _ = fixture
    assert get(client)['rows'][0]['ad_spend'] is None
    snapshot(m, '0')
    row = get(client)['rows'][0]
    assert Decimal(row['ad_spend']) == 0 and row['roi'] is None
    assert row['ad_status'] == 'provisional'


def test_analytics_scope_hides_tk_amount(fixture):
    client, m, _ = fixture
    snapshot(m)
    with patch('apps.sales_management.tiktok_spend.advertising_store_scope', return_value=(None, [])):
        row = get(client)['rows'][0]
    assert row['ad_spend'] is None and not row.get('ad_basis')


def test_integration_scope_hides_tk_amount_and_metadata(fixture):
    client, m, _ = fixture
    snapshot(m)
    with patch('apps.sales_management.tiktok_spend.permission_scope_configs', return_value=[]):
        row = get(client)['rows'][0]
    assert row['ad_spend'] is None and not row.get('ad_basis')


def test_conflicting_snapshot_identities_make_spend_unknown(fixture):
    client, m, _ = fixture
    snapshot(m, '10', suffix='one')
    payload = {'schema': 'gmv-max-day-v1', 'advertiser_id': m.advertiser_id,
        'date': DAY, 'platform_store_id': '100', 'currency': 'USD', 'timezone': 'Asia/Manila',
        'pages': [{'page_info': {'page': 1, 'page_size': 100, 'total_page': 1, 'total_number': 1},
            'list': [{'dimensions': {'campaign_id': '1'}, 'metrics': {'cost': '20', 'gross_revenue': '100', 'orders': '1'}}]}]}
    SharedAdvertisingRawPayload.objects.create(tenant=m.tenant, store=m.store, platform='tiktok',
        endpoint=REPORT_PATH, payload_hash=sha256(b'identity-conflict').hexdigest(), payload=verified(payload))
    row = get(client)['rows'][0]
    assert row['ad_spend'] is None
    assert '冲突' in row['ad_reason']


def test_conflict_outside_current_store_day_does_not_hide_current_spend(fixture):
    client, m, run = fixture
    _order(m.tenant, m.store.platform, m.store, run, 'current-day-order')
    SalesOrder.objects.filter(tenant=m.tenant, external_order_id='current-day-order').update(
        created_at_utc=datetime(2026, 11, 5, 8, tzinfo=UTC))
    snapshot(m, '10', day='2026-11-05', suffix='current')
    snapshot(m, '10', day='2026-11-04', suffix='old-one')
    payload = {'schema': 'gmv-max-day-v1', 'advertiser_id': m.advertiser_id,
        'date': '2026-11-04', 'platform_store_id': '100', 'currency': 'USD', 'timezone': 'Asia/Manila',
        'pages': [{'page_info': {'page': 1, 'page_size': 100, 'total_page': 1, 'total_number': 1},
            'list': [{'dimensions': {'campaign_id': '1'}, 'metrics': {'cost': '20', 'gross_revenue': '100', 'orders': '1'}}]}]}
    SharedAdvertisingRawPayload.objects.create(tenant=m.tenant, store=m.store, platform='tiktok',
        endpoint=REPORT_PATH, payload_hash=sha256(b'old-identity-conflict').hexdigest(), payload=verified(payload))
    with patch('apps.sales_management.current_sales_operations.timezone.now',
               return_value=datetime(2026, 11, 5, 12, tzinfo=UTC)):
        response = client.get(URL, {'period': 'current'})
    assert response.status_code == 200
    row = response.json()['data']['rows'][0]
    assert Decimal(row['ad_spend']) == 600


def test_partly_hidden_mapping_makes_store_spend_unknown(fixture):
    client, m, _ = fixture
    snapshot(m, '10')
    TikTokAdsAdvertiserMapping.objects.create(tenant=m.tenant, store=m.store,
        integration_config=m.integration_config, advertiser_id='5678', token_id='tok_' + '2' * 32,
        currency='USD', timezone='Asia/Manila')
    with patch('apps.sales_management.tiktok_spend._mapping_allowed', side_effect=lambda user, mapping, scopes: mapping.pk == m.pk):
        row = get(client)['rows'][0]
    assert row['ad_spend'] is None
    assert '部分广告账户' in row['ad_reason']
    assert '5678' not in row['ad_basis'] + row['ad_reason']


def test_board_uses_historical_multicurrency_orders_even_when_filtered(fixture):
    client, m, run = fixture
    snapshot(m)
    _order(m.tenant, m.store.platform, m.store, run, 'usd-order', currency='USD')
    board = client.get('/api/internal/commerce/realtime-board/',
                       {'date_from': DAY, 'date_to': DAY, 'currency': 'PHP'})
    assert board.status_code == 200
    group = next(g for g in board.json()['data']['currency_groups'] if g['currency'] == 'PHP')
    assert group['ad_spend'] is None
    assert '币种' in (group.get('ad_reason') or '') or '无法确定' in (group.get('ad_reason') or '')


def test_multicurrency_store_cannot_double_charge_via_filter(fixture):
    client, m, run = fixture
    snapshot(m)
    _order(m.tenant, m.store.platform, m.store, run, 'usd-order', currency='USD')
    row = get(client, currency='PHP')['rows'][0]
    assert row['ad_spend'] is None
    assert '尚未分摊' in row['ad_reason']


def test_current_uses_store_local_day(fixture):
    client, m, _ = fixture
    snapshot(m, '10')
    snapshot(m, '99', day='2026-08-16')
    with patch('apps.sales_management.current_sales_operations.timezone.now', return_value=datetime(2026, 8, 17, 12, tzinfo=UTC)):
        response = client.get(URL, {'period': 'current'})
    assert response.status_code == 200
    row = response.json()['data']['rows'][0]
    assert Decimal(row['ad_spend']) == 600
    assert 'GMV Max 10' in row['ad_basis']


def test_board_and_workbench_share_real_stored_gmvmax_cost(fixture):
    client, mapping, run = fixture
    snapshot(mapping, '99', suffix='older')
    snapshot(mapping, '10', suffix='latest')
    TikTokAdsDailySpend.objects.create(tenant=mapping.tenant, mapping=mapping,
                                      date=DAY, spend='200', currency='USD')
    board = client.get('/api/internal/commerce/realtime-board/',
                       {'date_from': DAY, 'date_to': DAY})
    assert board.status_code == 200
    board_group = next(g for g in board.json()['data']['currency_groups'] if g['currency'] == 'PHP')
    workbench_group = next(g for g in get(client, currency='PHP')['currency_groups'] if g['currency'] == 'PHP')
    assert Decimal(board_group['ad_spend']) == Decimal(workbench_group['ad_spend']) == Decimal('600')


def test_auction_fallback_is_shared_by_board_and_workbench(fixture):
    client, m, _ = fixture
    TikTokAdsDailySpend.objects.create(tenant=m.tenant, mapping=m, date=DAY, spend='2', currency='USD')
    board = client.get('/api/internal/commerce/realtime-board/', {'date_from': DAY, 'date_to': DAY})
    group = next(g for g in board.json()['data']['currency_groups'] if g['currency'] == 'PHP')
    row = get(client)['rows'][0]
    assert Decimal(group['ad_spend']) == Decimal(row['ad_spend']) == Decimal('120')
    assert '普通竞价' in row['ad_basis']


def test_verified_gmv_locks_source_across_comparison_window(fixture):
    client, m, _ = fixture
    snapshot(m, '5', day='2026-08-16')
    TikTokAdsDailySpend.objects.create(tenant=m.tenant, mapping=m, date=DAY, spend='2', currency='USD')
    row = get(client)['rows'][0]
    assert row['ad_spend'] is None
    assert '普通竞价' not in row['ad_basis'].split('；')[0]


def test_unverified_gmv_does_not_displace_auction_fallback(fixture):
    client, m, _ = fixture
    snapshot(m, '999', identity=False)
    TikTokAdsDailySpend.objects.create(tenant=m.tenant, mapping=m, date=DAY, spend='2', currency='USD')
    assert Decimal(get(client)['rows'][0]['ad_spend']) == Decimal('120')


def test_verified_empty_gmv_prevents_auction_fallback(fixture):
    client, m, _ = fixture
    payload = verified({'schema': 'gmv-max-day-v1', 'advertiser_id': m.advertiser_id,
        'date': DAY, 'platform_store_id': '99', 'currency': 'USD', 'timezone': 'Asia/Manila',
        'pages': [{'page_info': {'page': 1, 'page_size': 100, 'total_page': 0, 'total_number': 0}, 'list': []}]})
    SharedAdvertisingRawPayload.objects.create(tenant=m.tenant, store=m.store, platform='tiktok',
        endpoint=REPORT_PATH, payload_hash=sha256(b'empty-verified').hexdigest(), payload=payload)
    TikTokAdsDailySpend.objects.create(tenant=m.tenant, mapping=m, date=DAY, spend='2', currency='USD')
    row = get(client)['rows'][0]
    assert row['ad_spend'] is None and row['roi'] is None

@pytest.mark.parametrize("code,rate,expected", [("MYR", "0.6", "60"), ("THB", "5", "500")])
def test_usd_spend_in_selected_sales_currency(fixture, code, rate, expected):
    client, mapping, _ = fixture
    SalesOrder.objects.filter(store=mapping.store).update(currency=code)
    CountrySiteMaster.objects.create(tenant=mapping.tenant, code=code.lower(), name=code,
        country_code=code[:2], currency=code, cny_exchange_rate=rate, exchange_rate_date=DAY)
    snapshot(mapping, "10")
    for filters in ({}, {"currency": code}):
        data = get(client, **filters)
        row = data["rows"][0]
        assert row["currency"] == code
        assert Decimal(row["ad_spend"]) == Decimal(expected)
        assert Decimal(data["cny_summary"]["ad_spend"]) == 100
        assert Decimal(row["roi"]) == Decimal(1200) / Decimal(expected)
