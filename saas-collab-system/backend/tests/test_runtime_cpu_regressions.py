from types import SimpleNamespace
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import re
from contextvars import ContextVar
import pytest
from django.core.exceptions import ValidationError
from apps.integrations import production_settings as ps

@pytest.fixture(autouse=True)
def clear_cache(monkeypatch):
    monkeypatch.setattr(ps, "_validated_snapshot_cache_key", None)
    monkeypatch.setattr(ps, "_validated_snapshot_cache_value", None)


def test_current_value_changes_and_invalid_version_never_reuse_cache(monkeypatch):
    v = SimpleNamespace(id=1, version=1, value={"connection":{"max_retries":1}})
    current = [v]
    monkeypatch.setattr(ps, "get_effective_runtime_version", lambda: current[0])
    monkeypatch.setattr(ps, "_environment_config", lambda: {})
    assert ps.runtime_snapshot()["config"]["connection"]["max_retries"] == 1
    v.value["connection"]["max_retries"] = 2
    assert ps.runtime_snapshot()["config"]["connection"]["max_retries"] == 2
    v.value = {"platforms":{"shopee":{"token":"not-a-real-secret"}}}
    assert ps.runtime_snapshot()["source"] == "invalid_database"
    current[0] = None
    assert ps.runtime_snapshot()["effective_version"] is None
    current[0] = SimpleNamespace(id=2, version=2, value={"connection":{"max_retries":0}})
    assert ps.runtime_snapshot()["config"]["connection"]["max_retries"] == 0


def test_environment_failure_retains_original_fallback_and_is_not_cached(monkeypatch):
    monkeypatch.setattr(ps, "get_effective_runtime_version", lambda: SimpleNamespace(id=1,version=1,value={}))
    def bad(): raise ValidationError("environment rejected")
    monkeypatch.setattr(ps, "_environment_config", bad)
    assert ps.runtime_snapshot()["source"] == "database"
    assert ps._validated_snapshot_cache_key is None


def test_token_file_status_is_live_even_on_cache_hit(monkeypatch, tmp_path):
    token = tmp_path / "token"
    monkeypatch.setattr(ps, "get_effective_runtime_version", lambda: None)
    monkeypatch.setattr(ps, "_environment_config", lambda: {"custody":{"auth_file_path":str(token)}})
    monkeypatch.setattr(ps, "_setting", lambda name, default=None: default)
    assert not ps.runtime_snapshot()["masked_status"]["custody"]["token_available"]
    token.write_text("test-only")
    assert ps.runtime_snapshot()["masked_status"]["custody"]["token_available"]
    token.unlink()
    assert not ps.runtime_snapshot()["masked_status"]["custody"]["token_available"]


def test_non_idempotent_url_validation_remains_compatible(monkeypatch):
    monkeypatch.setattr(ps, "get_effective_runtime_version", lambda: None)
    monkeypatch.setattr(ps, "_environment_config", lambda: {"platforms":{"tiktok":{"api_host":"https://one.example/ /"}}})
    first = ps.runtime_snapshot()
    assert first["config"]["platforms"]["tiktok"]["api_host"] == "https://one.example"
    assert ps.runtime_snapshot() == first


def test_tilde_path_including_whitespace_bypasses_cache(monkeypatch):
    monkeypatch.setattr(ps, "get_effective_runtime_version", lambda: None)
    monkeypatch.setattr(ps, "_environment_config", lambda: {"custody":{"auth_file_path":" ~/token "}})
    ps.runtime_snapshot()
    assert ps._validated_snapshot_cache_key is None


def test_concurrent_inputs_and_mutation_are_isolated(monkeypatch):
    local = ContextVar("test_input", default=0)
    monkeypatch.setattr(ps, "get_effective_runtime_version", lambda: None)
    monkeypatch.setattr(ps, "_environment_config", lambda: {"connection":{"max_retries":local.get()}})
    barrier = Barrier(4)
    def run(n):
        barrier.wait(timeout=10)
        local.set(n)
        for _ in range(20):
            result = ps.runtime_snapshot()
            assert result["config"]["connection"]["max_retries"] == n
            result["config"]["connection"]["max_retries"] = 99
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(run, range(4)))

@pytest.mark.django_db
def test_real_sql_limit_one_and_legacy_keyset_pages():
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from django.utils import timezone
    from apps.configcenter.models import SystemConfigDefinition, TenantConfigVersion
    from apps.accounts.models import CustomUser
    from apps.tenants.models import Tenant
    tenant = Tenant.objects.create(name="CPU regression", code="cpu-regression")
    actor = CustomUser.objects.create_user(username="cpu-regression",tenant=tenant)
    definition = SystemConfigDefinition.objects.get(config_key=ps.CONFIG_KEY)
    def add(n, value):
        row = TenantConfigVersion(definition=definition,config_key=ps.CONFIG_KEY,scope_key="system",version=n,value=value,status="effective",effective_at=timezone.now(),created_by=actor)
        row._config_service_write = True
        row.save()
        return row
    oldest = add(10000, {"connection":{"max_retries":1}})
    for n in range(10001,10103):
        add(n, {"modules":{"core":"enabled"}})
    with CaptureQueriesContext(connection) as captured:
        assert ps.get_effective_runtime_version().id == oldest.id
    assert len(captured) == 3
    assert re.search(r"\bLIMIT 1\b", captured[0]["sql"])
    assert all("LIMIT 100" in q["sql"] for q in captured.captured_queries[1:])
    newest = add(20000, {"connection":{"max_retries":2}})
    with CaptureQueriesContext(connection) as captured:
        assert ps.get_effective_runtime_version().id == newest.id
    assert len(captured) == 1
    assert re.search(r"\bLIMIT 1\b", captured[0]["sql"])
