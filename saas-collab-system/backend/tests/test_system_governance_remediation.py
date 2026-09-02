import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.configcenter.models import ConfigChangeLog, SystemConfigDefinition
from apps.configcenter.services import create_config_version, rollback_config_version
from apps.masterdata.models import PlatformMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Department, Tenant


pytestmark = pytest.mark.django_db


def user(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(username=username, password="test-password", tenant=tenant, user_type=user_type)


def grant(actor, *codes, scope=DataScope.ScopeType.ALL, config=None):
    role = Role.objects.create(
        tenant=actor.tenant,
        name=f"Role {actor.username} {len(codes)}",
        code=f"role-{actor.username}-{len(actor.user_roles.all())}-{codes[0].replace('.', '-')}",
    )
    for code in codes:
        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": code.split(".")[0], "action": code.split(".", 1)[1]},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=actor.tenant, user=actor, role=role)
    DataScope.objects.create(tenant=actor.tenant, role=role, scope_type=scope, config=config or {})
    return role


def client(actor):
    api = APIClient()
    api.force_authenticate(actor)
    return api


def test_department_update_prevents_hierarchy_cycles_and_audits_delete():
    tenant = Tenant.objects.create(name="Governance tenant", code="governance-departments")
    manager = user(tenant, "department-manager")
    grant(manager, "system.organization.view", "system.organization.manage")
    api = client(manager)
    root = api.post("/api/internal/system/departments/", {"name": "Root"}, format="json").json()["data"]
    child = api.post(
        "/api/internal/system/departments/",
        {"name": "Child", "parent_id": root["id"]},
        format="json",
    ).json()["data"]

    cycle = api.patch(
        f"/api/internal/system/departments/{root['id']}/",
        {"parent_id": child["id"]},
        format="json",
    )
    assert cycle.status_code == 400

    updated = api.patch(
        f"/api/internal/system/departments/{child['id']}/",
        {"name": "Renamed child", "parent_id": None},
        format="json",
    )
    assert updated.status_code == 200

    assert api.delete(f"/api/internal/system/departments/{child['id']}/").status_code == 200
    assert OperationLog.objects.filter(tenant=tenant, action="department_delete", object_id=str(child["id"])).exists()


def test_role_custom_scope_is_tenant_validated_and_lifecycle_is_safe():
    tenant = Tenant.objects.create(name="Role tenant", code="governance-roles")
    foreign = Tenant.objects.create(name="Foreign tenant", code="governance-roles-foreign")
    manager = user(tenant, "role-manager")
    target = Role.objects.create(tenant=tenant, name="Operator", code="operator")
    foreign_department = Department.objects.create(tenant=foreign, name="Foreign department")
    foreign_platform = PlatformMaster.objects.create(
        tenant=foreign,
        code="foreign-platform",
        name="Foreign platform",
        platform_type=PlatformMaster.PlatformType.OTHER,
    )
    grant(manager, "system.roles.view", "system.roles.manage")
    api = client(manager)

    denied = api.put(
        f"/api/internal/system/roles/{target.pk}/permissions/",
        {
            "permission_codes": [],
            "scope_type": "custom",
            "scope_config": {"department_ids": [foreign_department.pk]},
        },
        format="json",
    )
    assert denied.status_code == 400
    denied_platform = api.put(
        f"/api/internal/system/roles/{target.pk}/permissions/",
        {
            "permission_codes": [],
            "scope_type": "custom",
            "scope_config": {"platform_ids": [foreign_platform.pk]},
        },
        format="json",
    )
    assert denied_platform.status_code == 400
    valid = api.put(
        f"/api/internal/system/roles/{target.pk}/permissions/",
        {"permission_codes": [], "scope_type": "custom", "scope_config": {"role_ids": [target.pk]}},
        format="json",
    )
    assert valid.status_code == 200
    assert valid.data["data"]["data_scopes"][0]["config"] == {"role_ids": [target.pk]}

    changed = api.post(f"/api/internal/system/roles/{target.pk}/status/", {"status": "inactive"}, format="json")
    assert changed.status_code == 200
    assert target.user_roles.count() == 0
    assert api.delete(f"/api/internal/system/roles/{target.pk}/").status_code == 200
    assert OperationLog.objects.filter(tenant=tenant, action="role_status_change").exists()


def test_config_actions_require_all_scope_and_api_rollback_is_real():
    tenant = Tenant.objects.create(name="Config tenant", code="governance-config")
    limited = user(tenant, "limited-config")
    grant(limited, "config.manage", scope=DataScope.ScopeType.OWN)
    definition = SystemConfigDefinition.objects.create(
        config_key="governance.threshold",
        scope_type=SystemConfigDefinition.ScopeType.TENANT,
        value_type=SystemConfigDefinition.ValueType.INTEGER,
        default_value=1,
    )
    with pytest.raises(PermissionDenied):
        create_config_version(definition=definition, actor=limited, value=2, effective_at=timezone.now())

    system_limited = user(tenant, "limited-system-config")
    grant(system_limited, "config.manage")
    grant(system_limited, "config.system.manage", scope=DataScope.ScopeType.OWN)
    system_definition = SystemConfigDefinition.objects.create(
        config_key="governance.system-threshold",
        scope_type=SystemConfigDefinition.ScopeType.SYSTEM,
        value_type=SystemConfigDefinition.ValueType.INTEGER,
        default_value=1,
    )
    with pytest.raises(PermissionDenied):
        create_config_version(
            definition=system_definition,
            actor=system_limited,
            value=2,
            effective_at=timezone.now(),
        )

    manager = user(tenant, "full-config")
    grant(manager, "config.manage")
    grant(manager, "config.rollback")
    first = create_config_version(definition=definition, actor=manager, value=2, effective_at=timezone.now())
    assert first.status == "effective"
    api = client(manager)
    response = api.post(f"/api/internal/config/values/{first.pk}/rollback/", {}, format="json")
    assert response.status_code == 201
    assert response.data["data"]["version"] == 2
    assert response.data["data"]["status"] == "effective"
    assert ConfigChangeLog.objects.filter(action=ConfigChangeLog.Action.ROLLBACK, tenant=tenant).exists()


def test_security_operations_returns_accounts_for_real_status_action():
    tenant = Tenant.objects.create(name="Security tenant", code="governance-security")
    manager = user(tenant, "security-manager")
    target = user(tenant, "security-target")
    grant(manager, "security.operations.view", "system.users.manage")
    api = client(manager)
    response = api.get("/api/internal/system/security-operations/")
    assert response.status_code == 200
    assert {item["id"] for item in response.data["data"]["accounts"]} == {manager.pk, target.pk}
    changed = api.post(
        f"/api/internal/system/users/{target.pk}/status/", {"is_active": False}, format="json"
    )
    assert changed.status_code == 200
    target.refresh_from_db()
    assert target.is_active is False
    assert OperationLog.objects.filter(tenant=tenant, action="user_status_change", object_id=str(target.pk)).exists()


def test_external_user_profile_update_rejects_department_assignment_without_server_error():
    tenant = Tenant.objects.create(name="Profile tenant", code="governance-profile")
    manager = user(tenant, "profile-manager")
    external = user(tenant, "profile-external", CustomUser.UserType.EXTERNAL)
    department = Department.objects.create(tenant=tenant, name="Operations")
    grant(manager, "system.users.view", "system.users.manage")
    api = client(manager)

    rejected = api.patch(
        f"/api/internal/system/users/{external.pk}/",
        {"department_ids": [department.pk]},
        format="json",
    )

    assert rejected.status_code == 400
    assert "department_ids" in rejected.data["data"]
