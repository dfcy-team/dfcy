"""Bounded creator-marketplace lookup and guarded draft-only identity enrichment.

Run via manage.py shell. MODE=collect reads business SQL; MODE=apply reuses the
frozen observations without repeating provider calls. No automatic merges.
"""
import hashlib
import json
import os
from pathlib import Path
import time

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from apps.audit.services import write_operation_log
from apps.tenants.models import Tenant
from apps.integrations.models import MarketplaceStoreAuthorization
from apps.integrations.readonly_clients import TikTokReadonlyClient
from apps.influencers.tiktok_creator_lookup import available_tiktok_lookup_stores
from apps.influencers.models import (
    Influencer, InfluencerProfile, InfluencerPlatformAccount,
    InfluencerRestriction, SampleFulfillment, normalize_tiktok_username,
    is_valid_tiktok_username,
)

ROOT = Path('/tmp/creator-draft-audit-20261105' + os.environ.get('DRAFT_CREATOR_RUN', ''))
MODE = os.environ.get('DRAFT_CREATOR_MODE', 'collect')
actor = get_user_model().objects.get(pk=1, tenant_id=1, is_active=True, is_superuser=True)


def conflict(influencer_id, username):
    return (Influencer.objects.filter(tenant_id=1, platform__iexact='tiktok', handle__iexact=username).exclude(pk=influencer_id).exists()
            or InfluencerPlatformAccount.objects.filter(tenant_id=1, platform='tiktok', handle__iexact=username).exclude(influencer_id=influencer_id).exists())


def blocked(row):
    return (InfluencerPlatformAccount.objects.filter(tenant_id=1, influencer_id=row['id']).exists()
            or InfluencerRestriction.objects.filter(tenant_id=1, influencer_id=row['id'], is_blacklisted=True).exists())


if MODE == 'collect':
    resume = os.environ.get('DRAFT_CREATOR_RESUME') == '1'
    ROOT.mkdir(mode=0o700, exist_ok=resume)
    results = json.loads((ROOT / 'plan.json').read_text()) if resume else []
    quarantined = {int(value) for value in os.environ.get('DRAFT_CREATOR_EXCLUDE_STORES', '').split(',') if value}
    for previous in results:
        if previous['status_reason'] == 'query_blocked':
            quarantined.update(SampleFulfillment.objects.filter(tenant_id=1,influencer_id=previous['id']).values_list('store_id',flat=True))
    completed_ids = {r['id'] for r in results}
    query_failures = 0
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION READ ONLY')
        allowed = {s['id'] for s in available_tiktok_lookup_stores(actor)}
        rows = list(Influencer.objects.filter(tenant_id=1, platform__iexact='tiktok', code__startswith='draft-', handle='')
                    .filter(Q(profile__external_influencer_id='') | Q(profile__external_influencer_id__isnull=True))
                    .order_by('id').values('id', 'name', 'code', 'status', 'updated_at'))
        assert len(rows) <= 200, 'Unexpected draft count; scope review required'
        rows.sort(key=lambda row: (row['name'] != 'anne_landicho', row['id']))
    for row in rows:
        if row['id'] in completed_ids:
            continue
        auth = None
        r = {**row, 'updated_at': row['updated_at'].isoformat(), 'checked_at': timezone.now().isoformat()}
        username = normalize_tiktok_username(row['name'])
        try:
            if not is_valid_tiktok_username(username):
                r['status_reason'] = 'not_a_username'
            elif conflict(row['id'], username):
                r['status_reason'] = 'existing_identity_conflict'
            elif blocked(row):
                r['status_reason'] = 'registered_or_blacklisted'
            else:
                auths = list(MarketplaceStoreAuthorization.objects.select_related('store', 'integration_config').filter(
                    tenant_id=1, platform='tiktok', status='active', store_id__in=allowed
                ).filter(store_id__in=SampleFulfillment.objects.filter(tenant_id=1, influencer_id=row['id']).values('store_id')).order_by('store_id'))
                regions = {a.region.upper() for a in auths}
                if len(regions) != 1:
                    r['status_reason'] = 'missing_or_ambiguous_authorized_country'
                elif auths[0].store_id in quarantined:
                    r['status_reason'] = 'store_query_quarantined'
                elif query_failures >= 3:
                    r['status_reason'] = 'query_deferred_after_errors'
                else:
                    auth = auths[0]
                    r.update(store_id=auth.store_id, store_code=auth.store.code, region=auth.region)
                    assert 'seller.creator_marketplace.read' in (auth.scopes or [])
                    client = TikTokReadonlyClient(auth.integration_config, auth)
                    client.resource_type = 'affiliate_creator_profile'
                    payload = client._request('/affiliate_seller/202608/marketplace_creators/search', method='POST',
                        query={'shop_cipher': auth.shop_cipher, 'page_size': 12},
                        body={'keyword': username, 'data_groups': ['BASIC_CREATOR_INFORMATION']})
                    data = payload.get('data') or {}
                    creators = data.get('creators')
                    assert isinstance(creators, list), 'Unexpected creator envelope'
                    exact = [c for c in creators if normalize_tiktok_username(c.get('username')) == username]
                    r.update(store_id=auth.store_id, store_code=auth.store.code, region=auth.region,
                             more_results=bool(data.get('next_page_token')))
                    if len(exact) != 1:
                        r['status_reason'] = 'not_found_first_page' if not exact else 'ambiguous_exact_match'
                    else:
                        c = exact[0]
                        followers = c.get('follower_count')
                        nickname = c.get('nickname') or ''
                        if (str(c.get('selection_region') or '').upper() != auth.region.upper()
                                or type(followers) is not int or not 0 <= followers <= 2**63-1
                                or not isinstance(nickname, str) or len(nickname) > 160):
                            r['status_reason'] = 'invalid_or_cross_country_result'
                        else:
                            # This search may omit a numeric creator ID. Do not invent one
                            # or copy an opaque open ID into the numeric-ID field.
                            r.update(status_reason='ready', username=c['username'], nickname=nickname,
                                     follower_count=followers, response_keys=sorted(c))
                    time.sleep(0.5)
        except Exception as exc:
            r.update(status_reason='query_blocked', error_type=type(exc).__name__,
                     error_code=str(getattr(exc, 'controlled_code', ''))[:80],
                     platform_error_code=str(getattr(exc, 'platform_error_code', ''))[:80])
            query_failures += 1
            if getattr(exc, 'controlled_code', '') == 'OAUTH_RATE_LIMITED':
                query_failures = 3
            if auth is not None:
                quarantined.add(auth.store_id)
        results.append(r)
        with (ROOT / 'observations.jsonl').open('a') as f:
            f.write(json.dumps(r) + '\n')
        print(json.dumps({'id': row['id'], 'name': row['name'], 'result': r['status_reason']}), flush=True)
    (ROOT / 'plan.json').write_text(json.dumps(results))
    print(json.dumps({'collected': len(results), 'total': len(rows), 'ready': sum(r['status_reason']=='ready' for r in results)}), flush=True)
