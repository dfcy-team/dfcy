from datetime import date, timedelta
import json
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.influencers.models import TikTokVideoSyncBatch, TikTokVideoSyncEvidence
from apps.influencers.tiktok_video_sync import DatasetError, receipt
from tests.test_lazada_store_authorization import lazada_context


def running_batch(store):
    return TikTokVideoSyncBatch.objects.create(
        tenant=store.tenant, store=store, window_start=date(2026, 11, 6),
        window_end=date(2026, 11, 7), api_version='test',
        idempotency_key='checkpoint-test', status='running', attempt_count=1,
        lease_token='test-only-lease', lease_expires_at=timezone.now() + timedelta(minutes=5),
        heartbeat_at=timezone.now(),
    )


@pytest.mark.django_db
def test_checkpoint_receipt_requires_live_lease(lazada_context):
    _, store, _ = lazada_context
    batch = running_batch(store)
    batch.lease_expires_at = timezone.now() - timedelta(minutes=1)
    batch.heartbeat_at = timezone.now() - timedelta(minutes=2)
    batch.save(update_fields=['lease_expires_at','heartbeat_at'])
    with pytest.raises(DatasetError, match='video_lease_lost'):
        receipt(batch, 1, {'videos': []}, checkpoint={'cursor': 'cursor-1'}, lease_token='test-only-lease')
    batch.refresh_from_db()
    assert batch.request_cursor == ''
    assert not TikTokVideoSyncEvidence.objects.filter(batch=batch).exists()


@pytest.mark.django_db
def test_existing_and_new_receipts_commit_checkpoint(lazada_context):
    _, store, _ = lazada_context
    batch = running_batch(store)
    payload = {'videos': [{'id': 'v1'}]}
    first = receipt(batch, 1, payload, checkpoint={'cursor': 'cursor-1'}, lease_token='test-only-lease')
    batch.refresh_from_db()
    assert json.loads(batch.request_cursor) == {'cursor': 'cursor-1'}
    again = receipt(batch, 1, payload, checkpoint={'cursor': 'cursor-2'}, lease_token='test-only-lease')
    batch.refresh_from_db()
    assert again.pk == first.pk
    assert batch.request_cursor == '{"cursor":"cursor-2"}'


@pytest.mark.django_db
def test_body_verification_failure_does_not_advance_checkpoint(lazada_context):
    _, store, _ = lazada_context
    batch = running_batch(store)
    receipt(batch, 1, {'videos': [1]}, checkpoint={'cursor': 'cursor-1'}, lease_token='test-only-lease')
    with pytest.raises(DatasetError):
        receipt(batch, 1, {'videos': [2]}, checkpoint={'cursor': 'cursor-bad'}, lease_token='test-only-lease')
    batch.refresh_from_db()
    assert batch.request_cursor == '{"cursor":"cursor-1"}'


@pytest.mark.django_db
def test_changed_representation_is_rejected_without_checkpoint(lazada_context):
    _, store, _ = lazada_context
    batch = running_batch(store)
    from django.db.models.query import QuerySet
    original = QuerySet.get_or_create

    def insert_then_change(queryset, *args, **kwargs):
        row, created = original(queryset, *args, **kwargs)
        if created:
            row.payload = {'changed': True}
        return row, created

    with patch.object(QuerySet, 'get_or_create', autospec=True, side_effect=insert_then_change):
        with pytest.raises(DatasetError):
            receipt(batch, 1, {'videos': [1]}, checkpoint={'cursor': 'cursor-bad'}, lease_token='test-only-lease')
    batch.refresh_from_db()
    assert batch.request_cursor == ''
