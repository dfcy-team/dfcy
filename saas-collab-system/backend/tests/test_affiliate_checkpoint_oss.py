from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.integrations import affiliate_sync, raw_services
from apps.integrations.readonly_clients import ReadonlyConfigurationError
from tests.test_affiliate_daily_ingestion import trial  # noqa: F401
from tests.test_mock_sync_isolation import context  # noqa: F401
from tests.test_raw_payload_storage import MemoryStorage

pytestmark = pytest.mark.django_db


def test_checkpoint_oss_roundtrip_and_idempotency(trial, monkeypatch):
    storage = MemoryStorage()
    monkeypatch.setattr(raw_services, 'storages', {'raw_oss': storage})
    journal = affiliate_sync.DatabasePageJournal(trial.job, trial.run, {})
    with override_settings(RAW_PAYLOAD_STORAGE_ALIAS='raw_oss', RAW_PAYLOAD_STORAGE_NAMESPACE='test'):
        journal.save({'page': 1}, {'records': [{'id': 'synthetic'}]})
        journal.save({'page': 1}, {'records': [{'id': 'synthetic'}]})
        entry = trial.run.raw_envelopes.get()
        assert entry.payload == {} and entry.payload_storage_alias == 'raw_oss'
        assert journal.load({'page': 1}) == {'records': [{'id': 'synthetic'}]}
        assert len(storage.objects) == 1


@pytest.mark.parametrize('corrupt', [False, True])
def test_checkpoint_failed_oss_leaves_no_database_payload(trial, monkeypatch, corrupt):
    storage = MemoryStorage(fail_save=not corrupt, corrupt_after_save=corrupt)
    monkeypatch.setattr(raw_services, 'storages', {'raw_oss': storage})
    journal = affiliate_sync.DatabasePageJournal(trial.job, trial.run, {})
    with override_settings(RAW_PAYLOAD_STORAGE_ALIAS='raw_oss', RAW_PAYLOAD_STORAGE_NAMESPACE='test'):
        with pytest.raises(ValidationError):
            journal.save({'page': 1}, {'records': []})
    assert not trial.run.raw_envelopes.exists()


def test_checkpoint_expired_lease_rejects_before_upload(trial, monkeypatch):
    trial.job.lock_expires_at = timezone.now() - timedelta(seconds=1)
    trial.job.save(update_fields=['lock_expires_at'])
    storage = MemoryStorage()
    monkeypatch.setattr(raw_services, 'storages', {'raw_oss': storage})
    with override_settings(RAW_PAYLOAD_STORAGE_ALIAS='raw_oss', RAW_PAYLOAD_STORAGE_NAMESPACE='test'):
        with pytest.raises(ReadonlyConfigurationError, match='LEASE_LOST'):
            affiliate_sync.DatabasePageJournal(trial.job, trial.run, {}).save({}, {})
    assert not storage.objects and not trial.run.raw_envelopes.exists()


def test_checkpoint_lease_expiring_during_upload_rolls_back_reference(trial, monkeypatch):
    storage = MemoryStorage()
    original_save = storage._save
    def slow_save(name, content):
        result = original_save(name, content)
        monkeypatch.setattr(affiliate_sync.timezone, 'now', lambda: trial.job.lock_expires_at + timedelta(seconds=1))
        return result
    monkeypatch.setattr(storage, '_save', slow_save)
    monkeypatch.setattr(raw_services, 'storages', {'raw_oss': storage})
    with override_settings(RAW_PAYLOAD_STORAGE_ALIAS='raw_oss', RAW_PAYLOAD_STORAGE_NAMESPACE='test'):
        with pytest.raises(ReadonlyConfigurationError, match='LEASE_LOST'):
            affiliate_sync.DatabasePageJournal(trial.job, trial.run, {}).save({}, {})
    assert not trial.run.raw_envelopes.exists()
    assert len(storage.objects) == 1  # An immutable orphan is retained, never automatically deleted.
