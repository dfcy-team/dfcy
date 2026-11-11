"""Read-only post-deployment verification, no real archive deletions."""
import json
from django.contrib.auth import get_user_model
from django.db import connection,transaction
from django.urls import resolve
from rest_framework.test import APIRequestFactory,force_authenticate
from apps.influencers.models import InfluencerPlatformAccount
from apps.influencers.views import InfluencerCollectionView,SampleFulfillmentCollectionView,InfluencerArchiveDeletionView

with transaction.atomic():
    with connection.cursor() as cursor:cursor.execute('SET TRANSACTION READ ONLY')
    actor=get_user_model().objects.get(pk=1,tenant_id=1)
    assert 'shopee' in InfluencerPlatformAccount.Platform.values
    assert resolve('/api/internal/influencers/26030/archive-deletion/').func.view_class is InfluencerArchiveDeletionView
    checks=[]
    for view,params in [(InfluencerCollectionView,{'include_nickname_id':'true'}),
                        (InfluencerCollectionView,{'deleted_only':'true'}),
                        (InfluencerCollectionView,{'platform':'shopee'}),
                        (SampleFulfillmentCollectionView,{'created_from':'2026-11-01','created_to':'2026-11-04'})]:
        req=APIRequestFactory().get('/api/internal/influencers/',{**params,'page_size':2},HTTP_HOST='xtsy.dingfengchuangyu.com')
        force_authenticate(req,user=actor)
        response=view.as_view()(req);assert response.status_code==200
        data=response.data['data'];rows=data['results']
        if view is InfluencerCollectionView:
            assert all(r['is_deleted']==(params.get('deleted_only')=='true') for r in rows)
        checks.append({'view':view.__name__,'params':params,'http':response.status_code,'count':data['count']})
    print(json.dumps({'checks':checks,'shopee':True,'archive_route':True,'business_writes':0}))
