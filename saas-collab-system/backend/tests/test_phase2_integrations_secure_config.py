import json

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import CredentialMutationRequest, IntegrationAuditLog, PlatformIntegrationConfig
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=user_type)


def grant_integration_access(user):
    role = Role.objects.create(tenant=user.tenant, name="Tech Admin", code="tech_admin")
    for permission_code in (
        "integrations.view",
        "integrations.manage",
        "integrations.rotate",
        "integrations.run",
        "integrations.config.view",
        "integrations.config.create",
        "integrations.config.update",
        "integrations.config.verify",
        "integrations.config.disable",
        "integrations.credential.rotate",
        "integrations.credential.clear",
        "integrations.audit.view",
    ):
        action = permission_code.rsplit(".", 1)[-1]
        permission, _created = Permission.objects.get_or_create(
            code=permission_code,
            defaults={
                "name": f"Integrations {action}",
                "module": "integrations",
                "action": action,
            },
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})


def grant_integration_view_only(user):
    role = Role.objects.create(tenant=user.tenant, name="Integration Viewer", code=f"integration-viewer-{user.id}")
    permission, _created = Permission.objects.get_or_create(
        code="integrations.config.view",
        defaults={
            "name": "View integrations",
            "module": "integrations",
            "action": "view",
        },
    )
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})


def grant_integration_permission(user, permission_code, scope_config):
    role = Role.objects.create(
        tenant=user.tenant,
        name=f"{permission_code} scoped",
        code=f"{permission_code}-{user.id}",
    )
    role.permissions.add(Permission.objects.get(code=permission_code))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=user.tenant,
        role=role,
        scope_type=DataScope.ScopeType.CUSTOM,
        config=scope_config,
    )


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


SHOPEE_LOOPBACK_CALLBACK = (
    "http://127.0.0.1:8000/api/internal/integrations/store-authorizations/oauth/callback/shopee/"
)


def shopee_pilot_payload(callback_url):
    return {
        "platform": "shopee",
        "account_alias": "pilot-loopback",
        "environment": "pilot",
        "status": "draft",
        "regions": ["PH"],
        "contract_version": "v2",
        "callback_url": callback_url,
        "platform_config": {"partner_id": "approved-public-partner-id"},
    }


