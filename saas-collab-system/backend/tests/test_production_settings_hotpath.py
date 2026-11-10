from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError

from apps.integrations import production_settings as settings

@pytest.fixture(autouse=True)
def clear_cache(monkeypatch):
    monkeypatch.setattr(settings, "_validated_snapshot_cache_key", None)
    monkeypatch.setattr(settings, "_validated_snapshot_cache_value", None)


def test_environment_is_reread_and_returned_config_is_isolated(monkeypatch):
    monkeypatch.setattr(settings, "get_effective_runtime_version", lambda: None)
    monkeypatch.setattr(settings, "_environment_config", lambda: {"connection": {"max_retries": 1}})

    first = settings.get_production_runtime_config()
    first["connection"]["max_retries"] = 99
    assert settings.get_production_runtime_config()["connection"]["max_retries"] == 1
    monkeypatch.setattr(settings, "_environment_config", lambda: {"connection": {"max_retries": 2}})

    second = settings.get_production_runtime_config()
    assert second["connection"]["max_retries"] == 2


def test_invalid_environment_fails_closed_without_reusing_previous_value(monkeypatch):
    monkeypatch.setattr(settings, "get_effective_runtime_version", lambda: None)
    monkeypatch.setattr(settings, "_environment_config", lambda: {"platforms": {"shopee": {"token": "bad"}}})

    snapshot = settings.runtime_snapshot()

    assert snapshot["source"] == "invalid_environment"
    assert snapshot["valid"] is False
    assert snapshot["config"] == settings.SAFE_DEFAULTS


def test_default_runtime_validates_environment_once(monkeypatch):
    monkeypatch.setattr(settings, "get_effective_runtime_version", lambda: None)
    marker = {"connection": {"max_retries": 1}}
    monkeypatch.setattr(settings, "_environment_config", lambda: marker)
    original = settings.validate_runtime_config
    calls = []

    def counted(value):
        calls.append(1)
        return original(value)

    monkeypatch.setattr(settings, "validate_runtime_config", counted)
    settings._load_snapshot()
    settings._load_snapshot()

    # The initial path preserves both validations; the second call is served
    # from the verified one-entry cache.
    assert len(calls) == 2


def test_cache_key_tracks_in_place_version_edits_and_preserves_order_and_types(monkeypatch):
    monkeypatch.setattr(settings, "_environment_config", lambda: {})
    version = SimpleNamespace(id=901, version=1, value={"connection": {"max_retries": 1}})
    monkeypatch.setattr(settings, "get_effective_runtime_version", lambda: version)
    original = settings.validate_runtime_config
    calls = []

    def counted(value):
        calls.append(1)
        return original(value)

    monkeypatch.setattr(settings, "validate_runtime_config", counted)
    settings._load_snapshot()
    before = len(calls)
    version.value["connection"]["max_retries"] = 2
    settings._load_snapshot()
    assert len(calls) > before
    assert settings._freeze_config({"market": "row", "region": "x"}) != settings._freeze_config(
        {"region": "x", "market": "row"}
    )
    assert settings._freeze_config({"flag": True}) != settings._freeze_config({"flag": 1})
