"""One finite, slow, resumable-by-receipt batch; never a recurring task.

User-approved profile enrichment only. Stop the whole batch on the first API
failure. Missing numeric IDs remain missing; open IDs are audit evidence only.
"""
from collections import Counter
import json
import os
from pathlib import Path
import time

from django.contrib.auth import get_user_model
from django.db import transaction,connection
from django.db.models import Q
from django.utils import timezone
from apps.audit.services import write_operation_log
from apps.tenants.models import Tenant
from apps.influencers.models import Influencer,InfluencerProfile,InfluencerPlatformAccount,InfluencerRestriction,SampleFulfillment,normalize_tiktok_username,is_valid_tiktok_username
from apps.influencers.tiktok_creator_lookup import available_tiktok_lookup_stores
from apps.integrations.models import MarketplaceStoreAuthorization
from apps.integrations.readonly_clients import TikTokReadonlyClient

os.umask(0o077)
ROOT=Path('/tmp/creator-details-batch-20261105-1400')
ROOT.mkdir(mode=0o700,exist_ok=False)
actor=get_user_model().objects.get(pk=1,tenant_id=1,is_active=True,is_superuser=True)
with transaction.atomic():
    with connection.cursor() as c:c.execute('SET TRANSACTION READ ONLY')
    allowed={s['id'] for s in available_tiktok_lookup_stores(actor)}
    rows=list(Influencer.objects.filter(tenant_id=1,platform__iexact='tiktok',is_deleted=False)
        .filter(Q(profile__external_influencer_id='')|Q(profile__external_influencer_id__isnull=True))
        .values('id','name','handle','status','code','updated_at').order_by('id'))
    assert len(rows)<=1000,'Unexpected scope growth'
    for r in rows:r['updated_at']=r['updated_at'].isoformat()
    (ROOT/'plan.json').write_text(json.dumps(rows))
counts=Counter();queries=0;stopped=False

def receipt(result):
    counts[result['result']]+=1
    with (ROOT/'results.jsonl').open('a') as f:f.write(json.dumps(result)+'\n')
    (ROOT/'progress.json').write_text(json.dumps({'total':len(rows),'processed':sum(counts.values()),'queries':queries,'counts':dict(counts),'stopped':stopped,'updated_at':timezone.now().isoformat()}))
    print(json.dumps(result),flush=True)

