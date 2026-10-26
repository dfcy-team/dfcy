import pytest

from apps.integrations.models import ShopeeAdvertisingRecord
from apps.commerce.models import SalesOrder
from apps.masterdata.models import StoreMaster
from tests.test_sales_realtime_board import DAY, _fixture, _grant, _order

URL = '/api/internal/commerce/sales-operations/'


@pytest.mark.django_db
def test_partial_advertising_is_estimated_without_blocking_other_stores():
    user, tenant, platform, store, run, client = _fixture('ops-observed')
    _grant(user, 'analytics.view')
    _order(tenant, platform, store, run, 'observed', amount='100')
    other = StoreMaster.objects.create(tenant=tenant, platform=platform, code='missing-ad', name='missing', country_code='PH', currency='PHP', timezone='Asia/Manila')
    _order(tenant, platform, other, run, 'missing', amount='900')
    for key, data in [('present', {'expense': '10'}), ('missing', {})]:
        ShopeeAdvertisingRecord.objects.create(tenant=tenant, store=store, kind='shop_daily', record_key=key,
            report_date=DAY, currency='PHP', report_timezone='Asia/Manila', source_run=run,
            dimensions={'store_id': str(store.id), 'platform': 'shopee'}, data=data)
    data = client.get(URL, {'date_from':DAY, 'date_to':DAY}).json()['data']
    group = data['currency_groups'][0]
    assert group['sales_amount'] == '1000'
    assert group['ad_sales_amount'] == '100'
    assert group['ad_spend'] == '10' and group['roi'] == '10'
    assert group['ad_status'] == 'provisional' and '仅统计' in group['ad_reason']
    rows = {r['store_id']:r for r in data['rows']}
    assert rows[store.id]['roi'] == '10'
    assert rows[other.id]['roi'] is None and rows[other.id]['sales_amount'] == '900'
    ShopeeAdvertisingRecord.objects.filter(tenant=tenant).update(data={'expense':'0'})
    data = client.get(URL, {'date_from':DAY, 'date_to':DAY}).json()['data']
    assert data['currency_groups'][0]['roi'] is None
    assert data['currency_groups'][0]['ad_spend'] == '0'
    ShopeeAdvertisingRecord.objects.filter(tenant=tenant).update(data={})
    data = client.get(URL, {'date_from':DAY, 'date_to':DAY}).json()['data']
    assert data['currency_groups'][0]['ad_spend'] is None


@pytest.mark.django_db
def test_observed_advertising_keeps_analytics_scope_and_country_conflicts():
    user, tenant, platform, store, run, client = _fixture('ops-observed-scope')
    _grant(user, 'analytics.view', {'analytics_dimensions':[{'store_id':'999999', 'platform':'shopee'}]})
    _order(tenant, platform, store, run, 'sale')
    ShopeeAdvertisingRecord.objects.create(tenant=tenant, store=store, kind='shop_daily', record_key='expense',
        report_date=DAY, currency='PHP', report_timezone='Asia/Manila', source_run=run,
        dimensions={'store_id':str(store.id), 'platform':'shopee'}, data={'expense':'10'})
    assert client.get(URL, {'date_from':DAY,'date_to':DAY}).json()['data']['rows'][0]['roi'] is None
    _grant(user, 'analytics.view')
    SalesOrder.objects.filter(tenant=tenant).update(region='MY')
    data=client.get(URL, {'date_from':DAY,'date_to':DAY}).json()['data']
    assert data['rows'][0]['roi'] is None and data['rows'][0]['sales_amount']=='100'
    assert data['rows'][0]['ad_spend'] is None
    assert '冲突' in data['rows'][0]['ad_reason']


@pytest.mark.django_db
def test_zero_expense_store_is_not_in_currency_roi_numerator():
    user, tenant, platform, store, run, client = _fixture('ops-observed-zero-mix')
    _grant(user, 'analytics.view')
    _order(tenant, platform, store, run, 'positive-sale', amount='100')
    zero = StoreMaster.objects.create(tenant=tenant, platform=platform, code='zero-ad', name='zero', country_code='PH', currency='PHP', timezone='Asia/Manila')
    _order(tenant, platform, zero, run, 'zero-sale', amount='900')
    for shop, key, expense in ((store, 'positive', '10'), (zero, 'zero', '0')):
        ShopeeAdvertisingRecord.objects.create(tenant=tenant, store=shop, kind='shop_daily', record_key=key,
            report_date=DAY, currency='PHP', report_timezone='Asia/Manila', source_run=run,
            dimensions={'store_id': str(shop.id), 'platform': 'shopee'}, data={'expense': expense})
    data = client.get(URL, {'date_from': DAY, 'date_to': DAY}).json()['data']
    group = data['currency_groups'][0]
    assert group['sales_amount'] == '1000' and group['ad_sales_amount'] == '100'
    assert group['ad_spend'] == '10' and group['roi'] == '10'
    rows = {row['store_id']: row for row in data['rows']}
    assert rows[zero.id]['sales_amount'] == '900'
    assert rows[zero.id]['ad_spend'] == '0' and rows[zero.id]['roi'] is None


