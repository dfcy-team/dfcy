import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.role_catalog import sync_tenant_administrator_role
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def setup_assignment(actor_kind, target_code):
    tenant = Tenant.objects.create(name="Inactive assignment", code=f"inactive-{target_code}")
    actor = CustomUser.objects.create_user(
        username=f"inactive-{actor_kind}-{target_code}",
        password="test-password-123",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
        is_superuser=(actor_kind == "superuser"),
        is_staff=(actor_kind == "superuser"),
    )
    if actor_kind == "tenantadmin":
        admin_role = sync_tenant_administrator_role(tenant)
        UserRole.objects.create(tenant=tenant, user=actor, role=admin_role)
    target = Role.objects.create(tenant=tenant, name="目标角色", code=target_code)
    DataScope.objects.create(tenant=tenant, role=target, scope_type="all", config={})
    return actor, target


def assign(client, role, codes):
    return client.put(
        f"/api/internal/system/roles/{role.pk}/permissions/",
        {"permission_codes": codes, "scope_type": "all", "scope_config": {}},
        format="json",
    )


@pytest.mark.parametrize("actor_kind", ["tenantadmin", "superuser"])
def test_inactive_permission_cannot_be_granted_even_by_privileged_actor(actor_kind):
    inactive = Permission.objects.get(code="menu.system.users.view")
    inactive.metadata = {"registry_status": "inactive"}
    inactive.save(update_fields=["metadata"])
    actor, target = setup_assignment(actor_kind, f"reject-{actor_kind}")
    client = APIClient()
    client.force_authenticate(actor)

    response = assign(client, target, [inactive.code])

    assert response.status_code == 400
    assert "不能新增已停用或已退役的权限" in str(response.json())
    assert not target.permissions.filter(pk=inactive.pk).exists()


def test_existing_inactive_history_is_retained_when_omitted():
    inactive = Permission.objects.get(code="menu.system.users.view")
    inactive.metadata = {"status": "retired"}
    inactive.save(update_fields=["metadata"])
    actor, target = setup_assignment("tenantadmin", "retain-history")
    target.permissions.add(inactive)
    client = APIClient()
    client.force_authenticate(actor)

    response = assign(client, target, ["reports.view"])

    assert response.status_code == 200, response.content
    assert target.permissions.filter(pk=inactive.pk).exists()
    assert target.permissions.filter(code="reports.view").exists()


def test_active_grant_succeeds_and_mixed_inactive_request_is_atomic():
    inactive = Permission.objects.get(code="menu.system.users.view")
    inactive.metadata = {"registry_status": "inactive"}
    inactive.save(update_fields=["metadata"])
    actor, target = setup_assignment("superuser", "atomic-mixed")
    client = APIClient()
    client.force_authenticate(actor)

    active_response = assign(client, target, ["reports.view"])
    assert active_response.status_code == 200, active_response.content
    assert target.permissions.filter(code="reports.view").exists()

    mixed_response = assign(client, target, ["system.users.view", inactive.code])
    assert mixed_response.status_code == 400
    assert target.permissions.filter(code="reports.view").exists()
    assert not target.permissions.filter(code="system.users.view").exists()
    assert not target.permissions.filter(pk=inactive.pk).exists()
