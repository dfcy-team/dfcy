"""No network or production database: verify preparation boundaries with mocked ORM."""
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from rest_framework.exceptions import ValidationError
from apps.integrations import video_jobs


@pytest.fixture
def preparation(monkeypatch):
    store = MagicMock()
    store.pk = 7
    store.status = "active"
    stores = MagicMock()
    stores.select_for_update.return_value.get.return_value = store
    monkeypatch.setattr(video_jobs.StoreMaster, "objects", stores)
    auth = SimpleNamespace(integration_config=object())
    auths = MagicMock()
    auths.select_related.return_value.filter.return_value.__getitem__.return_value = [auth]
    monkeypatch.setattr(video_jobs.MarketplaceStoreAuthorization, "objects", auths)
    jobs = MagicMock()
    jobs.objects.filter.return_value.order_by.return_value.__getitem__.return_value = []
    jobs.return_value.pk = None
    jobs.return_value.save.side_effect = lambda: setattr(jobs.return_value, "pk", 100)
    monkeypatch.setattr(video_jobs, "SyncJob", jobs)
    monkeypatch.setattr(video_jobs.transaction, "atomic", nullcontext)
    validate = MagicMock()
    monkeypatch.setattr(video_jobs, "validate_manual_sync_job", validate)
    return SimpleNamespace(actor=SimpleNamespace(pk=1, tenant_id=1, is_active=True),
                           jobs=jobs, auths=auths, validate=validate, stores=stores)


def test_preview_does_not_write(preparation):
    p = preparation
    row = video_jobs.prepare_video_job(actor=p.actor, store_id=7)
    assert row["action"] == "would_create_disabled"
    p.jobs.return_value.save.assert_not_called()
    p.validate.assert_called_once_with(p.jobs.return_value, live_only=True)
    p.stores.select_for_update.return_value.get.assert_called_once_with(
        pk=7, tenant_id=1, platform__platform_type="tiktok")


def test_commit_creates_disabled_manual_job(preparation):
    p = preparation
    row = video_jobs.prepare_video_job(actor=p.actor, store_id=7, commit=True)
    assert row == {"store_id": 7, "job_id": 100, "action": "created_disabled"}
    kwargs = p.jobs.call_args.kwargs
    assert kwargs["is_enabled"] is False
    assert kwargs["schedule_type"] == "manual"
    assert kwargs["next_run_at"] is None
    assert kwargs["sync_scope"]["collection"] == {"actor_id": 1, "recent_days": 1}
    p.jobs.return_value.full_clean.assert_called_once()


def test_existing_job_is_not_reconfigured(preparation):
    p = preparation
    p.jobs.objects.filter.return_value.order_by.return_value.__getitem__.return_value = [SimpleNamespace(pk=88)]
    assert video_jobs.prepare_video_job(actor=p.actor, store_id=7, commit=True)["job_id"] == 88
    p.jobs.assert_not_called()
    p.validate.assert_not_called()


def test_duplicate_jobs_block(preparation):
    p = preparation
    p.jobs.objects.filter.return_value.order_by.return_value.__getitem__.return_value = [1, 2]
    with pytest.raises(ValidationError, match="VIDEO_DUPLICATE_JOBS"):
        video_jobs.prepare_video_job(actor=p.actor, store_id=7, commit=True)
    p.jobs.assert_not_called()


@pytest.mark.parametrize("auths", [[], [1, 2]])
def test_missing_or_ambiguous_authorization_blocks(preparation, auths):
    p = preparation
    p.auths.select_related.return_value.filter.return_value.__getitem__.return_value = auths
    with pytest.raises(ValidationError, match="VIDEO_SINGLE_ACTIVE"):
        video_jobs.prepare_video_job(actor=p.actor, store_id=7, commit=True)
    p.jobs.assert_not_called()


def test_failed_preflight_does_not_save(preparation):
    p = preparation
    p.validate.side_effect = ValidationError("VIDEO disabled")
    with pytest.raises(ValidationError):
        video_jobs.prepare_video_job(actor=p.actor, store_id=7, commit=True)
    p.jobs.return_value.save.assert_not_called()


def test_inactive_actor_blocks_before_database(preparation):
    p = preparation
    p.actor.is_active = False
    with pytest.raises(ValidationError, match="VIDEO_ACTOR"):
        video_jobs.prepare_video_job(actor=p.actor, store_id=7, commit=True)
    p.stores.select_for_update.assert_not_called()