elif MODE == 'apply':
    plan = json.loads((ROOT / 'plan.json').read_text())
    assert not (ROOT / 'applied.jsonl').exists(), 'Do not replay; inspect audit receipts first'
    for r in plan:
        if r['status_reason'] != 'ready':
            continue
        outcome = {'id': r['id'], 'username': r['username']}
        try:
            assert (timezone.now()-timezone.datetime.fromisoformat(r['checked_at'])).total_seconds() < 86400
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('SET innodb_lock_wait_timeout = 3')
                Tenant.objects.select_for_update().get(pk=1)
                current = Influencer.objects.select_for_update().get(pk=r['id'], tenant_id=1)
                assert current.updated_at.isoformat() == r['updated_at'] and current.name == r['name']
                assert current.code == r['code'] and current.handle == '' and current.status == r['status']
                assert not blocked(r) and not conflict(current.pk, r['username'])
                profile = InfluencerProfile.objects.select_for_update().filter(tenant_id=1, influencer=current).first()
                assert not profile or not profile.external_influencer_id
                assert any(s['id'] == r['store_id'] for s in available_tiktok_lookup_stores(actor))
                before = {'handle': current.handle, 'follower_count': current.follower_count,
                          'display_name': profile.display_name if profile else None}
                # Backup only the fields we actually change, with no credentials.
                with (ROOT / 'before.jsonl').open('a') as f:
                    f.write(json.dumps({'id':current.pk, **before})+'\n')
                current.handle = r['username']
                current.follower_count = r['follower_count']
                current.save(update_fields=['handle', 'follower_count', 'updated_at'])
                if profile is None:
                    profile = InfluencerProfile(tenant_id=1, influencer=current)
                if not profile.display_name:
                    profile.display_name = r['nickname']
                    profile.save()
                audit = write_operation_log(tenant=actor.tenant,user=actor,module='influencers',
                    action='creator_draft_exact_api_enrichment',object_type='influencer',object_id=current.pk,
                    before_data=before,after_data={'handle':current.handle,'nickname':r['nickname'],
                        'follower_count':current.follower_count,'store_id':r['store_id'],
                        'selection_region':r['region'],'observed_at':r['checked_at'],
                        'numeric_id_missing':True,'source':'creator_marketplace_search_202608'})
                outcome.update(result='applied',audit_id=audit.pk)
        except Exception as exc:
            outcome.update(result='not_applied',error_type=type(exc).__name__)
        with (ROOT / 'applied.jsonl').open('a') as f:
            f.write(json.dumps(outcome)+'\n')
        print(json.dumps(outcome),flush=True)
        time.sleep(0.1)
else:
    raise ValueError('Unsupported mode')
