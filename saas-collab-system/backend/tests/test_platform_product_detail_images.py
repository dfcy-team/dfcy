from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

import pytest

from apps.accounts.models import CustomUser
from apps.listings.models import PlatformProductDetail
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _view_fixture():
    tenant = Tenant.objects.create(name="Platform image tenant", code="platform-image-tenant")
    user = CustomUser.objects.create_user(
        username="platform-image-user", tenant=tenant, user_type="internal"
    )
    platform = PlatformMaster.objects.create(
        tenant=tenant, code="image-platform", name="Image platform", platform_type="other"
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code="image-store",
        name="Image store",
        country_code="US",
        currency="USD",
    )
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="IMAGE-SPU", product_name="Image product")
    sku_one = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="IMAGE-SKU-1",
        image_url="https://cdn.example.test/sku-one.png",
    )
    sku_two = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="IMAGE-SKU-2",
        image_url="/media/product-images/tenant-1/sku-two.png",
    )
    sku_without_image = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="IMAGE-SKU-NONE",
        image_url="",
    )
    rows = [
        PlatformProductDetail.objects.create(
            tenant=tenant,
            platform=platform,
            store=store,
            platform_variant_id="IMAGE-V-1",
            internal_sku=sku_one,
        ),
        PlatformProductDetail.objects.create(
            tenant=tenant,
            platform=platform,
            store=store,
            platform_variant_id="IMAGE-V-2",
            internal_sku=sku_two,
        ),
        PlatformProductDetail.objects.create(
            tenant=tenant,
            platform=platform,
            store=store,
            platform_variant_id="IMAGE-V-NONE",
            internal_sku=sku_without_image,
        ),
    ]
    return tenant, user, platform, store, rows


def _grant_view(user, tenant):
    role = Role.objects.create(tenant=tenant, code="platform-image-view", name="Platform image view")
    role.permissions.add(Permission.objects.get(code="listings.product_detail.view"))
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})


def test_platform_detail_list_returns_linked_sku_images_without_leaking_other_tenants():
    tenant, user, platform, store, rows = _view_fixture()
    other_tenant = Tenant.objects.create(name="Other image tenant", code="other-image-tenant")
    other_platform = PlatformMaster.objects.create(
        tenant=other_tenant, code="other-image-platform", name="Other platform", platform_type="other"
    )
    other_store = StoreMaster.objects.create(
        tenant=other_tenant,
        platform=other_platform,
        code="other-image-store",
        name="Other store",
        country_code="US",
        currency="USD",
    )
    other_spu = ProductSPU.objects.create(tenant=other_tenant, spu_code="OTHER-IMAGE-SPU", product_name="Other")
    other_sku = ProductSKU.objects.create(
        tenant=other_tenant,
        spu=other_spu,
        sku_code="OTHER-IMAGE-SKU",
        image_url="https://private.example.test/other-tenant.png",
    )
    PlatformProductDetail.objects.create(
        tenant=other_tenant,
        platform=other_platform,
        store=other_store,
        platform_variant_id="OTHER-IMAGE-V-1",
        internal_sku=other_sku,
    )
    # A malformed legacy row must not expose a SKU image from another tenant
    # even though the detail itself remains in the current tenant's result.
    malformed = PlatformProductDetail.objects.create(
        tenant=tenant,
        platform=platform,
        store=store,
        platform_variant_id="IMAGE-V-CROSS-TENANT",
        internal_sku=other_sku,
    )

    _grant_view(user, tenant)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/internal/listings/product-details/", {"page_size": 100})

    assert response.status_code == 200
    payload = response.json()["data"]
    by_variant = {item["platform_variant_id"]: item for item in payload["results"]}
    assert payload["count"] == 4
    assert by_variant[rows[0].platform_variant_id]["internal_sku_image_url"] == rows[0].internal_sku.image_url
    assert by_variant[rows[1].platform_variant_id]["internal_sku_image_url"] == rows[1].internal_sku.image_url
    assert by_variant[rows[2].platform_variant_id]["internal_sku_image_url"] is None
    assert by_variant[malformed.platform_variant_id]["internal_sku_image_url"] is None
    assert "OTHER-IMAGE-V-1" not in by_variant
    assert all("other-tenant" not in (item["internal_sku_image_url"] or "") for item in payload["results"])


def test_platform_detail_image_serialization_does_not_add_a_query_per_row():
    tenant, user, _platform, _store, _rows = _view_fixture()
    _grant_view(user, tenant)
    client = APIClient()
    client.force_authenticate(user=user)

    with CaptureQueriesContext(connection) as one_page:
        one_response = client.get(
            "/api/internal/listings/product-details/", {"page": 1, "page_size": 1}
        )
    with CaptureQueriesContext(connection) as all_rows:
        all_response = client.get(
            "/api/internal/listings/product-details/", {"page": 1, "page_size": 100}
        )

    assert one_response.status_code == all_response.status_code == 200
    assert len(all_response.json()["data"]["results"]) == 3
    # The serializer reads internal_sku.image_url from the existing
    # select_related join; increasing the page size should not create one
    # additional query per returned detail.
    assert len(all_rows.captured_queries) <= len(one_page.captured_queries) + 1
