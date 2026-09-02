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
        "sync_read_enabled": True,
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
    LIVE_READONLY_SYNC_ENABLED=True,
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


def grant_readiness_actions(user):
    role = Role.objects.create(tenant=user.tenant, name="Readiness operator", code=f"readiness-operator-{user.id}")
    for permission_code in ("integrations.config.update", "integrations.config.verify"):
        permission, _ = Permission.objects.get_or_create(
            code=permission_code,
            defaults={"name": permission_code, "module": "integrations", "action": permission_code.rsplit(".", 1)[-1]},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})


@pytest.mark.django_db
@override_settings(
    DEBUG=False,
    PLATFORM_NETWORK_MODE="approved-live-test",
    LIVE_READONLY_SYNC_ENABLED=True,
    LIVE_PLATFORM_SECURITY_APPROVED=True,
    LIVE_PLATFORM_ALLOWED_HOSTS=["partner.shopeemobile.com"],
    LIVE_SHOPEE_CONTRACT_APPROVED=True,
    LIVE_SHOPEE_REDIRECT_URI="https://example.test/api/internal/integrations/store-authorizations/oauth/callback/shopee/",
    LIVE_OAUTH_REDIRECT_ALLOWLIST=["https://example.test/api/internal/integrations/store-authorizations/oauth/callback/shopee/"],
)
def test_readiness_projection_exposes_scoped_config_fields_and_action_metadata(monkeypatch):
    tenant = Tenant.objects.create(name="Tenant", code="readiness-actions-projection")
    user = CustomUser.objects.create_user(username="readiness-actions-viewer", tenant=tenant, user_type="internal")
    grant_view(user)
    config = create_config(tenant, user, contract_version="v1", network_enabled=False, sync_read_enabled=False)
    monkeypatch.setattr("apps.integrations.readiness_service.approved_custody_configured", lambda: True)
    monkeypatch.setattr("apps.integrations.live_providers.approved_custody_configured", lambda: True)

    payload = client_for(user).get("/api/internal/integrations/readiness/").json()["data"]
    shopee = next(item for item in payload["items"] if item["platform_code"] == "shopee")
    row = shopee["configs"][0]
    assert row["id"] == config.id
    assert row["contract_version"] == "v1"
    assert row["readonly_approved"] is False
    assert row["can_repair_contract"] is True
    assert row["can_approve_readonly"] is False
    assert "contract_not_approved" in row["blocker_codes"]
    assert {item["code"] for item in row["actions"]} == {
        "repair_contract", "approve_readonly", "revoke_readonly",
    }
    assert shopee["actions"]["repair_contract"]["config_ids"] == [config.id]


@pytest.mark.django_db
@override_settings(
    DEBUG=False,
    PLATFORM_NETWORK_MODE="approved-live-test",
    LIVE_READONLY_SYNC_ENABLED=True,
    LIVE_PLATFORM_SECURITY_APPROVED=True,
    LIVE_PLATFORM_ALLOWED_HOSTS=["partner.shopeemobile.com"],
    LIVE_SHOPEE_CONTRACT_APPROVED=True,
    LIVE_SHOPEE_REDIRECT_URI="https://example.test/api/internal/integrations/store-authorizations/oauth/callback/shopee/",
    LIVE_OAUTH_REDIRECT_ALLOWLIST=["https://example.test/api/internal/integrations/store-authorizations/oauth/callback/shopee/"],
)
def test_readiness_contract_repair_page_action_is_dry_run_apply_and_idempotent():
    tenant = Tenant.objects.create(name="Tenant", code="readiness-contract-action")
    user = CustomUser.objects.create_user(username="contract-operator", tenant=tenant, user_type="internal")
    grant_readiness_actions(user)
    config = create_config(tenant, user, contract_version="v1", network_enabled=False, sync_read_enabled=False)
    client = client_for(user)

    dry_run = client.post(
        f"/api/internal/integrations/readiness/configs/{config.id}/repair-contract/",
        {"confirm": True, "dry_run": True, "expected_version": 1},
        format="json",
    )
    assert dry_run.status_code == 200, dry_run.json()
    assert dry_run.json()["data"]["dry_run"] is True
    assert dry_run.json()["data"]["can_apply"] is True
    config.refresh_from_db()
    assert config.contract_version == "v1"
    assert config.config_version == 1

    applied = client.post(
        f"/api/internal/integrations/readiness/configs/{config.id}/repair-contract/",
        {"confirm": True, "dry_run": False, "expected_version": 1},
        format="json",
    )
    assert applied.status_code == 200, applied.json()
    config.refresh_from_db()
    assert config.contract_version == "v2"
    assert config.config_version == 2

    replay = client.post(
        f"/api/internal/integrations/readiness/configs/{config.id}/repair-contract/",
        {"confirm": True, "dry_run": False, "expected_version": 1},
        format="json",
    )
    assert replay.status_code == 200, replay.json()
    assert replay.json()["data"]["idempotent_replay"] is True
    config.refresh_from_db()
    assert config.config_version == 2


