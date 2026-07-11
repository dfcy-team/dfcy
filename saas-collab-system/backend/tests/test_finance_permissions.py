import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import Permission, Role, UserRole
from apps.tenants.models import Tenant


def create_user(tenant, username, user_type):
    return CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=user_type,
    )


@pytest.mark.django_db
def test_internal_user_without_finance_permission_cannot_access_finance_health():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "internal", CustomUser.UserType.INTERNAL)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/finance/health/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_internal_user_with_finance_view_permission_can_access_finance_health():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "finance-user", CustomUser.UserType.INTERNAL)
    role = Role.objects.create(tenant=tenant, name="Finance Viewer", code="finance-viewer")
    permission = Permission.objects.get(code="finance.view")
    role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/finance/health/")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "code": "OK",
        "message": "success",
        "data": {"status": "ok", "service": "finance"},
    }


@pytest.mark.django_db
def test_internal_user_with_finance_role_can_access_finance_health():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "finance-role-user", CustomUser.UserType.INTERNAL)
    role = Role.objects.create(tenant=tenant, name="Finance", code="finance")
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/finance/health/")

    assert response.status_code == 200
    assert response.json()["data"] == {"status": "ok", "service": "finance"}


@pytest.mark.django_db
def test_external_user_cannot_access_finance_health():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "external", CustomUser.UserType.EXTERNAL)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/finance/health/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_rpa_user_cannot_access_finance_health():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "rpa", CustomUser.UserType.RPA)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/finance/health/")

    assert response.status_code == 403
