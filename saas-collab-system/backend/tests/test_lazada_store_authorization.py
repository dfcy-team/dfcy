import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import MarketplaceStoreAuthorization, PlatformIntegrationConfig
from apps.integrations.platform_schema_service import get_platform_schema
from apps.masterdata.models import PlatformMaster, StatusChoices, StoreMaster
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


@pytest.fixture
def lazada_context():
    tenant = Tenant.objects.create(name="Lazada Tenant", code="lazada-tenant")
    user = CustomUser.objects.create_user(
        username="lazada-admin",
        password="not-a-real-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
        is_superuser=True,
    )
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code="lazada",
        name="Lazada",
        platform_type=PlatformMaster.PlatformType.LAZADA,
        status=StatusChoices.ACTIVE,
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code="LAZ-MY-01",
        name="Lazada MY Store",
        country_code="MY",
        currency="MYR",
        timezone="Asia/Kuala_Lumpur",
    )
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="lazada",
        account_alias="Lazada MY production",
        environment="production",
        status="verified",
        regions=["MY"],
        contract_version="open-platform-v1",
        callback_url="https://example.test/api/internal/integrations/store-authorizations/oauth/callback/lazada/",
        scopes=[],
        platform_config={"api_type": "marketplace", "app_key": "public-app-key"},
        created_by=user,
    )
    client = APIClient()
    client.force_authenticate(user)
    return client, store, config


def test_lazada_schema_exposes_six_supported_countries():
    schema = get_platform_schema("lazada")

    assert schema["contract_versions"] == ["open-platform-v1"]
    assert {item["value"] for item in schema["regions"]} == {"SG", "MY", "TH", "VN", "ID", "PH"}
    assert [field["key"] for field in schema["fields"]] == ["app_key", "account_reference"]


def test_lazada_store_access_only_exposes_marketplace_api(lazada_context):
    client, store, _config = lazada_context

    response = client.get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "store", "subject_id": store.id},
    )

    assert response.status_code == 200
    assert response.data["data"]["api_types"] == ["marketplace"]
    assert response.data["data"]["token_policy"] == "oauth-auto-refresh"


def test_lazada_oauth_start_and_callback_create_store_authorization(lazada_context):
    client, store, config = lazada_context
    start = client.post(
        "/api/internal/integrations/store-authorizations/oauth/start/",
        {
            "platform": "lazada",
            "integration_config_id": config.id,
            "store_id": store.id,
            "region": "MY",
            "redirect_uri": config.callback_url,
            "scopes": [],
        },
        format="json",
    )

    assert start.status_code == 201
    callback = start.data["data"]["simulation_callback"]
    response = APIClient().get(
        "/api/internal/integrations/store-authorizations/oauth/callback/lazada/",
        callback,
    )

    assert response.status_code == 200
    authorization = MarketplaceStoreAuthorization.objects.get(store=store, platform="lazada")
    assert authorization.status == MarketplaceStoreAuthorization.Status.ACTIVE
    assert authorization.platform_store_id == "laz-my-01"
    assert "credential_id" not in str(response.data)
    assert "token_id" not in str(response.data)
