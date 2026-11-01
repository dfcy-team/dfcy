from datetime import date, datetime, timezone as dt_timezone
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from apps.influencers import tiktok_video_sync
from apps.integrations import gmv_max_read


def test_gmv_max_read_uses_latest_success_audit_for_reused_content(monkeypatch):
    now = datetime(2026, 10, 31, tzinfo=dt_timezone.utc)
    mapping = SimpleNamespace(pk=7, store_id=3, advertiser_id='adv', store=SimpleNamespace(code='S'))
    def snapshot(pk, when, cost):
        return SimpleNamespace(pk=pk, store_id=3, created_at=when,
            payload={'advertiser_id':'adv','date':'2026-10-30','platform_store_id':'p',
                     'currency':'USD','timezone':'UTC','pages':[{'page_info':{'page':1,
                     'page_size':100,'total_page':1,'total_number':1},'list':[{'dimensions':{'campaign_id':'123'},
                     'metrics':{'cost':cost,'gross_revenue':cost,'orders':1}}]}]})
    a = snapshot(1, now, '1')
    b = snapshot(2, now.replace(minute=1), '2')
    # A was first stored before B, then observed again after B (A -> B -> A).
    audits = [SimpleNamespace(pk=10, created_at=now.replace(minute=2), masked_detail={'raw_payload_id':1})]
    class RawManager:
        def filter(self, *args, **kwargs): return RawQuery([b, a])
    class AuditManager:
        def filter(self, *args, **kwargs): return RawQuery(audits)
    monkeypatch.setattr(gmv_max_read.SharedAdvertisingRawPayload, 'objects', RawManager())
    monkeypatch.setattr(gmv_max_read.IntegrationAuditLog, 'objects', AuditManager())

    rows = gmv_max_read.stored_days(SimpleNamespace(tenant_id=9), [mapping], {7:'Name'},
                                    date(2026,10,30), date(2026,10,30))
    assert [row['snapshot_id'] for row in rows] == [1]
    assert rows[0]['cost'] == '1'
    assert rows[0]['fetched_at'] == audits[0].created_at.isoformat()


def test_gmv_max_read_keeps_created_at_order_when_history_has_no_audit(monkeypatch):
    now = datetime(2026, 10, 31, tzinfo=dt_timezone.utc)
    mapping = SimpleNamespace(pk=7, store_id=3, advertiser_id='adv', store=SimpleNamespace(code='S'))
    def snapshot(pk, minute, cost):
        return SimpleNamespace(pk=pk, store_id=3, created_at=now.replace(minute=minute),
            payload={'advertiser_id':'adv','date':'2026-10-30','platform_store_id':'p',
                     'currency':'USD','timezone':'UTC','pages':[{'page_info':{'page':1,
                     'page_size':100,'total_page':1,'total_number':1},'list':[{'dimensions':{'campaign_id':'123'},
                     'metrics':{'cost':cost,'gross_revenue':cost,'orders':1}}]}]})
    older, newer = snapshot(1, 1, '1'), snapshot(2, 2, '2')
    class RawManager:
        def filter(self, *args, **kwargs): return RawQuery([older, newer])
    class AuditManager:
        def filter(self, *args, **kwargs): return RawQuery([])
    monkeypatch.setattr(gmv_max_read.SharedAdvertisingRawPayload, 'objects', RawManager())
    monkeypatch.setattr(gmv_max_read.IntegrationAuditLog, 'objects', AuditManager())

    rows = gmv_max_read.stored_days(SimpleNamespace(tenant_id=9), [mapping], {},
                                    date(2026,10,30), date(2026,10,30))
    assert [row['snapshot_id'] for row in rows] == [2]


class RawQuery(list):
    def order_by(self, *args): return self
    def iterator(self): return iter(self)


def test_video_run_day_reloads_deactivated_actor_before_request_or_commit(monkeypatch):
    class Actor:
        pk, tenant_id, is_active = 11, 9, True
    stale_actor, persisted_actor = Actor(), Actor()
    class UserManager:
        def get(self, **kwargs): return persisted_actor
    Actor._default_manager = UserManager()
    auth = SimpleNamespace(integration_config=object(), store=SimpleNamespace(timezone='UTC'),
        currency='USD', platform_store_id='shop', shop_cipher='cipher')

    class Batch:
        pk, attempt_count, max_attempts = 44, 0, 3
        status = 'pending'
        lease_expires_at = None
        lease_token = ''
        def save(self, *args, **kwargs): pass
    batch = Batch()
    class BatchQuery:
        def select_for_update(self): return self
        def get_or_create(self, **kwargs): return batch, True
        def get(self, **kwargs): return batch
    class TenantQuery:
        def select_for_update(self): return self
        def get(self, **kwargs): return object()
    class Manager:
        def __init__(self, query): self.query = query
        def __getattr__(self, name): return getattr(self.query, name)

    def resolve(actor, store_id):
        if not actor.is_active:
            raise tiktok_video_sync.DatasetError('actor_inactive')
        return auth
    monkeypatch.setattr(tiktok_video_sync, 'resolve', resolve)
    monkeypatch.setattr(tiktok_video_sync, 'fingerprint', lambda _auth: 'same-binding')
    monkeypatch.setattr(tiktok_video_sync.transaction, 'atomic', nullcontext)
    monkeypatch.setattr(tiktok_video_sync.Tenant, 'objects', Manager(TenantQuery()))
    monkeypatch.setattr(tiktok_video_sync.TikTokVideoSyncBatch, 'objects', Manager(BatchQuery()))

    class Client:
        def __init__(self, *_): pass
        def verify_shop(self): persisted_actor.is_active = False
        def _request(self, *args, **kwargs): pytest.fail('request continued after actor deactivation')
    with pytest.raises(tiktok_video_sync.DatasetError):
        day = tiktok_video_sync.timezone.now().date() - tiktok_video_sync.timedelta(days=1)
        tiktok_video_sync.run_day(stale_actor, 3, day, apply=True, client_factory=Client)
    assert batch.status == 'failed'
    assert batch.completed_at is not None
    assert batch.lease_token == ''


def test_video_rate_error_identifies_only_fixed_metric_field():
    video = {'id':'123', 'total_performance':{'video_finish_rate':'1.25'}}
    with pytest.raises(tiktok_video_sync.DatasetError) as error:
        tiktok_video_sync.project(video, 'USD')
    assert str(error.value) == 'invalid_video_rate:field=video_finish_rate:range=0..1'
    assert '1.25' not in str(error.value)


@pytest.mark.parametrize(('data', 'expected'), [
    ({}, 'video_page_invalid:field=videos:category=missing'),
    ({'videos':None}, 'video_page_invalid:field=videos:category=null'),
    ({'videos':{'private':'payload'}}, 'video_page_invalid:field=videos:category=type_object'),
    ({'videos':[{}] * 51}, 'video_page_invalid:field=videos:category=oversized:range=0..50'),
])
def test_video_page_diagnostics_are_bounded_and_safe(data, expected):
    with pytest.raises(tiktok_video_sync.DatasetError) as error:
        tiktok_video_sync.validate_video_page(data)
    assert str(error.value) == expected
    assert 'private' not in str(error.value)


def test_video_page_accepts_valid_collection():
    values = [{'id':'123'}]
    assert tiktok_video_sync.validate_video_page({'videos':values}) is values

