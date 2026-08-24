import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductCategory, ProductLegacyItem, ProductSKU, ProductSPU
from apps.tenants.models import Tenant


def _user(tenant, username):
    user = CustomUser.objects.create_user(username=username, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    role = Role.objects.create(tenant=tenant, code=f"{username}-role", name="Product detail role")
    role.permissions.add(*Permission.objects.filter(code__in=["products.master.view", "products.master.manage"]))
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    return user


@pytest.mark.django_db
def test_product_detail_rows_keep_sku_name_separate_from_spu_and_map_status():
    tenant = Tenant.objects.create(name="Detail tenant", code="detail-tenant")
    user = _user(tenant, "detail-user")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-DETAIL", product_name="SPU base name")
    sku = ProductSKU.objects.create(
        tenant=tenant, spu=spu, sku_code="SKU-DETAIL", product_name="SKU variant name", is_active=False,
    )
    ProductLegacyItem.objects.create(
        tenant=tenant, legacy_spu_code="OLD-SPU", legacy_sku_code="OLD-SKU", product_name="Imported SKU name",
        status=ProductLegacyItem.Status.GENERATED, generated_spu=spu, generated_sku=sku,
    )
    response = APIClient()
    response.force_authenticate(user=user)

    payload = response.get("/api/internal/products/details/").json()["data"]
    row = next(item for item in payload["results"] if item["row_type"] == "legacy")
    assert row["sku_product_name"] == "SKU variant name"
    assert row["spu_product_name"] == "SPU base name"
    assert row["sku_id"] == sku.id
    assert row["sku_status_name"] == "下架"

    active = response.get("/api/internal/products/details/?sku_status=active").json()["data"]
    assert active["results"] == []


@pytest.mark.django_db
def test_product_detail_physical_fields_keep_legacy_and_sku_sources_separate():
    tenant = Tenant.objects.create(name="Physical tenant", code="physical-tenant")
    user = _user(tenant, "physical-user")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-PHYSICAL", product_name="Physical SPU")
    linked_sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="SKU-LINKED",
        product_name="Linked SKU",
        package_weight="9.999",
        package_volume="0.999999",
        package_length_cm="99.999",
        package_width_cm="88.888",
        package_height_cm="77.777",
        origin_country="US",
        hs_code="9999.99",
    )
    ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_spu_code="OLD-PHYSICAL",
        legacy_sku_code="OLD-LINKED",
        product_name="Imported linked SKU",
        status=ProductLegacyItem.Status.GENERATED,
        generated_spu=spu,
        generated_sku=linked_sku,
        package_weight="1.200",
        package_volume="0.030000",
        package_length_cm="10.000",
        package_width_cm="20.500",
        package_height_cm="30.250",
        origin_country="CN",
        hs_code="6203.42",
    )
    standalone_sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="SKU-STANDALONE",
        product_name="Standalone SKU",
        package_weight="2.500",
        package_volume="0.012345",
        package_length_cm="11.100",
        package_width_cm="22.200",
        package_height_cm="33.300",
        origin_country="VN",
        hs_code="9403.20",
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/internal/products/details/")
    assert response.status_code == 200
    rows = response.json()["data"]["results"]
    legacy = next(item for item in rows if item["row_type"] == "legacy")
    standalone = next(item for item in rows if item.get("sku_id") == standalone_sku.id)

    assert legacy["package_weight"] == "1.200"
    assert legacy["package_volume"] == "0.030000"
    assert legacy["package_length_cm"] == "10.000"
    assert legacy["package_width_cm"] == "20.500"
    assert legacy["package_height_cm"] == "30.250"
    assert legacy["origin_country"] == "CN"
    assert legacy["hs_code"] == "6203.42"
    assert standalone["package_weight"] == "2.500"
    assert standalone["package_volume"] == "0.012345"
    assert standalone["package_length_cm"] == "11.100"
    assert standalone["package_width_cm"] == "22.200"
    assert standalone["package_height_cm"] == "33.300"
    assert standalone["origin_country"] == "VN"
    assert standalone["hs_code"] == "9403.20"


