import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.role_catalog import sync_tenant_administrator_role
from apps.permissions.services import check_user_permission, has_field_permission
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def create_internal(tenant, username, *, is_superuser=False):
    return CustomUser.objects.create_user(
        username=username,
        password="test-password-123",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
        is_superuser=is_superuser,
        is_staff=is_superuser,
    )


def grant_role(user, code, permission_codes, *, scope_type=DataScope.ScopeType.ALL):
    role = Role.objects.create(tenant=user.tenant, name=code, code=code)
    role.permissions.set(Permission.objects.filter(code__in=permission_codes))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=scope_type, config={"all": True} if scope_type == "all" else {})
    return role


def test_permission_catalog_exposes_separate_menu_action_and_field_surfaces():
    assert Permission.objects.get(code="system.users.view").permission_type == Permission.PermissionType.ACTION
    assert Permission.objects.get(code="menu.system.users.view").permission_type == Permission.PermissionType.MENU
    field = Permission.objects.get(code="field.system.users.full_name.view")
    assert field.permission_type == Permission.PermissionType.FIELD
    assert field.metadata["resource"] == "users"


def test_menu_grant_alone_cannot_authorize_system_api():
    tenant = Tenant.objects.create(name="Menu tenant", code="menu-tenant")
    user = create_internal(tenant, "menu-only")
    grant_role(user, "menu-reader", ["menu.system.users.view"])

    client = APIClient()
    client.force_authenticate(user)
    response = client.get("/api/internal/system/users/")

    assert response.status_code == 403
    assert check_user_permission(user, "system.users.view") is False


def test_field_compatibility_is_scoped_to_the_requested_resource():
    tenant = Tenant.objects.create(name="Field tenant", code="field-tenant")
    user = create_internal(tenant, "field-reader")
    grant_role(user, "field-reader", ["field.system.users.full_name.view"])

    assert has_field_permission(user, "field.system.users.full_name.view") is True
    assert has_field_permission(user, "field.system.users.department.view") is False
    # A users allow-list does not turn on deny-by-default for other resources.
    assert has_field_permission(user, "field.system.roles.name.view") is True
    assert has_field_permission(user, "field.system.tenants.name.view") is True


def test_user_directory_applies_field_allow_list_without_exposing_sensitive_values():
    tenant = Tenant.objects.create(name="Field API tenant", code="field-api-tenant")
    user = create_internal(tenant, "field-api-reader")
    grant_role(user, "field-api-reader", ["system.users.view", "field.system.users.full_name.view"])

    client = APIClient()
    client.force_authenticate(user)
    response = client.get("/api/internal/system/users/")

    assert response.status_code == 200
    row = next(item for item in response.json()["data"]["results"] if item["id"] == user.pk)
    assert row["full_name"] == ""
    assert "department_name" not in row
    assert "roles" not in row
    assert "is_active" not in row
    assert row["email_masked"] == ""
    assert row["phone_masked"] == ""


