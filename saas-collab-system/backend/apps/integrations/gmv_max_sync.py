"""Single-day GMV Max evidence ingestion, separate from BASIC spend and reports."""
import hashlib
import json
import re
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError, PermissionDenied
from apps.permissions.services import user_has_integration_permission

from . import tiktok_ads_pilot as pilot
from .ads_subject import mapping_allowed
from .ads_sync import validate_mapping, snapshot, lock_runtime_approval
from .models import (TikTokAdsAdvertiserMapping, MarketplaceStoreAuthorization,
                     SharedAdvertisingRawPayload, IntegrationAuditLog, TikTokAdsSyncLease)
from .tiktok_ads_oauth import account_timezone

STORE_PATH = '/open_api/v1.3/gmv_max/store/list/'
REPORT_PATH = '/open_api/v1.3/gmv_max/report/get/'
PAGE_SIZE = 100


def decimal_value(value):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ValidationError('GMV Max metric is unknown or not an exact decimal.')
    if not re.fullmatch(r'\d{1,14}(?:\.\d{1,6})?', str(value)):
        raise ValidationError('GMV Max metric is missing, negative or outside precision.')
    return Decimal(str(value))


def summarize(pages):
    ids, cost, revenue, orders = set(), Decimal(0), Decimal(0), 0
    expected = None
    if not pages or len(pages) > 100:
        raise ValidationError('GMV Max report pages are absent or exceed the bound.')
    for number, data in enumerate(pages, 1):
        info, rows = data.get('page_info'), data.get('list')
        if not isinstance(info, dict) or not isinstance(rows, list):
            raise ValidationError('GMV Max report structure is invalid.')
        if any(type(info.get(k)) is not int for k in ('page','page_size','total_page','total_number')):
            raise ValidationError('GMV Max pagination requires integer evidence.')
        count, total_pages = info['total_number'], info['total_page']
        if (count < 0 or total_pages != max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)
                or info['page'] != number or info['page_size'] != PAGE_SIZE
                or total_pages != len(pages) or expected not in (None, count)
                or len(rows) != min(PAGE_SIZE, count - (number - 1) * PAGE_SIZE)):
            raise ValidationError('GMV Max pagination is incomplete or changed.')
        expected = count
        for row in rows:
            dims, metrics = row.get('dimensions', {}), row.get('metrics', {})
            campaign = dims.get('campaign_id')
            if not isinstance(campaign, str) or not campaign.isdigit() or campaign in ids:
                raise ValidationError('GMV Max campaign identity is missing or duplicated.')
            ids.add(campaign)
            cost += decimal_value(metrics.get('cost'))
            revenue += decimal_value(metrics.get('gross_revenue'))
            n = decimal_value(metrics.get('orders'))
            if n != n.to_integral_value():
                raise ValidationError('GMV Max order count is not integral.')
            orders += int(n)
    if not ids:
        raise ValidationError('Empty GMV Max report is not evidence of zero spend.')
    return {'campaign_count': len(ids), 'cost': str(cost),
            'gross_revenue': str(revenue), 'orders': orders}


def shop_authorization(mapping, *, lock=False):
    q = MarketplaceStoreAuthorization.objects
    if lock:
        q = q.select_for_update()
    rows = list(q.filter(tenant_id=mapping.tenant_id, store_id=mapping.store_id,
        platform='tiktok', status='active', revoked_at__isnull=True))
    if len(rows) != 1 or not rows[0].platform_store_id:
        raise ValidationError('GMV Max requires one active real Shop identity.')
    if rows[0].expires_at and rows[0].expires_at <= timezone.now():
        raise ValidationError('Shop authorization has expired.')
    return rows[0]


