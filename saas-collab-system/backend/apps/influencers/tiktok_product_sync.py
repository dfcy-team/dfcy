"""Bounded TikTok product performance collection for exact completed windows."""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.tenants.models import Tenant
from .models import TikTokProductPerformanceSnapshot
from .tiktok_video_sync import DatasetError, fingerprint, lock_sources, require, resolve
from .tiktok_shop_dataset import TikTokDatasetClient

PATH = '/analytics/202605/shop_products/performance'
COUNT_FIELDS = ('product_impressions','product_clicks','add_cart_count','unique_product_impressions',
                'unique_clicks','add_cart_users','estimated_customers')
RATE_FIELDS = ('ctr','add_cart_rate','click_order_rate','unique_ctr','unique_atc_rate','unique_click_order_rate')
CHANNEL_FIELDS = ('seller_live_performance','seller_video_performance','seller_product_card_performance',
                  'affiliate_total_performance','affiliate_live_performance','affiliate_video_performance',
                  'shop_tab_performance')
CHANNEL_COUNTS = ('product_impressions','product_clicks','estimated_customers','add_cart_count','orders','items_sold',
                  'shop_tab_product_impressions','shop_tab_product_clicks','shop_tab_sold_items')
CHANNEL_RATES = ('ctr','add_cart_rate','click_order_rate','shop_tab_ctr','shop_tab_ctor_sku')


def _metric(value, integer=False):
    if value is None: return None
    if type(value) not in (str, int, float, Decimal): raise DatasetError('invalid_product_metric')
    try: number = Decimal(str(value))
    except InvalidOperation: raise DatasetError('invalid_product_metric') from None
    if not number.is_finite() or number < 0: raise DatasetError('invalid_product_metric')
    if integer and (number != number.to_integral_value() or number > 2**63-1): raise DatasetError('invalid_product_count')
    return int(number) if integer else str(number)


def _project(row):
    if not isinstance(row,dict) or not str(row.get('id','')).isascii() or not str(row.get('id','')).isdecimal() or not 0<int(row['id'])<=2**63-1 or len(str(row['id']))>160:
        raise DatasetError('invalid_product_row')
    total=row.get('total_performance')
    if not isinstance(total,dict): raise DatasetError('invalid_product_metrics')
    values={key:_metric(total.get(key),True) for key in COUNT_FIELDS}
    values.update({key:_metric(total.get(key)) for key in RATE_FIELDS})
    for channel in CHANNEL_FIELDS:
        detail=row.get(channel)
        if detail is not None and not isinstance(detail,dict): raise DatasetError('invalid_product_channel')
        if detail is not None:
            values[channel]={}
            for key in CHANNEL_COUNTS:
                if key in detail: values[channel][key]=_metric(detail[key],True)
            for key in CHANNEL_RATES:
                if key in detail: values[channel][key]=_metric(detail[key])
    return str(row['id']),values


def run_window(actor,store_id,start,end,*,apply=False,client_factory=TikTokDatasetClient):
    start=date.fromisoformat(str(start));end=date.fromisoformat(str(end))
    require(start < end and (end-start).days <= 31,'product_window_must_be_1_to_31_days')
    current_actor=actor.__class__._default_manager.get(pk=actor.pk)
    require(current_actor.is_active and current_actor.tenant_id==actor.tenant_id,'product_actor_inactive')
    auth=resolve(current_actor,store_id); frozen=fingerprint(auth)
    def guard():
        current_actor=actor.__class__._default_manager.get(pk=actor.pk)
        require(current_actor.is_active and current_actor.tenant_id==actor.tenant_id,'product_actor_inactive')
        current=resolve(current_actor,store_id)
        require(fingerprint(current)==frozen,'product_binding_or_approval_changed')
        return current
    today=timezone.now().astimezone(ZoneInfo(auth.store.timezone)).date()
    require(end <= today,'product_window_must_be_completed')
    client=client_factory(auth.integration_config,auth)
    client._require_scope('data.shop_analytics.public.read')
    client.verify_shop()
    products={}; cursors=set(); cursor=''; total=None
    for _ in range(100):
        guard()
        query={'shop_cipher':auth.shop_cipher,'start_date_ge':start.isoformat(),'end_date_lt':end.isoformat(),
               'page_size':100,'currency':'LOCAL','product_status_filter':'ALL'}
        if cursor: query['page_token']=cursor
        data=client._request(PATH,query=query)['data']
        latest=data.get('latest_available_date')
        try:
            ready=isinstance(latest,str) and date.fromisoformat(latest)>=end-timedelta(days=1)
        except ValueError:
            ready=False
        require(ready,'product_window_data_not_available')
        rows=data.get('products')
        if not isinstance(rows,list) or len(rows)>100 or type(data.get('total_count')) is not int or not 0<=data['total_count']<=10000 or (not rows and data['total_count']>0): raise DatasetError('product_page_invalid')
        if total is not None and total!=data['total_count']: raise DatasetError('product_total_changed')
        total=data['total_count']
        for row in rows:
            pid,metrics=_project(row)
            if pid in products: raise DatasetError('duplicate_product_page_row')
            products[pid]=metrics
        next_cursor=data.get('next_page_token') or ''
        if not isinstance(next_cursor,str) or len(next_cursor)>4096 or (next_cursor and (not rows or next_cursor in cursors)):
            raise DatasetError('product_cursor_not_advancing')
        if not next_cursor: break
        cursors.add(next_cursor);cursor=next_cursor
    else: raise DatasetError('product_page_limit_exceeded')
    require(total==len(products),'product_total_mismatch')
    result={'store_id':store_id,'window_start':str(start),'window_end':str(end),'rows':len(products),'pages':len(cursors)+1,'status':'dry_run'}
    current=guard()
    if not apply:return result
    with transaction.atomic():
        Tenant.objects.select_for_update().get(pk=actor.tenant_id)
        lock_sources(current)
        guard()
        TikTokProductPerformanceSnapshot.objects.filter(tenant_id=actor.tenant_id,store_id=store_id,window_start=start,window_end=end).delete()
        observed_at=timezone.now()
        # The tenant-validated manager deliberately prohibits bulk_create.
        # Respect its relation validation; this is a bounded offline import,
        # never work performed by the sales list or modal request.
        for pid,metrics in products.items():
            TikTokProductPerformanceSnapshot.objects.create(
                tenant_id=actor.tenant_id,store_id=store_id,product_id=pid,
                window_start=start,window_end=end,metrics=metrics,source_updated_at=observed_at)
        saved=set(TikTokProductPerformanceSnapshot.objects.filter(tenant_id=actor.tenant_id,store_id=store_id,
            window_start=start,window_end=end).values_list('product_id',flat=True))
        require(saved==set(products),'product_database_readback_mismatch')
    return dict(result,status='completed',database_verified=True)
