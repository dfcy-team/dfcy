import pytest
from django.db import IntegrityError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import IntegrationAuditLog, PlatformIntegrationConfig, SyncJob
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant
from apps.integrations.views import _is_active_config_key_conflict


def test_only_config_identity_constraint_is_classified_as_conflict():
    assert _is_active_config_key_conflict(IntegrityError(1062, "Duplicate entry for key 'uniq_active_platform_integration_per_tenant'"))
    assert _is_active_config_key_conflict(IntegrityError("UNIQUE constraint failed: integrations_platformintegrationconfig.tenant_id, integrations_platformintegrationconfig.platform, integrations_platformintegrationconfig.account_alias, integrations_platformintegrationconfig.environment, integrations_platformintegrationconfig.active_uniqueness_marker"))
    assert not _is_active_config_key_conflict(IntegrityError(1048, "Column 'created_by_id' cannot be null"))
    assert not _is_active_config_key_conflict(IntegrityError(1062, "Duplicate entry for key 'some_other_unique_key'"))


def _client():
    tenant = Tenant.objects.create(name="Soft delete tenant", code="soft-delete")
    user = CustomUser.objects.create_user(username="soft-delete-admin", tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    role = Role.objects.create(tenant=tenant, name="Integration admin", code="integration-admin")
    for code in ("integrations.config.view", "integrations.config.create", "integrations.config.update", "integrations.config.disable"):
        permission, _ = Permission.objects.get_or_create(code=code, defaults={"name": code, "module": "integrations", "action": code.rsplit(".", 1)[-1]})
        role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    client = APIClient()
    client.force_authenticate(user=user)
    return tenant, user, client


def _payload(alias, environment="mock"):
    return {"platform": "mock", "account_alias": alias, "environment": environment, "regions": ["MY"]}


@pytest.mark.django_db
def test_collection_soft_delete_rebuilds_same_name_and_preserves_history():
    tenant, user, client = _client()
    created = client.post("/api/internal/integrations/configs/", _payload("rebuild"), format="json")
    assert created.status_code == 201, created.data
    old_id = created.data["data"]["id"]
    old = PlatformIntegrationConfig.all_objects.get(pk=old_id)
    SyncJob.objects.create(tenant=tenant, integration_config=old, resource_type=SyncJob.ResourceType.MOCK_RECORD)
    assert client.post(f"/api/internal/integrations/configs/{old_id}/disable/", {}, format="json").status_code == 200
    assert client.post(f"/api/internal/integrations/configs/{old_id}/delete/", {}, format="json").status_code == 200
    recreated = client.post("/api/internal/integrations/configs/", _payload("rebuild"), format="json")
    assert recreated.status_code == 201, recreated.data
    assert recreated.data["data"]["id"] != old_id
    assert PlatformIntegrationConfig.all_objects.filter(pk=old_id, account_alias="rebuild", deleted_at__isnull=False).exists()
    assert SyncJob.objects.filter(integration_config_id=old_id, is_enabled=False).exists()
    assert IntegrationAuditLog.objects.filter(integration_config_id=old_id, action="delete").exists()


@pytest.mark.django_db
def test_workspace_soft_delete_rebuilds_and_active_duplicate_is_conflict():
    tenant, user, client = _client()
    payload = {"platform": "jifeng_wms", "api_type": "inventory", "account_alias": "马来极风", "environment": "production", "regions": ["MY"]}
    first = client.post("/api/internal/integrations/workspace-configs/", payload, format="json")
    assert first.status_code == 201, first.data
    duplicate = client.post("/api/internal/integrations/workspace-configs/", payload, format="json")
    assert duplicate.status_code in (400, 409), duplicate.data
    old_id = first.data["data"]["id"]
    assert client.post(f"/api/internal/integrations/configs/{old_id}/disable/", {}, format="json").status_code == 200
    assert client.post(f"/api/internal/integrations/configs/{old_id}/delete/", {}, format="json").status_code == 200
    rebuilt = client.post("/api/internal/integrations/workspace-configs/", payload, format="json")
    assert rebuilt.status_code == 201, rebuilt.data
    assert rebuilt.data["data"]["id"] != old_id


@pytest.mark.django_db
def test_active_duplicate_patch_returns_conflict_and_tenants_are_isolated():
    tenant, user, client = _client()
    first = client.post("/api/internal/integrations/configs/", _payload("one"), format="json")
    second = client.post("/api/internal/integrations/configs/", _payload("two"), format="json")
    assert first.status_code == second.status_code == 201
    response = client.patch(
        f"/api/internal/integrations/configs/{second.data['data']['id']}/",
        {"version": 1, "account_alias": "one"},
        format="json",
    )
    assert response.status_code in (400, 409), response.data
    other_tenant = Tenant.objects.create(name="Other", code="soft-delete-other")
    other_user = CustomUser.objects.create_user(username="other-admin", tenant=other_tenant, user_type=CustomUser.UserType.INTERNAL)
    other_role = Role.objects.create(tenant=other_tenant, name="Other admin", code="other-admin")
    for code in ("integrations.config.view", "integrations.config.create"):
        permission = Permission.objects.get(code=code)
        other_role.permissions.add(permission)
    UserRole.objects.create(tenant=other_tenant, user=other_user, role=other_role)
    DataScope.objects.create(tenant=other_tenant, role=other_role, scope_type=DataScope.ScopeType.ALL, config={})
    other_client = APIClient(); other_client.force_authenticate(user=other_user)
    isolated = other_client.post("/api/internal/integrations/configs/", _payload("one"), format="json")
    assert isolated.status_code == 201, isolated.data
