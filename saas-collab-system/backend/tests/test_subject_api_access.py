import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import (
    MarketplaceStoreAuthorization,
    PlatformIntegrationConfig,
    WarehouseAuthorization,
    authorization_service_write,
    marketplace_identity_key,
    marketplace_store_binding_key,
)
from apps.integrations.platform_schema_service import integration_platform_key
from apps.masterdata.models import PlatformMaster, StatusChoices, StoreMaster, WarehouseMaster
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def test_subject_api_access_links_store_config_authorization_and_masks_credentials():
    tenant = Tenant.objects.create(name="Tenant A", code="subject-access-a")
    user = CustomUser.objects.create_user(
        username="subject-access-admin",
        password="not-a-real-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
        is_superuser=True,
    )
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code="shopee",
        name="Shopee",
        platform_type="shopee",
        status=StatusChoices.ACTIVE,
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code="STORE-MY-01",
        name="Shopee MY Store",
        country_code="MY",
        currency="MYR",
        timezone="Asia/Kuala_Lumpur",
    )
    with authorization_service_write():
        config = PlatformIntegrationConfig.objects.create(
            tenant=tenant,
            platform="shopee",
            account_alias="Shopee MY production",
            environment="production",
            status="verified",
            regions=["MY"],
            scopes=["shop.info.read"],
            platform_config={"api_type": "marketplace"},
            created_by=user,
        )
        identity_key = marketplace_identity_key("shopee", "MY", "987654")
        authorization = MarketplaceStoreAuthorization.objects.create(
            tenant=tenant,
            integration_config=config,
            store=store,
            platform="shopee",
            region="MY",
            platform_store_id="987654",
            platform_identity_key=identity_key,
            active_platform_identity_key=identity_key,
            active_store_binding_key=marketplace_store_binding_key(tenant.id, "shopee", store.id),
            merchant_subject_id="merchant-987654",
            credential_id="synthetic-credential-reference",
            token_id="synthetic-token-reference",
            credential_mask={"token": "********"},
            status="active",
            scopes=["marketplace"],
            authorized_at=timezone.now(),
            created_by=user,
            updated_by=user,
        )

    client = APIClient()
    client.force_authenticate(user)
    response = client.get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "store", "subject_id": store.id},
    )

    assert response.status_code == 200
    payload = response.data["data"]
    assert payload["subject"] == {
        "id": store.id,
        "code": "STORE-MY-01",
        "name": "Shopee MY Store",
        "country_code": "MY",
        "platform": "shopee",
        "platform_name": "Shopee",
    }
    assert payload["token_policy"] == "auto-refresh"
    assert payload["configs"][0]["api_type"] == "marketplace"
    assert payload["bindings"][0]["id"] == authorization.id
    assert payload["bindings"][0]["account_alias"] == "Shopee MY production"
    assert "credential_id" not in str(payload)
    assert "token_id" not in str(payload)
    assert "credential_mask" not in str(payload)


def test_subject_api_access_rejects_unknown_subject_type():
    tenant = Tenant.objects.create(name="Tenant B", code="subject-access-b")
    user = CustomUser.objects.create_user(
        username="subject-access-admin-b",
        password="not-a-real-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
        is_superuser=True,
    )
    client = APIClient()
    client.force_authenticate(user)

    response = client.get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "supplier", "subject_id": 1},
    )

    assert response.status_code == 400


def test_myjf_alias_resolves_to_existing_jifeng_inventory_provider():
    assert integration_platform_key(code="myjf") == "jifeng_wms"
    assert integration_platform_key(code="jifengwms") == "jifeng_wms"
    assert integration_platform_key(name="极风 WMS") == "jifeng_wms"


def test_subject_api_access_resolves_warehouse_service_platform_and_fail_closes_unknown_provider():
    tenant = Tenant.objects.create(name="Tenant C", code="subject-access-warehouse")
    user = CustomUser.objects.create_user(
        username="subject-access-warehouse-admin",
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
        code="warehouse-my-01",
        name="MY third-party warehouse",
        country_code="MY",
        warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY,
        service_platform=service_platform,
        status=StatusChoices.ACTIVE,
    )
    with authorization_service_write():
        config = PlatformIntegrationConfig.objects.create(
            tenant=tenant,
            platform="jifeng_wms",
            account_alias="Jifeng MY inventory",
            environment="sandbox",
            status="verified",
            regions=["MY"],
            platform_config={"api_type": "inventory"},
            created_by=user,
        )
        WarehouseAuthorization.objects.create(
            tenant=tenant,
            integration_config=config,
            warehouse=warehouse,
            provider="jifeng_wms",
            credential_id="synthetic-credential-reference",
            token_id="synthetic-token-reference",
            credential_mask={"token": "********"},
            status=WarehouseAuthorization.Status.ACTIVE,
            authorized_at=timezone.now(),
            created_by=user,
            updated_by=user,
        )

    client = APIClient()
    client.force_authenticate(user)
    response = client.get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "warehouse", "subject_id": warehouse.id},
    )

    assert response.status_code == 200
    payload = response.data["data"]
    assert payload["subject"]["platform"] == "jifeng_wms"
    assert payload["subject"]["platform_name"] == "马来极风"
    assert payload["subject"]["service_platform_id"] == service_platform.id
    assert payload["api_types"] == ["inventory"]
    assert payload["configs"][0]["platform"] == "jifeng_wms"
    assert payload["bindings"][0]["provider"] == "jifeng_wms"
    assert "credential_id" not in str(payload)
    assert "token_id" not in str(payload)

    unknown_platform = PlatformMaster.objects.create(
        tenant=tenant,
        code="unknown-warehouse-provider",
        name="Unknown warehouse provider",
        platform_type="warehouse_platform",
        status=StatusChoices.ACTIVE,
    )
    unknown_warehouse = WarehouseMaster.objects.create(
        tenant=tenant,
        code="warehouse-unknown-01",
        name="Unknown warehouse",
        country_code="MY",
        warehouse_type=WarehouseMaster.WarehouseType.PLATFORM,
        service_platform=unknown_platform,
        status=StatusChoices.ACTIVE,
    )
    serialized = client.get("/api/internal/master-data/warehouses/")
    unknown_row = next(row for row in serialized.data["data"]["results"] if row["id"] == unknown_warehouse.id)
    assert unknown_row["api_access_available"] is False
    blocked = client.get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "warehouse", "subject_id": unknown_warehouse.id},
    )
    assert blocked.status_code == 400
    assert "受支持" in str(blocked.data)


def test_subject_api_access_rejects_unbound_warehouse():
    tenant = Tenant.objects.create(name="Tenant D", code="subject-access-unbound-warehouse")
    user = CustomUser.objects.create_user(
        username="subject-access-unbound-warehouse-admin",
        password="not-a-real-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
        is_superuser=True,
    )
    warehouse = WarehouseMaster.objects.create(
        tenant=tenant,
        code="warehouse-unbound-01",
        name="Unbound warehouse",
        country_code="PH",
        warehouse_type=WarehouseMaster.WarehouseType.OWNED,
        status=StatusChoices.ACTIVE,
    )
    client = APIClient()
    client.force_authenticate(user)

    response = client.get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "warehouse", "subject_id": warehouse.id},
    )

    assert response.status_code == 400
    assert "尚未绑定" in str(response.data)
