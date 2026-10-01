import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant

pytestmark = pytest.mark.django_db


def test_product_scope_options_are_opt_in_bounded_searchable_and_tenant_scoped():
    tenant = Tenant.objects.create(name="scope-a", code="scope-a")
    other = Tenant.objects.create(name="scope-b", code="scope-b")
    actor = CustomUser.objects.create_superuser(username="scope-admin", password="test-scope-options", tenant=tenant)
    own_spu = ProductSPU.objects.create(tenant=tenant, spu_code="A-SPU", legacy_spu_code="OLD-A", product_name="Travel bag")
    own_sku = ProductSKU.objects.create(tenant=tenant, spu=own_spu, sku_code="A-SKU", legacy_sku_code="OLD-SKU", product_name="Black bag")
    foreign_spu = ProductSPU.objects.create(tenant=other, spu_code="B-SPU", product_name="Foreign bag")
    ProductSKU.objects.create(tenant=other, spu=foreign_spu, sku_code="B-SKU")
    client = APIClient()
    client.force_authenticate(actor)

    default = client.get("/api/internal/system/role-scope-options/")
    assert default.status_code == 200
    assert set(default.json()["data"]) == {"platforms", "sites", "stores", "warehouses", "suppliers"}

    response = client.get("/api/internal/system/role-scope-options/", {
        "include_products": "true", "tenant_id": tenant.pk, "product_search": " old-sku ",
        "selected_sku_ids": str(own_sku.pk), "selected_spu_ids": f"{own_spu.pk},{foreign_spu.pk}",
    })
    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["id"] for item in data["skus"]] == [own_sku.pk]
    assert data["skus"][0]["name"] == "Black bag"
    assert [item["id"] for item in data["spus"]] == [own_spu.pk]
    assert "skus" not in default.json()["data"]

    unprivileged = CustomUser.objects.create_user(
        username="scope-no-manage", password="test-scope-options", tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    client.force_authenticate(unprivileged)
    denied = client.get("/api/internal/system/role-scope-options/?include_products=true")
    assert denied.status_code == 403


def test_product_scope_option_lists_are_limited_to_one_hundred_each():
    tenant = Tenant.objects.create(name="scope-limit", code="scope-limit")
    actor = CustomUser.objects.create_superuser(username="scope-limit-admin", password="test-scope-options", tenant=tenant)
    for index in range(105):
        spu = ProductSPU.objects.create(tenant=tenant, spu_code=f"P-{index:03}", product_name="Product")
        ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code=f"S-{index:03}")
    client = APIClient()
    client.force_authenticate(actor)
    response = client.get("/api/internal/system/role-scope-options/?include_products=true")
    assert response.status_code == 200
    assert len(response.json()["data"]["skus"]) == 100
    assert len(response.json()["data"]["spus"]) == 100
