import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import Permission, Role, UserRole
from apps.tenants.models import Tenant


@pytest.mark.django_db
def test_internal_user_can_login_and_access_me():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = CustomUser.objects.create_user(
        username="internal",
        email="internal@example.com",
        password="test-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, name="Admin", code="admin")
    permission = Permission.objects.create(
        code="accounts.view",
        name="View accounts",
        module="accounts",
        action="view",
    )
    role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)

    client = APIClient()
    login_response = client.post(
        "/api/internal/auth/login/",
        {"username": "internal", "password": "test-password"},
        format="json",
    )

    assert login_response.status_code == 200
    assert "access" in login_response.json()
    assert "refresh" in login_response.json()

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login_response.json()['access']}")
    me_response = client.get("/api/internal/auth/me/")

    assert me_response.status_code == 200
    assert me_response.json() == {
        "success": True,
        "code": "OK",
        "message": "success",
        "data": {
            "user_id": user.id,
            "username": "internal",
            "email": "internal@example.com",
            "user_type": CustomUser.UserType.INTERNAL,
            "tenant_id": tenant.id,
            "roles": ["admin"],
            "permissions": ["accounts.view"],
        },
    }


@pytest.mark.django_db
def test_me_success_response_uses_standard_shape():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = CustomUser.objects.create_user(
        username="internal-me",
        email="internal-me@example.com",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/internal/auth/me/")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "code": "OK",
        "message": "success",
        "data": {
            "user_id": user.id,
            "username": "internal-me",
            "email": "internal-me@example.com",
            "user_type": CustomUser.UserType.INTERNAL,
            "tenant_id": tenant.id,
            "roles": [],
            "permissions": [],
        },
    }


@pytest.mark.django_db
def test_me_requires_authentication():
    response = APIClient().get("/api/internal/auth/me/")

    assert response.status_code == 401
    assert response.json()["success"] is False
    assert response.json()["code"] == "AUTH_REQUIRED"


@pytest.mark.django_db
def test_external_user_cannot_use_internal_login():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    CustomUser.objects.create_user(
        username="external",
        password="test-password",
        tenant=tenant,
        user_type=CustomUser.UserType.EXTERNAL,
    )

    response = APIClient().post(
        "/api/internal/auth/login/",
        {"username": "external", "password": "test-password"},
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_token_refresh_endpoint_exists():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    CustomUser.objects.create_user(
        username="internal",
        password="test-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    client = APIClient()
    login_response = client.post(
        "/api/internal/auth/login/",
        {"username": "internal", "password": "test-password"},
        format="json",
    )

    refresh_response = client.post(
        "/api/internal/auth/refresh/",
        {"refresh": login_response.json()["refresh"]},
        format="json",
    )

    assert refresh_response.status_code == 200
    assert "access" in refresh_response.json()
