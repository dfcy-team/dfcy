import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.files.models import AttachmentFile
from apps.products.models import ProductCategory, ProductLegacyItem, ProductSKU, ProductSPU
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


def _user(tenant, username):
    user = CustomUser.objects.create_user(username=username, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    role = Role.objects.create(tenant=tenant, code=f"{username}-role", name="Product role")
    role.permissions.add(*Permission.objects.filter(code__in=["products.master.view", "products.master.manage"]))
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    return user


def _category(tenant):
    l1 = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="Home")
    return ProductCategory.objects.create(tenant=tenant, parent=l1, level=2, code="01", name="Storage")


@pytest.mark.django_db
def test_sku_detail_fields_are_nullable_and_patchable_without_changing_name():
    tenant = Tenant.objects.create(name="Detail tenant", code="detail")
    user = _user(tenant, "detail-user")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-DETAIL", product_name="完整商品名称")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SKU-DETAIL")
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.patch(
        f"/api/internal/products/skus/{sku.id}/",
        {
            "product_name": "SKU detail name",
            "unit": "件",
            "package_weight": "12.500",
            "package_volume": "0.020",
            "package_length_cm": "20",
            "package_width_cm": "10",
            "package_height_cm": "5",
            "origin_country": "CN",
            "hs_code": "940360",
            "product_description": "商品描述",
            "image_url": "https://cdn.example.test/product.png",
        },
        format="json",
    )
    assert response.status_code == 200
    sku.refresh_from_db()
    assert sku.package_weight == 12.5
    assert sku.hs_code == "940360"
    assert sku.product_name == "SKU detail name"
    assert sku.spu.product_name == "完整商品名称"


@pytest.mark.django_db
def test_product_sales_status_has_chinese_display_and_api_value_is_preserved():
    tenant = Tenant.objects.create(name="Status tenant", code="status")
    user = _user(tenant, "status-user")
    ProductSPU.objects.create(tenant=tenant, spu_code="SPU-STATUS", product_name="Status", sales_status=ProductSPU.SalesStatus.PAUSED)
    client = APIClient()
    client.force_authenticate(user=user)
    payload = client.get("/api/internal/products/spus/").json()["data"]["results"][0]
    assert payload["sales_status"] == "paused"
    assert payload["sales_status_display"] == "已暂停"


@pytest.mark.django_db
def test_spu_list_includes_all_tenant_sku_links_in_spu_payload():
    tenant = Tenant.objects.create(name="SPU links tenant", code="spu-links")
    user = _user(tenant, "spu-links-user")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-LINKS", product_name="Linked product")
    ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SKU-LINK-001")
    ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SKU-LINK-002")
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/internal/products/spus/", {"page": 1, "page_size": 1})

    assert response.status_code == 200
    payload = response.json()["data"]["results"][0]
    assert payload["sku_codes"] == ["SKU-LINK-001", "SKU-LINK-002"]
    assert payload["sku_count"] == 2


@pytest.mark.django_db
def test_sku_image_upload_validates_content_and_is_tenant_scoped(tmp_path):
    tenant = Tenant.objects.create(name="Image tenant", code="image")
    other_tenant = Tenant.objects.create(name="Other image tenant", code="image-other")
    user = _user(tenant, "image-user")
    other_user = _user(other_tenant, "other-image-user")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-IMAGE", product_name="Image")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SKU-IMAGE")
    client = APIClient()
    client.force_authenticate(user=user)
    # Minimal valid PNG signature plus IHDR bytes is sufficient for the
    # service's extension/MIME/magic validation.
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    with override_settings(MEDIA_ROOT=tmp_path):
        response = client.post(
            f"/api/internal/products/skus/{sku.id}/image/",
            {"file": SimpleUploadedFile("product.png", png, content_type="image/png")},
            format="multipart",
        )
        assert response.status_code == 200
        sku.refresh_from_db()
        assert sku.image_url.startswith("/media/product-images/tenant-")
        assert AttachmentFile.objects.filter(tenant=tenant, business_id=str(sku.id)).exists()
        invalid = client.post(
            f"/api/internal/products/skus/{sku.id}/image/",
            {"file": SimpleUploadedFile("product.exe", b"MZ", content_type="application/octet-stream")},
            format="multipart",
        )
        assert invalid.status_code == 400
        cross = APIClient()
        cross.force_authenticate(user=other_user)
        assert cross.delete(f"/api/internal/products/skus/{sku.id}/image/").status_code == 404


