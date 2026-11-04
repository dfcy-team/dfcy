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


def snapshot(mapping, cost='10', day=DAY, suffix='1'):
    payload = {'schema': 'gmv-max-day-v1', 'advertiser_id': mapping.advertiser_id,
        'date': day, 'platform_store_id': '99', 'currency': 'USD', 'timezone': 'Asia/Manila',
        'pages': [{'page_info': {'page': 1, 'page_size': 100, 'total_page': 1, 'total_number': 1},
            'list': [{'dimensions': {'campaign_id': '1'}, 'metrics': {'cost': cost, 'gross_revenue': '100', 'orders': '1'}}]}]}
    return SharedAdvertisingRawPayload.objects.create(tenant=mapping.tenant, store=mapping.store,
        platform='tiktok', endpoint=REPORT_PATH, payload_hash=sha256((day+cost+suffix).encode()).hexdigest(), payload=payload)


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
