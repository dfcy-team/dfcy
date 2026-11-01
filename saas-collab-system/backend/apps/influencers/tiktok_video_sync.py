"""Shop video-only ingestion: scoped API reads, immutable receipts, atomic day commits."""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import secrets
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.integrations.models import MarketplaceStoreAuthorization
from apps.integrations.production_settings import get_runtime_platform_config
from apps.integrations.ads_sync import lock_runtime_approval
from apps.masterdata.models import StoreMaster
from apps.integrations.models import PlatformIntegrationConfig
from apps.permissions.services import check_user_permission
from apps.tenants.models import Tenant
from .management.commands.export_tiktok_shop_dataset import resolve_export_scope
from .models import TikTokShopVideo, TikTokVideoProduct, TikTokVideoDailyMetric, TikTokVideoSyncBatch, TikTokVideoSyncEvidence
from .tiktok_shop_dataset import TikTokDatasetClient, DatasetError, canonical_bytes, _published_time

PATH = '/analytics/202605/shop_videos/performance'
VERSION = '202605-videos-v1'
COUNTS = ('views', 'likes', 'comments', 'shares', 'new_followers', 'v_to_l_clicks',
          'product_impressions', 'product_clicks', 'unique_customers', 'orders', 'sku_orders', 'items_sold')
MONEY = {'reported_gmv':'gmv', 'attributed_gmv':'attributed_gmv', 'direct_gmv':'direct_gmv',
         'indirect_gmv':'indirect_gmv', 'gpm':'gpm'}
RATES = {'ctr':'click_through_rate', 'v_to_l_rate':'v_to_l_rate',
         'finish_rate':'video_finish_rate'}
METRICS = (*COUNTS, *MONEY, *RATES, 'reported_ctor', 'click_to_order_rate')


def require(ok, code):
    if not ok:
        raise DatasetError(code)


def digest(obj):
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def text(value, limit=160):
    require(isinstance(value, str) and len(value) <= limit, 'invalid_video_text')
    require(not any(ord(c) < 32 and not (limit == 8192 and c in '\r\n\t') for c in value), 'invalid_video_text')
    return value


def number(value, *, integer=False, rate=False):
    if value is None:
        return None
    require(type(value) in (str, int, Decimal), 'inexact_video_number')
    try:
        n = Decimal(value)
    except InvalidOperation:
        raise DatasetError('invalid_video_number') from None
    require(n.is_finite() and n >= 0, 'invalid_video_number')
    if integer:
        require(n == n.to_integral_value() and n <= 2**63-1, 'invalid_video_count')
        return int(n)
    require(n < Decimal('1e16') and n == n.quantize(Decimal('.0001')), 'video_decimal_precision')
    require(not rate or n <= 1, 'invalid_video_rate')
    return n


def validate_video_page(data):
    """Validate the videos collection with diagnostics safe for persisted summaries."""
    if not isinstance(data, dict) or 'videos' not in data:
        raise DatasetError('video_page_invalid:field=videos:category=missing')
    values = data['videos']
    if values is None:
        raise DatasetError('video_page_invalid:field=videos:category=null')
    if not isinstance(values, list):
        # Deliberately report only a fixed type label, never repr(value).
        type_name = {dict:'object', str:'string', int:'number', float:'number', bool:'boolean'}.get(type(values), 'other')
        raise DatasetError(f'video_page_invalid:field=videos:category=type_{type_name}')
    if len(values) > 50:
        raise DatasetError('video_page_invalid:field=videos:category=oversized:range=0..50')
    return values