@pytest.mark.django_db
def test_legacy_import_is_incremental_and_idempotent():
    tenant = Tenant.objects.create(name="Import tenant", code="import-tenant")
    user = _user(tenant, "import-user")
    client = APIClient()
    client.force_authenticate(user=user)
    csv = "旧SPU编码,旧SKU编码,商品名称\nOLD-SPU,OLD-SKU,First SKU\n"

    created = client.post("/api/internal/products/legacy-items/", {"csv_text": csv}, format="json").json()["data"]
    assert (created["created"], created["updated"], created["unchanged"]) == (1, 0, 0)
    unchanged = client.post("/api/internal/products/legacy-items/", {"csv_text": csv}, format="json").json()["data"]
    assert (unchanged["created"], unchanged["updated"], unchanged["unchanged"]) == (0, 0, 1)

    changed = client.post(
        "/api/internal/products/legacy-items/",
        {"csv_text": csv.replace("First SKU", "Updated SKU")},
        format="json",
    ).json()["data"]
    assert (changed["created"], changed["updated"], changed["unchanged"]) == (0, 1, 0)
    assert ProductLegacyItem.objects.get(tenant=tenant, legacy_sku_code="OLD-SKU").product_name == "Updated SKU"


@pytest.mark.django_db
def test_generated_legacy_import_does_not_change_variant_identity():
    tenant = Tenant.objects.create(name="Generated tenant", code="generated-tenant")
    user = _user(tenant, "generated-user")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-GENERATED", product_name="SPU")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SKU-GENERATED", product_name="SKU", color_code="blue")
    ProductLegacyItem.objects.create(
        tenant=tenant, legacy_sku_code="OLD-GENERATED", product_name="SKU", color_code="blue",
        status=ProductLegacyItem.Status.GENERATED, generated_spu=spu, generated_sku=sku,
    )
    client = APIClient()
    client.force_authenticate(user=user)

    result = client.post(
        "/api/internal/products/legacy-items/",
        {"csv_text": "旧SKU编码,商品名称,颜色英文编码\nOLD-GENERATED,Changed SKU,red\n"},
        format="json",
    ).json()["data"]
    assert result["skipped"] == 1
    assert result["updated"] == 0
    assert result["unchanged"] == 0
    assert result["processed"] == 1
    assert "颜色" in result["errors"][0]["message"]
    item = ProductLegacyItem.objects.get(tenant=tenant, legacy_sku_code="OLD-GENERATED")
    assert item.color_code == "blue"
    assert item.product_name == "SKU"


@pytest.mark.django_db
def test_product_detail_bulk_update_by_old_spu_is_safe_and_idempotent():
    tenant = Tenant.objects.create(name="Bulk tenant", code="bulk-tenant")
    user = _user(tenant, "bulk-user")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-NEW", legacy_spu_code="SPU-OLD", product_name="SPU")
    sku = ProductSKU.objects.create(
        tenant=tenant, spu=spu, sku_code="SKU-NEW", legacy_sku_code="SKU-OLD", product_name="Old name", purchase_price="3.0000",
    )
    ProductLegacyItem.objects.create(
        tenant=tenant, legacy_spu_code="SPU-OLD", legacy_sku_code="SKU-OLD", product_name="Old name",
        purchase_price="3.0000", status=ProductLegacyItem.Status.GENERATED, generated_spu=spu, generated_sku=sku,
    )
    client = APIClient(); client.force_authenticate(user=user)

    preview = client.post("/api/internal/products/details/bulk-update/", {
        "match_type": "old_spu", "spu_code": "SPU-OLD", "fields": {"product_name": "Bulk name"}, "preview": True,
    }, format="json").json()["data"]
    assert preview["matched"] == 1

    result = client.post("/api/internal/products/details/bulk-update/", {
        "match_type": "old_spu", "spu_code": "SPU-OLD", "fields": {
            "product_name": "Bulk name", "purchase_price": "4.5000", "is_active": False,
        },
    }, format="json").json()["data"]
    assert (result["matched"], result["updated"], result["unchanged"], result["errors"]) == (1, 1, 0, [])
    sku.refresh_from_db(); assert sku.product_name == "Bulk name" and str(sku.purchase_price) == "4.5000" and sku.is_active is False

    repeated = client.post("/api/internal/products/details/bulk-update/", {
        "match_type": "new_spu", "spu_code": "SPU-NEW", "fields": {
            "product_name": "Bulk name", "purchase_price": "4.5000", "is_active": False,
        },
    }, format="json").json()["data"]
    assert (repeated["updated"], repeated["unchanged"], repeated["errors"]) == (0, 1, [])


