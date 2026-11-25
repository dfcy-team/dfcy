import json
from unittest.mock import patch
import pytest
from django.core.files.storage import storages
from django.db import DatabaseError
from django.test import override_settings
from apps.influencers.models import TikTokVideoSyncBatch, TikTokVideoSyncEvidence
from apps.influencers.tiktok_video_sync import receipt, DatasetError
from tests.test_lazada_store_authorization import lazada_context
from tests.test_tk_oss_checkpoint import running_batch


def storage_settings(tmp_path):
    return override_settings(TIKTOK_VIDEO_EVIDENCE_STORAGE_ALIAS='raw_oss',
        RAW_PAYLOAD_STORAGE_NAMESPACE='prod-usw1',STORAGES={'raw_oss':{
        'BACKEND':'django.core.files.storage.FileSystemStorage','OPTIONS':{'location':str(tmp_path)}}})


@pytest.mark.django_db(transaction=True)
def test_external_duplicate_and_failed_get_preserve_cursor(lazada_context,tmp_path):
    _,store,_=lazada_context;batch=running_batch(store);body={'videos':[{'id':'one'}]}
    with storage_settings(tmp_path):
        first=receipt(batch,1,body,checkpoint={'cursor':'one'},lease_token='valid-token')
        assert first.payload=={}
        duplicate=receipt(batch,1,body,checkpoint={'cursor':'two'},lease_token='valid-token')
        assert duplicate.pk==first.pk
        with patch.object(storages['raw_oss'],'open',side_effect=OSError('injected GET failure')):
            with pytest.raises(Exception):
                receipt(batch,1,body,checkpoint={'cursor':'bad'},lease_token='valid-token')
        batch.refresh_from_db();assert json.loads(batch.request_cursor)=={'cursor':'two'}
        assert TikTokVideoSyncEvidence.objects.filter(batch=batch).count()==1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('error_code',[1205,1213])
def test_cursor_retry_reuses_verified_object(lazada_context,tmp_path,error_code):
    _,store,_=lazada_context;batch=running_batch(store);original=TikTokVideoSyncBatch.save
    calls=[]
    def save(instance,*args,**kwargs):
        if 'request_cursor' in kwargs.get('update_fields',[]):
            calls.append(1)
            if len(calls)==1:raise DatabaseError(error_code,'injected')
        return original(instance,*args,**kwargs)
    with storage_settings(tmp_path):
        storage=storages['raw_oss']
        with patch.object(storage,'save',wraps=storage.save) as put,patch.object(storage,'open',wraps=storage.open) as get,patch.object(TikTokVideoSyncBatch,'save',save),patch('time.sleep'):
            receipt(batch,1,{'videos':[1]},checkpoint={'cursor':'ok'},lease_token='valid-token')
        assert put.call_count==1 and get.call_count==1
    batch.refresh_from_db();assert json.loads(batch.request_cursor)=={'cursor':'ok'}
    assert TikTokVideoSyncEvidence.objects.filter(batch=batch).count()==1


@pytest.mark.django_db(transaction=True)
def test_cursor_failure_rolls_back_new_evidence(lazada_context,tmp_path):
    _,store,_=lazada_context;batch=running_batch(store)
    with storage_settings(tmp_path),patch.object(TikTokVideoSyncBatch,'save',side_effect=RuntimeError('cursor failure')):
        with pytest.raises(RuntimeError):receipt(batch,1,{'videos':[1]},checkpoint={'cursor':'bad'},lease_token='valid-token')
    batch.refresh_from_db();assert batch.request_cursor==''
    assert not TikTokVideoSyncEvidence.objects.filter(batch=batch).exists()
