from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.products.models import ProductLegacyItem, ProductSKU, ProductSPU
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


def _user(tenant):
    user = CustomUser.objects.create_user(
        username=f"detail-collection-{tenant.code}",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, code=f"detail-role-{tenant.code}", name="Product detail role")
    role.permissions.add(*Permission.objects.filter(code__in=["products.master.view", "products.master.manage"]))
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    return user


@pytest.mark.django_db
def test_product_detail_collection_flattens_rows_and_supports_pagination_and_global_search():
    tenant = Tenant.objects.create(name="Detail collection tenant", code="detail-collection")
    user = _user(tenant)
    ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_spu_code="OLD-PENDING-SPU",
        legacy_sku_code="OLD-PENDING-SKU",
        product_name="Pending item",
        color_code="red",
        specification="S",
        purchase_price=Decimal("3.5000"),
    )
    spu = ProductSPU.objects.create(
        tenant=tenant,
        spu_code="NEW-SPU-001",
        legacy_spu_code="OLD-GENERATED-SPU",
        product_name="Generated item",
    )
    ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="NEW-SKU-001",
        legacy_sku_code="OLD-GENERATED-SKU",
        color_code="blue",
        specification="M",
        purchase_price=Decimal("7.2500"),
    )

    client = APIClient()
    client.force_authenticate(user=user)
    first = client.get("/api/internal/products/details/", {"page": 1, "page_size": 1})
    assert first.status_code == 200
    assert first.json()["data"]["count"] == 2
    assert len(first.json()["data"]["results"]) == 1
    assert first.json()["data"]["next"]

    search = client.get("/api/internal/products/details/", {"search": "OLD-GENERATED-SKU"})
    assert search.status_code == 200
    rows = search.json()["data"]["results"]
    assert len(rows) == 1
    assert rows[0]["sku_code"] == "NEW-SKU-001"
    assert rows[0]["purchase_price"] == "7.2500"

    price_search = client.get("/api/internal/products/details/", {"search": "7.25"})
    assert price_search.status_code == 200
    assert price_search.json()["data"]["results"][0]["sku_code"] == "NEW-SKU-001"


@pytest.mark.django_db
def test_legacy_import_accepts_csv_text_and_purchase_price_column():
    tenant = Tenant.objects.create(name="Detail import tenant", code="detail-import")
    user = _user(tenant)
    client = APIClient()
    client.force_authenticate(user=user)
    csv_text = "旧SPU编码,旧SKU编码,商品名称,采购价格\nOLD-SPU,OLD-SKU,Imported item,12.50\n"

    response = client.post(
        "/api/internal/products/legacy-items/",
        {"csv_text": csv_text},
        format="json",
    )

    assert response.status_code == 201
    item = ProductLegacyItem.objects.get(tenant=tenant, legacy_sku_code="OLD-SKU")
    assert item.purchase_price == Decimal("12.5000")
