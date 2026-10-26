import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.role_catalog import sync_tenant_administrator_role
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def user(tenant, username, *, is_superuser=False):
    return CustomUser.objects.create_user(
        username=username,
        password="test-password-123",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
        is_superuser=is_superuser,
        is_staff=is_superuser,
    )


def grant_role(user_obj, code, permission_codes, *, scope_type=DataScope.ScopeType.ALL, scope_config=None):
    role = Role.objects.create(tenant=user_obj.tenant, name=code, code=code)
    role.permissions.set(Permission.objects.filter(code__in=permission_codes))
    UserRole.objects.create(tenant=user_obj.tenant, user=user_obj, role=role)
    DataScope.objects.create(
        tenant=user_obj.tenant,
        role=role,
        scope_type=scope_type,
        config=scope_config or ({"all": True} if scope_type == DataScope.ScopeType.ALL else {}),
    )
    return role


def client(actor):
    api = APIClient()
    api.force_authenticate(actor)
    return api


def test_tenant_administrator_can_copy_builtin_role_with_permissions_and_scope():
    tenant = Tenant.objects.create(name="Copy tenant", code="role-copy-tenant")
    administrator = sync_tenant_administrator_role(tenant)
    actor = user(tenant, "copy-admin")
    UserRole.objects.create(tenant=tenant, user=actor, role=administrator)

    response = client(actor).post(
        f"/api/internal/system/roles/{administrator.pk}/copy/",
        {"name": "运营管理员副本", "code": "operations-copy"},
        format="json",
    )

    assert response.status_code == 201
    copied = Role.objects.get(tenant=tenant, code="operations-copy")
    assert copied.role_type == Role.RoleType.CUSTOM
    assert copied.is_protected is False
    assert copied.status == Role.Status.ACTIVE
    assert set(copied.permissions.values_list("code", flat=True)) == set(
        administrator.permissions.values_list("code", flat=True)
    )
    assert list(copied.data_scopes.values("scope_type", "config")) == list(
        administrator.data_scopes.values("scope_type", "config")
    )
    assert copied.pk != administrator.pk
    administrator.refresh_from_db()
    assert administrator.is_protected is True
    assert OperationLog.objects.filter(
        tenant=tenant, action="role_copy", object_id=str(copied.pk)
    ).exists()


def test_role_copy_rejects_duplicate_code_with_readable_validation():
    tenant = Tenant.objects.create(name="Duplicate copy tenant", code="role-copy-duplicate")
    administrator = sync_tenant_administrator_role(tenant)
    actor = user(tenant, "duplicate-copy-admin")
    UserRole.objects.create(tenant=tenant, user=actor, role=administrator)
    Role.objects.create(tenant=tenant, name="Existing", code="existing-copy")

    response = client(actor).post(
        f"/api/internal/system/roles/{administrator.pk}/copy/",
        {"name": "Another copy", "code": "existing-copy"},
        format="json",
    )

    assert response.status_code == 400
    assert "已存在" in str(response.json())
    assert Role.objects.filter(tenant=tenant, name="Another copy").exists() is False


def test_role_copy_checks_delegation_against_released_permissions_only():
    tenant = Tenant.objects.create(name="Released copy tenant", code="role-copy-released")
    manager = user(tenant, "released-copy-manager")
    active = Permission.objects.get(code="system.roles.view")
    inactive = Permission.objects.create(
        code="historical.copy.permission", name="Historical", module="historical", action="view",
        metadata={"status": "inactive"},
    )
    grant_role(manager, "released-copy-manager-role", [active.code, "system.roles.manage"])
    source = Role.objects.create(tenant=tenant, name="Source", code="released-source")
    source.permissions.add(active, inactive)
    DataScope.objects.create(tenant=tenant, role=source, scope_type=DataScope.ScopeType.ALL, config={})

    response = client(manager).post(
        f"/api/internal/system/roles/{source.pk}/copy/",
        {"name": "Released copy", "code": "released-source-copy"},
        format="json",
    )

    assert response.status_code == 201
    copied = Role.objects.get(tenant=tenant, code="released-source-copy")
    assert set(copied.permissions.values_list("code", flat=True)) == {active.code}
    assert not copied.permissions.filter(pk=inactive.pk).exists()


def test_role_copy_requires_all_scope_and_preserves_tenant_isolation():
    tenant = Tenant.objects.create(name="Limited copy tenant", code="role-copy-limited")
    foreign = Tenant.objects.create(name="Foreign copy tenant", code="role-copy-foreign")
    source = Role.objects.create(tenant=tenant, name="Source", code="source-role")
    manager = user(tenant, "limited-copy-manager")
    grant_role(
        manager,
        "limited-copy-manager-role",
        ["system.roles.view", "system.roles.manage"],
        scope_type=DataScope.ScopeType.OWN,
    )
    foreign_source = Role.objects.create(tenant=foreign, name="Foreign source", code="foreign-source")

    limited_response = client(manager).post(
        f"/api/internal/system/roles/{source.pk}/copy/",
        {"name": "Should fail", "code": "should-fail"},
        format="json",
    )
    assert limited_response.status_code == 403
    assert Role.objects.filter(tenant=tenant, code="should-fail").exists() is False

    # A tenant-scoped actor cannot switch the source lookup to another tenant.
    cross_tenant_response = client(manager).post(
        f"/api/internal/system/roles/{foreign_source.pk}/copy/?tenant_id={foreign.pk}",
        {"name": "Should fail cross tenant", "code": "cross-tenant-copy"},
        format="json",
    )
    assert cross_tenant_response.status_code == 403


