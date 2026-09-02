import pytest
from django.core.management import call_command
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

    role = sync_tenant_administrator_role(tenant)

    assert role.code == TENANT_ADMIN_ROLE_CODE
    assert role.name == "管理员"
    assert role.permissions.filter(pk__in=[order_permission.pk, role_permission.pk]).count() == 2
    assert role.permissions.count() == Permission.objects.count()
    assert list(role.data_scopes.values("scope_type", "config")) == [{"scope_type": "all", "config": {}}]


def test_permission_sync_repairs_administrator_after_new_permission_is_registered():
    tenant = Tenant.objects.create(name="Sync tenant", code="sync-admin-tenant")
    role = sync_tenant_administrator_role(tenant)
    permission = Permission.objects.create(code="future.feature.view", name="Future", module="future", action="view")

    call_command("sync_permissions")

    role.refresh_from_db()
    assert role.permissions.filter(pk=permission.pk).exists()


def test_builtin_administrator_permissions_cannot_be_reduced_via_api():
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

    assert response.status_code == 409
    assert administrator.permissions.filter(code="system.roles.manage").exists()
