from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from apps.integrations import production_settings


def test_runtime_snapshot_scope_reads_once_and_returns_isolated_config(monkeypatch):
    loader = Mock(return_value={"config": {"network": {"enabled": True}}})
    monkeypatch.setattr(production_settings, "runtime_snapshot", loader)

    with production_settings.runtime_snapshot_scope():
        first = production_settings.get_production_runtime_config()
        first["network"]["enabled"] = False
        second = production_settings.get_production_runtime_config()
        assert second == {"network": {"enabled": True}}
        assert loader.call_count == 1

    production_settings.get_production_runtime_config()
    assert loader.call_count == 2


def test_runtime_snapshot_scope_resets_after_exception_and_restores_nested_scope(monkeypatch):
    loader = Mock(side_effect=[
        {"config": {"version": 1}},
        {"config": {"version": 2}},
        {"config": {"version": 3}},
        {"config": {"version": 4}},
    ])
    monkeypatch.setattr(production_settings, "runtime_snapshot", loader)

    with production_settings.runtime_snapshot_scope():
        assert production_settings.get_production_runtime_config()["version"] == 1
        with production_settings.runtime_snapshot_scope():
            assert production_settings.get_production_runtime_config()["version"] == 2
        assert production_settings.get_production_runtime_config()["version"] == 1

    with pytest.raises(RuntimeError):
        with production_settings.runtime_snapshot_scope():
            assert production_settings.get_production_runtime_config()["version"] == 3
            raise RuntimeError("scope exit")

    production_settings.get_production_runtime_config()
    assert loader.call_count == 4