@pytest.mark.django_db
@override_settings(
    LIVE_OAUTH_REDIRECT_ALLOWLIST=[SHOPEE_LOOPBACK_CALLBACK],
    LIVE_SHOPEE_REDIRECT_URI=SHOPEE_LOOPBACK_CALLBACK,
)
def test_pilot_accepts_exact_shopee_loopback_callback():
    tenant = Tenant.objects.create(name="Tenant", code="pilot-loopback-callback")
    user = create_user(tenant, "pilot-loopback-admin")
    grant_integration_access(user)

    response = authenticated_client(user).post(
        "/api/internal/integrations/configs/",
        shopee_pilot_payload(SHOPEE_LOOPBACK_CALLBACK),
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["data"]["callback_url"] == SHOPEE_LOOPBACK_CALLBACK


@pytest.mark.django_db
@pytest.mark.parametrize(
    "environment,callback_url",
    [
        (
            "production",
            "http://127.0.0.1:8000/api/internal/integrations/store-authorizations/oauth/callback/shopee/",
        ),
        (
            "pilot",
            "http://192.168.2.10:8000/api/internal/integrations/store-authorizations/oauth/callback/shopee/",
        ),
        (
            "pilot",
            "http://127.0.0.1:8001/api/internal/integrations/store-authorizations/oauth/callback/shopee/",
        ),
        (
            "pilot",
            "http://127.0.0.1:8000/api/internal/integrations/store-authorizations/oauth/callback/tiktok/",
        ),
        (
            "pilot",
            "http://127.0.0.1:8000/api/internal/integrations/store-authorizations/oauth/callback/shopee/?next=evil",
        ),
    ],
)
def test_marketplace_callback_rejects_unapproved_http_targets(environment, callback_url):
    tenant = Tenant.objects.create(name="Tenant", code="reject-http-callback")
    user = create_user(tenant, "reject-http-admin")
    grant_integration_access(user)

    with override_settings(
        LIVE_OAUTH_REDIRECT_ALLOWLIST=[callback_url],
        LIVE_SHOPEE_REDIRECT_URI=callback_url,
    ):
        payload = shopee_pilot_payload(callback_url)
        payload["environment"] = environment
        response = authenticated_client(user).post(
            "/api/internal/integrations/configs/",
            payload,
            format="json",
        )

    assert response.status_code == 400
    assert "callback_url" in json.dumps(response.json())


def config_payload(account_alias="demo-account", environment="mock", status="active"):
    return {
        "platform": "mock",
        "account_alias": account_alias,
        "environment": environment,
        "status": status,
    }


@pytest.mark.django_db
def test_integration_config_crud_uses_tenant_scope_and_standard_response():
    tenant = Tenant.objects.create(name="Tenant A", code="tenant-a")
    other_tenant = Tenant.objects.create(name="Tenant B", code="tenant-b")
    user = create_user(tenant, "tech-admin")
    other_user = create_user(other_tenant, "other-tech-admin")
    grant_integration_access(user)
    grant_integration_access(other_user)

    create_response = authenticated_client(user).post(
        "/api/internal/integrations/configs/",
        config_payload(),
        format="json",
    )

    assert create_response.status_code == 201
    body = create_response.json()
    assert body["success"] is True
    assert body["code"] == "OK"
    assert body["data"]["tenant_id"] == tenant.id
    assert "credential_ciphertext" not in body["data"]

    list_response = authenticated_client(other_user).get("/api/internal/integrations/configs/")

    assert list_response.status_code == 200
    assert list_response.json()["data"] == []


@pytest.mark.django_db
def test_integration_exact_permission_scope_filters_details_and_request_bodies():
    tenant = Tenant.objects.create(name="Tenant", code="integration-exact-scope")
    user = create_user(tenant, "integration-scoped")
    grant_integration_permission(user, "integrations.config.view", {"platforms": ["mock"]})
    grant_integration_permission(user, "integrations.config.create", {"platforms": ["mock"]})
    grant_integration_permission(user, "integrations.config.update", {"platforms": ["mock"]})
    visible = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="mock",
        account_alias="demo-visible",
        environment=PlatformIntegrationConfig.Environment.MOCK,
        status=PlatformIntegrationConfig.Status.ACTIVE,
        created_by=user,
    )
    hidden = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="other",
        account_alias="demo-hidden",
        environment=PlatformIntegrationConfig.Environment.MOCK,
        status=PlatformIntegrationConfig.Status.ACTIVE,
        created_by=user,
    )
    client = authenticated_client(user)
    listing = client.get("/api/internal/integrations/configs/")
    assert [item["id"] for item in listing.json()["data"]] == [visible.id]
    detail = client.get(f"/api/internal/integrations/configs/{hidden.id}/")
    assert detail.status_code == 404
    assert detail.json()["code"] == "RESOURCE_NOT_FOUND"
    payload = config_payload(account_alias="demo-forbidden")
    payload["platform"] = "other"
    denied = client.post("/api/internal/integrations/configs/", payload, format="json")
    assert denied.status_code == 403
    assert denied.json()["code"] == "DATA_SCOPE_FORBIDDEN"

    patch_denied = client.patch(
        f"/api/internal/integrations/configs/{visible.id}/",
        {"platform": "other", "version": visible.config_version},
        format="json",
    )
    assert patch_denied.status_code == 400
    visible.refresh_from_db()
    assert visible.platform == "mock"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "scope_config",
    (
        {"platforms": ["mock"], "unexpected": ["value"]},
        {"integration_config_ids": ["not-an-id"]},
        {"platforms": [""]},
    ),
)
def test_integration_scope_rejects_unknown_keys_and_invalid_values(scope_config):
    tenant = Tenant.objects.create(name="Tenant", code=f"invalid-integration-scope-{len(str(scope_config))}")
    user = create_user(tenant, f"invalid-integration-scope-{len(str(scope_config))}")
    grant_integration_permission(user, "integrations.config.create", scope_config)

    response = authenticated_client(user).post(
        "/api/internal/integrations/configs/",
        config_payload(account_alias="invalid-scope-probe"),
        format="json",
    )

    assert response.status_code == 403
    assert response.json()["code"] == "DATA_SCOPE_INVALID"


@pytest.mark.django_db
def test_unauthorized_external_and_rpa_users_are_rejected():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    internal = create_user(tenant, "plain-internal")
    external = create_user(tenant, "external", CustomUser.UserType.EXTERNAL)
    rpa = create_user(tenant, "rpa", CustomUser.UserType.RPA)

    assert APIClient().get("/api/internal/integrations/configs/").status_code == 401
    assert authenticated_client(internal).get("/api/internal/integrations/configs/").status_code == 403
    assert authenticated_client(external).get("/api/internal/integrations/configs/").status_code == 403
    assert authenticated_client(rpa).get("/api/internal/integrations/configs/").status_code == 403


