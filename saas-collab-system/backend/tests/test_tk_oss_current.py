from datetime import date
from unittest.mock import patch

import pytest
from django.core.files.storage import storages
from django.test import override_settings

from apps.influencers.models import TikTokVideoSyncBatch, TikTokVideoSyncEvidence
from apps.influencers.tiktok_video_sync import receipt, digest, DatasetError
from tests.test_lazada_store_authorization import lazada_context


@pytest.mark.django_db
def test_page_and_commit_retry_roundtrip(lazada_context, tmp_path):
    _, store, _ = lazada_context
    batch = TikTokVideoSyncBatch.objects.create(tenant=store.tenant, store=store,
        window_start=date(2026, 11, 6), window_end=date(2026, 11, 7),
        api_version='test', idempotency_key='evidence-oss-vm')
    payload = {'videos': [{'name':'测试商品'}]}
    storage = {'raw_oss': {'BACKEND':'django.core.files.storage.FileSystemStorage',
                          'OPTIONS':{'location':str(tmp_path)}}}
    with override_settings(STORAGES=storage, RAW_PAYLOAD_STORAGE_NAMESPACE='prod-usw1',
                           RAW_PAYLOAD_STORAGE_ALIAS='raw_oss', TIKTOK_VIDEO_EVIDENCE_STORAGE_ALIAS='raw_oss'):
        with patch.object(storages['raw_oss'], 'save', side_effect=OSError('injected failure')):
            with pytest.raises(DatasetError):
                receipt(batch, 1, payload)
        assert not TikTokVideoSyncEvidence.objects.filter(batch=batch).exists()
        backend = storages['raw_oss']
        save = backend.save
        def lost_response(key, content):
            save(key, content)
            raise TimeoutError('lost PUT response')
        with patch.object(backend, 'save', side_effect=lost_response):
            receipt(batch, 1, payload)
        receipt(batch, 1, payload)
        with pytest.raises(DatasetError):
            receipt(batch, 1, {'videos':[]})
        page = TikTokVideoSyncEvidence.objects.get(batch=batch,page=1)
        assert page.payload == {} and page.payload_hash == digest(payload)
        assert page.read_payload() == payload
        assert len(list(tmp_path.rglob('*.gz'))) == 1
        receipt(batch, 0, {'database_verified':True})
        assert TikTokVideoSyncEvidence.objects.get(batch=batch,page=0).read_payload()['database_verified']

