import pytest
from importlib import import_module
from types import SimpleNamespace
from django.apps import apps
from django.core.management import call_command
from django.db import connection
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.role_catalog import TENANT_ADMIN_ROLE_CODE, sync_tenant_administrator_role
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def test_sync_creates_full_tenant_administrator_role():
    tenant = Tenant.objects.create(name="Admin tenant", code="admin-tenant")
    order_permission, _ = Permission.objects.update_or_create(
        code="orders.view", defaults={"name": "View orders", "module": "orders", "action": "view"}
    )
    role_permission, _ = Permission.objects.update_or_create(
        code="system.roles.manage",
        defaults={"name": "Manage roles", "module": "system", "action": "roles.manage"},
    )
    delegated_field, _ = Permission.objects.update_or_create(
        code="field.employee_readonly.products.id.view",
        defaults={
            "name": "Employee product id",
            "module": "employee_readonly",
            "action": "view",
            "permission_type": "field",
            "metadata": {"resource": "employee_readonly.products", "field": "id"},
        },
    )

    role = sync_tenant_administrator_role(tenant)

    assert role.code == TENANT_ADMIN_ROLE_CODE
    assert role.name == "租户管理员"
    assert role.permissions.filter(pk__in=[order_permission.pk, role_permission.pk]).count() == 2
    assert role.permissions.count() == Permission.objects.count()
    assert role.permissions.filter(pk=delegated_field.pk).exists()
    assert role.permissions.filter(code__startswith="field.employee_readonly.").exists()
    assert list(role.data_scopes.values("scope_type", "config")) == [{"scope_type": "all", "config": {}}]
    ordinary_role = Role.objects.create(tenant=tenant, name="New role", code="new-role")
    assert ordinary_role.permissions_customized is False


def test_freeze_migration_marks_only_existing_administrator_flags_in_keyset_batches():
    freeze_existing_administrators = import_module(
        "apps.permissions.migrations.0054_role_permissions_customized"
    ).freeze_existing_administrators
    tenants = [
        Tenant(name=f"Migration tenant {index}", code=f"migration-freeze-tenant-{index}")
        for index in range(1001)
    ]
    Tenant.objects.bulk_create(tenants, batch_size=1000)
    tenants = list(Tenant.objects.filter(code__startswith="migration-freeze-tenant-").order_by("pk"))
    roles = [
        Role(tenant=tenants[index], name=f"Administrator {index}", code="administrator",
             status=Role.Status.INACTIVE if index == 1000 else Role.Status.ACTIVE)
        for index in range(1001)
    ]
    Role.objects.bulk_create(roles, batch_size=1000)
    ordinary = Role.objects.create(tenant=tenants[0], name="Ordinary", code="ordinary")
    admin_roles = list(Role.objects.filter(code="administrator").order_by("pk"))
    permissions = list(Permission.objects.order_by("pk"))
    admin_roles[0].permissions.set(permissions)
    admin_roles[1].permissions.add(permissions[0])
    scopes = [
        DataScope.objects.create(tenant=tenants[0], role=admin_roles[0], scope_type="all", config={}),
        DataScope.objects.create(tenant=tenants[1], role=admin_roles[1], scope_type="custom", config={"region": "north"}),
    ]
    through = Role.permissions.through
    before_admins = list(Role.objects.filter(code="administrator").order_by("pk").values("id", "status", "updated_at"))
    before_relations = list(
        through.objects.filter(role_id__in=[row["id"] for row in before_admins])
        .order_by("role_id", "permission_id").values_list("role_id", "permission_id")
    )
    before_scopes = list(
        DataScope.objects.filter(role_id__in=[row["id"] for row in before_admins])
        .order_by("role_id").values("role_id", "scope_type", "config")
    )

    freeze_existing_administrators(apps, SimpleNamespace(connection=connection))

    after_admins = list(Role.objects.filter(code="administrator").order_by("pk").values(
        "id", "status", "updated_at", "permissions_customized"
    ))
    assert len(after_admins) == 1001
    assert all(row["permissions_customized"] for row in after_admins)
    assert [{key: row[key] for key in ("id", "status", "updated_at")} for row in after_admins] == before_admins
    after_relations = list(
        through.objects.filter(role_id__in=[row["id"] for row in after_admins])
        .order_by("role_id", "permission_id").values_list("role_id", "permission_id")
    )
    assert after_relations == before_relations
    after_scopes = list(
        DataScope.objects.filter(role_id__in=[row["id"] for row in after_admins])
        .order_by("role_id").values("role_id", "scope_type", "config")
    )
    assert after_scopes == before_scopes
    assert ordinary.permissions_customized is False
    assert ordinary.status == Role.Status.ACTIVE
    assert list(DataScope.objects.filter(pk__in=[scope.pk for scope in scopes]).values("scope_type", "config")) == [
        {"scope_type": "all", "config": {}},
        {"scope_type": "custom", "config": {"region": "north"}},
    ]


