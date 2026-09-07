import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import PlatformIntegrationConfig, WarehouseAuthorization, authorization_service_write
from apps.masterdata.models import PlatformMaster, StatusChoices, WarehouseMaster
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _fixture():
    tenant = Tenant.objects.create(name="Warehouse API tenant", code="warehouse-api-closure")
    user = CustomUser.objects.create_user(
        username="warehouse-api-admin",
        password="not-a-real-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
        is_superuser=True,
    )
    service_platform = PlatformMaster.objects.create(
        tenant=tenant,
        code="myjf",
        name="马来极风",
        platform_type="warehouse_third_party",
        status=StatusChoices.ACTIVE,
    )
    warehouse = WarehouseMaster.objects.create(
        tenant=tenant,
        code="MY-WMS-01",
        name="马来极风仓",
        country_code="MY",
        warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY,
        service_platform=service_platform,
        status=StatusChoices.ACTIVE,
    )
    with authorization_service_write():
        config = PlatformIntegrationConfig.objects.create(
            tenant=tenant,
            platform="jifeng_wms",
            account_alias="极风库存配置 A",
            environment=PlatformIntegrationConfig.Environment.PILOT,
            status=PlatformIntegrationConfig.Status.VERIFIED,
            regions=["MY"],
            platform_config={"api_type": "inventory"},
            credential_id="synthetic-wms-credential",
            token_id="synthetic-wms-token",
            credential_status=PlatformIntegrationConfig.CredentialStatus.CONFIGURED,
            created_by=user,
        )
        replacement = PlatformIntegrationConfig.objects.create(
            tenant=tenant,
            platform="jifeng_wms",
            account_alias="极风库存配置 B",
            environment=PlatformIntegrationConfig.Environment.PILOT,
            status=PlatformIntegrationConfig.Status.VERIFIED,
            regions=["MY"],
            platform_config={"api_type": "inventory"},
            credential_id="synthetic-wms-credential-b",
            token_id="synthetic-wms-token-b",
            credential_status=PlatformIntegrationConfig.CredentialStatus.CONFIGURED,
            created_by=user,
        )
    return user, warehouse, config, replacement


def test_warehouse_api_binding_rebind_and_revoke_are_idempotent_and_masked():
    user, warehouse, config, replacement = _fixture()
    client = APIClient()
    client.force_authenticate(user)

    listed = client.get("/api/internal/integrations/warehouse-authorizations/", {"warehouse_id": warehouse.id})
    assert listed.status_code == 200
    assert listed.data["data"]["count"] == 0

    first = client.post(
        "/api/internal/integrations/warehouse-authorizations/",
        {"warehouse_id": warehouse.id, "integration_config_id": config.id},
        format="json",
    )
    assert first.status_code == 201
    first_payload = first.data["data"]["authorization"]
    assert first_payload["status"] == "active"
    assert "credential_id" not in str(first.data)
    assert "token_id" not in str(first.data)

    repeat = client.post(
        "/api/internal/integrations/warehouse-authorizations/",
        {"warehouse_id": warehouse.id, "integration_config_id": config.id},
        format="json",
    )
    assert repeat.status_code == 200
    assert repeat.data["data"]["idempotent"] is True
    assert WarehouseAuthorization.objects.filter(tenant=user.tenant).count() == 1

    blocked = client.post(
        "/api/internal/integrations/warehouse-authorizations/",
        {"warehouse_id": warehouse.id, "integration_config_id": replacement.id},
        format="json",
    )
    assert blocked.status_code == 409

    changed = client.post(
        "/api/internal/integrations/warehouse-authorizations/",
        {
            "warehouse_id": warehouse.id,
            "integration_config_id": replacement.id,
            "replace": True,
            "expected_authorization_id": first_payload["id"],
        },
        format="json",
    )
    assert changed.status_code == 201
    changed_id = changed.data["data"]["authorization"]["id"]
    assert WarehouseAuthorization.objects.get(pk=first_payload["id"]).status == WarehouseAuthorization.Status.REVOKED
    assert WarehouseAuthorization.objects.get(pk=changed_id).status == WarehouseAuthorization.Status.ACTIVE

    sync_payload = {
        "integration_config_id": replacement.id,
        "warehouse_authorization_id": changed_id,
        "resource_type": "inventory_snapshot",
        "schedule_type": "manual",
        "is_enabled": True,
    }
    sync_job = client.post(
        "/api/internal/integrations/sync-jobs/",
        sync_payload,
        format="json",
    )
    assert sync_job.status_code == 201
    repeat_sync_job = client.post(
        "/api/internal/integrations/sync-jobs/",
        sync_payload,
        format="json",
    )
    assert repeat_sync_job.status_code == 200
    assert repeat_sync_job.data["data"]["idempotent"] is True
    assert repeat_sync_job.data["data"]["sync_job"]["id"] == sync_job.data["data"]["id"]

    revoked = client.post(
        f"/api/internal/integrations/warehouse-authorizations/{changed_id}/revoke/",
        {},
        format="json",
    )
    assert revoked.status_code == 200
    assert revoked.data["data"]["authorization"]["status"] == "revoked"
    repeat_revoke = client.post(
        f"/api/internal/integrations/warehouse-authorizations/{changed_id}/revoke/",
        {},
        format="json",
    )
    assert repeat_revoke.status_code == 200
    assert repeat_revoke.data["data"]["idempotent"] is True


