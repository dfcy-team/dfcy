import pytest

from apps.accounts.models import CustomUser, InternalUserProfile
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Department, Tenant
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db


def user(tenant, username, **kwargs):
    return CustomUser.objects.create_user(username=username, password="test", tenant=tenant,
                                          user_type=kwargs.pop("user_type", "internal"), **kwargs)


def grant(person, code, scope=DataScope.ScopeType.DEPARTMENT_TREE):
    role = Role.objects.create(tenant=person.tenant, code=f"role-{person.username}", name="Role")
    permission, _ = Permission.objects.get_or_create(code=code, defaults={"name": code, "module": "masterdata", "action": "view"})
    role.permissions.add(permission)
    UserRole.objects.create(tenant=person.tenant, user=person, role=role)
    DataScope.objects.create(tenant=person.tenant, role=role, scope_type=scope, config={})


def client(person):
    api = APIClient()
    api.force_authenticate(person)
    return api


def test_store_person_options_include_department_tree_and_secondary_assignment_but_not_other_tenant():
    tenant = Tenant.objects.create(name="A", code="store-person-a")
    other = Tenant.objects.create(name="B", code="store-person-b")
    root = Department.objects.create(tenant=tenant, name="Operations")
    child = Department.objects.create(tenant=tenant, name="Shopee", parent=root)
    grandchild = Department.objects.create(tenant=tenant, name="PH", parent=child)
    separate = Department.objects.create(tenant=tenant, name="Support")
    viewer = user(tenant, "viewer")
    InternalUserProfile.objects.create(tenant=tenant, user=viewer, department=child)
    primary = user(tenant, "primary")
    InternalUserProfile.objects.create(tenant=tenant, user=primary, department=grandchild)
    secondary = user(tenant, "secondary")
    profile = InternalUserProfile.objects.create(tenant=tenant, user=secondary)
    profile.departments.add(separate)
    profile.departments.add(child)
    outside = user(tenant, "outside")
    InternalUserProfile.objects.create(tenant=tenant, user=outside, department=separate)
    inactive = user(tenant, "inactive", is_active=False)
    InternalUserProfile.objects.create(tenant=tenant, user=inactive, department=child)
    foreign = user(other, "foreign")
    InternalUserProfile.objects.create(tenant=other, user=foreign, department=Department.objects.create(tenant=other, name="Ops"))
    grant(viewer, "masterdata.view", scope=DataScope.ScopeType.ALL)

    response = client(viewer).get("/api/internal/master-data/store-person-options/")
    assert response.status_code == 200
    rows = response.data["data"]["results"]
    assert {row["username"] for row in rows} == {"primary", "secondary", "viewer"}
    assert set(rows[0]) == {"id", "full_name", "username"}


def test_store_person_options_without_departments_returns_empty_and_external_rejected():
    tenant = Tenant.objects.create(name="A", code="store-person-empty")
    viewer = user(tenant, "no-department")
    InternalUserProfile.objects.create(tenant=tenant, user=viewer)
    grant(viewer, "masterdata.view")
    assert client(viewer).get("/api/internal/master-data/store-person-options/").data["data"]["count"] == 0
    external = user(tenant, "external", user_type=CustomUser.UserType.EXTERNAL)
    grant(external, "masterdata.view", scope=DataScope.ScopeType.ALL)
    assert client(external).get("/api/internal/master-data/store-person-options/").status_code == 403


def test_store_person_options_requires_store_view_permission_without_system_user_permission():
    tenant = Tenant.objects.create(name="A", code="store-person-permission")
    viewer = user(tenant, "store-viewer")
    dept = Department.objects.create(tenant=tenant, name="Operations")
    InternalUserProfile.objects.create(tenant=tenant, user=viewer, department=dept)
    grant(viewer, "masterdata.view")
    response = client(viewer).get("/api/internal/master-data/store-person-options/")
    assert response.status_code == 200
    denied = user(tenant, "no-store-permission")
    grant(denied, "system.users.view", scope=DataScope.ScopeType.ALL)
    assert client(denied).get("/api/internal/master-data/store-person-options/").status_code == 403


def test_tenant_administrator_keeps_all_tenant_options():
    tenant = Tenant.objects.create(name="A", code="store-person-admin")
    admin = user(tenant, "tenant-admin")
    other_department = Department.objects.create(tenant=tenant, name="Other")
    coworker = user(tenant, "other-department-user")
    InternalUserProfile.objects.create(tenant=tenant, user=coworker, department=other_department)
    role = Role.objects.create(tenant=tenant, code="administrator", name="租户管理员", is_protected=True)
    permission, _ = Permission.objects.get_or_create(code="masterdata.view", defaults={"name": "Master data view", "module": "masterdata", "action": "view"})
    role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=admin, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    response = client(admin).get("/api/internal/master-data/store-person-options/")
    assert {row["username"] for row in response.data["data"]["results"]} == {"tenant-admin", "other-department-user"}
