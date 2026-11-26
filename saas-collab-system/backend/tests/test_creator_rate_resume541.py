import ast
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
import unittest


SOURCE = Path(__file__).parents[1] / "apps/integrations/sync_services.py"


def extracted(name, globals_):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    module = ast.Module(body=[function], type_ignores=[])
    exec(compile(module, str(SOURCE), "exec"), globals_)
    return globals_[name]


class CreatorRateResumeCandidateTests(unittest.TestCase):
    def test_delay_floor_and_24_hour_deadline(self):
        wait = extracted("_creator_rate_wait", {"datetime": datetime, "timedelta": timedelta})
        now = datetime(2026, 11, 25, tzinfo=dt_timezone.utc)
        self.assertEqual(wait(None, now, 1), (60, now.isoformat()))
        almost_expired = (now - timedelta(hours=23, minutes=59, seconds=30)).isoformat()
        self.assertIsNone(wait(almost_expired, now, 300))
        expired = (now - timedelta(hours=24)).isoformat()
        self.assertIsNone(wait(expired, now, 300))
        self.assertEqual(wait('2026-11-25T00:00:00', now, 300)[0], 300)
        self.assertEqual(wait('9999-12-31T00:00:00+00:00', now, 300), (300, now.isoformat()))
        self.assertEqual(wait('2099-01-01T00:00:00+00:00', now, 300), (300, now.isoformat()))

    def test_rate_yield_does_not_claim_page_commit_and_normal_yield_does(self):
        class Job:
            status = "running"
            lock_token = "test-only-lease"
            lock_expires_at = object()
            lock_heartbeat_at = None
            def save(self, **kwargs): pass

        class Run:
            masked_log = {}
            status = "running"
            def __init__(self):
                self.error_code = ""
                self.masked_error_message = ""
                self.finished_at = None

        class Zone:
            @staticmethod
            def now(): return datetime(2026, 11, 25, tzinfo=dt_timezone.utc)

        class RunStatus:
            QUEUED = "queued"

        ns = {
            "_owns_lease": lambda job, run: True,
            "timezone": Zone,
            "timedelta": timedelta,
            "SyncRun": type("SyncRun", (), {"Status": RunStatus}),
            "SyncJob": type("SyncJob", (), {"Status": type("Status", (), {"IDLE": "idle"})}),
            "sanitize_payload": lambda value: value,
            "_save_run": lambda run: None,
        }
        yield_slice = extracted("_yield_sync_slice", ns)
        rate_run, normal_run = Run(), Run()
        rate_job, normal_job = Job(), Job()
        first = Zone.now().isoformat()
        yield_slice(rate_job, rate_run, retry_after=60, creator_rate_first_seen_at=first)
        yield_slice(normal_job, normal_run)
        budget = rate_run.masked_log["runtime_budget"]
        self.assertEqual(budget["wait_reason"], "creator_shared_rate_limit")
        self.assertEqual(budget["creator_rate_limit_first_seen_at"], first)
        self.assertEqual(budget["ready_at"], (Zone.now() + timedelta(seconds=60)).isoformat())
        self.assertNotIn("last_page_committed_at", budget)
        self.assertIn("last_page_committed_at", normal_run.masked_log["runtime_budget"])

    def test_rate_branch_is_scoped_and_does_not_advance_cursor_or_receipt(self):
        source = SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        run = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "run_sync_job")
        handler = next(node for node in ast.walk(run) if isinstance(node, ast.ExceptHandler))
        text = ast.unparse(handler)
        self.assertIn("sync_job.resource_type == 'creator_profile'", text)
        self.assertIn("exc.controlled_code == OAUTH_RATE_LIMITED", text)
        self.assertIn("retry_count", text)
        self.assertIn("_yield_sync_slice(locked_job, run, retry_after=retry_after", text)
        self.assertNotIn("cursor.cursor_value =", text[text.index("exc.controlled_code == OAUTH_RATE_LIMITED"):text.index("ads_contention = False")])


if __name__ == "__main__":
    unittest.main()


# Exercise the real transactional orchestration with a provider-free adapter.
import pytest
from unittest.mock import patch
from tests.test_mock_sync_isolation import context

