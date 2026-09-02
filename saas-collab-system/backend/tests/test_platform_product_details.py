from decimal import Decimal

import pytest
from django.urls import resolve
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.listings.models import PlatformProductDetail
from apps.listings.platform_product_details import _resolve_sku, import_platform_product_details, parse_import_rows
from apps.listings.serializers import PlatformProductDetailSerializer
from apps.listings.views import PlatformProductDetailCollectionView, PlatformProductDetailImportView
from apps.masterdata.models import CountrySiteMaster, PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductLegacyItem, ProductSKU, ProductSPU
from apps.tenants.models import Tenant

pytestmark = pytest.mark.django_db


def fixture_data():
    tenant = Tenant.objects.create(name="Detail tenant", code="detail-tenant")
    user = CustomUser.objects.create_user(username="detail-user", tenant=tenant, user_type="internal")
    platform = PlatformMaster.objects.create(tenant=tenant, code="tiktok", name="TikTok", platform_type="tiktok")
    store = StoreMaster.objects.create(tenant=tenant, platform=platform, code="shop-th", name="店铺 TH", country_code="TH", currency="THB")
    CountrySiteMaster.objects.create(tenant=tenant, code="tiktok-th", name="TikTok TH", country_code="TH", platform="tiktok")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-1", product_name="Bag")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="NEW-1", legacy_sku_code="OLD-1", purchase_price=Decimal("1"))
    return tenant, platform, store, sku


def test_import_dry_run_and_idempotent_upsert():
    tenant, platform, store, sku = fixture_data()
    csv = "平台,店铺,主商品ID,变种ID,SKU,产品名称,变种,销售状态\nTikTok,shop-th,P-1,V-1,OLD-1,Bag,Black,在售\n"
    result = import_platform_product_details(tenant=tenant, raw=csv.encode(), filename="items.csv", dry_run=True)
    assert result["valid"] == 1 and result["created"] == 0
    result = import_platform_product_details(tenant=tenant, raw=csv.encode(), filename="items.csv")
    assert result["created"] == 1
    result = import_platform_product_details(tenant=tenant, raw=csv.encode(), filename="items.csv")
    assert result["updated"] == 0
    assert result["unchanged"] == 1
    item = PlatformProductDetail.objects.get(tenant=tenant)
    assert item.internal_sku_id == sku.id and item.source_old_sku_code == "OLD-1"


def test_import_reports_row_error_for_unknown_old_sku():
    tenant, *_ = fixture_data()
    csv = "平台,店铺,主商品ID,变种ID,SKU\nTikTok,shop-th,P-1,V-1,UNKNOWN\n"
    result = import_platform_product_details(tenant=tenant, raw=csv.encode(), filename="items.csv")
    assert result["errors"] and result["errors"][0]["row"] == 2


def test_import_normalizes_sku_nfkc_format_chars_and_case_for_old_code():
    tenant, platform, store, sku = fixture_data()
    normalized_sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=sku.spu,
        sku_code="HY040-Pink-6KG-NEW",
        legacy_sku_code="HY040-Pink-6KG",
        purchase_price=Decimal("1"),
    )
    raw = (
        "platform,store_code,country_code,platform_product_id,platform_variant_id,source_old_sku_code\n"
        "tiktok,shop-th,TH,P-HY,V-H, HY040-Pink-6KG\u200b \n"
    ).encode("utf-8")
    result = import_platform_product_details(tenant=tenant, raw=raw, filename="items.csv")
    assert result["valid"] == 1 and not result["errors"]
    item = PlatformProductDetail.objects.get(tenant=tenant)
    assert item.internal_sku_id == normalized_sku.id
    assert item.source_old_sku_code == "HY040-Pink-6KG"


