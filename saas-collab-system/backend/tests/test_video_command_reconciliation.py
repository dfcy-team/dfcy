from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.management.base import CommandError
from apps.influencers.management.commands import sync_tiktok_shop_videos as worker


@pytest.mark.parametrize('enabled,status,apply,called', [
    (False, 'completed', True, False),
    (True, 'completed', True, True),
    (True, 'already_completed', True, True),
    (True, 'dry_run', False, True),
    (True, 'failed', True, False),
    (True, 'blocked', True, False),
])
def test_reconciliation_is_opt_in_and_requires_success(monkeypatch, enabled, status, apply, called):
    actor = SimpleNamespace(is_active=True, tenant_id=1)
    model = Mock()
    model.objects.get.return_value = actor
    monkeypatch.setattr(worker, 'get_user_model', lambda: model)
    monkeypatch.setattr('apps.influencers.tiktok_video_sync.resolve',
                        lambda *args: SimpleNamespace(store=SimpleNamespace(timezone='Asia/Manila')))
    monkeypatch.setattr(worker, 'run_day', lambda *args, **kwargs: {'status': status})
    reconcile = Mock(return_value={'samples_updated': 1})
    monkeypatch.setattr('apps.influencers.video_registered_reconcile.reconcile', reconcile)
    command = worker.Command()
    options = dict(actor_id=1, tenant_id=1, pause=0, days=None, date='2026-11-01',
                   all_authorized=False, store_id=23, apply=apply, refresh=False,
                   reconcile_fulfillment=enabled)
    if status in {'failed', 'blocked'}:
        with pytest.raises(CommandError):
            command.handle(**options)
    else:
        command.handle(**options)
    if called:
        reconcile.assert_called_once_with(actor, 23, apply=apply)
    else:
        reconcile.assert_not_called()