@pytest.mark.django_db
def test_integration_view_permission_cannot_create_update_rotate_or_disable():
    tenant = Tenant.objects.create(name="Tenant", code="integration-view-only")
    user = create_user(tenant, "integration-viewer")
    grant_integration_view_only(user)
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="mock",
        account_alias="demo-view-only",
        environment=PlatformIntegrationConfig.Environment.MOCK,
        status=PlatformIntegrationConfig.Status.ACTIVE,
        created_by=user,
    )
    client = authenticated_client(user)

    assert client.get("/api/internal/integrations/configs/").status_code == 200
    assert client.get(f"/api/internal/integrations/configs/{config.id}/").status_code == 200
    assert client.post("/api/internal/integrations/configs/", config_payload(), format="json").status_code == 403
    assert (
        client.patch(
            f"/api/internal/integrations/configs/{config.id}/",
            {"account_alias": "unauthorized-change"},
            format="json",
        ).status_code
        == 403
    )
    assert client.post(f"/api/internal/integrations/configs/{config.id}/rotate/", {}, format="json").status_code == 403
    assert client.post(f"/api/internal/integrations/configs/{config.id}/disable/", {}, format="json").status_code == 403

    config.refresh_from_db()
    assert config.account_alias == "demo-view-only"
    assert config.status == PlatformIntegrationConfig.Status.ACTIVE


@pytest.mark.django_db
def test_credentials_never_appear_in_api_response_or_audit_log():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "tech-admin")
    grant_integration_access(user)

    response = authenticated_client(user).post(
        "/api/internal/integrations/configs/",
        config_payload(),
        format="json",
    )

    assert response.status_code == 201
    response_text = json.dumps(response.json())
    assert "synthetic-demo-config-credential" not in response_text
    assert "synthetic-demo-config-token" not in response_text
    assert "credential_ciphertext" not in response_text

    audit = IntegrationAuditLog.objects.get(action="create")
    audit_text = json.dumps(audit.masked_detail)
    assert "synthetic-demo-config-credential" not in audit_text
    assert "synthetic-demo-config-token" not in audit_text
    assert audit.masked_detail["credential_mask"] == {}

    rejected = authenticated_client(user).post(
        "/api/internal/integrations/configs/",
        {
            **config_payload(account_alias="demo-rejected-reference"),
            "credential_id": "synthetic-demo-config-credential",
            "token_id": "synthetic-demo-config-token",
        },
        format="json",
    )
    assert rejected.status_code == 400


@pytest.mark.django_db
def test_reference_rotation_is_atomic_and_changes_reference_version():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "tech-admin")
    grant_integration_access(user)

    create_response = authenticated_client(user).post(
        "/api/internal/integrations/configs/",
        config_payload(status="disabled"),
        format="json",
    )
    config_id = create_response.json()["data"]["id"]

    rotate_response = authenticated_client(user).post(
        f"/api/internal/integrations/configs/{config_id}/rotate/",
        {
            "credential_reference_version": 2,
            "credential_id": "synthetic-demo-rotated-credential",
            "token_id": "synthetic-demo-rotated-token",
        },
        format="json",
    )

    assert rotate_response.status_code == 200
    assert rotate_response.json()["data"]["credential_key_version"] == "reference-v2"
    assert rotate_response.json()["data"]["credential_reference_version"] == 2
    assert "credential_ciphertext" not in rotate_response.json()["data"]
    assert "synthetic-demo-rotated-token" not in json.dumps(rotate_response.json())
    assert IntegrationAuditLog.objects.filter(action="rotate_config_reference").exists()

    conflict_response = authenticated_client(user).post(
        f"/api/internal/integrations/configs/{config_id}/rotate/",
        {
            "credential_reference_version": 2,
            "credential_id": "synthetic-demo-conflict-credential",
            "token_id": "synthetic-demo-conflict-token",
        },
        format="json",
    )
    assert conflict_response.status_code == 409
    assert conflict_response.json()["code"] == "STATE_CONFLICT"


