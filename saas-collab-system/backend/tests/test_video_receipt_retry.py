from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.db import OperationalError
from apps.influencers import tiktok_video_sync as module
from apps.influencers.tiktok_shop_dataset import DatasetError


def setup(monkeypatch, effects, atomic=False):
    manager = MagicMock()
    manager.get_or_create.side_effect = effects
    monkeypatch.setattr(module.TikTokVideoSyncEvidence, 'objects', manager)
    monkeypatch.setattr(module, 'connection', SimpleNamespace(in_atomic_block=atomic))
    monkeypatch.setattr(module.transaction, 'atomic', lambda: nullcontext())
    sleep = MagicMock()
    monkeypatch.setattr('time.sleep', sleep)
    return manager, sleep


def test_lock_retry_only_replays_receipt(monkeypatch):
    payload = {'rows': 10}
    saved = SimpleNamespace(payload=payload, payload_hash=module.digest(payload))
    manager, sleep = setup(monkeypatch, [OperationalError(1205, 'locked'), (saved, True)])
    assert module.receipt(SimpleNamespace(tenant_id=1, attempt_count=1), 2, payload) is saved
    assert manager.get_or_create.call_count == 2
    sleep.assert_called_once_with(1)


def test_receipt_retry_is_bounded(monkeypatch):
    manager, sleep = setup(monkeypatch, [OperationalError(1205, 'locked')] * 4)
    with pytest.raises(OperationalError):
        module.receipt(SimpleNamespace(tenant_id=1, attempt_count=1), 2, {})
    assert manager.get_or_create.call_count == 4
    assert [call.args[0] for call in sleep.call_args_list] == [1, 2, 4]


def test_parent_transaction_is_not_retried(monkeypatch):
    manager, sleep = setup(monkeypatch, [OperationalError(1213, 'deadlock')], atomic=True)
    with pytest.raises(OperationalError):
        module.receipt(SimpleNamespace(tenant_id=1, attempt_count=1), 2, {})
    assert manager.get_or_create.call_count == 1
    sleep.assert_not_called()


def test_conflicting_receipt_is_not_overwritten(monkeypatch):
    manager, sleep = setup(monkeypatch, [(SimpleNamespace(payload={}, payload_hash='different'), False)])
    with pytest.raises(DatasetError, match='video_receipt_conflict'):
        module.receipt(SimpleNamespace(tenant_id=1, attempt_count=1), 2, {})
    assert manager.get_or_create.call_count == 1
    sleep.assert_not_called()