def test_import_prefers_new_sku_when_old_value_is_unknown():
    tenant, platform, store, sku = fixture_data()
    raw = (
        "platform,store_code,country_code,platform_product_id,platform_variant_id,source_old_sku_code,new_sku_code\n"
        "tiktok,shop-th,TH,P-NEW,V-NEW,missing-old,new-1\u200b\n"
    ).encode("utf-8")
    result = import_platform_product_details(tenant=tenant, raw=raw, filename="items.csv")
    assert result["valid"] == 1 and not result["errors"]
    item = PlatformProductDetail.objects.get(tenant=tenant)
    assert item.internal_sku_id == sku.id
    assert item.source_old_sku_code == "missing-old"


def test_import_rejects_ambiguous_normalized_old_sku_match():
    tenant, platform, store, sku = fixture_data()
    ProductSKU.objects.create(
        tenant=tenant,
        spu=sku.spu,
        sku_code="AMB-1",
        legacy_sku_code="DUP-OLD",
        purchase_price=Decimal("1"),
    )
    ProductSKU.objects.create(
        tenant=tenant,
        spu=sku.spu,
        sku_code="AMB-2",
        legacy_sku_code="dup-old",
        purchase_price=Decimal("1"),
    )
    raw = (
        "platform,store_code,country_code,platform_product_id,platform_variant_id,source_old_sku_code\n"
        "tiktok,shop-th,TH,P-DUP,V-DUP,Dup-Old\n"
    ).encode("utf-8")
    result = import_platform_product_details(tenant=tenant, raw=raw, filename="items.csv")
    assert result["valid"] == 0 and result["created"] == 0
    assert result["errors"] and "多个" in result["errors"][0]["message"]
    assert not PlatformProductDetail.objects.filter(tenant=tenant).exists()


def test_import_writes_valid_rows_and_skips_invalid_rows():
    tenant, platform, store, sku = fixture_data()
    raw = (
        "platform,store_code,country_code,platform_product_id,platform_variant_id,source_old_sku_code\n"
        "tiktok,shop-th,TH,P-VALID,V-VALID,OLD-1\n"
        "tiktok,shop-th,TH,P-INVALID,V-INVALID,UNKNOWN\n"
    ).encode("utf-8")
    result = import_platform_product_details(tenant=tenant, raw=raw, filename="items.csv")
    assert result["valid"] == 1 and result["created"] == 1
    assert result["skipped"] == 1 and result["partial_success"] is True
    assert result["errors"] and result["errors"][0]["row"] == 3
    assert PlatformProductDetail.objects.filter(tenant=tenant).count() == 1


def test_import_only_updates_changed_rows_and_counts_unchanged_rows():
    tenant, *_ = fixture_data()
    raw = (
        "platform,store_code,country_code,platform_product_id,platform_variant_id,source_old_sku_code,title\n"
        "tiktok,shop-th,TH,P-1,V-1,OLD-1,First\n"
        "tiktok,shop-th,TH,P-2,V-2,OLD-1,Second\n"
    ).encode()
    first = import_platform_product_details(tenant=tenant, raw=raw, filename="items.csv")
    assert first["created"] == 2

    changed = raw.replace(b"Second", b"Second (revised)")
    result = import_platform_product_details(tenant=tenant, raw=changed, filename="items.csv")
    assert result["updated"] == 1
    assert result["unchanged"] == 1
    assert PlatformProductDetail.objects.get(platform_variant_id="V-2").title == "Second (revised)"


def test_resolve_sku_database_fallback_normalizes_case_and_format_chars():
    tenant, platform, store, sku = fixture_data()
    assert _resolve_sku(
        tenant,
        {"source_old_sku_code": " old-1\u200b "},
    ).pk == sku.pk
    assert _resolve_sku(
        tenant,
        {"new_sku_code": " new-1\u200b "},
    ).pk == sku.pk


