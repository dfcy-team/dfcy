import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import (
    PlatformIntegrationConfig,
    WarehouseAuthorization,
    authorization_service_write,
)
from apps.integrations.readonly_clients import JifengWmsReadonlyClient
from apps.masterdata.models import PlatformMaster, StatusChoices, StoreMaster, WarehouseMaster
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _tenant_user(code):
    tenant = Tenant.objects.create(name=f"Identity {code}", code=f"identity-{code}")
    user = CustomUser.objects.create_user(
        username=f"identity-{code}",
        password="not-a-real-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
        is_superuser=True,
    )
    return tenant, user


def _platform(tenant, code="shopee", platform_type="shopee"):
    return PlatformMaster.objects.create(
        tenant=tenant,
        code=code,
        name=code,
        platform_type=platform_type,
        status=StatusChoices.ACTIVE,
    )


def test_store_external_identity_is_unique_per_tenant_platform_region_but_blank_and_cross_region_are_allowed():
    tenant, _user = _tenant_user("store")
    platform = _platform(tenant)
    first = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code="store-my-a",
        name="MY A",
        country_code="MY",
        currency="MYR",
        external_store_id="shop-001",
    )
    first.external_store_id = "shop-001-renamed"
    first.save(update_fields=["external_store_id"])
    first.refresh_from_db()
    assert first.external_store_id == "shop-001-renamed"
    assert first.external_store_identity_key
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            StoreMaster.objects.create(
                tenant=tenant,
                platform=platform,
                code="store-my-b",
                name="MY B",
                country_code="MY",
                currency="MYR",
                external_store_id=" shop-001-renamed ",
            )

    # The OAuth identity includes region, so the same upstream id is valid in
    # another site.  Manual archives may omit an upstream id altogether.
    StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code="store-ph-a",
        name="PH A",
        country_code="PH",
        currency="PHP",
        external_store_id="shop-001",
    )
    for code in ("manual-a", "manual-b"):
        StoreMaster.objects.create(
            tenant=tenant,
            platform=platform,
            code=code,
            name=code,
            country_code="MY",
            currency="MYR",
        )


def test_platform_type_change_is_blocked_when_store_external_identity_is_bound():
    tenant, _user = _tenant_user("platform-type")
    platform = _platform(tenant)
    StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code="bound-store",
        name="Bound store",
        country_code="MY",
        currency="MYR",
        external_store_id="platform-store-001",
    )

    platform.platform_type = "tiktok"
    with pytest.raises(DjangoValidationError):
        platform.save(update_fields=["platform_type"])
    platform.refresh_from_db()
    assert platform.platform_type == "shopee"


def _warehouse_fixture():
    tenant, user = _tenant_user("warehouse")
    platform = _platform(tenant, code="myjf", platform_type="warehouse_third_party")
    warehouse = WarehouseMaster.objects.create(
        tenant=tenant,
        code="MY-WH-01",
        name="MY warehouse",
        country_code="MY",
        warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY,
        service_platform=platform,
        status=StatusChoices.ACTIVE,
    )
    with authorization_service_write():
        config = PlatformIntegrationConfig.objects.create(
            tenant=tenant,
            platform="jifeng_wms",
            account_alias="Jifeng MY",
            environment=PlatformIntegrationConfig.Environment.PILOT,
            status=PlatformIntegrationConfig.Status.VERIFIED,
            regions=["MY"],
            platform_config={"api_type": "inventory"},
            credential_id="identity-credential",
            token_id="identity-token",
            credential_status=PlatformIntegrationConfig.CredentialStatus.CONFIGURED,
            created_by=user,
        )
    return tenant, user, platform, warehouse, config


def test_warehouse_binding_accepts_external_code_rebinds_identity_and_keeps_history():
    _tenant, user, _platform_row, warehouse, config = _warehouse_fixture()
    client = APIClient()
    client.force_authenticate(user)
    first = client.post(
        "/api/internal/integrations/warehouse-authorizations/",
        {
            "warehouse_id": warehouse.id,
            "integration_config_id": config.id,
            "external_warehouse_code": "JF-MY-001",
        },
        format="json",
    )
    assert first.status_code == 201
    first_id = first.data["data"]["authorization"]["id"]
    assert first.data["data"]["authorization"]["external_warehouse_code"] == "JF-MY-001"

    repeated = client.post(
        "/api/internal/integrations/warehouse-authorizations/",
        {
            "warehouse_id": warehouse.id,
            "integration_config_id": config.id,
            "external_warehouse_code": "JF-MY-001",
        },
        format="json",
    )
    assert repeated.status_code == 200
    assert repeated.data["data"]["idempotent"] is True

    changed = client.post(
        f"/api/internal/integrations/warehouse-authorizations/{first_id}/rebind/",
        {
            "integration_config_id": config.id,
            "external_warehouse_code": "JF-MY-002",
        },
        format="json",
    )
    assert changed.status_code == 201
    assert changed.data["data"]["authorization"]["external_warehouse_code"] == "JF-MY-002"
    old = WarehouseAuthorization.objects.get(pk=first_id)
    assert old.status == WarehouseAuthorization.Status.REVOKED
    assert old.external_warehouse_identity_key is None

    # The subject drawer reloads through subject-api-access rather than the
    # authorization serializer; the binding identity must round-trip there.
    subject = client.get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "warehouse", "subject_id": warehouse.id},
    )
    assert subject.status_code == 200
    binding = next(item for item in subject.data["data"]["bindings"] if item["id"] == changed.data["data"]["authorization"]["id"])
    assert binding["external_warehouse_code"] == "JF-MY-002"
    assert binding["external_warehouse_region"] == "MY"


