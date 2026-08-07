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
from apps.integrations.store_authorization_service import create_store_authorization
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


START_URL = "/api/internal/integrations/store-authorizations/oauth/start/"
SHOPEE_CALLBACK_URL = "/api/internal/integrations/store-authorizations/oauth/callback/shopee/"
TIKTOK_CALLBACK_URL = "/api/internal/integrations/store-authorizations/oauth/callback/tiktok/"


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=user_type)


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


def marketplace_context(code, platform="shopee"):
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


def shopee_callback(client, state, code="synthetic-auth-code", shop_id="demo-shop-sg", **extra):
    params = {"code": code, "shop_id": shop_id, "state": state}
    params["sign"] = synthetic_callback_signature("shopee", **params)
    params.update(extra)
    return client.get(SHOPEE_CALLBACK_URL, params)


@pytest.mark.django_db
def test_start_requires_permission_and_rejects_raw_or_insecure_input():
    tenant, user, store, config = marketplace_context("sp-start-guard")
    client = client_for(user)

    assert client.post(START_URL, {"platform": "shopee"}, format="json").status_code == 403

    grant(user, "integrations.store.authorize")
    raw = start_oauth(client, store, config, access_token="raw-token-value")
    assert raw.status_code == 422
    assert raw.json()["code"] == "BUSINESS_RULE_VIOLATION"

    insecure = start_oauth(client, store, config, redirect_uri="http://insecure.example.test/")
    assert insecure.status_code == 400

    invalid_platform = start_oauth(client, store, config, platform="bigseller")
    assert invalid_platform.status_code == 400


@pytest.mark.django_db
def test_start_returns_synthetic_authorization_url_and_pending_state():
    tenant, user, store, config = marketplace_context("sp-start-ok")
    grant(user, "integrations.store.authorize")

    response = start_oauth(client_for(user), store, config)

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["platform"] == "shopee"
    assert data["authorization_url"].startswith("https://synthetic-shopee-oauth.invalid/")
    assert "partner_id=synthetic-shopee-partner" in data["authorization_url"]
    assert f"state={data['state']}" in data["authorization_url"]
    assert data["expires_at"]

    session = OAuthStateSession.objects.get(tenant=tenant)
    assert session.status == OAuthStateSession.Status.PENDING
    assert data["state"] not in json.dumps(list(OAuthStateSession.objects.values()), default=str)
    audit = IntegrationAuditLog.objects.get(tenant=tenant, action="oauth_start")
    assert audit.result == IntegrationAuditLog.Result.SUCCESS
    response_text = json.dumps(response.json())
    assert "access_token" not in response_text and "refresh_token" not in response_text


@pytest.mark.django_db
def test_start_validates_store_platform_and_data_scope():
    tenant, user, store, config = marketplace_context("sp-start-scope")
    tiktok_platform = PlatformMaster.objects.create(
        tenant=tenant, code=f"tiktok-{tenant.code}", name="tiktok demo", platform_type="tiktok"
    )
    tiktok_store = StoreMaster.objects.create(
        tenant=tenant,
        platform=tiktok_platform,
        code=f"store-tiktok-{tenant.code}",
        name="TikTok store",
        country_code="SG",
        currency="SGD",
        timezone="Asia/Singapore",
    )
    grant(user, "integrations.store.authorize", DataScope.ScopeType.CUSTOM, {"platforms": ["tiktok"]})
    client = client_for(user)

    scope_denied = start_oauth(client, store, config)
    assert scope_denied.status_code == 403
    assert scope_denied.json()["code"] == "DATA_SCOPE_FORBIDDEN"

    grant(user, "integrations.store.authorize")
    cross_platform = start_oauth(client, tiktok_store, config)
    assert cross_platform.status_code == 422
    assert cross_platform.json()["code"] == "BUSINESS_RULE_VIOLATION"


@pytest.mark.django_db
def test_shopee_callback_success_binds_active_authorization_reference_only():
    tenant, user, store, config = marketplace_context("sp-callback-ok")
    grant(user, "integrations.store.authorize")
    started = start_oauth(client_for(user), store, config)
    state = started.json()["data"]["state"]

    anonymous = APIClient()
    response = shopee_callback(anonymous, state)

    assert response.status_code == 200
    payload = response.json()
    authorization = payload["data"]
    assert authorization["status"] == MarketplaceStoreAuthorization.Status.ACTIVE
    assert authorization["platform"] == "shopee"
    assert authorization["platform_store_id"] == "demo-shop-sg"
    assert authorization["credential_mask"]["credential"].startswith("synthetic-")
    assert authorization["credential_mask"]["token"].startswith("synthetic-")
    assert authorization["credential_reference_version"] == 1
    assert authorization["scopes"] == ["orders.read"]
    assert authorization["authorized_at"]
    response_text = json.dumps(payload)
    assert "credential_id" not in authorization and "token_id" not in authorization
    for forbidden in ("access_token", "refresh_token", "api_secret"):
        assert forbidden not in response_text

    record = MarketplaceStoreAuthorization.objects.get(tenant=tenant)
    assert record.credential_id.startswith("synthetic-shopee-credential-")
    assert record.store_id == store.id

    session = OAuthStateSession.objects.get(tenant=tenant)
    assert session.status == OAuthStateSession.Status.CONSUMED
    assert IntegrationAuditLog.objects.filter(tenant=tenant, action="oauth_callback", result=IntegrationAuditLog.Result.SUCCESS).exists()

    replay = shopee_callback(anonymous, state)
    assert replay.status_code == 409
    assert replay.json()["code"] == "STATE_CONFLICT"
    assert "OAUTH_STATE_CONSUMED" in replay.json()["message"]
    assert MarketplaceStoreAuthorization.objects.filter(tenant=tenant).count() == 1