def test_platform_superuser_must_supply_target_tenant_for_cross_tenant_role_operations():
    actor_tenant = Tenant.objects.create(name="Platform tenant", code="platform-tenant")
    target_tenant = Tenant.objects.create(name="Target tenant", code="target-tenant")
    superuser = create_internal(actor_tenant, "platform", is_superuser=True)
    role = Role.objects.create(tenant=target_tenant, name="Target viewer", code="target-viewer")
    report_permission = Permission.objects.get(code="reports.view")
    role.permissions.add(report_permission)

    client = APIClient()
    client.force_authenticate(superuser)
    selected = client.get(f"/api/internal/system/roles/?tenant_id={target_tenant.pk}")
    assert selected.status_code == 200
    assert selected.json()["data"]["tenant"]["id"] == target_tenant.pk
    assert selected.json()["data"]["results"][0]["tenant_id"] == target_tenant.pk

    # A global role id cannot switch the target context implicitly.
    assert client.patch(
        f"/api/internal/system/roles/{role.pk}/",
        {"name": "should-not-switch-tenant"},
        format="json",
    ).status_code == 404
    updated = client.put(
        f"/api/internal/system/roles/{role.pk}/permissions/?tenant_id={target_tenant.pk}",
        {
            "action_permission_codes": ["reports.view"],
            "menu_permission_codes": [],
            "field_permission_codes": [],
            "scope_type": "all",
            "scope_config": {},
        },
        format="json",
    )
    assert updated.status_code == 200
    role.refresh_from_db()
    assert role.permissions.filter(code="reports.view").exists()
    audit = OperationLog.objects.filter(tenant=target_tenant, action="role_permissions_update").latest("id")
    assert audit.after_data["actor_tenant_id"] == actor_tenant.pk
    assert audit.after_data["target_tenant_id"] == target_tenant.pk
    assert audit.after_data["cross_tenant"] is True

    regular = create_internal(actor_tenant, "regular-manager")
    grant_role(regular, "role-manager", ["system.roles.view", "system.roles.manage"])
    denied = APIClient()
    denied.force_authenticate(regular)
    response = denied.get(f"/api/internal/system/roles/?tenant_id={target_tenant.pk}")
    assert response.status_code == 403


def test_platform_tenant_creation_initializes_protected_administrator_role():
    actor_tenant = Tenant.objects.create(name="Platform tenant", code="platform-create")
    superuser = create_internal(actor_tenant, "platform-create-user", is_superuser=True)
    client = APIClient()
    client.force_authenticate(superuser)

    response = client.post(
        "/api/internal/system/tenants/",
        {"name": "Created tenant", "code": "created-tenant", "status": "active"},
        format="json",
    )

    assert response.status_code == 201
    tenant = Tenant.objects.get(code="created-tenant")
    administrator = Role.objects.get(tenant=tenant, code="administrator")
    assert administrator.status == Role.Status.ACTIVE
    assert administrator.permissions.count() == Permission.objects.count()
    assert list(administrator.data_scopes.values_list("scope_type", flat=True)) == [DataScope.ScopeType.ALL]


def test_only_platform_or_existing_administrator_can_grant_or_revoke_administrator():
    tenant = Tenant.objects.create(name="Protected tenant", code="protected-tenant")
    administrator = sync_tenant_administrator_role(tenant)
    manager = create_internal(tenant, "role-manager")
    grant_role(manager, "role-manager", ["system.users.view", "system.users.manage"])
    target = create_internal(tenant, "target-user")

    manager_client = APIClient()
    manager_client.force_authenticate(manager)
    grant_denied = manager_client.put(
        f"/api/internal/system/users/{target.pk}/roles/",
        {"role_codes": ["administrator"]},
        format="json",
    )
    assert grant_denied.status_code == 403

    admin_one = create_internal(tenant, "admin-one")
    admin_two = create_internal(tenant, "admin-two")
    UserRole.objects.create(tenant=tenant, user=admin_one, role=administrator)
    UserRole.objects.create(tenant=tenant, user=admin_two, role=administrator)
    admin_client = APIClient()
    admin_client.force_authenticate(admin_one)

    revoke_denied = manager_client.put(
        f"/api/internal/system/users/{admin_one.pk}/roles/",
        {"role_codes": []},
        format="json",
    )
    assert revoke_denied.status_code == 403

    revoke_second = admin_client.put(
        f"/api/internal/system/users/{admin_two.pk}/roles/",
        {"role_codes": []},
        format="json",
    )
    assert revoke_second.status_code == 200
    revoke_last = admin_client.put(
        f"/api/internal/system/users/{admin_one.pk}/roles/",
        {"role_codes": []},
        format="json",
    )
    assert revoke_last.status_code == 409

    deactivate_last = admin_client.post(
        f"/api/internal/system/users/{admin_one.pk}/status/",
        {"is_active": False},
        format="json",
    )
    assert deactivate_last.status_code == 409
