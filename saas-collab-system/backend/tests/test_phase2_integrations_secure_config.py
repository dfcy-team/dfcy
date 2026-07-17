import json

import pytest
from django.test import override_settings
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.credential_service import decrypt_credentials, encrypt_credentials
from apps.integrations.models import IntegrationAuditLog, PlatformIntegrationConfig
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=user_type)


def grant_integration_access(user):
    role = Role.objects.create(tenant=user.tenant, name="Tech Admin", code="tech_admin")
    for permission_code in ("integrations.view", "integrations.manage", "integrations.rotate", "integrations.run"):
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
        code="integrations.view",
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


def config_payload(account_alias="demo-account", environment="mock", status="active"):
    return {
        "platform": "mock",
        "account_alias": account_alias,
        "environment": environment,
        "status": status,
        "credential_key_version": "test-v1",
        "credentials": {
            "api_key": "not-a-real-secret",
            "api_secret": "placeholder-secret",
        },
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
    grant_integration_permission(user, "integrations.view", {"platforms": ["mock"]})
    grant_integration_permission(user, "integrations.manage", {"platforms": ["mock"]})
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
        {"platform": "other"},
        format="json",
    )
    assert patch_denied.status_code == 403
    assert patch_denied.json()["code"] == "DATA_SCOPE_FORBIDDEN"
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
    grant_integration_permission(user, "integrations.manage", scope_config)

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
        credential_key_version="test-v1",
        credential_fingerprint="placeholder-fingerprint",
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
    assert "not-a-real-secret" not in response_text
    assert "placeholder-secret" not in response_text
    assert "credential_ciphertext" not in response_text

    audit = IntegrationAuditLog.objects.get(action="create")
    audit_text = json.dumps(audit.masked_detail)
    assert "not-a-real-secret" not in audit_text
    assert "placeholder-secret" not in audit_text
    assert audit.masked_detail["credential_mask"]["api_key"] == "***"


@pytest.mark.django_db
def test_test_provider_encrypts_decrypts_and_rotation_changes_key_version():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "tech-admin")
    grant_integration_access(user)

    ciphertext, fingerprint = encrypt_credentials({"api_key": "not-a-real-secret"}, key_version="test-v1")
    assert decrypt_credentials(ciphertext) == {"api_key": "not-a-real-secret"}
    assert len(fingerprint) == 64

    create_response = authenticated_client(user).post(
        "/api/internal/integrations/configs/",
        config_payload(status="disabled"),
        format="json",
    )
    config_id = create_response.json()["data"]["id"]

    rotate_response = authenticated_client(user).post(
        f"/api/internal/integrations/configs/{config_id}/rotate/",
        {
            "credential_key_version": "test-v2",
            "credentials": {"api_key": "demo-rotated", "api_secret": "placeholder-rotated"},
        },
        format="json",
    )

    assert rotate_response.status_code == 200
    assert rotate_response.json()["data"]["credential_key_version"] == "test-v2"
    assert "credential_ciphertext" not in rotate_response.json()["data"]
    assert IntegrationAuditLog.objects.filter(action="rotate_credentials").exists()


def test_unconfigured_production_provider_rejects_credential_operations():
    with override_settings(INTEGRATION_ENCRYPTION_PROVIDER="unconfigured-production"):
        with pytest.raises(ValidationError, match="not configured"):
            encrypt_credentials({"api_key": "not-a-real-secret"})


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
