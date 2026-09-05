import json

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.custody import reset_custody_backend_cache
from apps.integrations.models import PlatformIntegrationConfig, authorization_service_write
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


def _client_with_permissions(tenant):
    user = CustomUser.objects.create_user(username="credential-maintainer", tenant=tenant, user_type="internal")
    role = Role.objects.create(tenant=tenant, name="Credential maintainer", code="credential-maintainer")
    for code in (
        "integrations.credential.rotate",
        "integrations.config.verify",
        "integrations.run_live_readonly",
    ):
        permission, _created = Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": "integrations", "action": code.rsplit(".", 1)[-1]},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


@pytest.mark.django_db
def test_legacy_wms_credential_can_be_replaced_and_checked_without_external_call(tmp_path):
    tenant = Tenant.objects.create(name="Tenant 1", code="tenant-1-credential-test")
    user, client = _client_with_permissions(tenant)
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="jifeng_wms",
        account_alias="legacy-wms",
        environment="pilot",
        status=PlatformIntegrationConfig.Status.CONFIGURED,
        platform_config={"api_type": "inventory", "identity": "legacy-client"},
        created_by=user,
    )
    with authorization_service_write():
        config.credential_id = "saas-mysql:legacy-credential"
        config.token_id = "saas-mysql:legacy-token"
        config.credential_status = PlatformIntegrationConfig.CredentialStatus.CONFIGURED
        config.save(update_fields=["credential_id", "token_id", "credential_status", "updated_at"])

    settings = override_settings(
        DEBUG=True,
        LIVE_CUSTODY_BACKEND="file",
        CREDENTIAL_CUSTODY_PATH=str(tmp_path / "custody"),
        PLATFORM_NETWORK_MODE="",
        LIVE_READONLY_SYNC_ENABLED=False,
    )
    settings.enable()
    reset_custody_backend_cache()
    try:
        secret = "placeholder-client-secret"
        response = client.post(
            f"/api/internal/integrations/configs/{config.id}/credentials/rotate/",
            {
                "version": config.config_version,
                "reason": "replace imported legacy credential",
                "credentials": {
                    "api_base_url": "https://api.example.test",
                    "domain": "tenant-one",
                    "client_id": "client-one",
                    "client_secret": secret,
                },
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="credential-maintenance-test-1",
        )

        assert response.status_code == 200
        assert secret not in json.dumps(response.json())
        config.refresh_from_db()
        assert config.credential_id.startswith("cred_")
        assert config.platform_config["api_host"] == "https://api.example.test"
        assert config.platform_config["domain"] == "tenant-one"
        assert config.platform_config["client_id"] == "client-one"

        reference_check = client.post(
            f"/api/internal/integrations/configs/{config.id}/reference-check/",
            {},
            format="json",
        )
        assert reference_check.status_code == 200
        assert reference_check.json()["data"]["external_api_called"] is False

        readonly_check = client.post(
            f"/api/internal/integrations/configs/{config.id}/readonly-check/",
            {},
            format="json",
        )
        assert readonly_check.status_code == 400
        assert "具体的店铺授权或仓库授权" in json.dumps(readonly_check.json(), ensure_ascii=False)
    finally:
        reset_custody_backend_cache()
        settings.disable()


@pytest.mark.django_db
def test_shopee_credential_maintenance_persists_only_approved_callback_and_custody_reference(tmp_path):
    tenant = Tenant.objects.create(name="Shopee Tenant", code="shopee-credential-test")
    user, client = _client_with_permissions(tenant)
    callback_url = "https://xtsy.example.test/api/internal/integrations/store-authorizations/oauth/callback/shopee/"
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="shopee",
        account_alias="Shopee production",
        environment="production",
        status=PlatformIntegrationConfig.Status.VERIFIED,
        regions=["PH"],
        contract_version="v2",
        platform_config={"api_type": "marketplace", "partner_id": "2038415"},
        network_enabled=True,
        created_by=user,
    )
    settings = override_settings(
        DEBUG=True,
        LIVE_CUSTODY_BACKEND="file",
        CREDENTIAL_CUSTODY_PATH=str(tmp_path / "custody"),
        LIVE_SHOPEE_REDIRECT_URI=callback_url,
        LIVE_OAUTH_REDIRECT_ALLOWLIST=[callback_url],
    )
    settings.enable()
    reset_custody_backend_cache()
    try:
        secret = "placeholder-partner-key"
        response = client.post(
            f"/api/internal/integrations/configs/{config.id}/credentials/rotate/",
            {
                "version": config.config_version,
                "reason": "configure approved Shopee production callback",
                "credentials": {
                    "partner_id": "2038415",
                    "partner_key": secret,
                    "redirect_uri": callback_url,
                },
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="shopee-production-credential-1",
        )

        assert response.status_code == 200, response.json()
        assert secret not in json.dumps(response.json())
        config.refresh_from_db()
        assert config.callback_url == callback_url
        assert config.credential_id.startswith("cred_")
        assert config.credential_status == PlatformIntegrationConfig.CredentialStatus.CONFIGURED
        assert config.sync_read_enabled is True
        assert config.sync_write_enabled is False
    finally:
        reset_custody_backend_cache()
        settings.disable()


@pytest.mark.django_db
def test_shopee_credential_maintenance_rejects_unregistered_callback(tmp_path):
    tenant = Tenant.objects.create(name="Shopee Tenant 2", code="shopee-callback-reject")
    user, client = _client_with_permissions(tenant)
    approved = "https://xtsy.example.test/api/internal/integrations/store-authorizations/oauth/callback/shopee/"
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="shopee",
        account_alias="Shopee production",
        environment="production",
        status=PlatformIntegrationConfig.Status.VERIFIED,
        regions=["PH"],
        contract_version="v2",
        platform_config={"api_type": "marketplace", "partner_id": "2038415"},
        network_enabled=True,
        created_by=user,
    )
    settings = override_settings(
        LIVE_CUSTODY_BACKEND="file",
        CREDENTIAL_CUSTODY_PATH=str(tmp_path / "custody"),
        LIVE_SHOPEE_REDIRECT_URI=approved,
        LIVE_OAUTH_REDIRECT_ALLOWLIST=[approved],
    )
    settings.enable()
    reset_custody_backend_cache()
    try:
        response = client.post(
            f"/api/internal/integrations/configs/{config.id}/credentials/rotate/",
            {
                "version": config.config_version,
                "reason": "reject unregistered callback",
                "credentials": {
                    "partner_id": "2038415",
                    "partner_key": "placeholder-partner-key",
                    "redirect_uri": "https://evil.example.test/callback",
                },
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="shopee-production-credential-reject-1",
        )

        assert response.status_code == 400
        config.refresh_from_db()
        assert config.callback_url == ""
        assert config.credential_id == ""
    finally:
        reset_custody_backend_cache()
        settings.disable()
