from contextlib import nullcontext
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def runner(monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[1] / "scripts" / "vm34_tiktok_dataset_trial.py"
    spec = importlib.util.spec_from_file_location("trial_runner_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # This fixture isolates the watchdog state machine, not MySQL session SQL.
    monkeypatch.setattr(module, "limit_lock_wait", Mock(return_value=None))
    monkeypatch.setattr(module, "reset_lock_wait", Mock())
    from django import db, contrib
    from apps.audit import services as audits
    from apps.audit import models as audit_models
    from apps.integrations import models
    from apps.permissions import services as permissions
    from apps.tenants import models as tenants
    from apps.influencers.management.commands import export_tiktok_shop_dataset as command
    from apps.influencers import tiktok_shop_dataset as dataset

    actor = SimpleNamespace(pk=1, tenant_id=1, tenant=SimpleNamespace(pk=1))
    user_model = SimpleNamespace(objects=Mock())
    user_model.objects.get.return_value = actor
    monkeypatch.setattr(contrib.auth, "get_user_model", lambda: user_model)
    monkeypatch.setattr(db.transaction, "atomic", nullcontext)
    monkeypatch.setattr(permissions, "check_user_permission", lambda *args: True)
    config = SimpleNamespace(network_enabled=True, sync_read_enabled=False, sync_write_enabled=False,
                             status="verified", config_version=10, save=Mock())
    config_manager = Mock()
    config_manager.select_for_update.return_value.get.return_value = config
    monkeypatch.setattr(models.PlatformIntegrationConfig, "objects", config_manager)
    monkeypatch.setattr(tenants.Tenant, "objects", Mock())
    for model in (models.SyncJob, models.SyncRun):
        manager = Mock()
        manager.filter.return_value.exists.return_value = False
        monkeypatch.setattr(model, "objects", manager)
    auths = [SimpleNamespace(store_id=23, integration_config_id=7, platform_store_id="7495739162492111766",
                             store=SimpleNamespace(code="TK1PH", timezone="Asia/Manila")),
             SimpleNamespace(store_id=8, integration_config_id=7, platform_store_id="7495704131459517026",
                             store=SimpleNamespace(code="TKKJ1PH", timezone="Asia/Manila"))]
    monkeypatch.setattr(command, "resolve_export_scope", lambda *args: (auths, []))
    events = []
    def audit(**kwargs):
        events.append((kwargs["action"], config.sync_read_enabled))
        armed = SimpleNamespace(pk=55, after_data=kwargs["after_data"])
        if kwargs["action"] == "tk_dataset_trial_armed":
            audit_manager.select_for_update.return_value.get.return_value = armed
        return armed
    audit_manager = Mock()
    audit_manager.filter.return_value.exists.return_value = False
    monkeypatch.setattr(audit_models.OperationLog, "objects", audit_manager)
    monkeypatch.setattr(audits, "write_operation_log", audit)
    child = SimpleNamespace(poll=lambda: None, terminate=Mock(), wait=Mock())
    def spawn(*args, **kwargs):
        assert not config.sync_read_enabled
        assert kwargs["start_new_session"] is True
        events.append(("watchdog_spawned", False))
        (tmp_path / "watchdog-ready-55").write_text("ready")
        return child
    monkeypatch.setattr(module.subprocess, "Popen", spawn)
    monkeypatch.setattr(module.signal, "signal", Mock())
    # The runner is Linux-only; its mocked signal API also needs to exist on Windows.
    monkeypatch.setattr(module.signal, "alarm", Mock(), raising=False)
    monkeypatch.setattr(module.signal, "SIGALRM", 14, raising=False)
    def restore(_id):
        config.sync_read_enabled = False
        events.append(("restored", False))
        return True
    monkeypatch.setattr(module, "restore", restore)
    def export(**kwargs):
        assert config.sync_read_enabled
        assert events[:3] == [("tk_dataset_trial_armed", False), ("watchdog_spawned", False), ("tk_dataset_trial_enable", True)]
        return {"components": [{"status": "complete"}]}, "a" * 64
    monkeypatch.setattr(dataset, "export_artifact", export)
    return module, config, events, child, dataset


def test_compensation_is_ready_before_flag_activation(runner, tmp_path):
    module, config, events, child, _ = runner
    result = module.run(tmp_path)
    assert result["success"] and result["readonly_flag_restored"]
    assert not config.sync_read_enabled
    child.terminate.assert_called_once()


def test_staging_options_are_forwarded_and_compensated(runner, tmp_path, monkeypatch):
    module, config, events, child, dataset = runner
    export = Mock(return_value=({"components": [{"status": "partial"}]}, "a" * 64))
    monkeypatch.setattr(dataset, "export_artifact", export)
    result = module.run(tmp_path, staging=True, enrich_orders=True, start_date="2026-10-08",
                        end_date="2026-10-08", timeout_seconds=300)
    assert result["artifact_created"] and not result["success"] and result["readonly_flag_restored"]
    assert export.call_args.kwargs["staging"] is True
    assert export.call_args.kwargs["enrich_orders"] is True
    assert export.call_args.kwargs["start_date"] == "2026-10-08"
    assert not config.sync_read_enabled


@pytest.mark.parametrize("options", [{"store_ids": [99]}, {"store_ids": [23, 23]},
                                      {"timeout_seconds": 1801}, {"enrich_orders": True}])
def test_unapproved_trial_options_do_not_arm(runner, tmp_path, options):
    module, config, events, child, dataset = runner
    with pytest.raises(ValueError, match="invalid_controlled_trial_scope"):
        module.run(tmp_path, **options)
    assert events == [] and not config.sync_read_enabled


def test_dead_compensator_prevents_any_activation(runner, tmp_path, monkeypatch):
    module, config, events, child, _ = runner
    child.poll = lambda: 1
    result = module.run(tmp_path)
    assert not result["success"]
    assert ("tk_dataset_trial_enable", True) not in events
    assert not config.sync_read_enabled


def test_interrupt_between_arming_and_activation_never_opens_flag(runner, tmp_path, monkeypatch):
    module, config, events, child, _ = runner
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(module.subprocess, "Popen", interrupt)
    with pytest.raises(KeyboardInterrupt):
        module.run(tmp_path)
    assert not config.sync_read_enabled
    assert ("tk_dataset_trial_enable", True) not in events


def test_failed_components_are_not_success_and_flag_restores(runner, tmp_path, monkeypatch):
    module, config, events, child, dataset = runner
    monkeypatch.setattr(dataset, "export_artifact", lambda **kwargs: ({"components": [{"status": "failed"}]}, "a" * 64))
    result = module.run(tmp_path)
    assert not result["success"] and result["readonly_flag_restored"]
    assert not config.sync_read_enabled


def test_query_timeout_restores_flag(runner, tmp_path, monkeypatch):
    module, config, events, child, dataset = runner
    def timeout(**kwargs):
        raise TimeoutError()
    monkeypatch.setattr(dataset, "export_artifact", timeout)
    result = module.run(tmp_path)
    assert result["error_type"] == "TimeoutError" and result["readonly_flag_restored"]
    assert not config.sync_read_enabled


def test_arm_expiring_during_activation_lock_wait_blocks_enable(runner, tmp_path, monkeypatch):
    module, config, events, child, dataset = runner
    from apps.audit import models as audits
    manager = audits.OperationLog.objects
    def expired_after_lock(**kwargs):
        armed = manager.select_for_update.return_value.get.return_value
        armed.after_data["activation_deadline_epoch"] = 0
        return armed
    manager.select_for_update.return_value.get.side_effect = expired_after_lock
    result = module.run(tmp_path)
    assert not result["success"]
    assert ("tk_dataset_trial_enable", True) not in events
    assert not config.sync_read_enabled


def test_cancelled_arm_blocks_enable_after_readiness(runner, tmp_path, monkeypatch):
    module, config, events, child, dataset = runner
    from apps.audit import models as audits
    audits.OperationLog.objects.filter.return_value.exists.return_value = True
    result = module.run(tmp_path)
    assert not result["success"]
    assert ("tk_dataset_trial_enable", True) not in events
    assert not config.sync_read_enabled


def test_transient_restore_fail_fail_success(runner, monkeypatch):
    module, config, events, child, dataset = runner
    from django import db
    restore = Mock(side_effect=[db.OperationalError(), db.OperationalError(), True])
    monkeypatch.setattr(module, "restore", restore)
    monkeypatch.setattr(module, "limit_lock_wait", Mock())
    sleep = Mock()
    monkeypatch.setattr(module.time, "sleep", sleep)
    monkeypatch.setattr(db, "close_old_connections", Mock())
    assert module.restore_with_retries(55) is True
    assert restore.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [1, 2]


def test_exhausted_restore_is_explicit_escalation(runner, monkeypatch):
    module, config, events, child, dataset = runner
    from django import db
    restore = Mock(side_effect=db.OperationalError())
    monkeypatch.setattr(module, "restore", restore)
    monkeypatch.setattr(module, "limit_lock_wait", Mock())
    monkeypatch.setattr(module.time, "sleep", Mock())
    monkeypatch.setattr(db, "close_old_connections", Mock())
    with pytest.raises(module.RestoreExhausted, match="manual_verification"):
        module.restore_with_retries(55)
    assert restore.call_count == 3


@pytest.mark.django_db
def test_mysql_session_lock_timeout_is_bounded_and_restored():
    from django.db import connection

    if connection.vendor != "mysql":
        pytest.skip("MySQL session timeout contract")
    path = Path(__file__).resolve().parents[1] / "scripts" / "vm34_tiktok_dataset_trial.py"
    spec = importlib.util.spec_from_file_location("trial_runner_session_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with connection.cursor() as cursor:
        cursor.execute("SELECT @@SESSION.innodb_lock_wait_timeout")
        original = int(cursor.fetchone()[0])
    try:
        assert module.limit_lock_wait() == original
        with connection.cursor() as cursor:
            cursor.execute("SELECT @@SESSION.innodb_lock_wait_timeout")
            assert int(cursor.fetchone()[0]) == 10
        module.reset_lock_wait(original)
        with connection.cursor() as cursor:
            cursor.execute("SELECT @@SESSION.innodb_lock_wait_timeout")
            assert int(cursor.fetchone()[0]) == original
    finally:
        module.reset_lock_wait(original)
