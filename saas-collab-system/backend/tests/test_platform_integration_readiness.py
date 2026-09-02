from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import PlatformIntegrationConfig, authorization_service_write
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


def grant_view(user):
    role = Role.objects.create(tenant=user.tenant, name="Integration Viewer", code=f"integration-view-{user.id}")
    permission, _ = Permission.objects.get_or_create(
        code="integrations.view",
        defaults={"name": "View integrations", "module": "integrations", "action": "view"},
    )
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_config(tenant, user, **overrides):
    values = {
        "tenant": tenant,
        "platform": "shopee",
        "account_alias": f"shopee-{tenant.id}",
        "environment": "production",
        "status": "verified",
        "regions": ["PH"],
        "contract_version": "v2",
        "callback_url": "https://example.test/api/internal/integrations/store-authorizations/oauth/callback/shopee/",
        "platform_config": {"partner_id": "2038415"},
        "network_enabled": True,
        "sync_write_enabled": False,
        "created_by": user,
    }
    values.update(overrides)
    config = PlatformIntegrationConfig.objects.create(**values)
    with authorization_service_write():
        config.credential_id = "custody://tenant/shopee"
        config.credential_status = PlatformIntegrationConfig.CredentialStatus.CONFIGURED
        config.save(update_fields=["credential_id", "credential_status", "updated_at"])
    return config


@pytest.mark.django_db
@override_settings(
    DEBUG=False,
    PLATFORM_NETWORK_MODE="approved-live-test",
    LIVE_PLATFORM_SECURITY_APPROVED=True,
    LIVE_PLATFORM_ALLOWED_HOSTS=["partner.shopeemobile.com"],
    LIVE_SHOPEE_CONTRACT_APPROVED=True,
    LIVE_SHOPEE_REDIRECT_URI="https://example.test/api/internal/integrations/store-authorizations/oauth/callback/shopee/",
    LIVE_OAUTH_REDIRECT_ALLOWLIST=["https://example.test/api/internal/integrations/store-authorizations/oauth/callback/shopee/"],
)
def test_readiness_is_real_tenant_scoped_and_never_enables_writes(monkeypatch):
    tenant = Tenant.objects.create(name="Tenant A", code="readiness-a")
    other_tenant = Tenant.objects.create(name="Tenant B", code="readiness-b")
    user = CustomUser.objects.create_user(
        username="readiness-user", tenant=tenant, user_type=CustomUser.UserType.INTERNAL
    )
    other_user = CustomUser.objects.create_user(
        username="readiness-other", tenant=other_tenant, user_type=CustomUser.UserType.INTERNAL
    )
    grant_view(user)
    create_config(tenant, user)
    create_config(other_tenant, other_user, account_alias="other-secret-config")
    monkeypatch.setattr("apps.integrations.readiness_service.approved_custody_configured", lambda: True)
    monkeypatch.setattr("apps.integrations.live_providers.approved_custody_configured", lambda: True)

    response = client_for(user).get("/api/internal/integrations/readiness/")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["api_status"] == "connected"
    assert payload["production_write_enabled"] is False
    shopee = next(item for item in payload["items"] if item["platform_code"] == "shopee")
    assert shopee["current_access_status"] == "read_only_ready"
    assert shopee["blocker_codes"] == []
    assert "other-secret-config" not in str(payload)
    assert "custody://" not in str(payload)


@pytest.mark.django_db
def test_readiness_requires_integration_view_permission():
    tenant = Tenant.objects.create(name="Tenant A", code="readiness-permission")
    user = CustomUser.objects.create_user(
        username="readiness-no-access", tenant=tenant, user_type=CustomUser.UserType.INTERNAL
    )
    response = client_for(user).get("/api/internal/integrations/readiness/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_contract_repair_command_is_dry_run_scoped_and_idempotent():
    tenant = Tenant.objects.create(name="Tenant A", code="repair-a")
    other_tenant = Tenant.objects.create(name="Tenant B", code="repair-b")
    user = CustomUser.objects.create_user(username="repair-user", tenant=tenant)
    other_user = CustomUser.objects.create_user(username="repair-other", tenant=other_tenant)
    config = create_config(tenant, user, contract_version="shopapi-local-v1")
    other = create_config(other_tenant, other_user, contract_version="shopapi-local-v1", account_alias="other")

    dry_run = StringIO()
    call_command("repair_platform_contract_versions", tenant_id=tenant.id, stdout=dry_run)
    config.refresh_from_db()
    assert "mode=DRY-RUN" in dry_run.getvalue()
    assert "proposed=v2" in dry_run.getvalue()
    assert config.contract_version == "shopapi-local-v1"

    applied = StringIO()
    call_command("repair_platform_contract_versions", tenant_id=tenant.id, apply=True, stdout=applied)
    config.refresh_from_db()
    other.refresh_from_db()
    assert config.contract_version == "v2"
    assert config.config_version == 2
    assert other.contract_version == "shopapi-local-v1"

    second = StringIO()
    call_command("repair_platform_contract_versions", tenant_id=tenant.id, apply=True, stdout=second)
    config.refresh_from_db()
    assert "proposals=0" in second.getvalue()
    assert config.config_version == 2
