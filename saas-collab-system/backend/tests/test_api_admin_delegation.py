import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.role_catalog import sync_tenant_administrator_role
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db

PRIVILEGED_CODES = ("administrator", "admin", "tech_admin", "integration_admin")
MANAGER_PERMISSIONS = ("system.roles.view", "system.roles.manage", "system.users.view", "system.users.manage")


def create_internal(tenant, username, *, is_superuser=False):
    return CustomUser.objects.create_user(
        username=username, password="test-password-123", tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL, is_superuser=is_superuser, is_staff=is_superuser,
    )


def grant_role(user, code, permission_codes):
    role = Role.objects.create(tenant=user.tenant, name=code, code=code)
    role.permissions.set(Permission.objects.filter(code__in=permission_codes))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={"all": True})
    return role


def manager_client(tenant, username="ordinary-manager"):
    manager = create_internal(tenant, username)
    grant_role(manager, "ordinary-manager-role", MANAGER_PERMISSIONS)
    client = APIClient()
    client.force_authenticate(manager)
    return manager, client


def tenant_admin_client(tenant, username="tenant-admin"):
    administrator_role = sync_tenant_administrator_role(tenant)
    administrator = create_internal(tenant, username)
    UserRole.objects.create(tenant=tenant, user=administrator, role=administrator_role)
    client = APIClient()
    client.force_authenticate(administrator)
    return administrator, client


@pytest.mark.parametrize("code", PRIVILEGED_CODES)
def test_ordinary_manager_cannot_create_privileged_role_identity(code):
    tenant = Tenant.objects.create(name="Create guard", code=f"create-guard-{code}")
    _, client = manager_client(tenant)
    audit_count = OperationLog.objects.count()

    response = client.post("/api/internal/system/roles/", {"name": code, "code": code}, format="json")

    assert response.status_code == 403
    assert not Role.objects.filter(tenant=tenant, code=code).exists()
    assert OperationLog.objects.count() == audit_count


@pytest.mark.parametrize("code", PRIVILEGED_CODES)
def test_ordinary_manager_cannot_bind_existing_empty_privileged_role(code):
    tenant = Tenant.objects.create(name="Binding guard", code=f"binding-guard-{code}")
    manager, client = manager_client(tenant)
    target = create_internal(tenant, f"target-{code}")
    role = Role.objects.create(tenant=tenant, name=code, code=code)
    existing = list(target.user_roles.values_list("role_id", flat=True))

    response = client.put(f"/api/internal/system/users/{target.pk}/roles/", {"role_codes": [code]}, format="json")

    assert response.status_code == 403
    assert list(target.user_roles.values_list("role_id", flat=True)) == existing
    assert not UserRole.objects.filter(tenant=tenant, user=manager, role=role).exists()


@pytest.mark.parametrize("code", PRIVILEGED_CODES)
def test_ordinary_manager_cannot_create_user_with_privileged_role(code):
    tenant = Tenant.objects.create(name="User creation guard", code=f"user-creation-guard-{code}")
    _, client = manager_client(tenant)
    before_users = set(CustomUser.objects.filter(tenant=tenant).values_list("pk", flat=True))

    response = client.post(
        "/api/internal/system/users/",
        {"username": f"new-user-{code}", "full_name": "New user", "role_codes": [code]},
        format="json",
    )

    assert response.status_code == 403
    assert set(CustomUser.objects.filter(tenant=tenant).values_list("pk", flat=True)) == before_users


@pytest.mark.parametrize("code", PRIVILEGED_CODES)
def test_ordinary_manager_cannot_copy_role_to_privileged_identity(code):
    tenant = Tenant.objects.create(name="Copy guard", code=f"copy-guard-{code}")
    _, client = manager_client(tenant)
    source = Role.objects.create(tenant=tenant, name="Ordinary source", code="ordinary-source")

    response = client.post(
        f"/api/internal/system/roles/{source.pk}/copy/", {"name": code, "code": code}, format="json"
    )

    assert response.status_code == 403
    assert not Role.objects.filter(tenant=tenant, code=code).exists()


@pytest.mark.parametrize("code", PRIVILEGED_CODES)
def test_ordinary_manager_cannot_activate_bound_inactive_privileged_role(code):
    tenant = Tenant.objects.create(name="Activation guard", code=f"activation-guard-{code}")
    _, client = manager_client(tenant)
    target = create_internal(tenant, f"activation-target-{code}")
    role = Role.objects.create(tenant=tenant, name=code, code=code, status=Role.Status.INACTIVE)
    UserRole.objects.create(tenant=tenant, user=target, role=role)

    patch = client.patch(f"/api/internal/system/roles/{role.pk}/", {"status": "active"}, format="json")
    post = client.post(f"/api/internal/system/roles/{role.pk}/status/", {"status": "active"}, format="json")

    assert patch.status_code == 403
    assert post.status_code == 403
    role.refresh_from_db()
    assert role.status == Role.Status.INACTIVE


def test_ordinary_manager_role_options_hide_all_privileged_aliases_but_keep_ordinary_role():
    tenant = Tenant.objects.create(name="Options guard", code="options-guard")
    _, client = manager_client(tenant)
    for code in PRIVILEGED_CODES:
        Role.objects.create(tenant=tenant, name=code, code=code)
    Role.objects.create(tenant=tenant, name="Operator", code="operator")

    response = client.get("/api/internal/system/user-role-options/")

    assert response.status_code == 200
    codes = {item["code"] for item in response.json()["data"]["results"]}
    assert not set(PRIVILEGED_CODES) & codes
    assert "operator" in codes


@pytest.mark.parametrize("code", ("admin", "tech_admin", "integration_admin"))
def test_tenant_administrator_can_create_copy_and_assign_privileged_alias(code):
    tenant = Tenant.objects.create(name="Admin allowed", code=f"admin-allowed-{code}")
    _, client = tenant_admin_client(tenant)
    target = create_internal(tenant, f"admin-target-{code}")
    source = Role.objects.create(tenant=tenant, name="Ordinary source", code="ordinary-source")

    created = client.post("/api/internal/system/roles/", {"name": code, "code": code}, format="json")
    copied_code = f"{code}-copy"
    copied = client.post(
        f"/api/internal/system/roles/{source.pk}/copy/", {"name": copied_code, "code": copied_code}, format="json"
    )
    assigned = client.put(
        f"/api/internal/system/users/{target.pk}/roles/", {"role_codes": [code, copied_code]}, format="json"
    )

    assert created.status_code == 201, created.content
    assert copied.status_code == 200, copied.content
    assert assigned.status_code == 200, assigned.content
    assert set(target.user_roles.values_list("role__code", flat=True)) == {code, copied_code}


def test_ordinary_manager_can_create_copy_and_bind_nonprivileged_role():
    tenant = Tenant.objects.create(name="Ordinary preserved", code="ordinary-preserved")
    _, client = manager_client(tenant)
    target = create_internal(tenant, "ordinary-target")
    source = Role.objects.create(tenant=tenant, name="Source", code="source")

    created = client.post("/api/internal/system/roles/", {"name": "Operator", "code": "operator"}, format="json")
    copied = client.post(
        f"/api/internal/system/roles/{source.pk}/copy/", {"name": "Copy", "code": "source-copy"}, format="json"
    )
    assigned = client.put(
        f"/api/internal/system/users/{target.pk}/roles/", {"role_codes": ["operator", "source-copy"]}, format="json"
    )

    assert created.status_code == 201, created.content
    assert copied.status_code == 200, copied.content
    assert assigned.status_code == 200, assigned.content
    assert set(target.user_roles.values_list("role__code", flat=True)) == {"operator", "source-copy"}
