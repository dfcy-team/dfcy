import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.accounts.serializers import CurrentUserSerializer
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.packages import expand_package_selections, permission_package_catalog
from apps.permissions.role_catalog import sync_tenant_administrator_role
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def test_builtin_role_labels_and_protection_metadata_are_stable():
    tenant = Tenant.objects.create(name="Role label tenant", code="role-label-tenant")
    role = sync_tenant_administrator_role(tenant)
    assert role.name == "租户管理员"
    assert role.role_type == Role.RoleType.BUILTIN
    assert role.is_protected is True


def test_platform_superuser_identity_is_not_a_assignable_role():
    tenant = Tenant.objects.create(name="Identity tenant", code="identity-tenant")
    user = CustomUser.objects.create_user(
        username="platform-label",
        password="test-password-123",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
        is_superuser=True,
        is_staff=True,
    )
    payload = CurrentUserSerializer(user).data
    assert payload["identity_label"] == "平台超级管理员"
    assert payload["role_labels"] == ["平台超级管理员"]
    assert payload["roles"] == []


def test_permission_package_catalog_derives_from_canonical_permission_definitions():
    packages = permission_package_catalog()
    products = next(item for item in packages if item["module"] == "products")
    assert set(products["levels"]) == {"none", "read", "operate", "admin"}
    assert "products.master.view" in products["levels"]["read"]
    assert "products.master.manage" not in products["levels"]["operate"]
    assert "products.master.manage" in products["levels"]["admin"]
    assert "products.master.freeze" in products["high_risk_codes"]
    assert "products.master.freeze" not in products["levels"]["admin"]

    system = next(item for item in packages if item["module"] == "system")
    assert {"system.roles.manage", "system.users.manage"}.issubset(system["high_risk_codes"])
    assert "system.roles.manage" not in system["levels"]["operate"]
    assert "system.roles.manage" not in system["levels"]["admin"]
    assert "system.users.manage" not in system["levels"]["operate"]
    assert "system.users.manage" not in system["levels"]["admin"]


def test_package_expansion_requires_explicit_high_risk_confirmation():
    codes = expand_package_selections({"products": "admin"})
    assert "products.master.manage" in codes
    assert "products.master.freeze" not in codes
    with pytest.raises(ValueError):
        expand_package_selections({"products": "admin"}, ["reports.view"])
    with pytest.raises(ValueError, match="explicit package selection"):
        expand_package_selections({"reports": "read"}, ["products.master.freeze"])
    with pytest.raises(ValueError, match="level is none"):
        expand_package_selections({"products": "none"}, ["products.master.freeze"])
    with pytest.raises(ValueError, match="explicit package selection"):
        expand_package_selections({}, ["system.roles.manage"])
    codes = expand_package_selections({"products": "admin"}, ["products.master.freeze"])
    assert "products.master.freeze" in codes


def test_permission_package_catalog_requires_tenant_boundary_for_explicit_context():
    tenant = Tenant.objects.create(name="Package actor tenant", code="package-actor-tenant")
    other_tenant = Tenant.objects.create(name="Package other tenant", code="package-other-tenant")
    actor = CustomUser.objects.create_user(
        username="package-catalog-reader",
        password="test-password-123",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, name="权限目录查看员", code="package-catalog-reader-role")
    role.permissions.add(Permission.objects.get(code="system.roles.view"))
    UserRole.objects.create(tenant=tenant, user=actor, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})

    client = APIClient()
    client.force_authenticate(actor)
    assert client.get("/api/internal/system/permission-packages/").status_code == 200
    assert client.get(
        f"/api/internal/system/permission-packages/?tenant_id={other_tenant.pk}"
    ).status_code == 403


def test_quick_assignment_preserves_modules_not_touched_by_package():
    tenant = Tenant.objects.create(name="Package tenant", code="package-tenant")
    administrator = sync_tenant_administrator_role(tenant)
    actor = CustomUser.objects.create_user(
        username="package-admin",
        password="test-password-123",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    UserRole.objects.create(tenant=tenant, user=actor, role=administrator)
    role = Role.objects.create(tenant=tenant, name="业务角色", code="business-role")
    role.permissions.add(Permission.objects.get(code="reports.view"))
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})

    client = APIClient()
    client.force_authenticate(actor)
    response = client.put(
        f"/api/internal/system/roles/{role.pk}/permissions/",
        {
            "package_selections": {"products": "read"},
            "extra_permission_codes": [],
            "scope_type": "all",
            "scope_config": {},
        },
        format="json",
    )
    assert response.status_code == 200, response.content
    role.refresh_from_db()
    assert role.permissions.filter(code="reports.view").exists()
    assert role.permissions.filter(code="products.master.view").exists()
    assert not role.permissions.filter(code="products.master.freeze").exists()


