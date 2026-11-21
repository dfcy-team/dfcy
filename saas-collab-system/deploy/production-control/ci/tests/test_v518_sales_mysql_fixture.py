import ast
from contextlib import contextmanager
from copy import deepcopy
import sys
from pathlib import Path

import pytest

CI_DIR = Path(__file__).parents[1]
sys.path.insert(0, str(CI_DIR))
from v518_sales_mysql_fixture import SALES_CODES, seed_disposable_sales_permissions


class RegistryMustNotBeRead:
    def get_model(self, *args):
        raise AssertionError("Django models must not be read before target guards pass")


class FakeConnection:
    def __init__(self, host="127.0.0.1", name="test_synthetic_sales_reports", vendor="mysql"):
        self.vendor = vendor
        self.settings_dict = {"HOST": host, "NAME": name}


class Query:
    def __init__(self, rows): self.rows = rows
    def values_list(self, field, flat=False): return [row[field] for row in self.rows]


class Manager:
    def __init__(self, rows=None): self.rows = rows if rows is not None else []
    def exists(self): return bool(self.rows)
    def count(self): return len(self.rows)
    def update_or_create(self, code, defaults):
        row = next((row for row in self.rows if row["code"] == code), None)
        created = row is None
        if created:
            row = {"code": code}; self.rows.append(row)
        row.update(defaults)
        return row, created
    def filter(self, **kwargs):
        return Query([row for row in self.rows if row.get("code") in kwargs.get("code__in", [])])


class FakeRegistry:
    def __init__(self):
        self.permission = type("Permission", (), {})
        self.permission.objects = Manager()
        self.through = type("Through", (), {})
        self.through.objects = Manager()
        self.permission.roles = type("Relation", (), {"through": self.through})()
        self.models = {"Permission": self.permission}
        self.models.update({name: type(name, (), {"objects": Manager()}) for name in ("Role", "DataScope", "UserRole")})
    def get_model(self, app, name): return self.models[name]


class Atomic:
    def __init__(self, registry): self.registry = registry
    @contextmanager
    def __call__(self):
        snapshot = {name: deepcopy(model.objects.rows) for name, model in self.registry.models.items()}
        try:
            yield
        except Exception:
            for name, rows in snapshot.items(): self.registry.models[name].objects.rows[:] = rows
            raise


CATALOG = ([{"code": code} for code in SALES_CODES], lambda definition: {"label": "label:" + definition["code"], "is_active": True})


def seed(registry=None, catalog=CATALOG, atomic=None):
    registry = registry or FakeRegistry()
    atomic = atomic or Atomic(registry)
    seed_disposable_sales_permissions(environ={"SYNTHETIC_SALES_TEST_ONLY": "true"}, db_connection=FakeConnection(), model_registry=registry, catalog=catalog, atomic=atomic)
    return registry


@pytest.mark.parametrize("env,db", [
    ({}, FakeConnection()),
    ({"SYNTHETIC_SALES_TEST_ONLY": "false"}, FakeConnection()),
    ({"SYNTHETIC_SALES_TEST_ONLY": "true"}, FakeConnection(host="db")),
    ({"SYNTHETIC_SALES_TEST_ONLY": "true"}, FakeConnection(name="production")),
    ({"SYNTHETIC_SALES_TEST_ONLY": "true"}, FakeConnection(vendor="sqlite")),
])
def test_fixture_refuses_before_model_access(env, db):
    with pytest.raises(RuntimeError):
        seed_disposable_sales_permissions(environ=env, db_connection=db, model_registry=RegistryMustNotBeRead())


def test_exact_twelve_sales_definitions_are_selected():
    source = CI_DIR / "v518_sales_mysql_fixture.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SALES_CODES" for t in node.targets))
    assert len(ast.literal_eval(assignment.value)) == 12
    assert len(SALES_CODES) == len(set(SALES_CODES)) == 12
    assert {code.rsplit(".", 1)[-1] for code in SALES_CODES} >= {"submit", "approve"}


