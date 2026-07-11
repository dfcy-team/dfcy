import pytest

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.services import check_user_permission, get_user_data_scope
from apps.tenants.models import Tenant


@pytest.mark.django_db
def test_role_is_isolated_by_tenant():
    tenant_a = Tenant.objects.create(name="Tenant A", code="tenant-a")
    tenant_b = Tenant.objects.create(name="Tenant B", code="tenant-b")

    role_a = Role.objects.create(tenant=tenant_a, name="Admin", code="admin")
    role_b = Role.objects.create(tenant=tenant_b, name="Admin", code="admin")

    assert role_a.code == role_b.code
    assert role_a.tenant != role_b.tenant


@pytest.mark.django_db
def test_user_role_can_bind_user_to_role():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = CustomUser.objects.create_user(
        username="alice",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, name="Operator", code="operator")

    user_role = UserRole.objects.create(tenant=tenant, user=user, role=role)

    assert user_role.user == user
    assert user_role.role == role
    assert user_role.tenant == tenant


@pytest.mark.django_db
def test_data_scope_records_scope_config():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    role = Role.objects.create(tenant=tenant, name="Finance", code="finance")

    scope = DataScope.objects.create(
        tenant=tenant,
        role=role,
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"department_ids": [1, 2]},
    )

    assert scope.scope_type == DataScope.ScopeType.CUSTOM
    assert scope.config == {"department_ids": [1, 2]}


@pytest.mark.django_db
def test_permission_helpers_use_user_tenant_roles():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    other_tenant = Tenant.objects.create(name="Other Tenant", code="other")
    user = CustomUser.objects.create_user(
        username="alice",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, name="Reporter", code="reporter")
    other_role = Role.objects.create(tenant=other_tenant, name="Reporter", code="reporter")
    permission = Permission.objects.get(code="reports.view")
    role.permissions.add(permission)
    other_role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=tenant,
        role=role,
        scope_type=DataScope.ScopeType.OWN,
        config={"owner_field": "created_by_id"},
    )

    assert check_user_permission(user, "reports.view") is True
    assert check_user_permission(user, "reports.delete") is False
    assert get_user_data_scope(user) == [
        {"scope_type": DataScope.ScopeType.OWN, "config": {"owner_field": "created_by_id"}, "role_id": role.id}
    ]