def test_quick_assignment_none_clears_touched_module_and_preserves_untouched_module():
    tenant = Tenant.objects.create(name="Package clear tenant", code="package-clear-tenant")
    administrator = sync_tenant_administrator_role(tenant)
    actor = CustomUser.objects.create_user(
        username="package-clear-admin",
        password="test-password-123",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    UserRole.objects.create(tenant=tenant, user=actor, role=administrator)
    role = Role.objects.create(tenant=tenant, name="清理业务角色", code="clear-business-role")
    role.permissions.set(Permission.objects.filter(code__in=[
        "products.master.view",
        "products.master.manage",
        "products.master.freeze",
        "reports.view",
    ]))
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})

    client = APIClient()
    client.force_authenticate(actor)
    response = client.put(
        f"/api/internal/system/roles/{role.pk}/permissions/",
        {
            "package_selections": {"products": "none"},
            "extra_permission_codes": [],
            "scope_type": "all",
            "scope_config": {},
        },
        format="json",
    )
    assert response.status_code == 200, response.content
    role.refresh_from_db()
    assert not role.permissions.filter(module="products").exists()
    assert role.permissions.filter(code="reports.view").exists()


def test_role_list_exposes_role_type_and_protection_metadata():
    tenant = Tenant.objects.create(name="Role API tenant", code="role-api-tenant")
    administrator = sync_tenant_administrator_role(tenant)
    actor = CustomUser.objects.create_user(
        username="role-api-admin",
        password="test-password-123",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    UserRole.objects.create(tenant=tenant, user=actor, role=administrator)
    client = APIClient()
    client.force_authenticate(actor)
    response = client.get("/api/internal/system/roles/")
    assert response.status_code == 200
    row = next(item for item in response.json()["data"]["results"] if item["code"] == "administrator")
    assert row["name"] == "租户管理员"
    assert row["role_type"] == "builtin"
    assert row["is_protected"] is True


def test_role_manager_cannot_delegate_permission_outside_its_all_scope():
    tenant = Tenant.objects.create(name="Delegation tenant", code="delegation-tenant")
    actor = CustomUser.objects.create_user(
        username="delegation-manager",
        password="test-password-123",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    manager_role = Role.objects.create(tenant=tenant, name="角色管理员", code="delegation-manager-role")
    manager_role.permissions.set(Permission.objects.filter(code__in=["system.roles.view", "system.roles.manage"]))
    UserRole.objects.create(tenant=tenant, user=actor, role=manager_role)
    DataScope.objects.create(tenant=tenant, role=manager_role, scope_type=DataScope.ScopeType.ALL, config={})
    target = Role.objects.create(tenant=tenant, name="目标角色", code="delegation-target")

    response = APIClient()
    response.force_authenticate(actor)
    result = response.put(
        f"/api/internal/system/roles/{target.pk}/permissions/",
        {
            "package_selections": {"products": "read"},
            "extra_permission_codes": [],
            "scope_type": "all",
            "scope_config": {},
        },
        format="json",
    )

    assert result.status_code == 403
    assert not target.permissions.exists()


def test_high_risk_permission_cannot_be_smuggled_through_category_fields():
    tenant = Tenant.objects.create(name="High risk tenant", code="high-risk-tenant")
    actor = CustomUser.objects.create_user(
        username="high-risk-manager",
        password="test-password-123",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    manager_role = Role.objects.create(tenant=tenant, name="高风险管理员", code="high-risk-manager-role")
    manager_role.permissions.set(Permission.objects.filter(code__in=[
        "system.roles.view",
        "system.roles.manage",
        "products.master.view",
    ]))
    UserRole.objects.create(tenant=tenant, user=actor, role=manager_role)
    DataScope.objects.create(tenant=tenant, role=manager_role, scope_type=DataScope.ScopeType.ALL, config={})
    target = Role.objects.create(tenant=tenant, name="目标角色", code="high-risk-target")

    client = APIClient()
    client.force_authenticate(actor)
    result = client.put(
        f"/api/internal/system/roles/{target.pk}/permissions/",
        {
            "package_selections": {"products": "admin"},
            "action_permission_codes": ["products.master.freeze"],
            "extra_permission_codes": [],
            "scope_type": "all",
            "scope_config": {},
        },
        format="json",
    )

    assert result.status_code == 400
    assert not target.permissions.exists()


def test_department_tree_scope_rejects_non_system_role_permissions():
    tenant = Tenant.objects.create(name="Tree boundary tenant", code="tree-boundary-tenant")
    administrator = sync_tenant_administrator_role(tenant)
    actor = CustomUser.objects.create_user(
        username="tree-boundary-admin",
        password="test-password-123",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    UserRole.objects.create(tenant=tenant, user=actor, role=administrator)
    target = Role.objects.create(tenant=tenant, name="混合角色", code="mixed-tree-role")
    target.permissions.add(Permission.objects.get(code="reports.view"))

    client = APIClient()
    client.force_authenticate(actor)
    result = client.put(
        f"/api/internal/system/roles/{target.pk}/permissions/",
        {
            "package_selections": {"system": "read"},
            "extra_permission_codes": [],
            "scope_type": "department_tree",
            "scope_config": {},
        },
        format="json",
    )

    assert result.status_code == 400
    target.refresh_from_db()
    assert target.permissions.filter(code="reports.view").exists()


def test_role_manager_cannot_widen_scope_of_existing_undelegable_permission():
    tenant = Tenant.objects.create(name="Scope widening tenant", code="scope-widening-tenant")
    actor = CustomUser.objects.create_user(
        username="scope-widening-manager",
        password="test-password-123",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    manager_role = Role.objects.create(tenant=tenant, name="范围管理员", code="scope-widening-manager-role")
    manager_role.permissions.set(Permission.objects.filter(code__in=["system.roles.view", "system.roles.manage"]))
    UserRole.objects.create(tenant=tenant, user=actor, role=manager_role)
    DataScope.objects.create(tenant=tenant, role=manager_role, scope_type=DataScope.ScopeType.ALL, config={})
    target = Role.objects.create(tenant=tenant, name="已有报表角色", code="scope-widening-target")
    target.permissions.add(Permission.objects.get(code="reports.view"))
    DataScope.objects.create(tenant=tenant, role=target, scope_type=DataScope.ScopeType.DEPARTMENT, config={})

    client = APIClient()
    client.force_authenticate(actor)
    result = client.put(
        f"/api/internal/system/roles/{target.pk}/permissions/",
        {
            "permission_codes": ["reports.view"],
            "scope_type": "all",
            "scope_config": {},
        },
        format="json",
    )

    assert result.status_code == 403
    assert target.data_scopes.get().scope_type == DataScope.ScopeType.DEPARTMENT


def test_user_creation_rejects_role_outside_assignable_role_scope():
    from apps.accounts.models import InternalUserProfile
    from apps.tenants.models import Department

    tenant = Tenant.objects.create(name="User role create tenant", code="user-role-create-tenant")
    department = Department.objects.create(tenant=tenant, name="Allowed department")
    actor = CustomUser.objects.create_user(
        username="user-create-manager",
        password="test-password-123",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    actor_profile = InternalUserProfile.objects.create(tenant=tenant, user=actor, department=department)
    actor_profile.departments.set([department])
    manager_role = Role.objects.create(tenant=tenant, name="用户管理员", code="user-create-manager-role")
    manager_role.permissions.set(Permission.objects.filter(code__in=["system.users.view", "system.users.manage"]))
    UserRole.objects.create(tenant=tenant, user=actor, role=manager_role)
    DataScope.objects.create(
        tenant=tenant,
        role=manager_role,
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"department_ids": [department.pk]},
    )
    target_role = Role.objects.create(tenant=tenant, name="不可委派角色", code="unassignable-role")

    client = APIClient()
    client.force_authenticate(actor)
    result = client.post(
        "/api/internal/system/users/",
        {
            "username": "created-with-unassignable-role",
            "initial_password": "test-password-123",
            "user_type": "internal",
            "department_id": department.pk,
            "role_codes": [target_role.code],
        },
        format="json",
    )

    assert result.status_code == 403
    assert not CustomUser.objects.filter(username="created-with-unassignable-role").exists()


def test_advanced_explicit_high_risk_permission_remains_supported_for_tenant_admin():
    tenant = Tenant.objects.create(name="Advanced high risk tenant", code="advanced-high-risk-tenant")
    administrator = sync_tenant_administrator_role(tenant)
    actor = CustomUser.objects.create_user(
        username="advanced-high-risk-admin",
        password="test-password-123",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    UserRole.objects.create(tenant=tenant, user=actor, role=administrator)
    target = Role.objects.create(tenant=tenant, name="高级配置角色", code="advanced-high-risk-target")

    client = APIClient()
    client.force_authenticate(actor)
    result = client.put(
        f"/api/internal/system/roles/{target.pk}/permissions/",
        {
            "menu_permission_codes": [],
            "action_permission_codes": ["products.master.freeze"],
            "field_permission_codes": [],
            "scope_type": "all",
            "scope_config": {},
        },
        format="json",
    )

    assert result.status_code == 200
    assert target.permissions.filter(code="products.master.freeze").exists()
