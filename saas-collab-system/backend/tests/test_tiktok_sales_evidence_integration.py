from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.db import DatabaseError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import PermissionDenied

from apps.influencers.models import (
    TikTokProductPerformanceSnapshot, TikTokShopVideo, TikTokVideoProduct,
    TikTokVideoDailyMetric, TikTokVideoSyncBatch,
)
from apps.influencers.tiktok_product_sync import DatasetError, run_window
from apps.sales_management.tiktok_product_evidence import product_traffic_section, video_section
from tests.test_sales_realtime_board import DAY, _fixture, _grant, _order

START, END = date(2026, 11, 1), date(2026, 11, 3)


@pytest.fixture
def context(db):
    user, tenant, platform, store, *_ = _fixture('tk-evidence')
    for code in ('influencers.outreach.view', 'influencers.fulfillment.view'):
        _grant(user, code)
    return user, tenant, store


def test_video_degraded_rows_are_known_subtotals_and_ctr_uses_paired_rows(context):
    user, tenant, store = context
    batch = TikTokVideoSyncBatch.objects.create(tenant=tenant, store=store,
        window_start=START, window_end=END, api_version='test', idempotency_key='test')
    for i, (impressions, clicks, quality) in enumerate([
        (100, 10, 'degraded'), (900, None, 'degraded'), (None, 90, 'degraded'),
        (10000, 9999, 'failed'),
    ]):
        video = TikTokShopVideo.objects.create(tenant=tenant, store=store,
            external_video_id=str(i + 1), creator_open_id='creator-1')
        for pid in ('P', 'OTHER'):
            TikTokVideoProduct.objects.create(tenant=tenant, video=video,
                external_product_id=pid, parse_status='parsed')
        TikTokVideoDailyMetric.objects.create(tenant=tenant, store=store,
            video=video, batch=batch, metric_date=START, currency='PHP', row_hash=str(i),
            product_impressions=impressions, product_clicks=clicks, quality_status=quality)
    result = video_section(user, store_id=store.pk, product_id='P', date_from=START, date_to=START)
    values = {m['label']: m['value'] for m in result['metrics']}
    assert values['关联视频数'] == 4 and values['关联达人数'] == 1
    assert values['关联视频商品曝光'] == 1000
    assert values['关联视频商品点击'] == 100
    assert values['关联视频商品点击率'] == .1
    assert values['播放量'] is None
    assert '未分摊' in result['scope']


def test_exact_window_does_not_sum_daily_uv_and_expands_channels(context):
    user, tenant, store = context
    for start, end, uv in [(START, date(2026,11,2), 10), (date(2026,11,2), END, 12)]:
        TikTokProductPerformanceSnapshot.objects.create(tenant=tenant, store=store,
            product_id='P', window_start=start, window_end=end, metrics={'unique_product_impressions': uv})
    args = dict(store_id=store.pk, product_id='P', date_from=START, date_to=date(2026,11,2))
    assert product_traffic_section(user, **args)['status'] == 'not_collected'
    TikTokProductPerformanceSnapshot.objects.create(tenant=tenant, store=store,
        product_id='P', window_start=START, window_end=END, metrics={
            'unique_product_impressions': 15, 'estimated_customers': 3,
            'shop_tab_performance': {'shop_tab_product_clicks': 8, 'shop_tab_ctr': '0.08'},
            'seller_video_performance': {'product_impressions': 120},
        })
    result = product_traffic_section(user, **args)
    values = {m['label']: m['value'] for m in result['metrics']}
    assert values['曝光人数'] == 15
    assert values['预估购买客户数'] == 3
    assert values['Shop Tab 点击'] == 8
    assert values['卖家视频 曝光'] == 120


