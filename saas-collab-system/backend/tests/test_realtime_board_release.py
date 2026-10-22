"""Candidate release gates on isolated data; these do not replace a MySQL migration run."""
import importlib

import pytest
from django.apps import apps
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.menu_registry import load_menu_registry
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


@pytest.mark.django_db
def test_board_menu_registration_is_idempotent_without_implicit_role_or_scope_grants():
    tenant = Tenant.objects.create(code="board-release", name="Synthetic release tenant")
    permission = Permission.objects.create(code="sales_management.view", name="Sales", module="sales_management", action="view")
    role = Role.objects.create(tenant=tenant, code="operator", name="Operator")
    role.permissions.add(permission)
    scope = DataScope.objects.create(tenant=tenant, role=role, scope_type="custom", config={"store_ids": [123]})
    migration = importlib.import_module("apps.permissions.migrations.0053_register_sales_realtime_board_menu")
    migration.register(apps, None)
    migration.register(apps, None)
    assert Permission.objects.filter(code=migration.CODE).count() == 1
    menu = Permission.objects.get(code=migration.CODE)
    definition = next(row for row in load_menu_registry()["menus"] if row["code"] == migration.CODE)
    for key in ("name", "module", "action", "permission_type"):
        assert getattr(menu, key) == definition[key]
    assert menu.metadata["path"] == "/sales-management/realtime-board"
    assert menu.metadata["action_codes"] == ["sales_management.view"]
    assert set(role.permissions.values_list("code", flat=True)) == {"sales_management.view"}
    scope.refresh_from_db()
    assert scope.config == {"store_ids": [123]}


@pytest.mark.django_db
def test_board_endpoint_denies_anonymous_external_and_ungranted_internal_accounts():
    client = APIClient()
    url = "/api/internal/commerce/realtime-board/"
    assert client.get(url).status_code in (401, 403)
    tenant = Tenant.objects.create(code="board-access-gate", name="Synthetic access tenant")
    user = CustomUser.objects.create_user(username="board-ungranted", tenant=tenant, user_type="internal")
    client.force_authenticate(user=user)
    assert client.get(url).status_code == 403
    permission = Permission.objects.create(code="sales_management.view", name="Sales", module="sales_management", action="view")
    role = Role.objects.create(tenant=tenant, code="external-test", name="External test")
    role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type="all", config={})
    user.user_type = "external"
    user.save(update_fields=["user_type"])
    assert client.get(url).status_code == 403
