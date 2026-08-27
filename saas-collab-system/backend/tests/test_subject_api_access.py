import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import (
    MarketplaceStoreAuthorization,
    PlatformIntegrationConfig,
    authorization_service_write,
    marketplace_identity_key,
    marketplace_store_binding_key,
)
from apps.masterdata.models import PlatformMaster, StatusChoices, StoreMaster
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
