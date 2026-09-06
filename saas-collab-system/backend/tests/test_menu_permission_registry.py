import importlib

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.catalog import runtime_permission_definitions
from apps.permissions.menu_registry import load_menu_registry
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.role_catalog import sync_tenant_administrator_role
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def test_frontend_sidebar_is_the_auditable_menu_registration_source():
    payload = load_menu_registry()
    menus = payload["menus"]
    assert len(menus) > 50
    assert all(item["permission_type"] == "menu" for item in menus)
    assert all(item["code"].startswith("menu.") for item in menus)
    assert all(item["metadata"]["source"] == "frontend/src/router/menu.js" for item in menus)
    assert all(item["metadata"]["status"] == "active" for item in menus)


def test_backend_registry_read_does_not_require_node(monkeypatch):
    monkeypatch.setenv("PATH", "")
    payload = load_menu_registry()
    assert len(payload["menus"]) > 50


def test_sync_adds_new_menu_grants_from_existing_action_grants_without_revoking():
    tenant = Tenant.objects.create(name="Menu registry tenant", code="menu-registry-tenant")
    role = Role.objects.create(tenant=tenant, name="开发查看员", code="development-reader")
    role.permissions.add(Permission.objects.get(code="development.requirement.view"))

    call_command("sync_permissions")

    menu_code = next(
        item["code"] for item in runtime_permission_definitions()
        if item.get("permission_type") == "menu"
        and item["metadata"].get("path") == "/development/requirements"
    )
    assert role.permissions.filter(code=menu_code).exists()


def test_removed_source_menu_is_retired_without_deleting_permission_or_role_grant(monkeypatch):
    call_command("sync_permissions")
    target = "menu.system.roles.view"
    tenant = Tenant.objects.create(name="Retired menu tenant", code="retired-menu-tenant")
    role = Role.objects.create(tenant=tenant, name="角色查看员", code="role-reader")
    permission = Permission.objects.get(code=target)
    role.permissions.add(permission)

    source_definitions = runtime_permission_definitions()
    command_module = importlib.import_module("apps.permissions.management.commands.sync_permissions")
    monkeypatch.setattr(
        command_module,
        "runtime_permission_definitions",
        lambda: tuple(item for item in source_definitions if item["code"] != target),
    )

    with pytest.raises(CommandError, match="retired_menu"):
        call_command("sync_permissions", "--check")

    call_command("sync_permissions")
    permission.refresh_from_db()
    assert permission.metadata["registry_status"] == "inactive"
    assert role.permissions.filter(code=target).exists()


def test_retired_menu_is_hidden_from_directory_and_preserved_by_role_edit():
    tenant = Tenant.objects.create(name="Retired edit tenant", code="retired-edit-tenant")
    administrator = sync_tenant_administrator_role(tenant)
    actor = CustomUser.objects.create_user(
        username="retired-menu-admin", password="test-password-123", tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    UserRole.objects.create(tenant=tenant, user=actor, role=administrator)
    role = Role.objects.create(tenant=tenant, name="历史菜单角色", code="retired-menu-role")
    retired = Permission.objects.create(
        code="menu.legacy.page.view", name="历史菜单", module="legacy", action="page.view",
        permission_type=Permission.PermissionType.MENU,
        metadata={"registry_status": "inactive", "status": "inactive"},
    )
    role.permissions.add(retired, Permission.objects.get(code="reports.view"))
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})

    client = APIClient()
    client.force_authenticate(actor)
    directory = client.get("/api/internal/system/permissions/?module=legacy")
    assert directory.status_code == 200
    assert retired.code not in {item["code"] for item in directory.json()["data"]["results"]}

    response = client.put(
        f"/api/internal/system/roles/{role.pk}/permissions/",
        {"action_permission_codes": ["reports.view"], "menu_permission_codes": [],
         "field_permission_codes": [], "scope_type": "all", "scope_config": {}},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert role.permissions.filter(code=retired.code).exists()