@pytest.mark.django_db
@override_settings(
    DEBUG=False,
    PLATFORM_NETWORK_MODE="approved-live-test",
    LIVE_READONLY_SYNC_ENABLED=True,
    LIVE_PLATFORM_SECURITY_APPROVED=True,
    LIVE_PLATFORM_ALLOWED_HOSTS=["partner.shopeemobile.com"],
    LIVE_CUSTODY_BACKEND="http",
    LIVE_CUSTODY_SERVICE_URL="https://custody.example.test",
    LIVE_CUSTODY_SERVICE_HOST="custody.example.test",
    LIVE_CUSTODY_SERVICE_TOKEN="test-token",
    LIVE_SHOPEE_CONTRACT_APPROVED=True,
    LIVE_SHOPEE_REDIRECT_URI="https://example.test/api/internal/integrations/store-authorizations/oauth/callback/shopee/",
    LIVE_OAUTH_REDIRECT_ALLOWLIST=["https://example.test/api/internal/integrations/store-authorizations/oauth/callback/shopee/"],
)
def test_readiness_readonly_approval_is_gated_scoped_and_never_enables_write(monkeypatch):
    tenant = Tenant.objects.create(name="Tenant", code="readiness-approval-action")
    other_tenant = Tenant.objects.create(name="Other", code="readiness-approval-other")
    user = CustomUser.objects.create_user(username="approval-operator", tenant=tenant, user_type="internal")
    other_user = CustomUser.objects.create_user(username="approval-other", tenant=other_tenant, user_type="internal")
    grant_readiness_actions(user)
    config = create_config(tenant, user, network_enabled=False, sync_read_enabled=False)
    other_config = create_config(other_tenant, other_user, account_alias="other-config", network_enabled=False, sync_read_enabled=False)
    monkeypatch.setattr("apps.integrations.readiness_service.approved_custody_configured", lambda: True)
    monkeypatch.setattr("apps.integrations.live_providers.approved_custody_configured", lambda: True)
    client = client_for(user)

    approved = client.post(
        f"/api/internal/integrations/readiness/configs/{config.id}/readonly-approval/",
        {"approved": True, "confirm": True, "expected_version": 1, "reason": "已核对生产只读条件"},
        format="json",
    )
    assert approved.status_code == 200, approved.json()
    config.refresh_from_db()
    assert config.network_enabled is True
    assert config.sync_read_enabled is True
    assert config.sync_write_enabled is False
    assert config.config_version == 2
    assert approved.json()["data"]["config"]["readonly_approved"] is True

    replay = client.post(
        f"/api/internal/integrations/readiness/configs/{config.id}/readonly-approval/",
        {"approved": True, "confirm": True, "expected_version": 1, "reason": "已核对生产只读条件"},
        format="json",
    )
    assert replay.status_code == 200, replay.json()
    assert replay.json()["data"]["idempotent_replay"] is True
    assert client.post(
        f"/api/internal/integrations/readiness/configs/{other_config.id}/readonly-approval/",
        {"approved": True, "confirm": True, "expected_version": 1, "reason": "不应跨租户操作"},
        format="json",
    ).status_code == 404

    revoked = client.post(
        f"/api/internal/integrations/readiness/configs/{config.id}/readonly-approval/",
        {"approved": False, "confirm": True, "expected_version": 2, "reason": "撤销当前只读审批"},
        format="json",
    )
    assert revoked.status_code == 200, revoked.json()
    config.refresh_from_db()
    assert config.network_enabled is False
    assert config.sync_read_enabled is False
    assert config.sync_write_enabled is False
    assert config.config_version == 3


