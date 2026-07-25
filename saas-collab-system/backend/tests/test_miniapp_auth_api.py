import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.miniapp_auth import digest_miniapp_subject
from apps.accounts.models import CustomUser, MiniAppIdentity
from apps.tenants.models import Tenant


def create_bound_user(subject="device-001"):
    tenant = Tenant.objects.create(name="Miniapp Tenant", code="miniapp-tenant")
    user = CustomUser.objects.create_user(
        username="miniapp-user",
        email="miniapp-user@example.com",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    MiniAppIdentity.objects.create(
        provider=MiniAppIdentity.Provider.WECHAT,
        subject_digest=digest_miniapp_subject(MiniAppIdentity.Provider.WECHAT, subject),
        user=user,
    )
    return tenant, user


@pytest.mark.django_db
@override_settings(MINIAPP_AUTH_MODE="sandbox")
def test_sandbox_login_refresh_and_me_use_standard_contract():
    tenant, user = create_bound_user()
    client = APIClient()

    login = client.post(
        "/api/miniapp/auth/login/",
        {"code": "sandbox:device-001"},
        format="json",
    )

    assert login.status_code == 200
    assert login.json()["success"] is True
    payload = login.json()["data"]
    assert payload["access_token"]
    assert payload["refresh_token"]
    assert payload["expires_in"] > 0
    assert payload["user"] == {
        "id": str(user.id),
        "username": user.username,
        "displayName": user.username,
        "userType": CustomUser.UserType.INTERNAL,
        "tenant": {"id": str(tenant.id), "name": tenant.name},
        "roles": [],
        "permissions": [],
        "dataScope": [],
    }
    assert "session_key" not in str(login.json()).lower()
    assert "device-001" not in str(login.json())

    refresh = client.post(
        "/api/miniapp/auth/refresh/",
        {"refresh_token": payload["refresh_token"]},
        format="json",
    )
    assert refresh.status_code == 200
    assert refresh.json()["data"]["access_token"]

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {payload['access_token']}")
    me = client.get("/api/miniapp/auth/me/")
    assert me.status_code == 200
    assert me.json()["data"]["tenant"]["id"] == str(tenant.id)


@pytest.mark.django_db
@override_settings(MINIAPP_AUTH_MODE="sandbox")
def test_unbound_and_invalid_sandbox_codes_fail_closed():
    invalid = APIClient().post(
        "/api/miniapp/auth/login/",
        {"code": "wechat-real-looking-code"},
        format="json",
    )
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "MINIAPP_CODE_INVALID"

    unbound = APIClient().post(
        "/api/miniapp/auth/login/",
        {"code": "sandbox:unbound-device"},
        format="json",
    )
    assert unbound.status_code == 401
    assert unbound.json()["code"] == "MINIAPP_IDENTITY_UNBOUND"


@pytest.mark.django_db
@override_settings(MINIAPP_AUTH_MODE="disabled")
def test_disabled_mode_does_not_exchange_codes():
    response = APIClient().post(
        "/api/miniapp/auth/login/",
        {"code": "sandbox:device-001"},
        format="json",
    )
    assert response.status_code == 503
    assert response.json()["code"] == "MINIAPP_AUTH_DISABLED"


@pytest.mark.django_db
@override_settings(MINIAPP_AUTH_MODE="sandbox")
def test_internal_channel_token_cannot_access_miniapp_me():
    _tenant, user = create_bound_user("device-002")
    internal_access = str(RefreshToken.for_user(user).access_token)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {internal_access}")

    response = client.get("/api/miniapp/auth/me/")

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


@pytest.mark.django_db
@override_settings(MINIAPP_AUTH_MODE="sandbox")
def test_internal_channel_refresh_token_is_rejected():
    _tenant, user = create_bound_user("device-003")
    internal_refresh = str(RefreshToken.for_user(user))

    response = APIClient().post(
        "/api/miniapp/auth/refresh/",
        {"refresh_token": internal_refresh},
        format="json",
    )

    assert response.status_code == 401
    assert response.json()["code"] == "MINIAPP_TOKEN_INVALID"


def test_health_discloses_capability_state_without_credentials(settings):
    settings.MINIAPP_AUTH_MODE = "sandbox"
    response = APIClient().get("/api/miniapp/health/")
    assert response.status_code == 200
    assert response.json()["data"] == {
        "service": "miniapp-auth",
        "capability_status": "sandbox",
        "provider_exchange": "mock-only",
    }


@pytest.mark.django_db
@override_settings(
    MINIAPP_AUTH_MODE="platform",
    MINIAPP_APP_ID="wx-test-app-id",
    MINIAPP_APP_SECRET="server-only-test-secret",
)
def test_platform_login_exchanges_code_without_exposing_provider_session(monkeypatch):
    tenant, user = create_bound_user("wechat-openid-001")
    monkeypatch.setattr(
        "apps.accounts.miniapp_auth._fetch_wechat_session",
        lambda code: {
            "openid": "wechat-openid-001",
            "session_key": "provider-session-must-not-leave-backend",
        },
    )

    response = APIClient().post(
        "/api/miniapp/auth/login/",
        {"code": "one-time-wechat-code"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["data"]["user"]["id"] == str(user.id)
    assert response.json()["data"]["user"]["tenant"]["id"] == str(tenant.id)
    serialized = str(response.json())
    assert "provider-session-must-not-leave-backend" not in serialized
    assert "wechat-openid-001" not in serialized
    assert "server-only-test-secret" not in serialized


@pytest.mark.django_db
@override_settings(
    MINIAPP_AUTH_MODE="platform",
    MINIAPP_APP_ID="wx-test-app-id",
    MINIAPP_APP_SECRET="server-only-test-secret",
)
def test_platform_login_maps_invalid_and_provider_failures(monkeypatch):
    monkeypatch.setattr(
        "apps.accounts.miniapp_auth._fetch_wechat_session",
        lambda code: {"errcode": 40029, "errmsg": "invalid code"},
    )
    invalid = APIClient().post(
        "/api/miniapp/auth/login/",
        {"code": "expired-wechat-code"},
        format="json",
    )
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "MINIAPP_CODE_INVALID"

    monkeypatch.setattr(
        "apps.accounts.miniapp_auth._fetch_wechat_session",
        lambda code: {"errcode": -1, "errmsg": "system busy"},
    )
    unavailable = APIClient().post(
        "/api/miniapp/auth/login/",
        {"code": "temporary-wechat-code"},
        format="json",
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "MINIAPP_PROVIDER_UNAVAILABLE"


def test_platform_health_reports_wechat_exchange(settings):
    settings.MINIAPP_AUTH_MODE = "platform"
    response = APIClient().get("/api/miniapp/health/")
    assert response.status_code == 200
    assert response.json()["data"] == {
        "service": "miniapp-auth",
        "capability_status": "platform",
        "provider_exchange": "wechat-code2session",
    }
