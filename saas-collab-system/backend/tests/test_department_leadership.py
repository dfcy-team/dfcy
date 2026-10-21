import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, InternalUserProfile
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


def test_tree_edit_round_trip_keeps_leader_and_explicit_clear_still_works(organization_client):
    tenant, client = organization_client
    leader = create_user(tenant, "round-trip-leader", full_name="Round Trip Lead")
    department = Department.objects.create(
        tenant=tenant,
        name="Round Trip",
        leader=leader,
        leader_include_descendants=True,
    )

    tree = client.get("/api/internal/system/departments/tree/")
    node = tree.data["data"]["items"][0]
    assert node["id"] == department.pk
    assert node["leader_id"] == leader.pk
    assert node["leader_name"] == "Round Trip Lead"
    assert node["leader_include_descendants"] is True

    updated = client.patch(
        f"/api/internal/system/departments/{department.pk}/",
        {"leader_id": None, "leader_include_descendants": False},
        format="json",
    )
    assert updated.status_code == 200
    assert updated.data["data"]["leader_id"] is None
    assert updated.data["data"]["leader_include_descendants"] is False


def test_leader_options_use_organization_manage_scope_without_user_directory_permission(organization_client):
    tenant, client = organization_client
    manager = client.handler._force_user
    role = UserRole.objects.get(user=manager).role
    manage_scope = DataScope.objects.get(role=role)

    allowed_department = Department.objects.create(tenant=tenant, name="Allowed")
    outside_department = Department.objects.create(tenant=tenant, name="Outside")
    manage_scope.scope_type = DataScope.ScopeType.CUSTOM
    manage_scope.config = {"department_ids": [allowed_department.pk]}
    manage_scope.save(update_fields=["scope_type", "config"])

    visible = create_user(tenant, "visible-candidate", full_name="Visible Person")
    InternalUserProfile.objects.create(user=visible, tenant=tenant, department=allowed_department)
    out_of_scope = create_user(tenant, "outside-candidate", full_name="Outside Person")
    InternalUserProfile.objects.create(user=out_of_scope, tenant=tenant, department=outside_department)
    inactive = create_user(tenant, "inactive-candidate", is_active=False)
    external = create_user(tenant, "external-candidate", user_type=CustomUser.UserType.EXTERNAL)
    other_tenant = Tenant.objects.create(name="Candidate other tenant", code="candidate-other")
    foreign = create_user(other_tenant, "foreign-candidate")

    response = client.get("/api/internal/system/departments/leader-options/?search=Visible")
    assert response.status_code == 200
    assert response.data["data"]["count"] == 1
    assert response.data["data"]["items"] == [{
        "id": visible.pk, "username": "visible-candidate", "full_name": "Visible Person",
    }]

    all_candidates = client.get("/api/internal/system/departments/leader-options/")
    candidate_ids = {candidate["id"] for candidate in all_candidates.data["data"]["items"]}
    assert visible.pk in candidate_ids
    assert not {out_of_scope.pk, inactive.pk, external.pk, foreign.pk} & candidate_ids

    # The dedicated picker does not grant or imply access to the user directory.
    assert client.get("/api/internal/system/users/").status_code == 403


def test_leader_options_have_a_fixed_hundred_candidate_cap(organization_client):
    tenant, client = organization_client
    for index in range(105):
        create_user(tenant, f"bounded-candidate-{index:03d}")

    response = client.get("/api/internal/system/departments/leader-options/?page_size=5000")
    assert response.status_code == 200
    assert response.data["data"]["count"] == 100
    assert len(response.data["data"]["items"]) == 100


def test_leader_options_require_organization_manage(organization_client):
    tenant, _ = organization_client
    reader = create_user(tenant, "organization-reader")
    role = Role.objects.create(tenant=tenant, code="organization-reader", name="Organization reader")
    view_permission = Permission.objects.get(code="system.organization.view")
    role.permissions.add(view_permission)
    UserRole.objects.create(tenant=tenant, user=reader, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})

    response = client_for(reader).get("/api/internal/system/departments/leader-options/")
    assert response.status_code == 403


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