def test_resolve_sku_legacy_cache_keys_are_case_insensitive():
    tenant, platform, store, sku = fixture_data()
    assert _resolve_sku(
        tenant,
        {"source_old_sku_code": " old-1\u200b "},
        legacy_skus={"OLD-1": sku},
    ).pk == sku.pk
    assert _resolve_sku(
        tenant,
        {"new_sku_code": " new-1\u200b "},
        new_skus={"NEW-1": sku},
    ).pk == sku.pk


def test_parse_downloadable_template_headers():
    raw = (
        "平台,店铺,国家代码,平台商品ID,变体ID,平台SKU,旧SKU编码,标题,销售状态\n"
        "tiktok,shop-th,TH,P-1,V-1,S-1,OLD-1,示例商品,在售\n"
    ).encode("utf-8-sig")
    sheets = list(parse_import_rows(raw, filename="platform-product-details.csv"))
    assert sheets[0][1][0]["platform"] == "tiktok"
    assert sheets[0][1][0]["store_name"] == "shop-th"
    assert sheets[0][1][0]["country_code"] == "TH"
    assert sheets[0][1][0]["platform_variant_id"] == "V-1"
    assert sheets[0][1][0]["source_old_sku_code"] == "OLD-1"


def test_import_country_code_resolves_country_archive_and_serializes_code():
    tenant, *_ = fixture_data()
    raw = (
        "平台,店铺,国家代码,平台商品ID,变体ID,平台SKU,旧SKU编码\n"
        "tiktok,shop-th,th,P-1,V-1,S-1,OLD-1\n"
    ).encode("utf-8-sig")
    result = import_platform_product_details(tenant=tenant, raw=raw, filename="items.csv")
    assert result["valid"] == 1 and not result["errors"]
    item = PlatformProductDetail.objects.get(tenant=tenant)
    assert item.site.country_code == "TH"
    assert PlatformProductDetailSerializer(item).data["country_code"] == "TH"


def test_import_keeps_legacy_site_header_compatible():
    tenant, *_ = fixture_data()
    raw = (
        "平台,店铺,站点,平台商品ID,变体ID,平台SKU,旧SKU编码\n"
        "tiktok,shop-th,tiktok-th,P-1,V-1,S-1,OLD-1\n"
    ).encode("utf-8-sig")
    result = import_platform_product_details(tenant=tenant, raw=raw, filename="items.csv")
    assert result["valid"] == 1 and not result["errors"]
    assert PlatformProductDetail.objects.get(tenant=tenant).site.code == "tiktok-th"


def test_platform_product_detail_api_routes_are_registered():
    collection = resolve("/api/internal/listings/product-details/")
    importer = resolve("/api/internal/listings/product-details/import/")
    assert collection.func.view_class is PlatformProductDetailCollectionView
    assert importer.func.view_class is PlatformProductDetailImportView


def test_platform_product_detail_collection_is_paginated():
    tenant, platform, store, sku = fixture_data()
    site = CountrySiteMaster.objects.get(tenant=tenant, country_code="TH")
    for variant_id in ("V-1", "V-2"):
        PlatformProductDetail.objects.create(
            tenant=tenant,
            platform=platform,
            store=store,
            site=site,
            platform_product_id=f"P-{variant_id}",
            platform_variant_id=variant_id,
            internal_sku=sku,
        )

    role = Role.objects.create(tenant=tenant, code="detail-view", name="Detail view")
    role.permissions.add(Permission.objects.get(code="listings.product_detail.view"))
    UserRole.objects.create(tenant=tenant, user=CustomUser.objects.get(username="detail-user"), role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})

    client = APIClient()
    client.force_authenticate(user=CustomUser.objects.get(username="detail-user"))
    response = client.get("/api/internal/listings/product-details/", {"page": 1, "page_size": 1})
    assert response.status_code == 200
    assert response.json()["data"]["count"] == 2
    assert len(response.json()["data"]["results"]) == 1
    assert response.json()["data"]["next"]

    too_large = client.get("/api/internal/listings/product-details/", {"page_size": 101})
    assert too_large.status_code == 400