@pytest.mark.django_db
def test_legacy_item_extended_values_copy_to_generated_sku():
    tenant = Tenant.objects.create(name="Legacy detail tenant", code="legacy-detail")
    user = _user(tenant, "legacy-detail-user")
    category = _category(tenant)
    item = ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_spu_code="OLD-SPU",
        legacy_sku_code="OLD-SKU",
        product_name="完整商品名称 红色",
        category_node=category,
        attribute_code="0",
        color_code="red",
        unit="件",
        package_weight="10.000",
        package_volume="0.010",
        package_length_cm="20",
        package_width_cm="10",
        package_height_cm="5",
        origin_country="CN",
        hs_code="940360",
        image_url="https://cdn.example.test/item.png",
        product_description="legacy detail",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.post(f"/api/internal/products/legacy-items/{item.id}/generate/", format="json")
    assert response.status_code == 200
    item.refresh_from_db()
    sku = ProductSKU.objects.get(pk=item.generated_sku_id)
    assert sku.package_weight == 10
    assert sku.package_length_cm == 20
    assert sku.image_url == "https://cdn.example.test/item.png"
    assert sku.product_name == "完整商品名称 红色"
    # Legacy generation must not rewrite the SPU name from a variant row.
    assert sku.spu.product_name == "完整商品名称 红色"


@pytest.mark.django_db
def test_spu_name_patch_does_not_overwrite_independent_sku_or_legacy_names():
    tenant = Tenant.objects.create(name="Independent name tenant", code="independent-name")
    user = _user(tenant, "independent-name-user")
    spu = ProductSPU.objects.create(
        tenant=tenant,
        spu_code="SPU-INDEPENDENT-NAME",
        product_name="SPU base name",
    )
    sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="SKU-INDEPENDENT-NAME",
        legacy_sku_code="OLD-INDEPENDENT-NAME",
        product_name="SKU variant name",
    )
    legacy = ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_spu_code="OLD-SPU-INDEPENDENT-NAME",
        legacy_sku_code="OLD-INDEPENDENT-NAME",
        product_name="Legacy imported variant name",
        generated_spu=spu,
        generated_sku=sku,
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.patch(
        f"/api/internal/products/spus/{spu.id}/",
        {"product_name": "Renamed SPU base"},
        format="json",
    )

    assert response.status_code == 200
    spu.refresh_from_db()
    sku.refresh_from_db()
    legacy.refresh_from_db()
    assert spu.product_name == "Renamed SPU base"
    assert sku.product_name == "SKU variant name"
    assert legacy.product_name == "Legacy imported variant name"


@pytest.mark.django_db
def test_generated_legacy_patch_updates_existing_sku_without_allocating_new_code():
    tenant = Tenant.objects.create(name="Generated patch tenant", code="generated-patch")
    user = _user(tenant, "generated-patch-user")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-GENERATED-PATCH", product_name="SPU")
    sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="SKU-GENERATED-PATCH",
        legacy_sku_code="OLD-GENERATED-PATCH",
        product_name="SKU old name",
    )
    legacy = ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_spu_code="OLD-SPU-GENERATED-PATCH",
        legacy_sku_code="OLD-GENERATED-PATCH",
        product_name="Legacy old name",
        purchase_price="1.0000",
        generated_spu=spu,
        generated_sku=sku,
        status=ProductLegacyItem.Status.GENERATED,
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.patch(
        f"/api/internal/products/legacy-items/{legacy.id}/",
        {
            "legacy_sku_code": "OLD-GENERATED-PATCH-EDITED",
            "product_name": "Legacy edited name",
            "purchase_price": "2.5000",
            "product_description": "edited detail",
        },
        format="json",
    )

    assert response.status_code == 200
    legacy.refresh_from_db()
    sku.refresh_from_db()
    assert legacy.status == ProductLegacyItem.Status.GENERATED
    assert legacy.generated_sku_id == sku.id
    assert sku.sku_code == "SKU-GENERATED-PATCH"
    assert sku.legacy_sku_code == "OLD-GENERATED-PATCH-EDITED"
    assert sku.product_name == "Legacy edited name"
    assert sku.purchase_price == 2.5
    assert sku.product_description == "edited detail"
