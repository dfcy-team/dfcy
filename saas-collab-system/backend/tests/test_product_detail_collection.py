from decimal import Decimal
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.products import views as product_views
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
def test_product_detail_collection_pages_across_legacy_and_sku_streams_without_duplicates(monkeypatch):
    tenant = Tenant.objects.create(name="Detail boundary tenant", code="detail-boundary")
    user = _user(tenant)
    pending_one = ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_spu_code="OLD-SPU-1",
        legacy_sku_code="OLD-SKU-1",
        product_name="Pending one",
    )
    pending_two = ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_spu_code="OLD-SPU-2",
        legacy_sku_code="OLD-SKU-2",
        product_name="Pending two",
    )
    linked_spu = ProductSPU.objects.create(
        tenant=tenant,
        spu_code="LINKED-SPU",
        product_name="Linked product",
    )
    linked_sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=linked_spu,
        sku_code="LINKED-SKU",
        product_name="Linked SKU",
        color_code="blue",
    )
    linked_legacy = ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_spu_code="OLD-SPU-LINKED",
        legacy_sku_code="OLD-SKU-LINKED",
        product_name="Linked legacy",
        status=ProductLegacyItem.Status.GENERATED,
        generated_spu=linked_spu,
        generated_sku=linked_sku,
    )
    standalone_one = ProductSKU.objects.create(
        tenant=tenant,
        spu=linked_spu,
        sku_code="A-SKU-1",
        product_name="Standalone one",
        color_code="red",
    )
    standalone_two = ProductSKU.objects.create(
        tenant=tenant,
        spu=linked_spu,
        sku_code="Z-SKU-2",
        product_name="Standalone two",
        color_code="green",
    )
    inactive = ProductSKU.objects.create(
        tenant=tenant,
        spu=linked_spu,
        sku_code="INACTIVE-SKU",
        product_name="Inactive SKU",
        is_active=False,
    )
    other_tenant = Tenant.objects.create(name="Other detail tenant", code="detail-boundary-other")
    other_spu = ProductSPU.objects.create(
        tenant=other_tenant,
        spu_code="OTHER-SPU",
        product_name="Other tenant product",
    )
    ProductSKU.objects.create(
        tenant=other_tenant,
        spu=other_spu,
        sku_code="OTHER-SKU",
        product_name="Other tenant SKU",
    )

    # Make the legacy ordering explicit so the page-2 assertion is stable
    # even when the database clock has coarse timestamp precision.
    anchor = timezone.now()
    ProductLegacyItem.objects.filter(pk=pending_one.pk).update(created_at=anchor - timedelta(seconds=2))
    ProductLegacyItem.objects.filter(pk=pending_two.pk).update(created_at=anchor - timedelta(seconds=1))
    ProductLegacyItem.objects.filter(pk=linked_legacy.pk).update(created_at=anchor)

    client = APIClient()
    client.force_authenticate(user=user)
    page_one = client.get("/api/internal/products/details/", {"page": 1, "page_size": 2})
    assert page_one.status_code == 200
    page_one_data = page_one.json()["data"]
    assert page_one_data["count"] == 6
    assert [row["row_type"] for row in page_one_data["results"]] == ["legacy", "legacy"]
    assert page_one_data["next"] and "page=2" in page_one_data["next"]
    assert page_one_data["previous"] is None

    serialized = {"legacy": 0, "sku": 0}
    original_legacy_row = product_views._product_detail_row_from_legacy
    original_sku_row = product_views._product_detail_row_from_sku

    def count_legacy_row(item):
        serialized["legacy"] += 1
        return original_legacy_row(item)

    def count_sku_row(item):
        serialized["sku"] += 1
        return original_sku_row(item)

    monkeypatch.setattr(product_views, "_product_detail_row_from_legacy", count_legacy_row)
    monkeypatch.setattr(product_views, "_product_detail_row_from_sku", count_sku_row)
    page_two = client.get("/api/internal/products/details/", {"page": 2, "page_size": 2})
    assert page_two.status_code == 200
    page_two_data = page_two.json()["data"]
    assert [row["row_type"] for row in page_two_data["results"]] == ["legacy", "sku"]
    assert page_two_data["results"][1]["sku_code"] == "A-SKU-1"
    assert sum(serialized.values()) == len(page_two_data["results"]) <= 2
    assert page_two_data["previous"] and "page=1" in page_two_data["previous"]
    assert page_two_data["next"] and "page=3" in page_two_data["next"]

    clamped = client.get("/api/internal/products/details/", {"page": 99, "page_size": 2})
    assert clamped.status_code == 200
    clamped_data = clamped.json()["data"]
    assert [row["sku_code"] for row in clamped_data["results"]] == ["INACTIVE-SKU", "Z-SKU-2"]
    assert clamped_data["next"] is None
    assert clamped_data["previous"] and "page=2" in clamped_data["previous"]

    search = client.get("/api/internal/products/details/", {"search": "A-SKU-1"})
    assert search.status_code == 200
    assert search.json()["data"]["count"] == 1
    assert search.json()["data"]["results"][0]["sku_code"] == "A-SKU-1"

    active = client.get(
        "/api/internal/products/details/",
        {"sku_status": "active", "page_size": 20},
    )
    assert active.status_code == 200
    active_data = active.json()["data"]
    assert active_data["count"] == 3
    assert {row["sku_code"] for row in active_data["results"]} == {
        "LINKED-SKU", "A-SKU-1", "Z-SKU-2"
    }

    inactive_response = client.get(
        "/api/internal/products/details/",
        {"sku_status": "inactive", "page_size": 20},
    )
    assert inactive_response.status_code == 200
    inactive_data = inactive_response.json()["data"]
    assert inactive_data["count"] == 1
    assert inactive_data["results"][0]["sku_code"] == "INACTIVE-SKU"


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