def _grant_detail_manage(user, tenant):
    role = Role.objects.create(tenant=tenant, code=f"{user.username}-manage", name="Detail manage")
    role.permissions.add(Permission.objects.get(code="listings.product_detail.manage"))
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})


def test_platform_product_detail_edit_and_bulk_update_by_spu_are_tenant_scoped():
    tenant, platform, store, sku = fixture_data()
    sku.spu.legacy_spu_code = "OLD-SPU"; sku.spu.save(update_fields=["legacy_spu_code"])
    user = CustomUser.objects.get(username="detail-user")
    _grant_detail_manage(user, tenant)
    detail = PlatformProductDetail.objects.create(
        tenant=tenant, platform=platform, store=store,
        platform_variant_id="V-EDIT", platform_product_id="P-EDIT", platform_sku="P-SKU",
        source_old_sku_code="OLD-1", internal_sku=sku, title="Before", sales_status="在售",
    )
    client = APIClient(); client.force_authenticate(user=user)
    edited = client.patch(
        f"/api/internal/listings/product-details/{detail.pk}/",
        {"title": "After", "platform_variant_id": "V-EDIT-2"}, format="json",
    )
    assert edited.status_code == 200
    detail.refresh_from_db(); assert detail.title == "After" and detail.platform_variant_id == "V-EDIT-2"

    preview = client.post("/api/internal/listings/product-details/bulk-update/", {
        "match_type": "new_spu", "spu_code": "SPU-1", "fields": {"sales_status": "停售"}, "preview": True,
    }, format="json")
    assert preview.status_code == 200 and preview.json()["data"]["matched"] == 1
    result = client.post("/api/internal/listings/product-details/bulk-update/", {
        "match_type": "old_spu", "spu_code": "OLD-SPU", "fields": {"sales_status": "停售"},
    }, format="json")
    assert result.status_code == 200 and result.json()["data"]["matched"] == 1
    detail.refresh_from_db(); assert detail.sales_status == "停售"

    missing = client.post("/api/internal/listings/product-details/bulk-update/", {
        "match_type": "old_spu", "spu_code": "MISSING", "fields": {"sales_status": "在售"},
    }, format="json")
    assert missing.status_code == 200 and missing.json()["data"]["matched"] == 0
    detail.refresh_from_db(); assert detail.sales_status == "停售"

def test_platform_old_spu_bulk_matches_unlinked_legacy_sku_only():
    tenant, platform, store, _sku = fixture_data()
    user = CustomUser.objects.get(username="detail-user")
    _grant_detail_manage(user, tenant)
    ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_spu_code="OLD-SPU-ORPHAN",
        legacy_sku_code="LEGACY-SKU-1",
        product_name="Legacy orphan",
    )
    linked_by_legacy_row = PlatformProductDetail.objects.create(
        tenant=tenant,
        platform=platform,
        store=store,
        platform_variant_id="V-ORPHAN-1",
        source_old_sku_code="LEGACY-SKU-1",
        title="Should match",
    )
    # Comparing source_old_sku_code directly to the SPU code would
    # incorrectly include this row because it has no legacy mapping.
    unlinked_wrong_match = PlatformProductDetail.objects.create(
        tenant=tenant,
        platform=platform,
        store=store,
        platform_variant_id="V-ORPHAN-2",
        source_old_sku_code="OLD-SPU-ORPHAN",
        title="Should not match",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.post(
        "/api/internal/listings/product-details/bulk-update/",
        {
            "match_type": "old_spu",
            "spu_code": "OLD-SPU-ORPHAN",
            "fields": {"title": "Updated"},
            "preview": True,
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["data"]["matched"] == 1
    linked_by_legacy_row.refresh_from_db()
    unlinked_wrong_match.refresh_from_db()
    assert linked_by_legacy_row.title == "Should match"
    assert unlinked_wrong_match.title == "Should not match"
