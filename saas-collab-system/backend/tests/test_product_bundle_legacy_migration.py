import pytest

from apps.accounts.models import CustomUser
from apps.products.bundle_services import confirm_legacy_migration, parse_legacy_bundle_file, preview_legacy_migration
from apps.products.models import ProductBundleComponent, ProductSKU, ProductSPU
from apps.tenants.models import Tenant


def test_parse_bigseller_wide_csv_expands_all_component_columns():
    raw = (
        "旧组合SKU编号,组合商品名称,Image URL,单品SKU1,SKU1 名称,SKU1 数量,"
        "SKU1成本价分摊比,SKU1参考成本价,单品SKU2,SKU2 名称,SKU2 数量\n"
        "BUNDLE-NO-ZH,测试组合,https://example.com/a.jpg,PART-1,单品一,2,1,0,PART-2,单品二,3\n"
    ).encode("utf-8-sig")

    rows = parse_legacy_bundle_file(raw, "组合商品.csv")

    assert [(row["legacy_component_sku"], row["quantity"]) for row in rows] == [("PART-1", "2"), ("PART-2", "3")]
    assert {row["legacy_bundle_sku"] for row in rows} == {"BUNDLE-NO-ZH"}
    assert all(row["legacy_bundle_spu"] == "" for row in rows)


