from datetime import timedelta
from types import SimpleNamespace

from django.utils import timezone

from apps.flash_sales.views import task_timing
from tests.test_flash_activity_pagination import reader, activity


def test_running_duration_includes_current_step_and_stops_at_lease_expiry():
    now = timezone.now()
    task = SimpleNamespace(execution_ms=2000, status='running', lease_until=now + timedelta(seconds=20),
                           state={'step_started_at': (now - timedelta(seconds=10)).isoformat(), 'sync_progress': '读取中'})
    result = task_timing(task, now)
    assert result['execution_ms'] == 12000
    assert result['execution_live_until'] == task.lease_until
    assert result['sync_progress'] == '读取中'
    assert task_timing(task, now + timedelta(seconds=30))['execution_ms'] == 32000
    assert task_timing(task, now + timedelta(seconds=30))['execution_live_until'] is None


def test_waiting_and_finished_tasks_do_not_add_retry_wait_to_execution():
    now = timezone.now()
    for status in ['waiting', 'succeeded', 'failed']:
        task = SimpleNamespace(execution_ms=2000, status=status, lease_until=None,
                               state={'step_started_at': (now - timedelta(minutes=5)).isoformat(), 'sync_progress': '旧进度'})
        assert task_timing(task, now) == {'execution_ms': 2000, 'execution_live_until': None, 'sync_progress': ''}


def test_paginated_sync_reports_real_unique_activity_count():
    adapter, calls = reader([activity(i) for i in range(101)])
    messages = []
    adapter.progress = messages.append
    assert len(adapter.activities()) == 101
    assert len(messages) == len(calls) == 4
    assert messages[-1] == '正在读取活动列表：本轮已读取 101 条活动，完成 4 次分页请求'
