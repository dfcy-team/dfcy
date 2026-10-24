import io
import gzip
import json

import pytest
from django.core.files.storage import Storage
from django.test import override_settings
from rest_framework.exceptions import ValidationError

from apps.integrations import raw_services
from apps.integrations.models import SyncRawEnvelope, SyncRun, WebhookEvent
from tests.test_mock_sync_isolation import context  # noqa: F401


pytestmark = pytest.mark.django_db


class MemoryStorage(Storage):
    def __init__(self, fail_save=False, corrupt_after_save=False):
        self.objects = {}
        self.fail_save = fail_save
        self.corrupt_after_save = corrupt_after_save

    def _open(self, name, mode="rb"):
        if name not in self.objects:
            raise FileNotFoundError(name)
        return io.BytesIO(self.objects[name])

    def _save(self, name, content):
        if self.fail_save:
            raise OSError("offline")
        self.objects[name] = content.read()
        if self.corrupt_after_save:
            self.objects[name] = b"read-back-mismatch"
        return name

    def exists(self, name):
        return name in self.objects


def run_for(job):
    return SyncRun.objects.create(tenant=job.tenant, sync_job=job, run_id="raw-storage-run",
                                  idempotency_key="raw-storage-key")


def create(journal, run, tenant):
    return journal._create_raw_envelope(payload={"records": [{"id": "r1"}]}, tenant=tenant,
        sync_run=run, platform="tiktok", endpoint="test://raw", cursor="", sequence=1,
        payload_hash=journal.payload_digest({"records": [{"id": "r1"}]}))


def test_inline_legacy_payload_remains_readable(context):
    _, job = context
    run = run_for(job)
    entry = create(raw_services, run, job.tenant)
    assert entry.payload == {"records": [{"id": "r1"}]}
    assert entry.payload_storage_alias is None and entry.payload_object_key is None
    assert raw_services.load_raw_payload(entry) == entry.payload


def test_external_payload_is_verified_and_loaded(context, monkeypatch):
    _, job = context
    run = run_for(job)
    storage = MemoryStorage()
    monkeypatch.setattr(raw_services, "storages", {"private_raw": storage})
    with override_settings(RAW_PAYLOAD_STORAGE_ALIAS="private_raw", RAW_PAYLOAD_STORAGE_NAMESPACE="test-env"):
        entry = create(raw_services, run, job.tenant)
        assert entry.payload == {}
        assert entry.payload_storage_alias == "private_raw"
        assert entry.payload_object_key.startswith(f"raw/test-env/tenant-{job.tenant_id}/")
        assert raw_services.load_raw_payload(entry) == {"records": [{"id": "r1"}]}


def test_real_archive_path_can_replay_external_payload(context, monkeypatch):
    _, job = context
    run = run_for(job)
    storage = MemoryStorage()
    monkeypatch.setattr(raw_services, "storages", {"private_raw": storage})
    adapter = type("Adapter", (), {"adapter_name": "unit", "authorization": None})()
    with override_settings(RAW_PAYLOAD_STORAGE_ALIAS="private_raw", RAW_PAYLOAD_STORAGE_NAMESPACE="test-env"):
        entry = raw_services.archive_raw_page(job, run, adapter, "start", {
            "raw_responses": [{"endpoint": "https://example.invalid/page", "payload": {"id": "r1"}}],
            "records": [{"id": "r1"}], "next_cursor": "next",
        })
        replay_adapter = type("ReplayAdapter", (), {
            "validate_configuration": lambda self, sync_job: None,
            "bind_run": lambda self, sync_run: None,
            "normalize_record": lambda self, record: record,
            "validate_record": lambda self, record: True,
            "persist_record": lambda self, sync_job, record: {"action": "created"},
        })()
        assert raw_services.replay_raw_envelope(entry, replay_adapter) == {
            "created": 1, "updated": 0, "skipped": 0, "failed": 0,
        }


@pytest.mark.parametrize("damage", ["tamper", "missing", "metadata"])
def test_external_payload_damage_fails_closed(context, monkeypatch, damage):
    _, job = context
    run = run_for(job)
    storage = MemoryStorage()
    monkeypatch.setattr(raw_services, "storages", {"private_raw": storage})
    with override_settings(RAW_PAYLOAD_STORAGE_ALIAS="private_raw", RAW_PAYLOAD_STORAGE_NAMESPACE="test-env"):
        entry = create(raw_services, run, job.tenant)
        if damage == "tamper":
            storage.objects[entry.payload_object_key] = gzip.compress(
                json.dumps({"records": [{"id": "changed"}]}, separators=(",", ":")).encode(), mtime=0
            )
        elif damage == "missing":
            del storage.objects[entry.payload_object_key]
        else:
            entry.payload_object_key = None
        with pytest.raises(ValidationError):
            raw_services.load_raw_payload(entry)