def test_permission_sync_repairs_administrator_after_new_permission_is_registered():
    tenant = Tenant.objects.create(name="Sync tenant", code="sync-admin-tenant")
    role = sync_tenant_administrator_role(tenant)
    permission = Permission.objects.create(code="future.feature.view", name="Future", module="future", action="view")

    call_command("sync_permissions")

    role.refresh_from_db()
    assert role.permissions.filter(pk=permission.pk).exists()


def test_permission_sync_preserves_explicitly_customized_administrator_grants():
    tenant = Tenant.objects.create(name="Customized tenant", code="customized-admin-tenant")
    role = sync_tenant_administrator_role(tenant)
    retained = role.permissions.get(code="system.roles.view")
    removed = role.permissions.get(code="menu.system.users.view")
    role.permissions.remove(removed)
    role.permissions_customized = True
    role.save(update_fields=["permissions_customized"])
    newly_registered = Permission.objects.create(
        code="future.customized.view", name="Future", module="future", action="view"
    )

    sync_tenant_administrator_role(tenant)
    call_command("sync_permissions")

    role.refresh_from_db()
    assert role.permissions_customized is True
    assert role.permissions.filter(pk=retained.pk).exists()
    assert not role.permissions.filter(pk=removed.pk).exists()
    assert not role.permissions.filter(pk=newly_registered.pk).exists()


def test_ordinary_tenant_administrator_cannot_edit_administrator_permissions():
    tenant = Tenant.objects.create(name="Protected tenant", code="protected-admin-tenant")
    manage, _ = Permission.objects.update_or_create(
        code="system.roles.manage",
        defaults={"name": "Manage roles", "module": "system", "action": "roles.manage"},
    )
    view, _ = Permission.objects.update_or_create(
        code="system.roles.view", defaults={"name": "View roles", "module": "system", "action": "roles.view"}
    )
    administrator = sync_tenant_administrator_role(tenant)
    actor = CustomUser.objects.create_user(
        username="manager", password="test-password-123", tenant=tenant, user_type=CustomUser.UserType.INTERNAL
    )
    UserRole.objects.create(tenant=tenant, user=actor, role=administrator)
    client = APIClient()
    client.force_authenticate(actor)

    response = client.put(
        f"/api/internal/system/roles/{administrator.pk}/permissions/",
        {"permission_codes": [], "scope_type": "all", "scope_config": {}},
        format="json",
    )

    assert response.status_code == 403
    assert administrator.permissions.filter(code="system.roles.manage").exists()