@pytest.mark.django_db
def test_shopee_callback_rejects_tampered_signature_and_platform_mixing():
    tenant, user, store, config = marketplace_context("sp-callback-bad")
    grant(user, "integrations.store.authorize")
    client = client_for(user)
    anonymous = APIClient()

    state_two = start_oauth(client, store, config).json()["data"]["state"]
    bad_sign = anonymous.get(
        SHOPEE_CALLBACK_URL,
        {"code": "synthetic-auth-code", "shop_id": "demo-shop-sg", "state": state_two, "sign": "0" * 64},
    )
    assert bad_sign.status_code == 409
    assert "OAUTH_CALLBACK_REJECTED" in bad_sign.json()["message"]
    failed_session = OAuthStateSession.objects.get(tenant=tenant, status=OAuthStateSession.Status.FAILED)
    assert failed_session.result_code == "OAUTH_CALLBACK_REJECTED"
    assert not MarketplaceStoreAuthorization.objects.filter(tenant=tenant).exists()

    state_three = start_oauth(client, store, config).json()["data"]["state"]
    wrong_platform = anonymous.get(TIKTOK_CALLBACK_URL, {
        "auth_code": "synthetic-auth-code",
        "shop_id": "demo-shop-sg",
        "shop_cipher": "CIPHER-ABC",
        "state": state_three,
        "sign": synthetic_callback_signature("tiktok", auth_code="synthetic-auth-code", shop_id="demo-shop-sg", state=state_three),
    })
    assert wrong_platform.status_code == 400
    assert "OAUTH_PLATFORM_MISMATCH" in wrong_platform.json()["message"]


@pytest.mark.django_db
def test_shopee_callback_rejects_raw_credential_query_params():
    tenant, user, store, config = marketplace_context("sp-callback-raw")
    grant(user, "integrations.store.authorize")
    state = start_oauth(client_for(user), store, config).json()["data"]["state"]

    response = shopee_callback(APIClient(), state, access_token="leaked-token")

    assert response.status_code == 409
    assert "OAUTH_CALLBACK_REJECTED" in response.json()["message"]
    session = OAuthStateSession.objects.get(tenant=tenant)
    assert session.status == OAuthStateSession.Status.FAILED
    assert session.result_code == "OAUTH_CALLBACK_REJECTED"
    assert not MarketplaceStoreAuthorization.objects.filter(tenant=tenant).exists()
    assert IntegrationAuditLog.objects.filter(
        tenant=tenant, action="oauth_callback", result=IntegrationAuditLog.Result.BLOCKED
    ).exists()


@pytest.mark.django_db
def test_shopee_callback_unknown_or_missing_state_is_rejected():
    anonymous = APIClient()

    unknown = anonymous.get(SHOPEE_CALLBACK_URL, {"state": "forged-state", "code": "c", "shop_id": "s", "sign": "x"})
    assert unknown.status_code == 400
    assert unknown.json()["code"] == "VALIDATION_ERROR"
    assert "OAUTH_STATE_INVALID" in unknown.json()["message"]

    missing = anonymous.get(SHOPEE_CALLBACK_URL, {"code": "c", "shop_id": "s", "sign": "x"})
    assert missing.status_code == 400
    assert "OAUTH_STATE_INVALID" in missing.json()["message"]


@pytest.mark.django_db
def test_shopee_callback_cross_tenant_binding_conflict():
    tenant_a, user_a, store_a, config_a = marketplace_context("sp-conflict-a")
    create_store_authorization(
        tenant=tenant_a,
        integration_config=config_a,
        store=store_a,
        platform="shopee",
        region="SG",
        platform_store_id="shared-shop",
        merchant_subject_id="synthetic-shopee-merchant-shared-shop",
        shop_cipher="",
        credential_id="synthetic-shopee-credential-shared-shop",
        token_id="synthetic-shopee-token-shared-shop",
        scopes=["orders.read"],
        actor=user_a,
    )
    _tenant_b, user_b, store_b, config_b = marketplace_context("sp-conflict-b")
    grant(user_b, "integrations.store.authorize")
    state = start_oauth(client_for(user_b), store_b, config_b).json()["data"]["state"]

    response = shopee_callback(APIClient(), state, shop_id="shared-shop")

    assert response.status_code == 409
    assert response.json()["code"] == "STATE_CONFLICT"
    assert "OAUTH_STORE_BOUND_CONFLICT" in response.json()["message"]
    assert MarketplaceStoreAuthorization.objects.filter(tenant=tenant_a).count() == 1
    assert MarketplaceStoreAuthorization.objects.count() == 1
    session = OAuthStateSession.objects.get(tenant=user_b.tenant)
    assert session.status == OAuthStateSession.Status.FAILED
    assert session.result_code == "OAUTH_STORE_BOUND_CONFLICT"