@pytest.mark.django_db
def test_raw_credentials_are_rejected_without_persistence():
    tenant = Tenant.objects.create(name="Tenant", code="raw-credential-rejection")
    user = create_user(tenant, "raw-credential-user")
    grant_integration_access(user)
    payload = config_payload()
    payload["credentials"] = {"api_key": "forbidden-value"}

    response = authenticated_client(user).post("/api/internal/integrations/configs/", payload, format="json")

    assert response.status_code == 422
    assert response.json()["code"] == "BUSINESS_RULE_VIOLATION"
    assert not PlatformIntegrationConfig.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_production_config_cannot_be_active_or_verified_in_phase2():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "tech-admin")
    grant_integration_access(user)
    client = authenticated_client(user)

    active_response = client.post(
        "/api/internal/integrations/configs/",
        config_payload(account_alias="prod-active", environment="production", status="active"),
        format="json",
    )
    assert active_response.status_code == 400
    assert active_response.json()["success"] is False

    pending_response = client.post(
        "/api/internal/integrations/configs/",
        config_payload(account_alias="prod-pending", environment="production", status="pending_review"),
        format="json",
    )
    assert pending_response.status_code == 201
    config_id = pending_response.json()["data"]["id"]

    verify_response = client.post(f"/api/internal/integrations/configs/{config_id}/verify/", {}, format="json")
    assert verify_response.status_code == 400
    assert verify_response.json()["success"] is False
    assert IntegrationAuditLog.objects.filter(action="verify", result=IntegrationAuditLog.Result.BLOCKED).exists()


@pytest.mark.django_db
def test_disable_endpoint_updates_status_without_exposing_credentials():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "tech-admin")
    grant_integration_access(user)
    client = authenticated_client(user)
    create_response = client.post("/api/internal/integrations/configs/", config_payload(), format="json")
    config_id = create_response.json()["data"]["id"]

    response = client.post(f"/api/internal/integrations/configs/{config_id}/disable/", {}, format="json")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == PlatformIntegrationConfig.Status.DISABLED
    assert "credential_ciphertext" not in response.json()["data"]


class FakeCustody:
    def __init__(self):
        self.revoked = []
        self.store_calls = 0
        self.rotate_calls = 0

    def store_secrets(self, **kwargs):
        self.store_calls += 1
        assert kwargs.get("app_secret")
        return {
            "credential_id": "custody/credential/abcdef12",
            "token_id": "custody/token/abcdef12",
            "credential_mask": {"configured": "custody-must-not-control-the-mask"},
            "reference_version": kwargs["reference_version"],
        }

    def rotate_secrets(self, **kwargs):
        self.rotate_calls += 1
        return {
            "credential_id": "custody/credential/rotated12",
            "token_id": "custody/token/rotated12",
            "credential_mask": {"configured": "********"},
            "reference_version": kwargs["reference_version"],
            "previous_reference_status": "revoked",
        }

    def revoke(self, credential_id, token_id):
        self.revoked.append((credential_id, token_id))
        return {"status": "revoked", "error_code": ""}