def test_inactive_permission_is_rejected_before_delegability_and_existing_history_is_retained():
    tenant = Tenant.objects.create(name="Inactive permission tenant", code="inactive-permission-tenant")
    inactive = Permission.objects.get(code="menu.system.users.view")
    inactive.metadata = {"registry_status": "inactive"}
    inactive.save(update_fields=["metadata"])
    actor = CustomUser.objects.create_user(
        username="inactive-permission-admin", password="test-password-123", tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    administrator = sync_tenant_administrator_role(tenant)
    UserRole.objects.create(tenant=tenant, user=actor, role=administrator)
    target = Role.objects.create(tenant=tenant, name="Target", code="inactive-permission-target")
    client = APIClient()
    client.force_authenticate(actor)

    rejected = client.put(
        f"/api/internal/system/roles/{target.pk}/permissions/",
        {"permission_codes": [inactive.code], "scope_type": "all", "scope_config": {}},
        format="json",
    )
    assert rejected.status_code == 400
    assert "不能新增已停用或已退役的权限" in str(rejected.json())
    target.permissions.add(inactive)

    retained = client.put(
        f"/api/internal/system/roles/{target.pk}/permissions/",
        {"permission_codes": ["reports.view"], "scope_type": "all", "scope_config": {}},
        format="json",
    )

    assert retained.status_code == 200, retained.content
    assert target.permissions.filter(pk=inactive.pk).exists()


def test_tenant_role_manager_still_cannot_delegate_active_undelegable_permission():
    tenant = Tenant.objects.create(name="Delegation guard tenant", code="delegation-guard-tenant")
    actor = CustomUser.objects.create_user(
        username="limited-role-manager", password="test-password-123", tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    manager_role = Role.objects.create(tenant=tenant, name="Role manager", code="limited-role-manager")
    manager_role.permissions.add(
        Permission.objects.get(code="system.roles.manage"),
        Permission.objects.get(code="system.roles.view"),
    )
    DataScope.objects.create(tenant=tenant, role=manager_role, scope_type="all", config={})
    UserRole.objects.create(tenant=tenant, user=actor, role=manager_role)
    target = Role.objects.create(tenant=tenant, name="Target", code="undelegable-target")
    client = APIClient()
    client.force_authenticate(actor)

    response = client.put(
        f"/api/internal/system/roles/{target.pk}/permissions/",
        {"permission_codes": ["system.users.manage"], "scope_type": "all", "scope_config": {}},
        format="json",
    )

    assert response.status_code == 403
    assert not target.permissions.filter(code="system.users.manage").exists()


def test_platform_superuser_can_customise_administrator_menu_action_and_field_grants():
    tenant = Tenant.objects.create(name="Editable tenant", code="editable-admin-tenant")
    actor = CustomUser.objects.create_user(
        username="platform-editor", password="test-password-123", tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL, is_superuser=True, is_staff=True,
    )
    administrator = sync_tenant_administrator_role(tenant)
    desired_codes = [
        "menu.system.users.view",
        "system.users.view",
        "field.system.users.full_name.view",
    ]
    client = APIClient()
    client.force_authenticate(actor)

    response = client.put(
        f"/api/internal/system/roles/{administrator.pk}/permissions/",
        {
            "menu_permission_codes": [desired_codes[0]],
            "action_permission_codes": [desired_codes[1]],
            "field_permission_codes": [desired_codes[2]],
            "scope_type": "all",
            "scope_config": {},
        },
        format="json",
    )

    assert response.status_code == 200, response.content
    administrator.refresh_from_db()
    assert administrator.permissions_customized is True
    assert set(administrator.permissions.values_list("code", flat=True)) == set(desired_codes)
    assert list(administrator.data_scopes.values("scope_type", "config")) == [
        {"scope_type": "all", "config": {}}
    ]

    rejected_scope_change = client.put(
        f"/api/internal/system/roles/{administrator.pk}/permissions/",
        {
            "menu_permission_codes": desired_codes[:1],
            "action_permission_codes": desired_codes[1:2],
            "field_permission_codes": desired_codes[2:],
            "scope_type": "custom",
            "scope_config": {},
        },
        format="json",
    )

    assert rejected_scope_change.status_code == 400
    administrator.refresh_from_db()
    assert list(administrator.data_scopes.values("scope_type", "config")) == [
        {"scope_type": "all", "config": {}}
    ]


def test_external_platform_superuser_cannot_edit_tenant_administrator():
    actor_tenant = Tenant.objects.create(name="External actor tenant", code="external-actor-tenant")
    target_tenant = Tenant.objects.create(name="External target tenant", code="external-target-tenant")
    actor = CustomUser.objects.create_user(
        username="external-platform-editor", password="test-password-123", tenant=actor_tenant,
        user_type=CustomUser.UserType.EXTERNAL, is_superuser=True, is_staff=True,
    )
    administrator = sync_tenant_administrator_role(target_tenant)
    before = set(administrator.permissions.values_list("code", flat=True))
    client = APIClient()
    client.force_authenticate(actor)

    response = client.put(
        f"/api/internal/system/roles/{administrator.pk}/permissions/?tenant_id={target_tenant.pk}",
        {"permission_codes": [], "scope_type": "all", "scope_config": {}},
        format="json",
    )

    assert response.status_code == 403
    administrator.refresh_from_db()
    assert administrator.permissions_customized is False
    assert set(administrator.permissions.values_list("code", flat=True)) == before