@pytest.mark.django_db
def test_legacy_cursor_survives_stale_delivery_and_rate_wait(context, monkeypatch):
    from apps.integrations.adapters import MockPlatformAdapter
    from apps.integrations.models import SyncCursor, SyncRun
    from apps.integrations.oauth_errors import OAuthFlowError, OAUTH_RATE_LIMITED
    from apps.integrations.sync_services import run_sync_job
    from apps.integrations.sync_delivery import DeliverySnapshot
    _, job = context
    type(job).objects.filter(pk=job.pk).update(resource_type='creator_profile')
    job.refresh_from_db()
    monkeypatch.setattr('apps.integrations.sync_services.require_sync_read_capability', lambda *a, **k: None)
    monkeypatch.setattr('apps.integrations.sync_services.record_sync_source_decision', lambda *a, **k: None)
    monkeypatch.setattr('apps.integrations.sync_delivery.read_delivery_snapshot', lambda: DeliverySnapshot(complete=True))
    class RateAdapter(MockPlatformAdapter):
        scope = {}
        def validate_configuration(self, job): pass
        def fetch_page(self, job, cursor_value=None):
            self.cursors.append(cursor_value)
            raise OAuthFlowError(OAUTH_RATE_LIMITED)
        def __init__(self): self.cursors=[]
    old = SyncCursor.objects.create(tenant=job.tenant, sync_job=job, cursor_key='default', cursor_value='saved-provider-page', detail_state={'immutable':'kept'})
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job, run_id='legacy-creator-run', idempotency_key='legacy-key', status='queued', fetched_count=7, created_count=5, retry_count=0, masked_log={'runtime_budget':{'sequence':2,'pending':True,'resolved_scope':{}}})
    adapter=RateAdapter()
    stale, created = run_sync_job(job, adapter=adapter, idempotency_key='legacy-key', resume_sequence=1)
    assert stale.pk==run.pk and not created and adapter.cursors==[]
    assert list(SyncCursor.objects.filter(sync_job=job).values_list('cursor_key',flat=True))==['default']
    resumed, created=run_sync_job(job,adapter=adapter,idempotency_key='legacy-key',resume_sequence=2)
    resumed.refresh_from_db();old.refresh_from_db();job.refresh_from_db()
    assert resumed.pk==run.pk and created and adapter.cursors==['saved-provider-page']
    assert old.cursor_value=='saved-provider-page' and old.detail_state=={'immutable':'kept'}
    assert (resumed.fetched_count,resumed.created_count,resumed.failed_count,resumed.retry_count)==(7,5,0,0)
    assert resumed.status=='queued' and resumed.masked_log['runtime_budget']['sequence']==3
    assert job.status=='idle' and not job.lock_token and job.lock_expires_at is None
    resumed,created=run_sync_job(job,adapter=adapter,idempotency_key='legacy-key',resume_sequence=3)
    assert created and adapter.cursors==['saved-provider-page','saved-provider-page']

@pytest.mark.django_db
def test_fresh_creator_run_ignores_legacy_checkpoint(context,monkeypatch):
    from apps.integrations.adapters import MockPlatformAdapter
    from apps.integrations.models import SyncCursor,SyncCheckpoint
    from apps.integrations.oauth_errors import OAuthFlowError,OAUTH_RATE_LIMITED
    from apps.integrations.sync_services import run_sync_job
    from apps.integrations.sync_delivery import DeliverySnapshot
    _,job=context
    type(job).objects.filter(pk=job.pk).update(resource_type='creator_profile');job.refresh_from_db()
    SyncCursor.objects.create(tenant=job.tenant,sync_job=job,cursor_key='default',cursor_value='old-page')
    SyncCheckpoint.objects.create(tenant=job.tenant,sync_job=job,cursor_json={'default':'old-page'})
    monkeypatch.setattr('apps.integrations.sync_services.require_sync_read_capability',lambda *a,**k:None)
    monkeypatch.setattr('apps.integrations.sync_services.record_sync_source_decision',lambda *a,**k:None)
    monkeypatch.setattr('apps.integrations.sync_delivery.read_delivery_snapshot',lambda:DeliverySnapshot(complete=True))
    class Adapter(MockPlatformAdapter):
        scope={}
        def validate_configuration(self,job):pass
        def fetch_page(self,job,cursor_value=None):
            assert cursor_value==''
            raise OAuthFlowError(OAUTH_RATE_LIMITED)
    run,created=run_sync_job(job,adapter=Adapter(),idempotency_key='fresh-key')
    assert created and run.status=='queued'
    assert SyncCursor.objects.get(sync_job=job,cursor_key='default').cursor_value=='old-page'
    assert SyncCursor.objects.filter(sync_job=job,cursor_key__startswith='creator:').count()==1