def run_day(*, actor, mapping_id, day, commit=False):
    def load(lock=False):
        q = TikTokAdsAdvertiserMapping.objects
        if lock:
            q = q.select_for_update()
        m = q.select_related('store__platform','integration_config','tenant').get(
            pk=mapping_id, tenant_id=actor.tenant_id)
        if (not user_has_integration_permission(actor, 'integrations.store.authorize')
                or not mapping_allowed(actor, m, 'integrations.store.authorize')):
            raise PermissionDenied('Ads mapping is outside the actor permission scope.')
        return m
    actor.refresh_from_db()
    mapping = load()
    evidence = validate_mapping(mapping)
    frozen = snapshot(mapping, evidence)
    auth = shop_authorization(mapping)
    shop_identity = (auth.pk, auth.platform_store_id, auth.updated_at)
    today = timezone.now().astimezone(ZoneInfo(mapping.timezone)).date()
    if not isinstance(day, date) or not today - timedelta(days=30) <= day < today:
        raise ValidationError('Use one completed advertiser-local day in the last 30 days.')
    lease = pilot._claim_lease(mapping.tenant_id)
    try:
        token = pilot.get_custody_backend().retrieve_access_token(mapping.token_id)
        http = pilot.PlatformHttpClient()
        def guard():
            actor.refresh_from_db()
            current = load()
            if snapshot(current, validate_mapping(current)) != frozen:
                raise ValidationError('Ads approvals or mapping changed.')
            a = shop_authorization(current)
            if (a.pk, a.platform_store_id, a.updated_at) != shop_identity:
                raise ValidationError('Shop binding changed.')
            pilot._renew_lease(mapping.tenant_id, *lease)
        def get(path, params):
            guard()
            response = http.request('GET', pilot.HOST + path + '?' + urlencode(params),
                headers={'Access-Token':token}, retry=False, connect_timeout=5,
                read_timeout=15, diagnostic_platform='tiktok_ads')
            p = response.json()
            if response.status_code != 200 or p.get('code') not in (0, '0') or not isinstance(p.get('data'), dict):
                raise ValidationError('GMV Max official read rejected; no data committed.')
            return p['data']
        accounts = get(pilot.INFO_PATH, {'advertiser_ids':json.dumps([mapping.advertiser_id])}).get('list', [])
        if (len(accounts) != 1 or str(accounts[0].get('advertiser_id')) != mapping.advertiser_id
                or accounts[0].get('currency') != mapping.currency
                or account_timezone(accounts[0]) != mapping.timezone):
            raise ValidationError('Advertiser identity/currency/timezone mismatch.')
        stores = get(STORE_PATH, {'advertiser_id':mapping.advertiser_id}).get('store_list', [])
        matches = [s for s in stores if str(s.get('store_id')) == auth.platform_store_id]
        if (len(matches) != 1 or matches[0].get('is_gmv_max_available') is not True
                or str((matches[0].get('exclusive_authorized_advertiser_info') or {}).get('advertiser_id')) != mapping.advertiser_id):
            raise ValidationError('GMV Max store identity/exclusive advertiser is not verified.')
        pages = []
        for page in range(1, 101):
            data = get(REPORT_PATH, {'advertiser_id':mapping.advertiser_id,
                'store_ids':json.dumps([auth.platform_store_id]), 'dimensions':json.dumps(['campaign_id']),
                'metrics':json.dumps(['cost','orders','gross_revenue','roi']),
                'start_date':day.isoformat(), 'end_date':day.isoformat(), 'page':page, 'page_size':PAGE_SIZE})
            pages.append(data)
            total = (data.get('page_info') or {}).get('total_page')
            if type(total) is not int or not 1 <= total <= 100:
                raise ValidationError('GMV Max page total is invalid.')
            if page >= total:
                break
        totals = summarize(pages)
        payload = {'schema':'gmv-max-day-v1', 'advertiser_id':mapping.advertiser_id,
            'platform_store_id':auth.platform_store_id, 'date':day.isoformat(),
            'currency':mapping.currency, 'timezone':mapping.timezone,
            'report_scope':'GMV_MAX_CAMPAIGN', 'store_evidence':matches[0], 'pages':pages}
        content_hash = hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        result = {**totals,'date':day.isoformat(),'currency':mapping.currency,
            'timezone':mapping.timezone,'advertiser_id':mapping.advertiser_id,
            'platform_store_id':auth.platform_store_id,'payload_hash':content_hash,
            'committed':False,'storage':'verified_raw_snapshot','report_refreshed':False}
        if commit:
            guard()
            with transaction.atomic():
                locked_lease = TikTokAdsSyncLease.objects.select_for_update().get(tenant_id=mapping.tenant_id)
                if ((locked_lease.owner_token,locked_lease.generation) != lease
                        or locked_lease.lease_expires_at <= timezone.now()):
                    raise ValidationError('Ads lease lost before commit.')
                lock_runtime_approval()
                current = load(lock=True)
                if snapshot(current,validate_mapping(current,lock=True)) != frozen:
                    raise ValidationError('Ads approval changed before commit.')
                a = shop_authorization(current,lock=True)
                if (a.pk,a.platform_store_id,a.updated_at) != shop_identity:
                    raise ValidationError('Shop identity changed before commit.')
                row, created = SharedAdvertisingRawPayload.objects.get_or_create(
                    tenant_id=mapping.tenant_id,store_id=mapping.store_id,platform='tiktok',
                    endpoint=REPORT_PATH,payload_hash=content_hash,defaults={'payload':payload})
                if row.payload != payload or summarize(row.payload['pages']) != totals:
                    raise ValidationError('GMV Max database readback differs from API evidence.')
                audit = IntegrationAuditLog.objects.create(tenant_id=mapping.tenant_id,
                    integration_config_id=mapping.integration_config_id,actor=actor,
                    action='ads_gmv_max_day',result='success',masked_detail={**result,
                        'committed':True,'raw_payload_id':row.pk,'created':created,'mapping_id':mapping.pk})
                result.update(committed=True,raw_payload_id=row.pk,created=created,audit_id=audit.pk)
        return result
    finally:
        pilot._release_lease(mapping.tenant_id,*lease)
