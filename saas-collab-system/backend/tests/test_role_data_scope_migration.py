import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.masterdata.models import CountrySiteMaster, PlatformMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def internal_user(tenant, username):
    return CustomUser.objects.create_user(
        username=username, password="test-password-123", tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )


def grant_role_manager(user):
    role = Role.objects.create(tenant=user.tenant, name="范围管理员", code=f"{user.username}-manager")
    role.permissions.set(Permission.objects.filter(code__in=("system.roles.view", "system.roles.manage")))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})


def permission_payload(**scope):
    return {
        "menu_permission_codes": [], "action_permission_codes": [], "field_permission_codes": [],
        "scope_type": scope.get("scope_type", DataScope.ScopeType.ALL),
        "scope_config": scope.get("scope_config", {}),
    }


def test_legacy_organization_scope_is_readable_but_rejected_on_new_save():
    tenant = Tenant.objects.create(name="范围迁移租户", code="scope-migration-legacy")
    manager = internal_user(tenant, "scope-migration-manager")
    grant_role_manager(manager)
    target = Role.objects.create(tenant=tenant, name="历史角色", code="legacy-scope-role")
    target.permissions.add(Permission.objects.get(code="reports.view"))
    DataScope.objects.create(tenant=tenant, role=target, scope_type=DataScope.ScopeType.DEPARTMENT_TREE, config={})

    client = APIClient(); client.force_authenticate(manager)
    listed = client.get("/api/internal/system/roles/")
    assert listed.status_code == 200
    row = next(item for item in listed.json()["data"]["results"] if item["id"] == target.pk)
    assert row["data_scopes"] == [{"scope_type": "department_tree", "config": {}}]

    for legacy_type in ("department", "department_tree", "own"):
        response = client.put(
            f"/api/internal/system/roles/{target.pk}/permissions/",
            permission_payload(scope_type=legacy_type), format="json",
        )
        assert response.status_code == 400
        assert "历史组织范围" in str(response.json())

    target.refresh_from_db()
    assert list(target.data_scopes.values_list("scope_type", flat=True)) == ["department_tree"]
    assert target.permissions.filter(code="reports.view").exists()


def test_business_scope_rejects_organization_keys_and_keeps_objects_tenant_local():
    tenant = Tenant.objects.create(name="范围租户", code="scope-migration-business")
    foreign_tenant = Tenant.objects.create(name="外部租户", code="scope-migration-foreign")
    manager = internal_user(tenant, "scope-business-manager"); grant_role_manager(manager)
    target = Role.objects.create(tenant=tenant, name="业务角色", code="business-scope-role")
    site = CountrySiteMaster.objects.create(tenant=tenant, code="ph", name="菲律宾站", country_code="PH", currency="PHP")
    foreign_site = CountrySiteMaster.objects.create(tenant=foreign_tenant, code="us", name="美国站", country_code="US", currency="USD")
    client = APIClient(); client.force_authenticate(manager)

    legacy = client.put(
        f"/api/internal/system/roles/{target.pk}/permissions/",
        permission_payload(scope_type="custom", scope_config={"department_ids": [1]}), format="json",
    )
    assert legacy.status_code == 400 and "department_ids" in str(legacy.json())
    cross_tenant = client.put(
        f"/api/internal/system/roles/{target.pk}/permissions/",
        permission_payload(scope_type="custom", scope_config={"site_ids": [foreign_site.pk]}), format="json",
    )
    assert cross_tenant.status_code == 400 and "当前租户之外" in str(cross_tenant.json())
    accepted = client.put(
        f"/api/internal/system/roles/{target.pk}/permissions/",
        permission_payload(scope_type="custom", scope_config={"site_ids": [site.pk]}), format="json",
    )
    assert accepted.status_code == 200
    target.refresh_from_db()
    assert list(target.data_scopes.values("scope_type", "config")) == [{"scope_type": "custom", "config": {"site_ids": [site.pk]}}]


def test_role_scope_options_are_business_only_and_target_tenant_scoped():
    tenant = Tenant.objects.create(name="选项租户", code="scope-options-tenant")
    foreign_tenant = Tenant.objects.create(name="外部选项租户", code="scope-options-foreign")
    manager = internal_user(tenant, "scope-options-manager"); grant_role_manager(manager)
    local_platform = PlatformMaster.objects.create(tenant=tenant, code="local-platform-options", name="本租户平台", platform_type=PlatformMaster.PlatformType.OTHER)
    foreign_platform = PlatformMaster.objects.create(tenant=foreign_tenant, code="foreign-platform-options", name="外部平台", platform_type=PlatformMaster.PlatformType.OTHER)
    client = APIClient(); client.force_authenticate(manager)
    response = client.get("/api/internal/system/role-scope-options/")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert set(payload) == {"platforms", "sites", "stores", "warehouses", "suppliers"}
    assert [item["id"] for item in payload["platforms"]] == [local_platform.pk]
    assert foreign_platform.pk not in {item["id"] for item in payload["platforms"]}
