from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.configcenter.models import SystemConfigDefinition, TenantConfigVersion
from apps.configcenter.services import approve_config_version, create_config_version, rollback_config_version
from apps.integrations.capability import live_mode_allowed
from apps.integrations import custody as custody_module
from apps.integrations.platform_schema_service import get_platform_schema
from apps.integrations.production_settings import (
    CONFIG_KEY,
    get_runtime_platform_config,
    runtime_snapshot,
    validate_runtime_config,
)
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


def _user(tenant, username):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)


def _grant(user, code, scope=DataScope.ScopeType.ALL):
    role = Role.objects.create(tenant=user.tenant, name=f"{code}-{user.id}", code=f"{code}-{user.id}")
    role.permissions.add(Permission.objects.get(code=code))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=scope)


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _runtime_definition():
    return SystemConfigDefinition.objects.get(config_key=CONFIG_KEY)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"network": {"allowed_hosts": ["https://api.example.com"]}}, "hostname"),
        ({"custody": {"service_url": "http://custody.example.com"}}, "HTTPS"),
        ({"custody": {"auth_file_path": "relative/token"}}, "absolute"),
        ({"platforms": {"shopee": {"token": "plaintext"}}}, "credential/token"),
    ],
)
def test_production_runtime_rejects_unsafe_values(payload, message):
    with pytest.raises(ValidationError, match=message):
        validate_runtime_config(payload)


@pytest.mark.django_db
def test_system_admin_create_approve_rollback_and_all_scope_permissions():
    tenant = Tenant.objects.create(name="Runtime tenant", code="runtime-admin")
    creator = _user(tenant, "runtime-creator")
    approver = _user(tenant, "runtime-approver")
    viewer = _user(tenant, "runtime-viewer")
    for code in ("config.view", "config.manage", "config.system.manage"):
        _grant(creator, code)
    for code in ("config.view", "config.approve", "config.system.manage"):
        _grant(approver, code)
    for code in ("config.view", "config.system.manage"):
        _grant(viewer, code)

    payload = {
        "change_reason": "启用 Lazada 生产只读配置",
        "value": {
            "network": {
                "mode": "approved-live-test",
                "security_approved": True,
                "readonly_sync_enabled": True,
                "allowed_hosts": ["api.example.com"],
                "oauth_redirect_allowlist": ["https://app.example.com/oauth/callback"],
            },
            "platforms": {
                "lazada": {
                    "contract_approved": True,
                    "redirect_uri": "https://app.example.com/oauth/callback",
                },
            },
        },
        "effective_at": str(timezone.now()),
    }
    # The versions collection is the canonical write endpoint used by the
    # production-settings UI.  Exercise the real URL (rather than invoking
    # the root @api_view from another wrapper) so DRF request initialisation
    # and permissions are covered end to end.
    response = _client(creator).post(
        "/api/internal/integrations/production-settings/versions/",
        payload,
        format="json",
    )
    assert response.status_code == 201
    version_id = response.json()["data"]["version"]["id"]
    assert response.json()["data"]["version"]["change_reason"] == "启用 Lazada 生产只读配置"
    version = TenantConfigVersion.objects.get(pk=version_id)
    assert version.status == TenantConfigVersion.Status.PENDING_APPROVAL
    assert _client(viewer).get("/api/internal/integrations/production-settings/versions/").status_code == 200
    assert _client(creator).post(
        f"/api/internal/integrations/production-settings/versions/{version_id}/",
        {},
        format="json",
    ).status_code == 403
    approved = _client(approver).post(
        f"/api/internal/integrations/production-settings/versions/{version_id}/approve/",
        {},
        format="json",
    )
    assert approved.status_code == 200
    assert approved.json()["data"]["status"] == TenantConfigVersion.Status.EFFECTIVE

    current = _client(viewer).get("/api/internal/integrations/production-settings/")
    assert current.status_code == 200
    body = current.json()["data"]
    assert body["source"] == "database"
    assert body["effective_version"] == 1
    assert body["masked_status"]["credentials_stored"] is False
    assert body["config"]["network"]["mode"] == "approved-live-test"
    assert body["current_version"]["change_reason"] == "启用 Lazada 生产只读配置"

    rollback = _user(tenant, "runtime-rollback")
    for code in ("config.rollback", "config.system.manage"):
        _grant(rollback, code)
    response = _client(rollback).post(
        f"/api/internal/integrations/production-settings/versions/{version_id}/rollback/",
        {},
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["data"]["config_key"] == CONFIG_KEY


@pytest.mark.django_db
def test_effective_database_runtime_overrides_environment_and_keeps_production_write_closed():
    tenant = Tenant.objects.create(name="Runtime override", code="runtime-override")
    creator = _user(tenant, "runtime-override-creator")
    approver = _user(tenant, "runtime-override-approver")
    _grant(creator, "config.manage")
    _grant(creator, "config.system.manage")
    _grant(approver, "config.approve")
    _grant(approver, "config.system.manage")
    version = create_config_version(
        definition=_runtime_definition(),
        actor=creator,
        value={"network": {"mode": "approved-live-test", "allowed_hosts": ["db.example.com"]}},
        effective_at=timezone.now(),
    )
    approve_config_version(version=version, actor=approver)
    snapshot = runtime_snapshot()
    assert snapshot["source"] == "database"
    assert snapshot["config"]["network"]["mode"] == "approved-live-test"
    assert snapshot["config"]["network"]["allowed_hosts"] == ["db.example.com"]
    assert snapshot["config"]["platforms"]["shopee"]["token_path"].startswith("/")
    assert get_runtime_platform_config("shopee")["api_host"].startswith("https://")
    assert get_platform_schema("lazada")["production_write_enabled"] is False
    with override_settings(DEBUG=False):
        assert live_mode_allowed() is False


@pytest.mark.django_db
def test_custody_backend_cache_switches_when_effective_runtime_changes(monkeypatch):
    custody_module.reset_custody_backend_cache()
    runtime = {"custody": {"backend": "refuse", "service_url": "", "service_host": "", "auth_file_path": "", "ca_file_path": ""}}
    monkeypatch.setattr(custody_module, "get_runtime_config", lambda: runtime)
    first = custody_module.get_custody_backend()
    runtime["custody"] = {
        "backend": "http",
        "service_url": "https://custody.example.com",
        "service_host": "custody.example.com",
        "auth_file_path": "",
        "ca_file_path": "",
    }
    monkeypatch.setattr(custody_module, "resolve_service_auth_token", lambda *_args: "mounted-token")
    second = custody_module.get_custody_backend()
    assert type(first).__name__ == "RefusingCustodyBackend"
    assert type(second).__name__ == "HttpCustodyBackend"
    assert first is not second
