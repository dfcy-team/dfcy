import json
import secrets

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.marketplace_providers import synthetic_callback_signature
from apps.integrations.models import (
    IntegrationAuditLog,
    MarketplaceStoreAuthorization,
    OAuthStateSession,
    PlatformIntegrationConfig,
)
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


START_URL = "/api/internal/integrations/store-authorizations/oauth/start/"
TIKTOK_CALLBACK_URL = "/api/internal/integrations/store-authorizations/oauth/callback/tiktok/"


def create_user(tenant, username):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)


def grant(user, permission_code, scope_type=DataScope.ScopeType.ALL, config=None):
    suffix = secrets.token_hex(3)
    role = Role.objects.create(
        tenant=user.tenant,
        name=f"Role {permission_code} {user.id} {suffix}",
        code=f"role-{user.id}-{permission_code.replace('.', '-')}-{suffix}",
    )
    role.permissions.add(Permission.objects.get(code=permission_code))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    if scope_type:
        DataScope.objects.create(
            tenant=user.tenant,
            role=role,
            scope_type=scope_type,
            config=config or {},
        )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def marketplace_context(code, platform="tiktok"):
    tenant = Tenant.objects.create(name=f"Tenant {code}", code=code)
    user = create_user(tenant, f"user-{code}")
    platform_master = PlatformMaster.objects.create(
        tenant=tenant,
        code=f"{platform}-{code}",
        name=f"{platform} demo",
        platform_type=platform,
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform_master,
        code=f"store-{code}",
        name=f"Store {code}",
        country_code="SG",
        currency="SGD",
        timezone="Asia/Singapore",
    )
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform=platform,
        account_alias=f"demo-{code}",
        environment=PlatformIntegrationConfig.Environment.MOCK,
        status=PlatformIntegrationConfig.Status.DISABLED,
        created_by=user,
    )
    return tenant, user, store, config


def start_oauth(client, store, config, **overrides):
    payload = {
        "platform": config.platform,
        "integration_config_id": config.id,
        "store_id": store.id,
        "region": "SG",
        "redirect_uri": "https://callback.example.test/oauth/return/",
        "scopes": ["orders.read"],
    }
    payload.update(overrides)
    return client.post(START_URL, payload, format="json")


def tiktok_callback(client, state, auth_code="synthetic-auth-code", shop_id="demo-tt-shop", shop_cipher="CIPHER-ABCDEFGH", **extra):
    params = {"auth_code": auth_code, "shop_id": shop_id, "state": state, "shop_cipher": shop_cipher}
    params["sign"] = synthetic_callback_signature("tiktok", **params)
    params.update(extra)
    return client.get(TIKTOK_CALLBACK_URL, params)


@pytest.mark.django_db
def test_tiktok_start_builds_synthetic_authorization_url():
    tenant, user, store, config = marketplace_context("tt-start-ok")
    grant(user, "integrations.store.authorize")

    response = start_oauth(client_for(user), store, config)

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["platform"] == "tiktok"
    assert data["authorization_url"].startswith("https://synthetic-tiktok-oauth.invalid/")
    assert "app_key=synthetic-tiktok-app-key" in data["authorization_url"]
    assert f"state={data['state']}" in data["authorization_url"]
    assert OAuthStateSession.objects.filter(tenant=tenant, platform="tiktok").count() == 1


@pytest.mark.django_db
def test_tiktok_callback_success_persists_cipher_without_exposing_it():
    tenant, user, store, config = marketplace_context("tt-callback-ok")
    grant(user, "integrations.store.authorize")
    state = start_oauth(client_for(user), store, config).json()["data"]["state"]

    response = tiktok_callback(APIClient(), state)

    assert response.status_code == 200
    payload = response.json()
    authorization = payload["data"]
    assert authorization["status"] == MarketplaceStoreAuthorization.Status.ACTIVE
    assert authorization["platform"] == "tiktok"
    assert authorization["platform_store_id"] == "demo-tt-shop"
    assert authorization["credential_mask"]["credential"].startswith("synthetic-")
    response_text = json.dumps(payload)
    assert "CIPHER-ABCDEFGH" not in response_text
    assert "shop_cipher" not in authorization

    record = MarketplaceStoreAuthorization.objects.get(tenant=tenant)
    assert record.shop_cipher == "CIPHER-ABCDEFGH"
    assert record.credential_id.startswith("synthetic-tiktok-credential-")
    assert record.token_id.startswith("synthetic-tiktok-token-")
    assert IntegrationAuditLog.objects.filter(
        tenant=tenant, action="oauth_callback", result=IntegrationAuditLog.Result.SUCCESS
    ).exists()

    replay = tiktok_callback(APIClient(), state)
    assert replay.status_code == 409
    assert "OAUTH_STATE_CONSUMED" in replay.json()["message"]


@pytest.mark.django_db
def test_tiktok_callback_requires_valid_shop_cipher():
    tenant, user, store, config = marketplace_context("tt-callback-cipher")
    grant(user, "integrations.store.authorize")
    client = client_for(user)
    anonymous = APIClient()

    state = start_oauth(client, store, config).json()["data"]["state"]
    missing = tiktok_callback(anonymous, state, shop_cipher="")
    assert missing.status_code == 409
    assert "OAUTH_CALLBACK_REJECTED" in missing.json()["message"]
    assert not MarketplaceStoreAuthorization.objects.filter(tenant=tenant).exists()

    state_two = start_oauth(client, store, config).json()["data"]["state"]
    session_two = OAuthStateSession.objects.filter(tenant=tenant).order_by("-id").first()
    whitespace = tiktok_callback(anonymous, state_two, shop_cipher="BAD CIPHER")
    assert whitespace.status_code == 409
    session_two.refresh_from_db()
    assert session_two.status == OAuthStateSession.Status.FAILED
    assert session_two.result_code == "OAUTH_CALLBACK_REJECTED"


@pytest.mark.django_db
def test_tiktok_callback_rejects_missing_auth_code_signature_fields():
    tenant, user, store, config = marketplace_context("tt-callback-fields")
    grant(user, "integrations.store.authorize")
    state = start_oauth(client_for(user), store, config).json()["data"]["state"]

    params = {"shop_id": "demo-tt-shop", "state": state, "shop_cipher": "CIPHER-ABCDEFGH"}
    params["sign"] = synthetic_callback_signature("tiktok", **params)
    response = APIClient().get(TIKTOK_CALLBACK_URL, params)

    assert response.status_code == 409
    assert "OAUTH_CALLBACK_REJECTED" in response.json()["message"]
    assert not MarketplaceStoreAuthorization.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_tiktok_callback_rejects_raw_credential_params_and_unknown_state():
    tenant, user, store, config = marketplace_context("tt-callback-raw")
    grant(user, "integrations.store.authorize")
    state = start_oauth(client_for(user), store, config).json()["data"]["state"]

    raw = tiktok_callback(APIClient(), state, refresh_token="leaked-refresh")
    assert raw.status_code == 409
    assert "OAUTH_CALLBACK_REJECTED" in raw.json()["message"]
    session = OAuthStateSession.objects.get(tenant=tenant)
    assert session.status == OAuthStateSession.Status.FAILED
    assert not MarketplaceStoreAuthorization.objects.filter(tenant=tenant).exists()

    unknown = APIClient().get(TIKTOK_CALLBACK_URL, {"state": "forged", "auth_code": "c", "shop_id": "s", "shop_cipher": "C", "sign": "x"})
    assert unknown.status_code == 400
    assert "OAUTH_STATE_INVALID" in unknown.json()["message"]
