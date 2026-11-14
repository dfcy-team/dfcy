from types import SimpleNamespace
from unittest.mock import MagicMock

from apps.integrations import sync_dispatch_policy as policy


def test_video_queue_is_selected_from_job_not_key(monkeypatch):
    runs, jobs = MagicMock(), MagicMock()
    runs.filter.return_value.exists.return_value = False
    jobs.filter.return_value.exists.return_value = True
    monkeypatch.setattr(policy.SyncRun, 'objects', runs)
    monkeypatch.setattr(policy.SyncJob, 'objects', jobs)
    assert policy.queue_for_run(265, 'arbitrary') == 'sync-video'
    jobs.filter.assert_called_once_with(pk=265, resource_type='video_metrics')


def test_history_keeps_its_queue(monkeypatch):
    runs = MagicMock()
    jobs = MagicMock()
    jobs.filter.return_value.exists.return_value = False
    monkeypatch.setattr(policy.SyncJob, 'objects', jobs)
    runs.filter.return_value.exists.return_value = True
    monkeypatch.setattr(policy.SyncRun, 'objects', runs)
    assert policy.queue_for_run(265, 'arbitrary') == 'sync-history'


def test_second_daily_video_is_not_admitted():
    admission = object.__new__(policy.DispatchAdmission)
    admission.video_occupied = 1
    assert not admission.claim(SimpleNamespace(resource_type='video_metrics'), 'daily')


def test_history_does_not_change_daily_video_admission():
    admission = object.__new__(policy.DispatchAdmission)
    admission.video_occupied = 1
    assert not admission.claim(SimpleNamespace(resource_type='video_metrics'), 'daily')