@pytest.mark.django_db
def test_sales_api_reads_tk_evidence_for_non_decline_product_only_on_modal_request():
    user, tenant, platform, store, run, client = _fixture('tk-modal-api')
    platform.platform_type='tiktok'; platform.save(update_fields=['platform_type'])
    config=run.sync_job.integration_config
    config.platform='tiktok'; config.save(update_fields=['platform'])
    for code in ('sales_management.skus.view', 'influencers.outreach.view', 'influencers.fulfillment.view'):
        _grant(user, code)
    _order(tenant, platform, store, run, 'TK')
    TikTokProductPerformanceSnapshot.objects.create(tenant=tenant, store=store,
        product_id='product-TK', window_start=date(2026,8,17), window_end=date(2026,8,18),
        metrics={'product_impressions': 120})
    query=dict(view='products', store_id=store.pk, currency='PHP', date_from=DAY, date_to=DAY, product_id='product-TK')
    url='/api/internal/commerce/sales-operations/'
    with CaptureQueriesContext(connection) as queries:
        response=client.get(url, query)
    assert response.status_code == 200
    assert response.json()['data']['rows'][0]['diagnosis'] is None
    assert not any('tiktokproductperformancesnapshot' in q['sql'].lower() or 'tiktokvideodailymetric' in q['sql'].lower() for q in queries)
    response=client.get(url, dict(query,evidence='1'))
    assert response.status_code == 200
    diagnosis=response.json()['data']['rows'][0]['diagnosis']
    assert diagnosis['platform'] == 'tiktok' and diagnosis['status'] == 'reference'
    assert diagnosis['sections'][1]['metrics'][0]['value'] == 120
    assert all(s['label'] != '商品访客数' for s in diagnosis['steps'])


def page(ids, next_token=''):
    return {'data': {'products': [{'id': str(pid), 'total_performance': {'product_impressions': 12}} for pid in ids],
        'total_count': 2, 'latest_available_date': '2026-11-02', 'next_page_token': next_token}}


@pytest.mark.parametrize('failure', ['duplicate', 'permission', 'write', 'not_ready', None])
def test_collection_is_atomic_and_rechecks_each_page(context, failure):
    user, tenant, store = context
    old = TikTokProductPerformanceSnapshot.objects.create(tenant=tenant, store=store,
        product_id='OLD', window_start=START, window_end=END, metrics={'product_impressions': 77})
    auth = SimpleNamespace(store=store, integration_config=object(), shop_cipher='test')
    client = Mock()
    first, second = page([1], 'next'), page([1 if failure == 'duplicate' else 2])
    if failure == 'not_ready': first['data']['latest_available_date'] = '2026-10-31'
    client._request.side_effect = [first, second]
    # Initial resolve, then page 1, then page 2. Revocation must stop page 2.
    resolved = [auth, auth, PermissionDenied('revoked')] if failure == 'permission' else None
    with patch('apps.influencers.tiktok_product_sync.resolve', side_effect=resolved, return_value=auth), \
         patch('apps.influencers.tiktok_product_sync.fingerprint', return_value='frozen'), \
         patch('apps.influencers.tiktok_product_sync.lock_sources'), \
         patch.object(TikTokProductPerformanceSnapshot.objects, 'create',
                      side_effect=DatabaseError('write failed') if failure == 'write' else None,
                      wraps=None if failure == 'write' else TikTokProductPerformanceSnapshot.objects.create):
        if failure:
            with pytest.raises((DatasetError, PermissionDenied, DatabaseError)):
                run_window(user, store.pk, START, END, apply=True, client_factory=lambda *args: client)
            assert TikTokProductPerformanceSnapshot.objects.get(pk=old.pk).metrics == {'product_impressions': 77}
        else:
            result = run_window(user, store.pk, START, END, apply=True, client_factory=lambda *args: client)
            assert result['database_verified'] and result['pages'] == 2
            assert set(TikTokProductPerformanceSnapshot.objects.values_list('product_id', flat=True)) == {'1','2'}
            assert product_traffic_section(user, store_id=store.pk, product_id='1',
                date_from=START, date_to=date(2026,11,2))['status'] == 'available'
    if failure == 'permission': assert client._request.call_count == 1