def test_seeds_exact_metadata_idempotently_without_grants_or_unrelated_permissions():
    registry = seed()
    rows = deepcopy(registry.models["Permission"].objects.rows)
    assert {row["code"] for row in rows} == set(SALES_CODES)
    assert len(rows) == 12 and all(row["label"] == "label:" + row["code"] and row["is_active"] for row in rows)
    assert registry.through.objects.count() == 0
    seed(registry)
    assert registry.models["Permission"].objects.rows == rows


@pytest.mark.parametrize("model", ["Role", "DataScope", "UserRole", "through"])
def test_existing_role_scope_userrole_or_grant_records_refuse_before_permission_writes(model):
    registry = FakeRegistry()
    target = registry.through if model == "through" else registry.models[model]
    target.objects.rows.append({"sentinel": True})
    with pytest.raises(RuntimeError): seed(registry)
    assert registry.models["Permission"].objects.rows == []


@pytest.mark.parametrize("definitions", [CATALOG[0][:-1], CATALOG[0] + [CATALOG[0][0]]])
def test_missing_or_duplicate_catalog_definitions_refuse_without_writes(definitions):
    registry = FakeRegistry()
    with pytest.raises(RuntimeError): seed(registry, (definitions, CATALOG[1]))
    assert registry.models["Permission"].objects.rows == []


def test_verification_failure_rolls_back_seed_transaction():
    class BrokenRegistry(FakeRegistry):
        def get_model(self, app, name):
            model = super().get_model(app, name)
            if name == "Permission":
                original_filter = model.objects.filter
                model.objects.filter = lambda **kwargs: Query([])
            return model
    registry = BrokenRegistry()
    with pytest.raises(RuntimeError): seed(registry)
    assert registry.models["Permission"].objects.rows == []


def test_artifact_workflow_uses_controller_plugin_and_preserves_selection():
    root = Path(__file__).parents[5]
    workflow = (root / ".github/workflows/v518-cloud-artifacts-build-only.yml").read_text(encoding="utf-8")
    assert "sales_plugin=v518_sales_mysql_fixture" in workflow
    assert "PYTHONPATH=\"$GITHUB_WORKSPACE/control/saas-collab-system/deploy/production-control/ci" in workflow
    assert "tests/test_sales_management_permissions.py" in workflow
    assert "sales_mysql_index_probe" in workflow


@pytest.mark.parametrize("change", ["optin", "vendor", "host", "base", "test_name", "mirror"])
def test_pre_setup_guard_refuses_unsafe_schema_targets(change):
    from v518_sales_mysql_fixture import validate_pre_setup_target
    env = {"SYNTHETIC_SALES_TEST_ONLY": "true"}
    db = FakeConnection(name="synthetic_sales_reports")
    db.settings_dict["TEST"] = {"NAME": None, "MIRROR": None}
    if change == "optin": env.clear()
    elif change == "vendor": db.vendor = "sqlite"
    elif change == "host": db.settings_dict["HOST"] = "production-db"
    elif change == "base": db.settings_dict["NAME"] = "saas_collab_production"
    elif change == "test_name": db.settings_dict["TEST"]["NAME"] = "saas_collab_production"
    else: db.settings_dict["TEST"]["MIRROR"] = "default"
    with pytest.raises(RuntimeError):
        validate_pre_setup_target(environ=env, db_connection=db)


@pytest.mark.parametrize("test_name", [None, "test_synthetic_sales_reports"])
def test_pre_setup_guard_accepts_only_exact_disposable_plan(test_name):
    from v518_sales_mysql_fixture import validate_pre_setup_target
    db = FakeConnection(name="synthetic_sales_reports")
    db.settings_dict["TEST"] = {"NAME": test_name, "MIRROR": None}
    validate_pre_setup_target(environ={"SYNTHETIC_SALES_TEST_ONLY": "true"}, db_connection=db)


def test_session_guard_is_early_and_fails_without_django(monkeypatch):
    import v518_sales_mysql_fixture as fixture
    assert fixture.pytest_sessionstart.pytest_impl["tryfirst"] is True
    monkeypatch.delenv("SYNTHETIC_SALES_TEST_ONLY", raising=False)
    monkeypatch.setitem(sys.modules, "django", None)
    with pytest.raises(pytest.UsageError, match="before database setup"):
        fixture.pytest_sessionstart(None)
