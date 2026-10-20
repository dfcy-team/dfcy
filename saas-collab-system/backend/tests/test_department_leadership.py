import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Department, Tenant


pytestmark = pytest.mark.django_db


def create_user(tenant, username, *, user_type=CustomUser.UserType.INTERNAL, is_active=True, full_name=""):
    return CustomUser.objects.create_user(
        username=username,
        password="not-a-real-password",
        tenant=tenant,
        user_type=user_type,
        is_active=is_active,
        full_name=full_name,
    )


def grant_organization_permissions(user):
    role = Role.objects.create(tenant=user.tenant, code=f"organization-{user.username}", name="Organization manager")
    for code in ("system.organization.view", "system.organization.manage"):
        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": "system", "action": code.removeprefix("system.")},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def organization_client():
    tenant = Tenant.objects.create(name="Leadership tenant", code="leadership-tenant")
    manager = create_user(tenant, "leadership-manager")
    grant_organization_permissions(manager)
    return tenant, client_for(manager)


def test_department_crud_saves_leader_and_management_range(organization_client):
    tenant, client = organization_client
    leader = create_user(tenant, "department-leader", full_name="Team Lead")

    created = client.post(
        "/api/internal/system/departments/",
        {"name": "Operations", "leader_id": leader.pk, "leader_include_descendants": True},
        format="json",
    )

    assert created.status_code == 201
    assert created.data["data"]["leader_id"] == leader.pk
    assert created.data["data"]["leader_name"] == "Team Lead"
    assert created.data["data"]["leader_include_descendants"] is True

    department_id = created.data["data"]["id"]
    updated = client.patch(
        f"/api/internal/system/departments/{department_id}/",
        {"leader_id": None, "leader_include_descendants": False},
        format="json",
    )

    assert updated.status_code == 200
    assert updated.data["data"]["leader_id"] is None
    assert updated.data["data"]["leader_name"] is None
    assert updated.data["data"]["leader_include_descendants"] is False
    department = Department.objects.get(pk=department_id)
    assert department.leader_id is None
    assert department.leader_include_descendants is False


@pytest.mark.parametrize("leader_kind", ["foreign_tenant", "external", "inactive"])
def test_department_rejects_invalid_leader(organization_client, leader_kind):
    tenant, client = organization_client
    if leader_kind == "foreign_tenant":
        other = Tenant.objects.create(name="Other tenant", code="leadership-other")
        leader = create_user(other, "foreign-leader")
    elif leader_kind == "external":
        leader = create_user(tenant, "external-leader", user_type=CustomUser.UserType.EXTERNAL)
    else:
        leader = create_user(tenant, "inactive-leader", is_active=False)

    response = client.post(
        "/api/internal/system/departments/",
        {"name": "Invalid assignment", "leader_id": leader.pk},
        format="json",
    )

    assert response.status_code == 400
    assert "leader_id" in response.data["data"]
    assert not Department.objects.filter(tenant=tenant, name="Invalid assignment").exists()
