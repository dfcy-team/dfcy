import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
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
            "full_name": "",
            "phone": "",
            "user_type": CustomUser.UserType.INTERNAL,
            "tenant_id": tenant.id,
            "is_superuser": False,
            "roles": ["admin"],
            "permissions": ["accounts.view"],
            "menu_permission_codes": [],
            "action_permission_codes": ["accounts.view"],
            "field_permission_codes": [],
            "data_scope": [],
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
            "full_name": "",
            "phone": "",
            "user_type": CustomUser.UserType.INTERNAL,
            "tenant_id": tenant.id,
            "is_superuser": False,
            "roles": [],
            "permissions": [],
            "menu_permission_codes": [],
            "action_permission_codes": [],
            "field_permission_codes": [],
            "data_scope": [],
        },
    }


@pytest.mark.django_db
def test_me_exposes_trusted_superuser_and_all_scope():
    tenant = Tenant.objects.create(name="Tenant", code="superuser-tenant")
    user = CustomUser.objects.create_superuser(
        username="root",
        email="root@example.com",
        password="test-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/internal/auth/me/")

    assert response.status_code == 200
    assert response.json()["data"]["is_superuser"] is True
    assert response.json()["data"]["roles"] == []
    assert response.json()["data"]["data_scope"] == [
        {"scope_type": "all", "config": {"all": True}, "role_id": None}
    ]


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


@pytest.mark.django_db
def test_current_user_profile_is_authenticated_and_updates_only_the_current_user():
    tenant = Tenant.objects.create(name="Tenant", code="profile-tenant")
    user = CustomUser.objects.create_user(
        username="profile-user",
        email="profile@example.com",
        password="test-old-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    other_user = CustomUser.objects.create_user(
        username="other-profile-user",
        email="other@example.com",
        full_name="Other user",
        phone="13800000000",
        password="test-other-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )

    client = APIClient()
    assert client.get("/api/internal/auth/profile/").status_code == 401
    client.force_authenticate(user=user)

    initial = client.get("/api/internal/auth/profile/")
    assert initial.status_code == 200
    assert initial.json()["data"] == {
        "username": "profile-user",
        "full_name": "",
        "email": "profile@example.com",
        "phone": "",
    }

    response = client.patch(
        "/api/internal/auth/profile/",
        {
            "username": "must-not-change",
            "full_name": "张三",
            "email": "zhangsan@example.com",
            "phone": "13900000000",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "username": "profile-user",
        "full_name": "张三",
        "email": "zhangsan@example.com",
        "phone": "13900000000",
    }
    user.refresh_from_db()
    other_user.refresh_from_db()
    assert user.username == "profile-user"
    assert user.full_name == "张三"
    assert user.email == "zhangsan@example.com"
    assert user.phone == "13900000000"
    assert other_user.full_name == "Other user"
    assert other_user.email == "other@example.com"
    assert other_user.phone == "13800000000"

    log = OperationLog.objects.get(action="profile_update")
    assert log.user_id == user.id
    assert log.after_data == {
        "full_name": "张三",
        "email": "zhangsan@example.com",
        "phone": "13900000000",
    }


@pytest.mark.django_db
def test_current_user_password_change_validates_credentials_and_strength():
    tenant = Tenant.objects.create(name="Tenant", code="password-tenant")
    user = CustomUser.objects.create_user(
        username="password-user",
        email="password@example.com",
        password="test-old-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    client = APIClient()

    assert client.post("/api/internal/auth/password/", {}, format="json").status_code == 401
    client.force_authenticate(user=user)

    wrong_current = client.post(
        "/api/internal/auth/password/",
        {
            "current_password": "wrong-password",
            "new_password": "NewSecure!234",
            "confirm_password": "NewSecure!234",
        },
        format="json",
    )
    assert wrong_current.status_code == 400
    assert "current_password" in wrong_current.json()["data"]

    mismatch = client.post(
        "/api/internal/auth/password/",
        {
            "current_password": "test-old-password",
            "new_password": "NewSecure!234",
            "confirm_password": "NewSecure!235",
        },
        format="json",
    )
    assert mismatch.status_code == 400
    assert "confirm_password" in mismatch.json()["data"]

    too_short = client.post(
        "/api/internal/auth/password/",
        {
            "current_password": "test-old-password",
            "new_password": "Short!23",
            "confirm_password": "Short!23",
        },
        format="json",
    )
    assert too_short.status_code == 400
    assert "new_password" in too_short.json()["data"]

    weak = client.post(
        "/api/internal/auth/password/",
        {
            "current_password": "test-old-password",
            "new_password": "123456789012",
            "confirm_password": "123456789012",
        },
        format="json",
    )
    assert weak.status_code == 400
    assert "new_password" in weak.json()["data"]

    success = client.post(
        "/api/internal/auth/password/",
        {
            "current_password": "test-old-password",
            "new_password": "NewSecure!234",
            "confirm_password": "NewSecure!234",
        },
        format="json",
    )
    assert success.status_code == 200
    assert success.json() == {
        "success": True,
        "code": "OK",
        "message": "success",
        "data": {"password_changed": True},
    }
    user.refresh_from_db()
    assert user.check_password("NewSecure!234")
    log = OperationLog.objects.get(action="password_change")
    assert log.user_id == user.id
    assert log.after_data == {"username": "password-user", "changed": True}
    assert "test-old-password" not in repr(log.after_data)
    assert "NewSecure!234" not in repr(log.after_data)
