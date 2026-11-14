from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from rest_framework.exceptions import ValidationError
from apps.integrations import collection_sync


@pytest.fixture
def adapter(monkeypatch):
    adapter = object.__new__(collection_sync.TikTokCollectionAdapter)
    adapter.source_run = SimpleNamespace(run_id="test-run")
    adapter.scope = {"collection_plan": {"units": ["2026-11-11"]}}
    adapter.actor = object()
    adapter.authorization = SimpleNamespace(store_id=7)
    receipt = SimpleNamespace(pk=12)
    manager = MagicMock()
    manager.filter.return_value.first.return_value = None
    manager.get.return_value = receipt
    monkeypatch.setattr(collection_sync.CollectionUnitReceipt, "objects", manager)
    callback = MagicMock()
    monkeypatch.setattr(adapter, "_receipt", callback)
    run = MagicMock()
    monkeypatch.setattr("apps.influencers.tiktok_video_sync.run_day", run)
    return adapter, manager, run, callback


def test_video_calls_business_import_without_refresh(adapter):
    item, manager, run, callback = adapter
    job = SimpleNamespace(resource_type="video_metrics")
    page = item.fetch_page(job)
    assert page["next_cursor"] == ""
    assert page["receipt_id"] == 12
    assert run.call_args.args[1] == 7
    assert run.call_args.kwargs["apply"] is True
    assert run.call_args.kwargs["refresh"] is False
    assert run.call_args.kwargs["page_size"] == 10
    assert run.call_args.kwargs["page_delay_seconds"] == 2
    run.call_args.kwargs["commit_receipt"]({"created": 3})
    callback.assert_called_once_with(job, "video_metrics:2026-11-11", {"created": 3})


def test_committed_unit_is_not_collected_twice(adapter):
    item, manager, run, _ = adapter
    manager.filter.return_value.first.return_value = SimpleNamespace(pk=12)
    item.fetch_page(SimpleNamespace(resource_type="video_metrics"))
    run.assert_not_called()


@pytest.mark.parametrize("cursor", ["collection:other-run:0", "collection:test-run:-1", "collection:test-run:9"])
def test_invalid_cursor_never_collects(adapter, cursor):
    item, _, run, _ = adapter
    with pytest.raises(ValidationError, match="COLLECTION_CURSOR_INVALID"):
        item.fetch_page(SimpleNamespace(resource_type="video_metrics"), cursor)
    run.assert_not_called()