@pytest.mark.django_db
def test_denied_ad_scope_and_missing_previous_expense_do_not_stale_roi():
    from unittest.mock import patch
    from apps.common.exceptions import DataScopeDenied

    user, tenant, platform, store, run, client = _fixture('ops-observed-no-ad-scope')
    _order(tenant, platform, store, run, 'current', amount='100')
    _grant(user, 'analytics.view')
    with patch('apps.sales_management.observed_roi.advertising_queryset',
               side_effect=DataScopeDenied('广告数据当前范围不可见。')):
        denied = client.get(URL, {'date_from': DAY, 'date_to': DAY}).json()['data']
    assert denied['rows'][0]['sales_amount'] == '100'
    assert denied['rows'][0]['roi'] is None and denied['rows'][0]['ad_spend'] is None
    assert '当前广告数据范围查看权限' in denied['rows'][0]['ad_reason']

    previous = _order(tenant, platform, store, run, 'previous', amount='60')
    previous.created_at_utc = previous.created_at_utc.replace(day=16)
    previous.save(update_fields=['created_at_utc'])
    ShopeeAdvertisingRecord.objects.create(tenant=tenant, store=store, kind='shop_daily', record_key='current-ad',
        report_date=DAY, currency='PHP', report_timezone='Asia/Manila', source_run=run,
        dimensions={'store_id': str(store.id), 'platform': 'shopee'}, data={'expense': '10'})
    data = client.get(URL, {'date_from': DAY, 'date_to': DAY}).json()['data']
    assert data['rows'][0]['roi'] == '10' and data['rows'][0]['roi_delta'] is None
    assert data['currency_groups'][0]['roi_delta'] is None


@pytest.mark.django_db
def test_currency_roi_uses_only_periods_with_both_sales_and_expense():
    user, tenant, platform, store, run, client = _fixture('ops-observed-period-pairs')
    _grant(user, 'analytics.view')
    current = _order(tenant, platform, store, run, 'matched-current', amount='100')
    prior = _order(tenant, platform, store, run, 'matched-previous', amount='100')
    prior.created_at_utc = prior.created_at_utc.replace(day=16)
    prior.save(update_fields=['created_at_utc'])

    previous_only = StoreMaster.objects.create(tenant=tenant, platform=platform, code='previous-only', name='previous only', country_code='PH', currency='PHP', timezone='Asia/Manila')
    unmatched_prior = _order(tenant, platform, previous_only, run, 'unmatched-previous', amount='900')
    unmatched_prior.created_at_utc = unmatched_prior.created_at_utc.replace(day=16)
    unmatched_prior.save(update_fields=['created_at_utc'])
    current_only = StoreMaster.objects.create(tenant=tenant, platform=platform, code='current-only', name='current only', country_code='PH', currency='PHP', timezone='Asia/Manila')
    _order(tenant, platform, current_only, run, 'unmatched-current', amount='900')

    for shop, key, report_day, expense in (
        (store, 'matched-current-ad', DAY, '10'),
        (store, 'matched-previous-ad', '2026-08-16', '10'),
        (previous_only, 'current-ad-without-current-sales', DAY, '90'),
        (current_only, 'previous-ad-without-previous-sales', '2026-08-16', '90'),
    ):
        ShopeeAdvertisingRecord.objects.create(tenant=tenant, store=shop, kind='shop_daily', record_key=key,
            report_date=report_day, currency='PHP', report_timezone='Asia/Manila', source_run=run,
            dimensions={'store_id': str(shop.id), 'platform': 'shopee'}, data={'expense': expense})

    group = client.get(URL, {'date_from': DAY, 'date_to': DAY}).json()['data']['currency_groups'][0]
    assert group['sales_amount'] == '1000' and group['previous_sales_amount'] == '1000'
    assert group['ad_sales_amount'] == '100'
    assert group['ad_spend'] == '10' and group['roi'] == '10' and group['roi_delta'] == '0'