@pytest.mark.django_db
def test_product_detail_bulk_update_does_not_cross_tenant_or_overwrite_empty_values():
    tenant_a = Tenant.objects.create(name="Bulk A", code="bulk-a")
    tenant_b = Tenant.objects.create(name="Bulk B", code="bulk-b")
    user_a = _user(tenant_a, "bulk-a-user")
    user_b = _user(tenant_b, "bulk-b-user")
    spu = ProductSPU.objects.create(tenant=tenant_a, spu_code="A-SPU", product_name="A SPU")
    sku = ProductSKU.objects.create(tenant=tenant_a, spu=spu, sku_code="A-SKU", product_name="Keep", purchase_price="2.0000")
    client = APIClient(); client.force_authenticate(user=user_b)
    cross = client.post("/api/internal/products/details/bulk-update/", {
        "match_type": "new_spu", "spu_code": "A-SPU", "fields": {"product_name": "Should not cross tenant"},
    }, format="json").json()["data"]
    assert cross["matched"] == 0
    client.force_authenticate(user=user_a)
    empty = client.post("/api/internal/products/details/bulk-update/", {
        "match_type": "new_spu", "spu_code": "A-SPU", "fields": {"product_name": "", "purchase_price": None},
    }, format="json").json()["data"]
    assert empty["unchanged"] == 1
    sku.refresh_from_db(); assert sku.product_name == "Keep" and str(sku.purchase_price) == "2.0000"


@pytest.mark.django_db
def test_product_detail_bulk_category_requires_active_coding_category_and_tenant():
    tenant = Tenant.objects.create(name="Category bulk tenant", code="category-bulk-tenant")
    foreign_tenant = Tenant.objects.create(name="Foreign category tenant", code="foreign-category-tenant")
    user = _user(tenant, "category-bulk-user")
    foreign_user = _user(foreign_tenant, "foreign-category-user")
    l1 = ProductCategory.objects.create(tenant=tenant, level=ProductCategory.Level.L1, code="1", name="Root")
    l2 = ProductCategory.objects.create(tenant=tenant, parent=l1, level=ProductCategory.Level.L2, code="01", name="Leaf")
    inactive = ProductCategory.objects.create(
        tenant=tenant, parent=l1, level=ProductCategory.Level.L2, code="02", name="Inactive", is_active=False,
    )
    foreign_l1 = ProductCategory.objects.create(
        tenant=foreign_tenant, level=ProductCategory.Level.L1, code="1", name="Foreign root",
    )
    foreign_l2 = ProductCategory.objects.create(
        tenant=foreign_tenant, parent=foreign_l1, level=ProductCategory.Level.L2, code="01", name="Foreign leaf",
    )
    ProductLegacyItem.objects.create(
        tenant=tenant, legacy_spu_code="CATEGORY-OLD", legacy_sku_code="CATEGORY-SKU", product_name="Pending",
    )
    client = APIClient(); client.force_authenticate(user=user)

    for category_id in (l1.id, inactive.id, foreign_l2.id):
        response = client.post("/api/internal/products/details/bulk-update/", {
            "match_type": "old_spu", "spu_code": "CATEGORY-OLD",
            "fields": {"category_node": category_id},
        }, format="json")
        assert response.status_code == 400

    valid = client.post("/api/internal/products/details/bulk-update/", {
        "match_type": "old_spu", "spu_code": "CATEGORY-OLD",
        "fields": {"category_node": l2.id},
    }, format="json")
    assert valid.status_code == 200
    assert valid.json()["data"]["updated"] == 1
    assert ProductLegacyItem.objects.get(tenant=tenant, legacy_sku_code="CATEGORY-SKU").category_node_id == l2.id

    client.force_authenticate(user=foreign_user)
    cross = client.post("/api/internal/products/details/bulk-update/", {
        "match_type": "old_spu", "spu_code": "CATEGORY-OLD",
        "fields": {"category_node": l2.id},
    }, format="json")
    assert cross.status_code == 400