for r in rows:
    out={'id':r['id'],'name':r['name']}
    name=normalize_tiktok_username(r['handle'] or r['name'])
    if not is_valid_tiktok_username(name):
        receipt({**out,'result':'not_a_username'});continue
    if not r['handle']:
        if not r['code'].startswith('draft-'):
            receipt({**out,'result':'unconfirmed_name'});continue
        occupied=(Influencer.objects.filter(tenant_id=1,platform__iexact='tiktok',handle__iexact=name).exclude(pk=r['id']).exists()
            or InfluencerPlatformAccount.objects.filter(tenant_id=1,platform='tiktok',handle__iexact=name).exclude(influencer_id=r['id']).exists())
        if occupied or InfluencerPlatformAccount.objects.filter(tenant_id=1,influencer_id=r['id']).exists():
            receipt({**out,'result':'identity_conflict'});continue
    if InfluencerRestriction.objects.filter(tenant_id=1,influencer_id=r['id'],is_blacklisted=True).exists():
        receipt({**out,'result':'blacklisted_preserved'});continue
    auths=list(MarketplaceStoreAuthorization.objects.select_related('store','integration_config').filter(
        tenant_id=1,platform='tiktok',status='active',store_id__in=allowed).filter(
        store_id__in=SampleFulfillment.objects.filter(tenant_id=1,influencer_id=r['id']).values('store_id')).order_by('store_id'))
    if not auths or len({a.region.upper() for a in auths})!=1:
        receipt({**out,'result':'no_unique_authorized_country'});continue
    auth=auths[0];out.update(username=name,store_id=auth.store_id,store_code=auth.store.code)
    if queries:time.sleep(6)
    try:
        # Native preflight and scope checks remain effective; no alternate token
        # or shop is tried on errors or rate limits.
        assert 'seller.creator_marketplace.read' in (auth.scopes or [])
        assert auth.store_id in {s['id'] for s in available_tiktok_lookup_stores(actor)}
        client=TikTokReadonlyClient(auth.integration_config,auth);client.resource_type='affiliate_creator_profile'
        queries+=1
        payload=client._request('/affiliate_seller/202608/marketplace_creators/search',method='POST',
            query={'shop_cipher':auth.shop_cipher,'page_size':12},body={'keyword':name,'data_groups':['BASIC_CREATOR_INFORMATION']})
        data=payload.get('data') or {};candidates=data.get('creators');assert isinstance(candidates,list)
        exact=[c for c in candidates if normalize_tiktok_username(c.get('username'))==name]
        if len(exact)!=1:
            receipt({**out,'result':'not_unique_on_first_page','matches':len(exact),'more':bool(data.get('next_page_token'))});continue
        creator=exact[0];followers=creator.get('follower_count');nickname=creator.get('nickname') or ''
        assert str(creator.get('selection_region') or '').upper()==auth.region.upper()
        assert type(followers) is int and 0<=followers<=2**63-1
        assert isinstance(nickname,str) and len(nickname)<=160
        open_id=creator.get('creator_open_id') or ''
        assert isinstance(open_id,str) and len(open_id)<=160
        observed=timezone.now().isoformat()
    except Exception as exc:
        stopped=True
        receipt({**out,'result':'api_blocked','type':type(exc).__name__,'code':getattr(exc,'controlled_code',''),
                 'platform_code':getattr(exc,'platform_error_code','')})
        break
    try:
        with transaction.atomic():
            with connection.cursor() as c:c.execute('SET innodb_lock_wait_timeout=3')
            Tenant.objects.select_for_update().get(pk=1)
            obj=Influencer.objects.select_for_update().get(pk=r['id'],tenant_id=1,is_deleted=False)
            assert obj.updated_at.isoformat()==r['updated_at'] and obj.handle==r['handle'] and obj.name==r['name'] and obj.status==r['status']
            assert not InfluencerRestriction.objects.filter(tenant_id=1,influencer=obj,is_blacklisted=True).exists()
            assert auth.store_id in {s['id'] for s in available_tiktok_lookup_stores(actor)}
            profile=InfluencerProfile.objects.select_for_update().filter(tenant_id=1,influencer=obj).first()
            assert not profile or not profile.external_influencer_id
            before={'handle':obj.handle,'follower_count':obj.follower_count,'display_name':profile.display_name if profile else None}
            with (ROOT/'before.jsonl').open('a') as f:f.write(json.dumps({'id':obj.pk,**before})+'\n')
            if not obj.handle:
                assert not Influencer.objects.filter(tenant_id=1,platform__iexact='tiktok',handle__iexact=name).exclude(pk=obj.pk).exists()
                assert not InfluencerPlatformAccount.objects.filter(tenant_id=1,platform='tiktok',handle__iexact=name).exclude(influencer_id=obj.pk).exists()
                obj.handle=creator['username']
            obj.follower_count=followers;obj.save(update_fields=['handle','follower_count','updated_at'])
            if profile is None:profile=InfluencerProfile(tenant_id=1,influencer=obj)
            if not profile.display_name:
                profile.display_name=nickname;profile.save()
            audit=write_operation_log(tenant=actor.tenant,user=actor,module='influencers',action='creator_details_exact_api_enrichment',
                object_type='influencer',object_id=obj.pk,before_data=before,
                after_data={'handle':obj.handle,'display_name':profile.display_name,'follower_count':followers,'creator_open_id':open_id,
                    'numeric_id_missing':True,'store_id':auth.store_id,'region':auth.region,'observed_at':observed,'source':'creator_marketplace_search_202608'})
            out.update(result='applied',audit_id=audit.pk,numeric_id_filled=False)
    except Exception as exc:
        out.update(result='not_applied',type=type(exc).__name__)
    receipt(out)
print(json.dumps({'total':len(rows),'processed':sum(counts.values()),'queries':queries,'counts':dict(counts),'stopped':stopped,'receipt':str(ROOT)}),flush=True)