def test_stale_rebind_cannot_revive_a_revoked_warehouse_binding():
    user, warehouse, config, replacement = _fixture()
    client = APIClient()
    client.force_authenticate(user)

    bound = client.post(
        "/api/internal/integrations/warehouse-authorizations/",
        {"warehouse_id": warehouse.id, "integration_config_id": config.id},
        format="json",
    )
    authorization_id = bound.data["data"]["authorization"]["id"]
    revoked = client.post(
        f"/api/internal/integrations/warehouse-authorizations/{authorization_id}/revoke/",
        {},
        format="json",
    )
    assert revoked.status_code == 200

    stale = client.post(
        f"/api/internal/integrations/warehouse-authorizations/{authorization_id}/rebind/",
        {"integration_config_id": replacement.id},
        format="json",
    )
    assert stale.status_code == 404
    assert WarehouseAuthorization.objects.filter(
        tenant=user.tenant,
        warehouse=warehouse,
        status=WarehouseAuthorization.Status.ACTIVE,
    ).count() == 0


def test_warehouse_readonly_check_uses_the_selected_warehouse_binding(monkeypatch):
    user, warehouse, config, _replacement = _fixture()
    client = APIClient()
    client.force_authenticate(user)

    bound = client.post(
        "/api/internal/integrations/warehouse-authorizations/",
        {"warehouse_id": warehouse.id, "integration_config_id": config.id},
        format="json",
    )
    authorization_id = bound.data["data"]["authorization"]["id"]
    created = client.post(
        "/api/internal/integrations/sync-jobs/",
        {
            "integration_config_id": config.id,
            "warehouse_authorization_id": authorization_id,
            "resource_type": "inventory_snapshot",
            "schedule_type": "manual",
            "is_enabled": True,
        },
        format="json",
    )
    assert created.status_code == 201

    def runtime_setting(_section, key, default=None):
        return {
            "mode": "approved-live-test",
            "readonly_sync_enabled": True,
        }.get(key, default)

    class Custody:
        @staticmethod
        def retrieve_secret(_credential_id):
            return {"token": "masked-in-test"}

    seen = {}

    class Adapter:
        @staticmethod
        def validate_configuration(job):
            seen["authorization_id"] = job.warehouse_authorization_id

        @staticmethod
        def fetch_page(_job, _cursor):
            return {"records": [{"sku": "TEST-SKU"}]}

    monkeypatch.setattr("apps.integrations.views.get_runtime_setting", runtime_setting)
    monkeypatch.setattr("apps.integrations.views.get_custody_backend", lambda: Custody())
    monkeypatch.setattr("apps.integrations.views.get_adapter_for_config", lambda _config, _resource: Adapter())

    checked = client.post(
        f"/api/internal/integrations/configs/{config.id}/readonly-check/",
        {"warehouse_authorization_id": authorization_id},
        format="json",
    )

    assert checked.status_code == 200
    assert checked.data["data"]["sample_count"] == 1
    assert seen["authorization_id"] == authorization_id
    assert WarehouseAuthorization.objects.get(pk=authorization_id).last_verified_at is not None


def test_configured_wms_credentials_keep_workspace_job_ready():
    user, warehouse, config, _replacement = _fixture()
    client = APIClient()
    client.force_authenticate(user)

    bound = client.post(
        "/api/internal/integrations/warehouse-authorizations/",
        {"warehouse_id": warehouse.id, "integration_config_id": config.id},
        format="json",
    )
    authorization_id = bound.data["data"]["authorization"]["id"]
    created = client.post(
        "/api/internal/integrations/sync-jobs/",
        {
            "integration_config_id": config.id,
            "warehouse_authorization_id": authorization_id,
            "resource_type": "inventory_snapshot",
            "schedule_type": "manual",
            "is_enabled": True,
        },
        format="json",
    )
    assert created.status_code == 201

    response = client.get("/api/internal/integrations/workspace/", {"mode": "sync-jobs"})

    assert response.status_code == 200
    row = response.data["data"]["results"][0]
    assert row["credential_status"] == PlatformIntegrationConfig.CredentialStatus.CONFIGURED
    assert row["health_state"] == "healthy"
    assert row["blocked_reason"] == ""
    assert response.data["data"]["previews"]["reconcile"]["eligible_subject_count"] == 1


@pytest.mark.parametrize(
    ("credential_status", "config_status"),
    [
        (PlatformIntegrationConfig.CredentialStatus.EXPIRED, PlatformIntegrationConfig.Status.VERIFIED),
        (PlatformIntegrationConfig.CredentialStatus.REVOKED, PlatformIntegrationConfig.Status.VERIFIED),
        (PlatformIntegrationConfig.CredentialStatus.CONFIGURED, PlatformIntegrationConfig.Status.DISABLED),
    ],
)
def test_expired_revoked_or_disabled_wms_credentials_block_workspace_job(
    credential_status,
    config_status,
):
    user, warehouse, config, _replacement = _fixture()
    client = APIClient()
    client.force_authenticate(user)

    bound = client.post(
        "/api/internal/integrations/warehouse-authorizations/",
        {"warehouse_id": warehouse.id, "integration_config_id": config.id},
        format="json",
    )
    authorization_id = bound.data["data"]["authorization"]["id"]
    created = client.post(
        "/api/internal/integrations/sync-jobs/",
        {
            "integration_config_id": config.id,
            "warehouse_authorization_id": authorization_id,
            "resource_type": "inventory_snapshot",
            "schedule_type": "manual",
            "is_enabled": True,
        },
        format="json",
    )
    assert created.status_code == 201

    with authorization_service_write():
        config.credential_status = credential_status
        config.status = config_status
        config.save(update_fields=["credential_status", "status", "updated_at"])

    response = client.get("/api/internal/integrations/workspace/", {"mode": "sync-jobs"})

    assert response.status_code == 200
    row = response.data["data"]["results"][0]
    assert row["health_state"] == "configuration"
    assert row["blocked_reason"] == "开发者凭据尚未就绪"
    assert response.data["data"]["previews"]["reconcile"]["eligible_subject_count"] == 0