@pytest.mark.django_db
def test_platform_schema_and_write_only_credential_lifecycle(monkeypatch):
    tenant = Tenant.objects.create(name="Tenant", code="platform-config-secrets")
    user = create_user(tenant, "platform-config-admin")
    grant_integration_access(user)
    client = authenticated_client(user)

    schema_response = client.get("/api/internal/integrations/platform-schemas/shopee/?environment=sandbox")
    assert schema_response.status_code == 200
    assert {field["key"] for field in schema_response.json()["data"]["secret_fields"]} >= {
        "app_secret",
        "access_token",
        "refresh_token",
    }

    create_response = client.post(
        "/api/internal/integrations/configs/",
        {
            "platform": "shopee",
            "account_alias": "pilot-shop",
            "environment": "sandbox",
            "status": "draft",
            "regions": ["PH", "TH", "MY"],
            "contract_version": "v2",
            "callback_url": "https://dingfengchuangyu.com/api/internal/integrations/store-authorizations/oauth/callback/shopee/",
            "platform_config": {"partner_id": "masked-partner"},
        },
        format="json",
    )
    assert create_response.status_code == 201
    config_id = create_response.json()["data"]["id"]
    secret_value = "not-a-real-secret-test-value"
    custody = FakeCustody()
    monkeypatch.setattr("apps.integrations.credential_service.get_custody_backend", lambda: custody)

    rotate_payload = {
        "version": 1,
        "reason": "initial approved custody setup",
        "credentials": {"app_secret": secret_value},
    }
    rotate_response = client.post(
        f"/api/internal/integrations/configs/{config_id}/credentials/rotate/",
        rotate_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="platform-config-rotate-0001",
    )
    assert rotate_response.status_code == 200
    assert rotate_response.json()["data"]["credential_mask"] == {"configured": "********"}
    assert secret_value not in json.dumps(rotate_response.json())
    assert secret_value not in json.dumps(IntegrationAuditLog.objects.filter(integration_config_id=config_id).values_list("masked_detail", flat=True), default=list)
    operation = CredentialMutationRequest.objects.get(action="rotate")
    assert secret_value not in json.dumps(operation.response_metadata)

    replay = client.post(
        f"/api/internal/integrations/configs/{config_id}/credentials/rotate/",
        rotate_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="platform-config-rotate-0001",
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["idempotent_replay"] is True
    assert custody.store_calls == 1

    changed_replay = client.post(
        f"/api/internal/integrations/configs/{config_id}/credentials/rotate/",
        {**rotate_payload, "reason": "different credential replacement request"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="platform-config-rotate-0001",
    )
    assert changed_replay.status_code == 409

    stale = client.post(
        f"/api/internal/integrations/configs/{config_id}/credentials/rotate/",
        rotate_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="platform-config-rotate-stale-0002",
    )
    assert stale.status_code == 409
    assert custody.rotate_calls == 0

    clear_response = client.post(
        f"/api/internal/integrations/configs/{config_id}/credentials/clear/",
        {"version": 2, "reason": "operator confirmed credential removal"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="platform-config-clear-0001",
    )
    assert clear_response.status_code == 200
    assert clear_response.json()["data"]["credential_status"] == "revoked"
    assert clear_response.json()["data"]["credential_revoked_at"]
    assert clear_response.json()["data"]["credential_mask"] == {}


@pytest.mark.django_db
def test_tiktok_platform_schema_requires_service_id():
    tenant = Tenant.objects.create(name="Tenant", code="tiktok-schema-service-id")
    user = create_user(tenant, "tiktok-schema-admin")
    grant_integration_access(user)
    client = authenticated_client(user)

    schema = client.get("/api/internal/integrations/platform-schemas/tiktok/?environment=pilot")
    assert schema.status_code == 200
    assert {field["key"] for field in schema.json()["data"]["public_fields"]} >= {"app_key", "service_id"}

    response = client.post(
        "/api/internal/integrations/configs/",
        {
            "platform": "tiktok",
            "account_alias": "pilot-tiktok",
            "environment": "pilot",
            "status": "draft",
            "regions": ["PH"],
            "contract_version": "202407",
            "callback_url": "https://dingfengchuangyu.com/api/internal/integrations/store-authorizations/oauth/callback/tiktok/",
            "scopes": ["seller.authorization.info"],
            "platform_config": {"app_key": "approved-public-app-key"},
        },
        format="json",
    )

    assert response.status_code == 400
    assert "service_id" in json.dumps(response.json())


@pytest.mark.django_db
def test_config_exact_scope_filters_environment_and_regions():
    tenant = Tenant.objects.create(name="Tenant", code="config-environment-region-scope")
    user = create_user(tenant, "config-region-viewer")
    scope = {"platforms": ["shopee"], "environments": ["sandbox"], "regions": ["PH"]}
    grant_integration_permission(user, "integrations.config.view", scope)
    grant_integration_permission(user, "integrations.config.create", scope)
    visible = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="shopee",
        account_alias="visible-ph",
        environment="sandbox",
        regions=["PH"],
        created_by=user,
    )
    PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="shopee",
        account_alias="hidden-th",
        environment="sandbox",
        regions=["TH"],
        created_by=user,
    )
    PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="shopee",
        account_alias="hidden-pilot",
        environment="pilot",
        regions=["PH"],
        created_by=user,
    )

    listing = authenticated_client(user).get("/api/internal/integrations/configs/")
    assert listing.status_code == 200
    assert [row["id"] for row in listing.json()["data"]] == [visible.id]

    denied = authenticated_client(user).post(
        "/api/internal/integrations/configs/",
        {
            "platform": "shopee",
            "account_alias": "denied-th",
            "environment": "sandbox",
            "status": "draft",
            "regions": ["TH"],
            "contract_version": "v2",
            "callback_url": "https://dingfengchuangyu.com/api/internal/integrations/store-authorizations/oauth/callback/shopee/",
            "platform_config": {"partner_id": "masked-partner"},
        },
        format="json",
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "DATA_SCOPE_FORBIDDEN"