def project(value, currency):
    require(isinstance(value, dict), 'invalid_video_shape')
    vid = text(str(value.get('id') or value.get('video_id') or ''))
    require(vid.isascii() and vid.isdecimal() and int(vid) > 0, 'invalid_video_id')
    require(not value.get('video_id') or str(value['video_id']) == vid, 'conflicting_video_id')
    creator = value.get('creator') or {}
    require(isinstance(creator, dict), 'invalid_creator')
    source = value.get('total_performance', value)
    require(isinstance(source, dict), 'invalid_video_metrics')
    metrics = {k:number(source.get(k), integer=True) for k in COUNTS}
    for target, field in MONEY.items():
        money = source.get(field)
        require(money is None or isinstance(money, dict), 'invalid_video_money')
        if money and money.get('amount') is not None:
            require(money.get('currency') == currency, 'video_currency_mismatch')
        metrics[target] = number(money.get('amount') if money else None)
    for key, field in RATES.items():
        rate_value = source.get(field)
        if key != 'ctr' and rate_value is not None:
            try:
                parsed = number(rate_value, rate=True)
            except DatasetError as exc:
                if str(exc) == 'invalid_video_rate':
                    raise DatasetError(f'invalid_video_rate:field={field}:range=0..1') from None
                raise
        else:
            parsed = number(rate_value)
        metrics[key] = parsed
    require(metrics['ctr'] is None or metrics['ctr'] < 1000, 'video_ctr_precision')
    # Provider CTOR can exceed one (e.g. two SKU orders / one click).
    # Preserve its native value rather than treating it as a probability.
    metrics['reported_ctor'] = number(source.get('ctor'))
    metrics['click_to_order_rate'] = None
    published, raw_time = _published_time(value.get('video_post_time'))
    # A naive publication string is retained in evidence, never guessed as UTC.
    publication = datetime.fromisoformat(published) if published else None
    if publication:
        require(publication <= timezone.now(), 'future_video_publication')
    products = value.get('products')
    require(products is None or isinstance(products, list), 'invalid_video_products')
    parsed_products = {}
    for p in products or []:
        require(isinstance(p, dict), 'invalid_video_product')
        pid = text(str(p.get('id') or ''))
        require(pid.isascii() and pid.isdecimal() and int(pid) > 0, 'invalid_video_product_id')
        name = text(p.get('name') or '', 8192)[:240]
        require(pid not in parsed_products or parsed_products[pid] == name, 'conflicting_video_product')
        parsed_products[pid] = name
    return {'id':vid, 'identity':{
        'creator_open_id':text(creator.get('open_id') or ''),
        'creator_username':text(creator.get('user_name') or value.get('username') or ''),
        'title':text(value.get('title') or '',8192), 'published_at':publication},
        'metrics':metrics, 'products':parsed_products, 'publication_unknown':bool(raw_time)}


def resolve(actor, store_id):
    auths, _ = resolve_export_scope(actor, [store_id], 0)
    auth = auths[0]
    require(auth.store.status=='active','video_store_disabled')
    from .tiktok_dataset_import import _scope_matches_store
    require(check_user_permission(actor,'influencers.manage') and _scope_matches_store(actor,auth.store),
            'video_write_scope_denied')
    require(auth.expires_at is not None and auth.expires_at > timezone.now(), 'video_authorization_expired')
    require(bool(auth.platform_store_id and auth.shop_cipher), 'video_binding_missing')
    require('data.shop_analytics.public.read' in (auth.scopes or []), 'video_scope_missing')
    require(auth.store.currency and len(auth.store.currency) == 3, 'video_currency_missing')
    require(bool(auth.store.timezone), 'video_timezone_missing')
    ZoneInfo(auth.store.timezone)
    TikTokDatasetClient(auth.integration_config, auth).preflight()
    return auth


def fingerprint(auth):
    c = auth.integration_config
    return digest({'auth_id':auth.pk,'updated':str(auth.updated_at),'shop':auth.platform_store_id,
        'config_id':c.pk,'config_updated':str(c.updated_at), 'timezone':auth.store.timezone,
        'currency':auth.store.currency,'runtime':get_runtime_platform_config('tiktok')})


def receipt(batch, page, payload):
    TikTokVideoSyncEvidence.objects.create(tenant_id=batch.tenant_id, batch=batch,
        attempt=batch.attempt_count,page=page,payload=payload,payload_hash=digest(payload))


def lock_sources(auth):
    lock_runtime_approval()
    PlatformIntegrationConfig.objects.select_for_update().get(pk=auth.integration_config_id)
    StoreMaster.objects.select_for_update().get(pk=auth.store_id)
    MarketplaceStoreAuthorization.objects.select_for_update().get(pk=auth.pk)


def metric_snapshot(metric):
    return {k:None if getattr(metric,k) is None else
            format(getattr(metric,k),'.4f') if k in MONEY or k in RATES or k in ('reported_ctor','click_to_order_rate') else str(getattr(metric,k))
            for k in METRICS}