@pytest.mark.django_db
@override_settings(
    DEBUG=False,
    PLATFORM_NETWORK_MODE="approved-live-test",
    LIVE_READONLY_SYNC_ENABLED=False,
    LIVE_PLATFORM_SECURITY_APPROVED=True,
    LIVE_PLATFORM_ALLOWED_HOSTS=["partner.shopeemobile.com"],
    LIVE_SHOPEE_CONTRACT_APPROVED=True,
    LIVE_SHOPEE_REDIRECT_URI="https://example.test/api/internal/integrations/store-authorizations/oauth/callback/shopee/",
    LIVE_OAUTH_REDIRECT_ALLOWLIST=["https://example.test/api/internal/integrations/store-authorizations/oauth/callback/shopee/"],
)
def test_readiness_readonly_approval_reports_runtime_gate_without_mutating_config(monkeypatch):
    tenant = Tenant.objects.create(name="Tenant", code="readiness-approval-gate")
    user = CustomUser.objects.create_user(username="approval-gate", tenant=tenant, user_type="internal")
    grant_readiness_actions(user)
    config = create_config(tenant, user, network_enabled=False, sync_read_enabled=False)
    monkeypatch.setattr("apps.integrations.readiness_service.approved_custody_configured", lambda: True)
    monkeypatch.setattr("apps.integrations.live_providers.approved_custody_configured", lambda: True)

    response = client_for(user).post(
        f"/api/internal/integrations/readiness/configs/{config.id}/readonly-approval/",
        {"approved": True, "confirm": True, "expected_version": 1, "reason": "尝试审批生产只读"},
        format="json",
    )
    assert response.status_code == 400
    payload = response.json()
    assert "readonly_sync_feature_disabled" in payload["data"]["blocker_codes"]
    config.refresh_from_db()
    assert config.network_enabled is False
    assert config.sync_read_enabled is False


@pytest.mark.django_db
@override_settings(
    DEBUG=False,
    PLATFORM_NETWORK_MODE="approved-live-test",
    LIVE_READONLY_SYNC_ENABLED=False,
    LIVE_PLATFORM_SECURITY_APPROVED=True,
    LIVE_PLATFORM_ALLOWED_HOSTS=["partner.shopeemobile.com"],
    LIVE_SHOPEE_CONTRACT_APPROVED=True,
    LIVE_SHOPEE_REDIRECT_URI="https://example.test/api/internal/integrations/store-authorizations/oauth/callback/shopee/",
    LIVE_OAUTH_REDIRECT_ALLOWLIST=["https://example.test/api/internal/integrations/store-authorizations/oauth/callback/shopee/"],
)
def test_readiness_keeps_persisted_approval_visible_when_runtime_gate_is_down(monkeypatch):
    tenant = Tenant.objects.create(name="Tenant", code="readiness-persisted-approval")
    user = CustomUser.objects.create_user(username="persisted-approval-viewer", tenant=tenant, user_type="internal")
    grant_view(user)
    create_config(tenant, user, network_enabled=True, sync_read_enabled=True)
    monkeypatch.setattr("apps.integrations.readiness_service.approved_custody_configured", lambda: True)
    monkeypatch.setattr("apps.integrations.live_providers.approved_custody_configured", lambda: True)

    payload = client_for(user).get("/api/internal/integrations/readiness/").json()["data"]
    shopee = next(item for item in payload["items"] if item["platform_code"] == "shopee")
    row = shopee["configs"][0]
    assert row["readonly_approved"] is True
    assert "readonly_sync_feature_disabled" in row["blocker_codes"]
    assert shopee["production_status"] == "production_disabled"
