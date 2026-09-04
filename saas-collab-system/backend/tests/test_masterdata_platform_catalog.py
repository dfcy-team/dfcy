from types import SimpleNamespace

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.masterdata.models import PlatformMaster
from apps.masterdata.platform_catalog import (
    PLATFORM_CATALOG,
    normalize_platform_code,
    platform_catalog_item,
    resolve_platform_connector,
)
from apps.masterdata.serializers import PlatformMasterSerializer
from apps.tenants.models import Tenant


def test_catalog_covers_requested_priorities_and_keeps_connector_state_fail_closed():
    by_code = {item["canonical_code"]: item for item in PLATFORM_CATALOG}
    for code in ("SHOPEE", "TIKTOK_SHOP", "AMAZON", "WILDBERRIES", "OZON", "SHOPIFY", "ETSY", "CUSTOM_STORE"):
        assert code in by_code
    assert by_code["SHOPEE"]["connector_status"] == "ACTIVE"
    assert by_code["TIKTOK_SHOP"]["connector_status"] == "ACTIVE"
    assert by_code["LAZADA"]["connector_status"] == "TESTING"
    assert by_code["AMAZON"]["connector_status"] == "NOT_IMPLEMENTED"
    assert by_code["SHOPIFY"]["priority_level"] == "P1"
    assert by_code["ETSY"]["priority_level"] == "P2"
    assert by_code["CUSTOM_STORE"]["priority_level"] == "P3"


@pytest.mark.parametrize("alias, expected", [
    ("TK", "tiktok"), ("TIKTOKSHOP", "tiktok"), ("TIKTOK_SHOP", "tiktok"),
    ("WB", "wildberries"), ("MERCADOLIBRE", "mercado_libre"),
])
def test_platform_aliases_normalize_to_compatible_internal_values(alias, expected):
    assert normalize_platform_code(alias) == expected


def test_model_choices_match_catalog_values():
    assert {value for value, _ in PlatformMaster.PlatformType.choices} == {item["value"] for item in PLATFORM_CATALOG}
    assert platform_catalog_item("TIKTOK_SHOP")["value"] == PlatformMaster.PlatformType.TIKTOK


def test_warehouse_platform_types_are_business_categories_not_connectors():
    for value in ("warehouse_owned", "warehouse_third_party", "warehouse_platform"):
        item = platform_catalog_item(value)
        assert item["is_business_category"] is True
        assert item["platform_category"] == "WAREHOUSE_SERVICE"
        assert item["option_group"] == "仓储服务分类"
        assert item["connector_status"] == "UNMAPPED"
        assert "具体服务商" in item["connector_hint"]


def test_myjf_warehouse_row_resolves_to_the_explicit_jifeng_connector():
    resolution = resolve_platform_connector(
        platform_type="warehouse_third_party", code="myjf", name="马来极风"
    )
    assert resolution == {
        "connector_key": "jifeng_wms",
        "connector_name": "极风 WMS",
        "connector_status": "ACTIVE",
        "connector_hint": "已按平台编码或名称识别为极风 WMS，支持库存 API 接入。",
    }


def test_unknown_warehouse_provider_fails_closed_as_unmapped():
    resolution = resolve_platform_connector(
        platform_type="warehouse_third_party", code="unknown-3pl", name="未知三方仓"
    )
    assert resolution["connector_key"] == ""
    assert resolution["connector_name"] == "待识别服务商"
    assert resolution["connector_status"] == "UNMAPPED"
    assert "不是单一连接器" in resolution["connector_hint"]


@pytest.mark.django_db
def test_platform_serializer_exposes_record_level_connector_identity():
    tenant = Tenant.objects.create(name="Connector tenant", code="connector-tenant")
    user = CustomUser.objects.create_user(
        username="connector-admin", password="not-a-real-password", tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL, is_superuser=True,
    )
    platform = PlatformMaster.objects.create(
        tenant=tenant, code="myjf", name="马来极风", platform_type="warehouse_third_party",
    )
    data = PlatformMasterSerializer(platform, context={"request": SimpleNamespace(user=user)}).data
    assert data["connector_key"] == "jifeng_wms"
    assert data["connector_name"] == "极风 WMS"
    assert data["connector_status"] == "ACTIVE"
    assert "库存 API" in data["connector_hint"]

    unknown = PlatformMaster.objects.create(
        tenant=tenant, code="unknown-3pl", name="未知三方仓", platform_type="warehouse_third_party",
    )
    unknown_data = PlatformMasterSerializer(unknown, context={"request": SimpleNamespace(user=user)}).data
    assert unknown_data["connector_status"] == "UNMAPPED"
    assert unknown_data["connector_name"] == "待识别服务商"


@pytest.mark.django_db
def test_platform_catalog_endpoint_is_read_only_and_permission_protected():
    tenant = Tenant.objects.create(name="Catalog tenant", code="catalog-tenant")
    user = CustomUser.objects.create_user(
        username="catalog-admin", password="not-a-real-password", tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL, is_superuser=True,
    )
    client = APIClient()
    assert client.get(reverse("platform-catalog")).status_code in {401, 403}
    client.force_authenticate(user)
    response = client.get(reverse("platform-catalog"))
    assert response.status_code == 200
    assert response.data["data"]["count"] == len(PLATFORM_CATALOG)
    assert client.post(reverse("platform-catalog"), {}).status_code in {403, 405}

    serializer = PlatformMasterSerializer(
        data={"code": "tk-shop", "name": "TK Shop", "platform_type": "TIKTOK_SHOP"},
        context={"request": SimpleNamespace(user=user)},
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["platform_type"] == "tiktok"
