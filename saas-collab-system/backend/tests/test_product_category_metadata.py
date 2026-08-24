import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductCategory, ProductLegacyItem, ProductSKU, ProductSPU
from apps.tenants.models import Tenant


def _client_for(tenant, username):
    user = CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, code=f"{username}-role", name="Category metadata role")
    role.permissions.add(*Permission.objects.filter(code__in=["products.master.view", "products.master.manage"]))
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_spu_list_exposes_stable_l2_category_metadata_for_l2_and_l3_nodes():
    tenant = Tenant.objects.create(name="Category metadata tenant", code="category-metadata")
    client = _client_for(tenant, "category-metadata-user")
    l1 = ProductCategory.objects.create(
        tenant=tenant, level=ProductCategory.Level.L1, code="1", name="家纺布艺"
    )
    l2 = ProductCategory.objects.create(
        tenant=tenant, parent=l1, level=ProductCategory.Level.L2, code="01", name="床上用品"
    )
    l3 = ProductCategory.objects.create(
        tenant=tenant, parent=l2, level=ProductCategory.Level.L3, code="01", name="床笠"
    )
    l2_spu = ProductSPU.objects.create(
        tenant=tenant, spu_code="10101001", product_name="L2 product", category_node=l2,
        l1_code="1", l2_code="01", l3_code="", season_code="1",
    )
    l3_spu = ProductSPU.objects.create(
        tenant=tenant, spu_code="10101011", product_name="L3 product", category_node=l3,
        l1_code="1", l2_code="01", l3_code="01", season_code="1",
    )

    response = client.get("/api/internal/products/spus/?page_size=20")

    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()["data"]["results"]}
    assert rows[l2_spu.id]["category_node_id"] == l2.id
    assert rows[l2_spu.id]["category_l2_id"] == l2.id
    assert rows[l2_spu.id]["category_l2_code"] == "01"
    assert rows[l2_spu.id]["category_l2_name"] == "床上用品"
    assert rows[l3_spu.id]["category_node_id"] == l3.id
    assert rows[l3_spu.id]["category_l2_id"] == l2.id
    assert rows[l3_spu.id]["category_l2_code"] == "01"
    assert rows[l3_spu.id]["category_l2_name"] == "床上用品"


@pytest.mark.django_db
def test_product_detail_rows_resolve_l2_metadata_from_effective_category_without_cross_tenant_data():
    tenant = Tenant.objects.create(name="Detail metadata tenant", code="detail-metadata")
    foreign_tenant = Tenant.objects.create(name="Foreign detail tenant", code="foreign-detail-metadata")
    client = _client_for(tenant, "detail-metadata-user")
    l1 = ProductCategory.objects.create(tenant=tenant, level=ProductCategory.Level.L1, code="1", name="家纺布艺")
    l2 = ProductCategory.objects.create(tenant=tenant, parent=l1, level=ProductCategory.Level.L2, code="01", name="床上用品")
    l3 = ProductCategory.objects.create(tenant=tenant, parent=l2, level=ProductCategory.Level.L3, code="02", name="被套")
    foreign_l1 = ProductCategory.objects.create(
        tenant=foreign_tenant, level=ProductCategory.Level.L1, code="1", name="Foreign root"
    )
    foreign_l2 = ProductCategory.objects.create(
        tenant=foreign_tenant, parent=foreign_l1, level=ProductCategory.Level.L2, code="01", name="Foreign leaf"
    )
    spu = ProductSPU.objects.create(
        tenant=tenant, spu_code="10101021", product_name="Detail SPU", category_node=l3,
        l1_code="1", l2_code="01", l3_code="02", season_code="1",
    )
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="10101021-blue", product_name="Detail SKU")
    legacy = ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_spu_code="OLD-META",
        legacy_sku_code="OLD-META-SKU",
        product_name="Imported detail",
        category_node=None,
        status=ProductLegacyItem.Status.GENERATED,
        generated_spu=spu,
        generated_sku=sku,
    )
    ProductSPU.objects.create(
        tenant=foreign_tenant, spu_code="10101001", product_name="Must stay hidden", category_node=foreign_l2,
    )

    response = client.get("/api/internal/products/details/?page_size=20")

    assert response.status_code == 200
    rows = response.json()["data"]["results"]
    row = next(item for item in rows if item["id"] == legacy.id)
    assert row["category_node"] is None
    assert row["category_node_id"] == l3.id
    assert row["category_l2_id"] == l2.id
    assert row["category_l2_code"] == "01"
    assert row["category_l2_name"] == "床上用品"
    assert all(item.get("spu_code") != "10101001" for item in rows)