def test_storage_failure_does_not_create_envelope(context, monkeypatch):
    _, job = context
    run = run_for(job)
    monkeypatch.setattr(raw_services, "storages", {"private_raw": MemoryStorage(fail_save=True)})
    with override_settings(RAW_PAYLOAD_STORAGE_ALIAS="private_raw", RAW_PAYLOAD_STORAGE_NAMESPACE="test-env"):
        before = SyncRawEnvelope.objects.count()
        with pytest.raises(ValidationError):
            create(raw_services, run, job.tenant)
        assert SyncRawEnvelope.objects.count() == before


def test_readback_mismatch_does_not_create_envelope(context, monkeypatch):
    _, job = context
    run = run_for(job)
    monkeypatch.setattr(raw_services, "storages", {"private_raw": MemoryStorage(corrupt_after_save=True)})
    with override_settings(RAW_PAYLOAD_STORAGE_ALIAS="private_raw", RAW_PAYLOAD_STORAGE_NAMESPACE="test-env"):
        before = SyncRawEnvelope.objects.count()
        with pytest.raises(ValidationError):
            create(raw_services, run, job.tenant)
        assert SyncRawEnvelope.objects.count() == before


def test_missing_storage_alias_does_not_create_envelope(context, monkeypatch):
    _, job = context
    run = run_for(job)
    monkeypatch.setattr(raw_services, "storages", {})
    with override_settings(RAW_PAYLOAD_STORAGE_ALIAS="missing", RAW_PAYLOAD_STORAGE_NAMESPACE="test-env"):
        before = SyncRawEnvelope.objects.count()
        with pytest.raises(ValidationError):
            create(raw_services, run, job.tenant)
        assert SyncRawEnvelope.objects.count() == before


def test_webhook_external_archive(context, monkeypatch):
    _, job = context
    event = WebhookEvent.objects.create(tenant=job.tenant, platform="shopee",
        event_id="storage-test", event_type="order", payload_hash="a" * 64)
    storage = MemoryStorage()
    monkeypatch.setattr(raw_services, "storages", {"private_raw": storage})
    with override_settings(RAW_PAYLOAD_STORAGE_ALIAS="private_raw", RAW_PAYLOAD_STORAGE_NAMESPACE="test-env"):
        entry = raw_services.archive_webhook_payload(event, {"order_id": "test-order"})
        entry.refresh_from_db()
        assert entry.webhook_event_id == event.pk
        assert entry.payload == {}
        assert raw_services.load_raw_payload(entry)["payload"] == {"order_id": "test-order"}
        # Disabling future external writes must not disable existing external reads.
        with override_settings(RAW_PAYLOAD_STORAGE_ALIAS=""):
            assert raw_services.load_raw_payload(entry)["event_id"] == event.event_id


def test_renamed_object_does_not_create_unreadable_envelope(context, monkeypatch):
    _, job = context
    run = run_for(job)
    storage = MemoryStorage()
    original_save = storage.save
    monkeypatch.setattr(storage, "save", lambda key, content: original_save(key + "_changed", content))
    monkeypatch.setattr(raw_services, "storages", {"private_raw": storage})
    with override_settings(RAW_PAYLOAD_STORAGE_ALIAS="private_raw", RAW_PAYLOAD_STORAGE_NAMESPACE="test-env"):
        with pytest.raises(ValidationError):
            create(raw_services, run, job.tenant)
        assert not run.raw_envelopes.exists()


def test_database_error_is_preserved_for_retry(context, monkeypatch):
    from django.db import OperationalError
    _, job = context
    run = run_for(job)
    monkeypatch.setattr(raw_services, "storages", {"private_raw": MemoryStorage()})
    def fail(**kwargs):
        raise OperationalError("simulated database deadlock")
    monkeypatch.setattr(SyncRawEnvelope.objects, "create", fail)
    with override_settings(RAW_PAYLOAD_STORAGE_ALIAS="private_raw", RAW_PAYLOAD_STORAGE_NAMESPACE="test-env"):
        with pytest.raises(OperationalError):
            create(raw_services, run, job.tenant)


def test_cross_tenant_reference_is_rejected(context, monkeypatch):
    _, job = context
    run = run_for(job)
    monkeypatch.setattr(raw_services, "storages", {"private_raw": MemoryStorage()})
    with override_settings(RAW_PAYLOAD_STORAGE_ALIAS="private_raw", RAW_PAYLOAD_STORAGE_NAMESPACE="test-env"):
        entry = create(raw_services, run, job.tenant)
        entry.payload_object_key = entry.payload_object_key.replace(f"tenant-{job.tenant_id}/", "tenant-other/")
        with pytest.raises(ValidationError):
            raw_services.load_raw_payload(entry)