@pytest.mark.django_db
def test_preview_derives_spu_and_matches_current_or_legacy_sku_without_zh_prefix():
    tenant = Tenant.objects.create(name="Bundle migration", code="bundle-migration")
    actor = CustomUser.objects.create_user(username="bundle-migration-user", tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    bundle_spu = ProductSPU.objects.create(tenant=tenant, spu_code="CURRENT-SPU", legacy_spu_code="OLD-SPU", product_name="Old bundle")
    bundle = ProductSKU.objects.create(tenant=tenant, spu=bundle_spu, sku_code="BUNDLE-NO-ZH", product_name="Old bundle")
    component_spu = ProductSPU.objects.create(tenant=tenant, spu_code="PART-SPU", product_name="Part")
    component = ProductSKU.objects.create(tenant=tenant, spu=component_spu, sku_code="CURRENT-PART", legacy_sku_code="OLD-PART")

    _token, batch = preview_legacy_migration(tenant=tenant, actor=actor, rows=[{
        "line": 2,
        "legacy_bundle_spu": "",
        "legacy_bundle_sku": "BUNDLE-NO-ZH",
        "legacy_component_sku": "OLD-PART",
        "quantity": 2,
    }])

    assert batch.preview_summary["error_count"] == 0
    assert batch.preview_summary["bundles_ready"] == 1
    assert batch.preview_summary["rows"][0]["legacy_bundle_spu"] == "OLD-SPU"
    assert batch.normalized_rows[0]["bundle_sku_id"] == bundle.id
    assert batch.normalized_rows[0]["components"] == [{"component_sku_id": component.id, "quantity": 2}]


@pytest.mark.django_db
def test_preview_reports_not_found_and_multiple_match_counts_separately():
    tenant = Tenant.objects.create(name="Bundle blockers", code="bundle-blockers")
    actor = CustomUser.objects.create_user(username="bundle-blocker-user", tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    bundle_spu = ProductSPU.objects.create(tenant=tenant, spu_code="BUNDLE-SPU", product_name="Bundle")
    ProductSKU.objects.create(tenant=tenant, spu=bundle_spu, sku_code="BUNDLE-1", product_name="Bundle")
    duplicate_spu = ProductSPU.objects.create(tenant=tenant, spu_code="DUPLICATE-SPU", product_name="Duplicate")
    ProductSKU.objects.create(tenant=tenant, spu=duplicate_spu, sku_code="DUPLICATE-A", legacy_sku_code="OLD-DUP")
    ProductSKU.objects.create(tenant=tenant, spu=duplicate_spu, sku_code="DUPLICATE-B", legacy_sku_code="OLD-DUP")

    _token, batch = preview_legacy_migration(tenant=tenant, actor=actor, rows=[
        {"line": 2, "legacy_bundle_spu": "", "legacy_bundle_sku": "MISSING-BUNDLE", "legacy_component_sku": "MISSING-PART", "quantity": 1},
        {"line": 3, "legacy_bundle_spu": "", "legacy_bundle_sku": "BUNDLE-1", "legacy_component_sku": "OLD-DUP", "quantity": 1},
    ])

    assert batch.preview_summary["error_count"] == 2
    assert batch.preview_summary["error_breakdown"] == {
        "bundle_not_unique:not_found": 1,
        "component_not_unique:multiple_matches": 1,
    }
    assert batch.preview_summary["errors"] == [
        {"line": 2, "legacy_bundle_sku": "MISSING-BUNDLE", "code": "bundle_not_unique", "match_reason": "not_found", "match_count": 0},
        {"line": 3, "legacy_bundle_sku": "BUNDLE-1", "legacy_component_sku": "OLD-DUP", "code": "component_not_unique", "match_reason": "multiple_matches", "match_count": 2},
    ]
    assert batch.preview_summary["rejected_rows"] == [
        {"line": 2, "legacy_bundle_spu": "", "legacy_bundle_sku": "MISSING-BUNDLE", "legacy_component_sku": "MISSING-PART", "quantity": 1, "code": "bundle_not_unique", "match_reason": "not_found", "match_count": 0},
        {"line": 3, "legacy_bundle_spu": "BUNDLE-SPU", "legacy_bundle_sku": "BUNDLE-1", "legacy_component_sku": "OLD-DUP", "quantity": 1, "code": "component_not_unique", "match_reason": "multiple_matches", "match_count": 2},
    ]


@pytest.mark.django_db
def test_preview_bundle_error_uses_first_source_line_for_group():
    tenant = Tenant.objects.create(name="Bundle line", code="bundle-line")
    actor = CustomUser.objects.create_user(username="bundle-line-user", tenant=tenant, user_type=CustomUser.UserType.INTERNAL)

    _token, batch = preview_legacy_migration(tenant=tenant, actor=actor, rows=[
        {"line": 18, "legacy_bundle_spu": "", "legacy_bundle_sku": "MISSING-BUNDLE", "legacy_component_sku": "PART-1", "quantity": 1},
        {"line": 19, "legacy_bundle_spu": "", "legacy_bundle_sku": "MISSING-BUNDLE", "legacy_component_sku": "PART-2", "quantity": 1},
    ])

    assert batch.preview_summary["errors"][0]["line"] == 18


@pytest.mark.django_db
def test_confirm_migrates_ready_bundles_and_keeps_blocked_rows_skipped():
    tenant = Tenant.objects.create(name="Partial bundle", code="partial-bundle")
    actor = CustomUser.objects.create_user(username="partial-bundle-user", tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    bundle_spu = ProductSPU.objects.create(tenant=tenant, spu_code="BUNDLE-SPU", product_name="Bundle")
    bundle = ProductSKU.objects.create(tenant=tenant, spu=bundle_spu, sku_code="READY-BUNDLE", product_name="Bundle")
    component_spu = ProductSPU.objects.create(tenant=tenant, spu_code="PART-SPU", product_name="Part")
    component = ProductSKU.objects.create(tenant=tenant, spu=component_spu, sku_code="READY-PART", product_name="Part")

    token, batch = preview_legacy_migration(tenant=tenant, actor=actor, rows=[
        {"line": 2, "legacy_bundle_spu": "", "legacy_bundle_sku": "READY-BUNDLE", "legacy_component_sku": "READY-PART", "quantity": 2, "image_url": "https://example.com/bundle.jpg"},
        {"line": 3, "legacy_bundle_spu": "", "legacy_bundle_sku": "MISSING-BUNDLE", "legacy_component_sku": "READY-PART", "quantity": 1},
    ])

    assert batch.preview_summary["bundles_ready"] == 1
    assert batch.preview_summary["error_count"] == 1

    confirmed = confirm_legacy_migration(tenant=tenant, actor=actor, token=token)

    assert confirmed.preview_summary["migrated"] == 1
    assert confirmed.preview_summary["skipped_errors"] == 1
    assert ProductBundleComponent.objects.get(bundle_sku=bundle, component_sku=component).quantity == 2
    bundle.refresh_from_db()
    assert bundle.image_url == "https://example.com/bundle.jpg"


@pytest.mark.django_db
def test_confirm_skips_bundle_that_would_become_nested_and_migrates_independent_bundle():
    tenant = Tenant.objects.create(name="Nested bundle", code="nested-bundle")
    actor = CustomUser.objects.create_user(username="nested-bundle-user", tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    parent_spu = ProductSPU.objects.create(tenant=tenant, spu_code="PARENT-SPU", product_name="Parent")
    parent = ProductSKU.objects.create(tenant=tenant, spu=parent_spu, sku_code="PARENT", product_name="Parent")
    child_spu = ProductSPU.objects.create(tenant=tenant, spu_code="CHILD-SPU", product_name="Child")
    child = ProductSKU.objects.create(tenant=tenant, spu=child_spu, sku_code="CHILD", product_name="Child")
    part_spu = ProductSPU.objects.create(tenant=tenant, spu_code="PART-SPU", product_name="Part")
    part = ProductSKU.objects.create(tenant=tenant, spu=part_spu, sku_code="PART", product_name="Part")

    token, _batch = preview_legacy_migration(tenant=tenant, actor=actor, rows=[
        {"line": 2, "legacy_bundle_spu": "", "legacy_bundle_sku": "PARENT", "legacy_component_sku": "CHILD", "quantity": 1},
        {"line": 3, "legacy_bundle_spu": "", "legacy_bundle_sku": "CHILD", "legacy_component_sku": "PART", "quantity": 1},
    ])

    confirmed = confirm_legacy_migration(tenant=tenant, actor=actor, token=token)

    assert confirmed.preview_summary["migrated"] == 1
    assert confirmed.preview_summary["runtime_rejected_bundles"] == 1
    assert confirmed.preview_summary["rejected_rows"][-1]["code"] == "nested_bundle_component"
    assert not ProductBundleComponent.objects.filter(bundle_sku=parent).exists()
    assert ProductBundleComponent.objects.get(bundle_sku=child, component_sku=part).quantity == 1
