"""Controller-owned disposable sales permission fixture for MySQL regressions."""
import os

import pytest


SALES_CODES = (
    "sales_management.view",
    "sales_management.orders.view",
    "sales_management.returns.view",
    "sales_management.stores.view",
    "sales_management.skus.view",
    "sales_management.export",
    "sales_management.data_quality.view",
    "sales_management.sync.view",
    "sales_management.exchange.submit",
    "sales_management.exchange.approve",
    "sales_management.promotion.submit",
    "sales_management.promotion.approve",
)


def validate_pre_setup_target(*, environ=None, db_connection=None):
    """Refuse unsafe targets before pytest-django can create/sync a test DB."""
    environ = os.environ if environ is None else environ
    if environ.get("SYNTHETIC_SALES_TEST_ONLY") != "true":
        raise RuntimeError("synthetic sales opt-in required before database setup")
    if db_connection is None:
        from django.db import connection as db_connection
    settings = db_connection.settings_dict
    test = settings.get("TEST") or {}
    planned_name = test.get("NAME") or "test_" + str(settings.get("NAME", ""))
    if (db_connection.vendor != "mysql" or settings.get("HOST") != "127.0.0.1"
            or settings.get("NAME") != "synthetic_sales_reports"
            or planned_name != "test_synthetic_sales_reports" or test.get("MIRROR")):
        raise RuntimeError("refusing unsafe sales test database setup target")


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    try:
        validate_pre_setup_target()
    except RuntimeError as exc:
        raise pytest.UsageError(str(exc)) from exc


def seed_disposable_sales_permissions(*, environ=None, db_connection=None, model_registry=None, catalog=None, atomic=None):
    environ = os.environ if environ is None else environ
    if environ.get("SYNTHETIC_SALES_TEST_ONLY") != "true":
        raise RuntimeError("synthetic sales opt-in required")
    if db_connection is None:
        from django.db import connection as db_connection
    settings = db_connection.settings_dict
    if db_connection.vendor != "mysql" or settings.get("HOST") != "127.0.0.1" or settings.get("NAME") != "test_synthetic_sales_reports":
        raise RuntimeError("refusing non-disposable sales database")

    # Resolve catalog and models only after all external-target guards passed.
    if catalog is None:
        from apps.permissions.catalog import PERMISSION_DEFINITIONS, permission_defaults
    else:
        PERMISSION_DEFINITIONS, permission_defaults = catalog
    definitions_list = [item for item in PERMISSION_DEFINITIONS if item.get("code") in SALES_CODES]
    definitions = {item["code"]: item for item in definitions_list}
    if len(definitions_list) != len(SALES_CODES) or set(definitions) != set(SALES_CODES):
        raise RuntimeError("sales permission catalog is missing or has duplicate definitions")
    if model_registry is None:
        from django.apps import apps as model_registry
    if atomic is None:
        from django.db.transaction import atomic
    Permission = model_registry.get_model("permissions", "Permission")
    guard_models = [model_registry.get_model("permissions", name) for name in ("Role", "DataScope", "UserRole")]
    through = Permission.roles.through
    with atomic():
        if any(model.objects.exists() for model in guard_models) or through.objects.exists():
            raise RuntimeError("refusing fixture seed when roles, scopes, user roles, or grants exist")
        grants_before = through.objects.count()
        for code in SALES_CODES:
            Permission.objects.update_or_create(code=code, defaults=permission_defaults(definitions[code]))
        actual = set(Permission.objects.filter(code__in=SALES_CODES).values_list("code", flat=True))
        if actual != set(SALES_CODES) or through.objects.count() != grants_before:
            raise RuntimeError("sales permission fixture verification failed")
        if any(model.objects.exists() for model in guard_models):
            raise RuntimeError("fixture unexpectedly changed role-related records")


@pytest.fixture(scope="session", autouse=True)
def isolated_sales_permission_dictionary(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        seed_disposable_sales_permissions()