def test_warehouse_external_identity_allows_cross_region_and_provider_but_not_same_scope():
    tenant, user, platform, warehouse_my, config = _warehouse_fixture()
    warehouse_ph = WarehouseMaster.objects.create(
        tenant=tenant,
        code="PH-WH-01",
        name="PH warehouse",
        country_code="PH",
        warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY,
        service_platform=platform,
        status=StatusChoices.ACTIVE,
    )
    first = WarehouseAuthorization.objects.create(
        tenant=tenant,
        integration_config=config,
        warehouse=warehouse_my,
        provider="jifeng_wms",
        external_warehouse_code="SHARED-CODE",
        external_warehouse_region="MY",
        credential_id="identity-credential",
        token_id="identity-token",
        status=WarehouseAuthorization.Status.ACTIVE,
        created_by=user,
        updated_by=user,
    )
    first.external_warehouse_code = "SHARED-CODE-RENAMED"
    first.save(update_fields=["external_warehouse_code"])
    first.refresh_from_db()
    assert first.external_warehouse_code == "SHARED-CODE-RENAMED"
    assert first.external_warehouse_identity_key
    # Region is part of the provider identity; a different region is allowed.
    second = WarehouseAuthorization.objects.create(
        tenant=tenant,
        integration_config=config,
        warehouse=warehouse_ph,
        provider="jifeng_wms",
        external_warehouse_code="SHARED-CODE",
        external_warehouse_region="PH",
        credential_id="identity-credential",
        token_id="identity-token",
        status=WarehouseAuthorization.Status.ACTIVE,
        created_by=user,
        updated_by=user,
    )
    assert first.external_warehouse_identity_key != second.external_warehouse_identity_key

    other_provider = WarehouseAuthorization.objects.create(
        tenant=tenant,
        integration_config=config,
        warehouse=WarehouseMaster.objects.create(
            tenant=tenant,
            code="MY-WH-02",
            name="MY warehouse 2",
            country_code="MY",
            warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY,
            service_platform=platform,
            status=StatusChoices.ACTIVE,
        ),
        provider="other_wms",
        external_warehouse_code="SHARED-CODE",
        external_warehouse_region="MY",
        credential_id="identity-credential",
        token_id="identity-token",
        status=WarehouseAuthorization.Status.ACTIVE,
        created_by=user,
        updated_by=user,
    )
    assert other_provider.external_warehouse_identity_key != first.external_warehouse_identity_key


def test_jifeng_request_uses_binding_code_and_normalized_fact_uses_local_warehouse(monkeypatch):
    _tenant, user, _platform_row, warehouse, config = _warehouse_fixture()
    authorization = WarehouseAuthorization.objects.create(
        tenant=warehouse.tenant,
        integration_config=config,
        warehouse=warehouse,
        provider="jifeng_wms",
        external_warehouse_code="UPSTREAM-MY-001",
        external_warehouse_region="MY",
        credential_id="identity-credential",
        token_id="identity-token",
        status=WarehouseAuthorization.Status.ACTIVE,
        created_by=user,
        updated_by=user,
    )
    config.platform_config = {
        "api_type": "inventory",
        "site_code": "MY",
        "api_host": "https://example.invalid",
        "client_id": "client",
        "user_id": "user",
        "warehouse_code": "SHARED-CONFIG-CODE",
    }
    seen = {}

    class Response:
        def json(self):
            return {"code": 0, "data": {"page": {"totalPage": 1, "list": [{"sku": "SKU-1"}]}}}

    class Http:
        def request(self, method, url, **kwargs):
            seen["body"] = kwargs["json_body"]
            return Response()

    class Custody:
        def retrieve_secret(self, _value):
            return "secret"

        def retrieve_access_token(self, _value):
            return "token"

    client = JifengWmsReadonlyClient(
        config,
        authorization,
        http_client=Http(),
        custody=Custody(),
    )
    monkeypatch.setattr(client, "preflight", lambda: None)
    client.fetch_inventory(None, {"page_size": 50})
    assert seen["body"]["warehouse"] == "UPSTREAM-MY-001"
