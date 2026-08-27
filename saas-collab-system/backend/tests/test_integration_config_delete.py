import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import IntegrationAuditLog, PlatformIntegrationConfig
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


def grant_integration_access(user):
    role = Role.objects.create(tenant=user.tenant, name="Tech Admin", code="tech_admin")
    for permission_code in ("integrations.config.view", "integrations.config.disable"):
        permission, _created = Permission.objects.get_or_create(
            code=permission_code,
            defaults={"name": permission_code, "module": "integrations", "action": permission_code.rsplit(".", 1)[-1]},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})


@pytest.mark.django_db
def test_only_disabled_integration_config_can_be_soft_deleted():
    tenant = Tenant.objects.create(name="Tenant", code="integration-delete")
    user = CustomUser.objects.create_user(username="tech-admin", tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    grant_integration_access(user)
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="mock",
        account_alias="delete-after-disable",
        environment=PlatformIntegrationConfig.Environment.MOCK,
        status=PlatformIntegrationConfig.Status.ACTIVE,
        created_by=user,
    )
    client = APIClient()
    client.force_authenticate(user=user)

    active_response = client.post(f"/api/internal/integrations/configs/{config.id}/delete/", {}, format="json")

    assert active_response.status_code == 409
    assert PlatformIntegrationConfig.objects.filter(pk=config.id).exists()

    client.post(f"/api/internal/integrations/configs/{config.id}/disable/", {}, format="json")
    delete_response = client.post(f"/api/internal/integrations/configs/{config.id}/delete/", {}, format="json")

    assert delete_response.status_code == 200
    assert delete_response.json()["data"] == {"id": config.id, "deleted": True}
    assert not PlatformIntegrationConfig.objects.filter(pk=config.id).exists()
    assert PlatformIntegrationConfig.all_objects.filter(pk=config.id, deleted_at__isnull=False).exists()
    assert client.get(f"/api/internal/integrations/configs/{config.id}/").status_code == 404
    assert all(item["id"] != config.id for item in client.get("/api/internal/integrations/configs/").json()["data"])
    assert IntegrationAuditLog.objects.filter(integration_config_id=config.id, action="delete").exists()