@pytest.mark.django_db
def test_product_detail_bulk_extended_fields_validate_preview_and_explicit_clear():
    tenant = Tenant.objects.create(name="Extended bulk tenant", code="extended-bulk-tenant")
    user = _user(tenant, "extended-bulk-user")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="EXT-SPU", legacy_spu_code="EXT-OLD", product_name="SPU")
    sku = ProductSKU.objects.create(
        tenant=tenant, spu=spu, sku_code="EXT-SKU", product_name="SKU",
        package_weight="1.000", package_volume="0.010000", package_length_cm="10.000",
        package_width_cm="20.000", package_height_cm="30.000", origin_country="CN", hs_code="6203.42",
    )
    ProductLegacyItem.objects.create(
        tenant=tenant, legacy_spu_code="EXT-OLD", legacy_sku_code="EXT-LEGACY", product_name="SKU",
        status=ProductLegacyItem.Status.GENERATED, generated_spu=spu, generated_sku=sku,
        package_weight="1.000", package_volume="0.010000", package_length_cm="10.000",
        package_width_cm="20.000", package_height_cm="30.000", origin_country="CN", hs_code="6203.42",
    )
    client = APIClient(); client.force_authenticate(user=user)

    preview = client.post("/api/internal/products/details/bulk-update/", {
        "match_type": "old_spu", "spu_code": "EXT-OLD", "preview": True,
        "fields": {"package_weight": "9.999", "origin_country": "US", "hs_code": "9403.20"},
    }, format="json")
    assert preview.status_code == 200
    assert preview.json()["data"]["matched"] == 1
    sku.refresh_from_db()
    assert str(sku.package_weight) == "1.000" and sku.origin_country == "CN"

    updated = client.post("/api/internal/products/details/bulk-update/", {
        "match_type": "old_spu", "spu_code": "EXT-OLD",
        "fields": {
            "package_weight": "9.999", "package_volume": "0.123456", "package_length_cm": "11.111",
            "package_width_cm": "22.222", "package_height_cm": "33.333", "origin_country": "US", "hs_code": "9403.20",
        },
    }, format="json")
    assert updated.status_code == 200
    assert updated.json()["data"]["updated"] == 1
    sku.refresh_from_db()
    assert str(sku.package_weight) == "9.999" and str(sku.package_volume) == "0.123456"
    assert sku.origin_country == "US" and sku.hs_code == "9403.20"

    cleared = client.post("/api/internal/products/details/bulk-update/", {
        "match_type": "new_spu", "spu_code": "EXT-SPU",
        "clear_fields": ["package_weight", "package_volume", "package_length_cm", "package_width_cm", "package_height_cm", "origin_country", "hs_code"],
    }, format="json")
    assert cleared.status_code == 200
    assert cleared.json()["data"]["updated"] == 1
    sku.refresh_from_db()
    assert all(getattr(sku, field) is None for field in (
        "package_weight", "package_volume", "package_length_cm", "package_width_cm", "package_height_cm", "origin_country", "hs_code",
    ))

    for fields in (
        {"package_weight": "1.2345"},
        {"package_volume": "1.1234567"},
        {"origin_country": "X" * 81},
        {"hs_code": "X" * 21},
    ):
        invalid = client.post("/api/internal/products/details/bulk-update/", {
            "match_type": "new_spu", "spu_code": "EXT-SPU", "fields": fields,
        }, format="json")
        assert invalid.status_code == 400
