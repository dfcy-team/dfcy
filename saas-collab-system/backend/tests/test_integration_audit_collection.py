import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import IntegrationAuditLog, PlatformChoices, PlatformIntegrationConfig
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def create_user(tenant, username):
    return CustomUser.objects.create_user(
        username=username,
        password="not-a-real-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )


def grant_audit_view(user, *, scope_type=DataScope.ScopeType.ALL, scope_config=None):
    role = Role.objects.create(
        tenant=user.tenant,
        code=f"integration-audit-{user.username}",
        name=f"Integration audit {user.username}",
    )
    permission, _ = Permission.objects.get_or_create(
        code="integrations.audit.view",
        defaults={
            "name": "View integration audit logs",
            "module": "integrations",
            "action": "audit.view",
        },
    )
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=user.tenant,
        role=role,
        scope_type=scope_type,
        config=scope_config or {},
    )


def create_config(tenant, actor, *, platform=PlatformChoices.MOCK, alias="default"):
    return PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform=platform,
        account_alias=alias,
        environment=PlatformIntegrationConfig.Environment.MOCK,
        status=PlatformIntegrationConfig.Status.ACTIVE,
        created_by=actor,
    )


def create_audit(config, actor, action, *, result=IntegrationAuditLog.Result.SUCCESS, detail=None):
    return IntegrationAuditLog.objects.create(
        tenant=config.tenant,
        integration_config=config,
        action=action,
        actor=actor,
        result=result,
        masked_detail=detail or {},
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_integration_audit_collection_requires_authentication_and_permission():
    tenant = Tenant.objects.create(name="Tenant", code="integration-audit-auth")
    anonymous = APIClient().get("/api/internal/integrations/audit/")
    assert anonymous.status_code == 401

    user = create_user(tenant, "integration-audit-no-permission")
    assert client_for(user).get("/api/internal/integrations/audit/").status_code == 403


def test_integration_audit_collection_is_tenant_isolated_and_redacted():
    tenant = Tenant.objects.create(name="Tenant A", code="integration-audit-tenant-a")
    other_tenant = Tenant.objects.create(name="Tenant B", code="integration-audit-tenant-b")
    viewer = create_user(tenant, "integration-audit-viewer")
    other_actor = create_user(other_tenant, "integration-audit-other")
    grant_audit_view(viewer)
    config = create_config(tenant, viewer)
    foreign_config = create_config(other_tenant, other_actor)
    visible = create_audit(
        config,
        viewer,
        "rotate_credential",
        detail={"credential_status": "configured", "credential_mask": {"client_id": "clie…"}},
    )
    create_audit(foreign_config, other_actor, "foreign_action")

    response = client_for(viewer).get("/api/internal/integrations/audit/")

    assert response.status_code == 200
    payload = response.data["data"]
    assert payload["count"] == 1
    assert [row["id"] for row in payload["results"]] == [visible.id]
    assert payload["results"][0]["integration_config_id"] == config.id
    assert "credential_id" not in payload["results"][0]
    assert "token_id" not in payload["results"][0]


def test_integration_audit_collection_reuses_config_data_scope_and_filters():
    tenant = Tenant.objects.create(name="Tenant", code="integration-audit-scope")
    viewer = create_user(tenant, "integration-audit-scoped")
    allowed_config = create_config(tenant, viewer, platform=PlatformChoices.SHOPEE, alias="allowed")
    blocked_config = create_config(tenant, viewer, platform=PlatformChoices.MOCK, alias="blocked")
    grant_audit_view(
        viewer,
        scope_type=DataScope.ScopeType.CUSTOM,
        scope_config={"integration_config_ids": [allowed_config.id]},
    )
    allowed = create_audit(allowed_config, viewer, "verify")
    create_audit(allowed_config, viewer, "rotate_credential")
    create_audit(blocked_config, viewer, "verify")

    response = client_for(viewer).get(
        "/api/internal/integrations/audit/",
        {"config_id": allowed_config.id, "platform": "shopee", "action": "verify"},
    )

    assert response.status_code == 200
    assert [row["id"] for row in response.data["data"]["results"]] == [allowed.id]

    assert client_for(viewer).get(
        "/api/internal/integrations/audit/",
        {"config_id": blocked_config.id},
    ).data["data"]["count"] == 0


def test_integration_audit_collection_rejects_unknown_and_invalid_filters():
    tenant = Tenant.objects.create(name="Tenant", code="integration-audit-filters")
    viewer = create_user(tenant, "integration-audit-filter-viewer")
    grant_audit_view(viewer)

    client = client_for(viewer)
    assert client.get(
        "/api/internal/integrations/audit/", {"unexpected": "value"}
    ).status_code == 400
    assert client.get(
        "/api/internal/integrations/audit/", {"config_id": "not-an-id"}
    ).status_code == 400
    assert client.get(
        "/api/internal/integrations/audit/", {"platform": "unsupported"}
    ).status_code == 400


def test_integration_audit_collection_paginates_with_stable_envelope():
    tenant = Tenant.objects.create(name="Tenant", code="integration-audit-pagination")
    viewer = create_user(tenant, "integration-audit-page-viewer")
    grant_audit_view(viewer)
    config = create_config(tenant, viewer)
    logs = [create_audit(config, viewer, f"action-{index}") for index in range(3)]

    client = client_for(viewer)
    first = client.get("/api/internal/integrations/audit/", {"page": 1, "page_size": 2})
    second = client.get("/api/internal/integrations/audit/", {"page": 2, "page_size": 2})

    assert first.status_code == 200
    assert first.data["success"] is True
    assert first.data["data"]["count"] == 3
    assert [row["id"] for row in first.data["data"]["results"]] == [logs[2].id, logs[1].id]
    assert first.data["data"]["next"]
    assert first.data["data"]["previous"] is None
    assert [row["id"] for row in second.data["data"]["results"]] == [logs[0].id]
    assert second.data["data"]["previous"]
