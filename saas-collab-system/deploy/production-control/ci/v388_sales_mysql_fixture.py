"""Restore only the sales permission dictionary in the disposable MySQL test DB."""
from importlib import import_module
import os

import pytest
from django.apps import apps
from django.db import connection


@pytest.fixture(scope="session", autouse=True)
def isolated_sales_permission_dictionary(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        assert os.environ.get("SYNTHETIC_SALES_TEST_ONLY") == "true"
        assert connection.vendor == "mysql"
        assert connection.settings_dict["HOST"] == "127.0.0.1"
        assert connection.settings_dict["NAME"] == "test_synthetic_sales_reports"
        guards = [apps.get_model("permissions", name) for name in ("Role", "DataScope", "UserRole")]
        assert all(model.objects.count() == 0 for model in guards)
        migration = import_module("apps.permissions.migrations.0030_seed_sales_management_permissions")
        migration.seed_sales_management_permissions(apps, None)
        # --nomigrations omits later catalog seeds. Populate dictionary rows
        # only, without running sync_permissions or granting any role.
        from apps.permissions.catalog import PERMISSION_DEFINITIONS, permission_defaults

        permission = apps.get_model("permissions", "Permission")
        definitions = {item["code"]: item for item in PERMISSION_DEFINITIONS}
        for code in (
            "sales_management.exchange.submit",
            "sales_management.exchange.approve",
            "sales_management.promotion.submit",
            "sales_management.promotion.approve",
        ):
            permission.objects.update_or_create(code=code, defaults=permission_defaults(definitions[code]))
        assert all(model.objects.count() == 0 for model in guards)
        assert apps.get_model("permissions", "Permission").objects.filter(
            code__in=migration.PERMISSION_CODES
        ).count() == len(migration.PERMISSION_CODES)
