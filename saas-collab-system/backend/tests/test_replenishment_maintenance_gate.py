import pytest
from django.conf import settings
from django.test import override_settings
from unittest.mock import patch

from apps.supply_chain import tasks
from config.settings.base import env_bool


MAINTENANCE_BEAT_TASKS = {
    "purge-expired-replenishment-calculations",
    "recover-replenishment-calculations",
}


@pytest.mark.parametrize("setting_value", [False, None, "false", "malformed"])
@pytest.mark.parametrize(
    "task,worker",
    [
        (tasks.cleanup_replenishment_jobs, "purge_replenishment_jobs"),
        (tasks.recover_replenishment_calculation_jobs, "recover_replenishment_jobs"),
    ],
)
def test_queued_maintenance_tasks_are_noops_unless_setting_is_boolean_true(setting_value, task, worker):
    with override_settings(REPLENISHMENT_MAINTENANCE_ENABLED=setting_value):
        with patch.object(tasks, worker) as run:
            assert task() == 0
            run.assert_not_called()


@pytest.mark.parametrize(
    "task,worker",
    [
        (tasks.cleanup_replenishment_jobs, "purge_replenishment_jobs"),
        (tasks.recover_replenishment_calculation_jobs, "recover_replenishment_jobs"),
    ],
)
def test_maintenance_worker_runs_only_when_explicitly_enabled(task, worker):
    with override_settings(REPLENISHMENT_MAINTENANCE_ENABLED=True):
        with patch.object(tasks, worker, return_value=7) as run:
            assert task() == 7
            run.assert_called_once_with()


def test_maintenance_schedule_is_absent_by_default():
    assert settings.REPLENISHMENT_MAINTENANCE_ENABLED is False
    assert MAINTENANCE_BEAT_TASKS.isdisjoint(settings.CELERY_BEAT_SCHEDULE)


def test_malformed_environment_value_keeps_maintenance_disabled(monkeypatch):
    monkeypatch.setenv("REPLENISHMENT_MAINTENANCE_ENABLED", "sometimes")
    assert env_bool("REPLENISHMENT_MAINTENANCE_ENABLED", False) is False