def test_role_manager_cannot_copy_permissions_outside_its_delegation_boundary():
    tenant = Tenant.objects.create(name="Delegation copy tenant", code="role-copy-delegation")
    manager = user(tenant, "delegation-copy-manager")
    grant_role(
        manager,
        "delegation-copy-manager-role",
        ["system.roles.view", "system.roles.manage"],
    )
    source = Role.objects.create(tenant=tenant, name="Report source", code="report-source")
    source.permissions.add(Permission.objects.get(code="reports.view"))
    DataScope.objects.create(tenant=tenant, role=source, scope_type=DataScope.ScopeType.ALL, config={})

    response = client(manager).post(
        f"/api/internal/system/roles/{source.pk}/copy/",
        {"name": "Report source copy", "code": "report-source-copy"},
        format="json",
    )

    assert response.status_code == 403
    assert Role.objects.filter(tenant=tenant, code="report-source-copy").exists() is False


def test_customized_administrator_cannot_regrant_or_copy_revoked_permissions():
    tenant = Tenant.objects.create(name="Customized delegation tenant", code="custom-admin-delegation")
    administrator = sync_tenant_administrator_role(tenant)
    actor = user(tenant, "customized-admin-delegator")
    UserRole.objects.create(tenant=tenant, user=actor, role=administrator)
    revoked_permission = Permission.objects.get(code="reports.view")
    administrator.permissions.remove(revoked_permission)
    administrator.permissions_customized = True
    administrator.save(update_fields=["permissions_customized"])

    target = Role.objects.create(tenant=tenant, name="Target", code="custom-target")
    direct_grant = client(actor).put(
        f"/api/internal/system/roles/{target.pk}/permissions/",
        {
            "action_permission_codes": [revoked_permission.code],
            "scope_type": "all",
            "scope_config": {},
        },
        format="json",
    )
    assert direct_grant.status_code == 403
    assert not target.permissions.filter(pk=revoked_permission.pk).exists()

    # The quick form leaves untouched modules' grants in place. A scope change
    # must still fail if one of those retained grants exceeds the actor's own.
    scoped_target = Role.objects.create(tenant=tenant, name="Scoped", code="custom-scoped-target")
    scoped_target.permissions.add(revoked_permission)
    DataScope.objects.create(tenant=tenant, role=scoped_target, scope_type="custom", config={})
    scope_expansion = client(actor).put(
        f"/api/internal/system/roles/{scoped_target.pk}/permissions/",
        {
            "assignment_mode": "quick",
            "package_selections": {"system": "read"},
            "scope_type": "all",
            "scope_config": {},
        },
        format="json",
    )
    assert scope_expansion.status_code == 403
    assert scoped_target.data_scopes.get().scope_type == "custom"

    source = Role.objects.create(tenant=tenant, name="Source", code="custom-source")
    source.permissions.add(revoked_permission)
    copy_response = client(actor).post(
        f"/api/internal/system/roles/{source.pk}/copy/",
        {"name": "Unauthorized copy", "code": "custom-source-copy"},
        format="json",
    )
    assert copy_response.status_code == 403
    assert not Role.objects.filter(tenant=tenant, code="custom-source-copy").exists()


def test_role_manager_can_copy_a_role_with_only_delegable_permissions():
    tenant = Tenant.objects.create(name="Allowed copy tenant", code="role-copy-allowed")
    manager = user(tenant, "allowed-copy-manager")
    grant_role(
        manager,
        "allowed-copy-manager-role",
        ["system.roles.view", "system.roles.manage", "reports.view"],
    )
    source = Role.objects.create(tenant=tenant, name="Report source", code="allowed-source")
    source.permissions.add(Permission.objects.get(code="reports.view"))
    DataScope.objects.create(tenant=tenant, role=source, scope_type=DataScope.ScopeType.ALL, config={})

    response = client(manager).post(
        f"/api/internal/system/roles/{source.pk}/copy/",
        {"name": "Allowed source copy", "code": "allowed-source-copy"},
        format="json",
    )

    assert response.status_code == 201
    copied = Role.objects.get(tenant=tenant, code="allowed-source-copy")
    assert list(copied.permissions.values_list("code", flat=True)) == ["reports.view"]


def test_custom_role_name_can_change_but_system_code_is_immutable():
    tenant = Tenant.objects.create(name="Role rename tenant", code="role-rename-tenant")
    administrator = sync_tenant_administrator_role(tenant)
    actor = user(tenant, "role-rename-admin")
    UserRole.objects.create(tenant=tenant, user=actor, role=administrator)
    custom = Role.objects.create(tenant=tenant, name="原角色", code="stable-role-code")

    rejected = client(actor).patch(
        f"/api/internal/system/roles/{custom.pk}/",
        {"name": "新角色", "code": "changed-role-code"},
        format="json",
    )

    assert rejected.status_code == 400
    assert "不可修改" in str(rejected.json())
    custom.refresh_from_db()
    assert custom.name == "原角色"
    assert custom.code == "stable-role-code"

    renamed = client(actor).patch(
        f"/api/internal/system/roles/{custom.pk}/",
        {"name": "新角色"},
        format="json",
    )

    assert renamed.status_code == 200
    custom.refresh_from_db()
    assert custom.name == "新角色"
    assert custom.code == "stable-role-code"
