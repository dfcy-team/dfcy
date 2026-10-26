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