def run_day(actor, store_id, day, *, apply=False, refresh=False, client_factory=TikTokDatasetClient):
    auth = resolve(actor, store_id)
    frozen = fingerprint(auth)
    today = timezone.now().astimezone(ZoneInfo(auth.store.timezone)).date()
    require(today-timedelta(days=30) <= day < today, 'video_day_outside_last_30_complete_days')
    token, batch = secrets.token_hex(24), None
    if apply:
        with transaction.atomic():
            Tenant.objects.select_for_update().get(pk=actor.tenant_id)
            batch, _ = TikTokVideoSyncBatch.objects.select_for_update().get_or_create(
                tenant_id=actor.tenant_id,store_id=store_id,window_start=day,window_end=day+timedelta(days=1),
                api_version=VERSION,defaults={'idempotency_key':f'{VERSION}:{day}', 'max_attempts':365})
            if batch.status == 'completed' and not refresh:
                return {'store_id':store_id,'date':str(day),'status':'already_completed','batch_id':batch.pk}
            require(not batch.lease_expires_at or batch.lease_expires_at <= timezone.now(), 'video_batch_busy')
            require(batch.attempt_count < batch.max_attempts, 'video_attempts_exhausted')
            now = timezone.now()
            batch.status='running'; batch.lease_token=token
            batch.lease_expires_at=now+timedelta(minutes=10); batch.heartbeat_at=now
            batch.started_at=now; batch.completed_at=None; batch.error_summary=''
            batch.attempt_count += 1; batch.save()

    def guard():
        # The caller's in-memory user may outlive a permission/deactivation
        # change while provider requests are in flight. Re-read it at every
        # guard so DB-backed status and grants are authoritative.
        current_actor = actor.__class__._default_manager.get(pk=actor.pk)
        current = resolve(current_actor,store_id)
        require(fingerprint(current) == frozen, 'video_binding_or_approval_changed')
        if batch:
            now = timezone.now()
            with transaction.atomic():
                live=TikTokVideoSyncBatch.objects.select_for_update().get(pk=batch.pk,tenant_id=actor.tenant_id)
                require(live.status=='running' and live.lease_token==token and live.lease_expires_at>now,'video_lease_lost')
                live.heartbeat_at=now;live.lease_expires_at=now+timedelta(minutes=10)
                live.save(update_fields=['heartbeat_at','lease_expires_at','updated_at'])
        return current

    try:
        client=client_factory(auth.integration_config,auth)
        guard(); client.verify_shop()
        pages, rows, seen, tokens, cursor, total = [], [], set(), set(), '', None
        latest=None
        for page in range(1,101):
            guard()
            params={'shop_cipher':auth.shop_cipher,'start_date_ge':str(day),
                'end_date_lt':str(day+timedelta(days=1)),'currency':'LOCAL','page_size':50}
            if cursor: params['page_token']=cursor
            data=client._request(PATH,query=params)['data']
            values=validate_video_page(data)
            advertised = data.get('latest_available_date')
            require(isinstance(advertised,str),'video_latest_date_missing')
            latest=date.fromisoformat(advertised)
            require(latest>=day,'video_data_not_yet_available')
            count=number(data.get('total_count'),integer=True)
            require(count is not None and (total is None or total==count),'video_total_changed')
            total=count
            for v in values:
                row=project(v,auth.store.currency)
                require(row['id'] not in seen,'video_duplicate_page_row')
                seen.add(row['id']);rows.append(row)
            next_cursor=text(data.get('next_page_token') or '',4096)
            require(not next_cursor or (values and next_cursor not in tokens),'video_cursor_not_advancing')
            payload={'schema':'tk-video-page-v1','date':str(day),'timezone':auth.store.timezone,
                'currency':auth.store.currency,'platform_store_id':auth.platform_store_id,
                'endpoint':PATH,'latest_available_date':str(latest),'total_count':total,'videos':values,
                'has_next':bool(next_cursor),'observed_at':timezone.now().isoformat()}
            pages.append(payload)
            if batch:
                guard(); receipt(batch,page,payload)
            if not next_cursor: break
            tokens.add(next_cursor);cursor=next_cursor
        else:
            raise DatasetError('video_page_limit_exceeded')
        require(total==len(rows),'video_total_mismatch')
        totals={field:str(sum((r['metrics'][field] for r in rows if r['metrics'][field] is not None),Decimal(0)))
                for field in ('reported_gmv','attributed_gmv','views','sku_orders')}
        known={field:sum(r['metrics'][field] is not None for r in rows) for field in totals}
        result={'store_id':store_id,'date':str(day),'rows':len(rows),'pages':len(pages),
                'currency':auth.store.currency,'totals':totals,'known_counts':known,'status':'dry_run',
                'fulfillment_updated':0}
        if not apply: return result
        guard()
        with transaction.atomic():
            Tenant.objects.select_for_update().get(pk=actor.tenant_id)
            # Lock the actual authorization as well as the batch; revocation cannot race the commit.
            lock_sources(auth)
            locked=TikTokVideoSyncBatch.objects.select_for_update().get(pk=batch.pk)
            require(locked.lease_token==token and locked.lease_expires_at>timezone.now(),'video_lease_lost')
            guard()
            existing_ids=set(TikTokVideoDailyMetric.objects.filter(tenant_id=actor.tenant_id,
                store_id=store_id,metric_date=day).values_list('video__external_video_id',flat=True))
            require(existing_ids.issubset(seen),'video_previously_observed_rows_missing')
            expected, changes = {}, []
            now=timezone.now()
            for row in rows:
                video,created=TikTokShopVideo.objects.get_or_create(tenant_id=actor.tenant_id,store_id=store_id,
                    external_video_id=row['id'],defaults={'video_type':'unknown','source_api':PATH,
                        'first_seen_at':now,'last_seen_at':now})
                identity=row['identity']
                require(not video.creator_open_id or not identity['creator_open_id'] or
                    video.creator_open_id==identity['creator_open_id'],'video_creator_identity_conflict')
                for k,v in identity.items():
                    if v not in (None,''): setattr(video,k,v)
                video.last_seen_at=now;video.save()
                for pid,name in row['products'].items():
                    product,_=TikTokVideoProduct.objects.get_or_create(tenant_id=actor.tenant_id,
                        video=video,external_product_id=pid,defaults={'source':'api','confidence':Decimal('1'),
                        'parse_status':'parsed','name':name,'first_seen_at':now,'last_seen_at':now})
                    if product.source=='api':
                        product.name=name;product.last_seen_at=now;product.save()
                metric=TikTokVideoDailyMetric.objects.filter(tenant_id=actor.tenant_id,video=video,metric_date=day).first()
                require(not metric or metric.currency==auth.store.currency,'video_existing_currency_conflict')
                before=metric_snapshot(metric) if metric else None
                if metric is None:
                    metric=TikTokVideoDailyMetric(tenant_id=actor.tenant_id,store_id=store_id,video=video,
                        batch=batch,metric_date=day,currency=auth.store.currency)
                for k,v in row['metrics'].items():
                    if v is not None: setattr(metric,k,v)
                effective=metric_snapshot(metric)
                metric.row_hash=digest(effective)
                metric.quality_status='degraded' if any(v is None for v in effective.values()) else 'passed'
                metric.diagnosis='Unknown metrics retained as NULL; publication/creator attribution not inferred.'
                if before!=effective:
                    metric.batch=batch;metric.save()
                    changes.append({'video_id':row['id'],'before':before,'after':effective})
                expected[video.pk]=effective
            actual={m.video_id:metric_snapshot(m)
                for m in TikTokVideoDailyMetric.objects.filter(tenant_id=actor.tenant_id,store_id=store_id,
                    metric_date=day,video_id__in=expected)}
            require(actual==expected,'video_database_readback_mismatch')
            receipt(batch,0,{'schema':'tk-video-commit-v1','api_totals':totals,'known_counts':known,
                'rows':len(rows),'changed_rows':changes,'binding_fingerprint':frozen,'actor_id':actor.pk,
                'database_verified':True,'fulfillment_updated':0})
            locked.status='completed';locked.completed_at=now;locked.video_count=len(rows)
            locked.page_count=len(pages);locked.latest_available_date=latest;locked.lease_token=''
            locked.lease_expires_at=None;locked.request_cursor='';locked.save()
        return dict(result,status='completed',batch_id=batch.pk,changed=len(changes),database_verified=True)
    except Exception as exc:
        if batch:
            code=str(exc) if isinstance(exc,DatasetError) else type(exc).__name__
            with transaction.atomic():
                live=TikTokVideoSyncBatch.objects.select_for_update().get(pk=batch.pk)
                if live.lease_token==token:
                    live.status='failed';live.error_summary=code[:160];live.completed_at=timezone.now()
                    live.lease_token='';live.lease_expires_at=None;live.save()
        raise
