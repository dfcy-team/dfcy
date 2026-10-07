"""Synthetic current-model MySQL fixtures; never a production migration runner."""
from importlib import import_module
import os

import pytest
from django.apps import apps
from django.db import connection


@pytest.fixture(scope="session", autouse=True)
def isolated_permission_dictionary(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        assert os.environ.get("SYNTHETIC_LOCK_TEST_ONLY") == "true"
        assert connection.vendor == "mysql"
        assert connection.settings_dict["NAME"] == "test_synthetic_lock_scope"
        assert connection.settings_dict["HOST"] in {
            "127.0.0.1", "dfcy-lock-v221-mysql-20261003",
        }
        Role = apps.get_model("permissions", "Role")
        DataScope = apps.get_model("permissions", "DataScope")
        UserRole = apps.get_model("permissions", "UserRole")
        assert Role.objects.count() == DataScope.objects.count() == UserRole.objects.count() == 0
        import_module("apps.permissions.migrations.0002_seed_action_permissions").seed_permissions(apps, None)
        import_module("apps.permissions.migrations.0032_seed_live_readonly_sync_permission").seed_permission(apps, None)
        import_module("apps.permissions.migrations.0050_register_history_sync_permissions").register(apps, None)
        import_module("apps.permissions.migrations.0051_history_range_permission_description").update_description(apps, None)
        assert Role.objects.count() == DataScope.objects.count() == UserRole.objects.count() == 0
        assert apps.get_model("permissions", "Permission").objects.filter(code__in=[
            "integrations.run_live_readonly", "integrations.history.view", "integrations.history.manage",
        ]).count() == 3
