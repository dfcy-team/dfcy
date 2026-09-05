import io
import json
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.integrations.models import (
    MarketplaceProductMapping,
    MarketplaceStoreAuthorization,
    MarketplaceStoreMapping,
    PlatformIntegrationConfig,
    authorization_service_write,
    marketplace_identity_key,
    marketplace_store_binding_key,
    product_mapping_service_write,
    store_mapping_service_write,
)
from apps.listings.models import PlatformProductDetail
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _tenant_bundle(code):
    tenant = Tenant.objects.create(name=f"Report {code}", code=f"report-{code}")
    user = CustomUser.objects.create_user(
        username=f"report-{code}",
        password="test-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code="shopee",
        name="Shopee",
        platform_type="shopee",
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code=f"store-{code}",
        name=f"Store {code}",
        country_code="MY",
        currency="MYR",
    )
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="shopee",
        account_alias=f"report-{code}",
        environment=PlatformIntegrationConfig.Environment.PILOT,
        status=PlatformIntegrationConfig.Status.VERIFIED,
        regions=["MY"],
        created_by=user,
    )
    platform_store_id = f"{code}-auth-store"
    identity = marketplace_identity_key("shopee", "MY", platform_store_id)
    with authorization_service_write():
        authorization = MarketplaceStoreAuthorization.objects.create(
            tenant=tenant,
            integration_config=config,
            store=store,
            platform="shopee",
            region="MY",
            platform_store_id=platform_store_id,
            platform_identity_key=identity,
            active_platform_identity_key=identity,
            active_store_binding_key=marketplace_store_binding_key(tenant.id, "shopee", store.id),
            merchant_subject_id=f"merchant-{code}",
            credential_id=f"credential-{code}",
            token_id=f"token-{code}",
            credential_mask={"token": "********"},
            status=MarketplaceStoreAuthorization.Status.ACTIVE,
            authorized_at=timezone.now(),
            created_by=user,
            updated_by=user,
        )
    spu = ProductSPU.objects.create(
        tenant=tenant,
        spu_code=f"SPU-{code}",
        product_name=f"Report product {code}",
    )
    sku_a = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code=f"SKU-{code}-A",
        legacy_sku_code=f"OLD-{code}-A",
        purchase_price=Decimal("1"),
    )
    sku_b = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code=f"SKU-{code}-B",
        legacy_sku_code=f"OLD-{code}-B",
        purchase_price=Decimal("1"),
    )
    return {
        "tenant": tenant,
        "user": user,
        "platform": platform,
        "store": store,
        "authorization": authorization,
        "sku_a": sku_a,
        "sku_b": sku_b,
    }


def _store_mapping(bundle, suffix):
    """Create synthetic legacy rows without invoking the service audit path."""

    platform_store_id = f"{bundle['tenant'].code}-{suffix}"
    mapping = MarketplaceStoreMapping(
        tenant=bundle["tenant"],
        platform="shopee",
        store=bundle["store"],
        authorization=bundle["authorization"],
        platform_store_id=platform_store_id,
        platform_identity_key=f"legacy-{bundle['tenant'].id}-{suffix}",
        platform_subject_id=f"subject-{suffix}",
        region="MY",
        timezone="Asia/Kuala_Lumpur",
        currency="MYR",
        status=MarketplaceStoreMapping.Status.ACTIVE,
        mapping_source=MarketplaceStoreMapping.MappingSource.SYNTHETIC_FIXTURE,
        mapped_by=bundle["user"],
    )
    # Historical rows may predate current service validation.  bulk_create is
    # deliberately scoped to this test fixture; the reporting command itself
    # only reads these records.
    with store_mapping_service_write():
        MarketplaceStoreMapping.objects.bulk_create([mapping])
    return MarketplaceStoreMapping.objects.get(pk=mapping.pk)


def _detail(bundle, variant, *, product_id=None, sku=None, platform=None):
    return PlatformProductDetail.objects.create(
        tenant=bundle["tenant"],
        platform=platform or bundle["platform"],
        store=bundle["store"],
        platform_product_id=product_id or f"P-{variant}",
        platform_variant_id=variant,
        platform_sku=f"PSKU-{variant}",
        internal_sku=sku,
    )


def _mapping(
    bundle,
    store_mapping,
    variant,
    *,
    product_id=None,
    platform_sku=None,
    sku=None,
    status=MarketplaceProductMapping.Status.UNMAPPED,
    detail=None,
):
    mapping = MarketplaceProductMapping(
        tenant=bundle["tenant"],
        platform="shopee",
        store_mapping=store_mapping,
        platform_detail=detail,
        platform_product_id=product_id or f"P-{variant}",
        platform_variant_id=variant,
        platform_sku=platform_sku or f"PSKU-{variant}",
        product=sku.spu if sku else None,
        sku=sku,
        status=status,
        mapping_source=MarketplaceProductMapping.MappingSource.MANUAL,
        confidence=100 if status == MarketplaceProductMapping.Status.SUGGESTED else None,
        manually_confirmed=status == MarketplaceProductMapping.Status.MAPPED,
        created_by=bundle["user"],
        updated_by=bundle["user"],
    )
    with product_mapping_service_write():
        MarketplaceProductMapping.objects.bulk_create([mapping])
    return MarketplaceProductMapping.objects.get(pk=mapping.pk)


def _run_report(*args):
    output = io.StringIO()
    call_command("report_mapping_consolidation", *args, stdout=output)
    return json.loads(output.getvalue())


def test_report_covers_all_reasons_and_does_not_mutate_database():
    bundle = _tenant_bundle("reasons")

    ready_detail = _detail(bundle, "V-READY", sku=bundle["sku_a"])
    ready = _mapping(
        bundle,
        _store_mapping(bundle, "ready"),
        "V-READY",
        sku=bundle["sku_a"],
    )

    unmatched = _mapping(bundle, _store_mapping(bundle, "unmatched"), "V-UNMATCHED")

    multi_platform = PlatformMaster.objects.create(
        tenant=bundle["tenant"],
        code="shopee-alias",
        name="Shopee alias",
        platform_type="shopee",
    )
    _detail(bundle, "V-MULTI", platform=multi_platform)
    _detail(bundle, "V-MULTI")
    multiple = _mapping(bundle, _store_mapping(bundle, "multiple"), "V-MULTI")

    identity_detail = _detail(bundle, "V-IDENTITY", product_id="P-CANONICAL")
    identity = _mapping(
        bundle,
        _store_mapping(bundle, "identity"),
        "V-IDENTITY",
        product_id="P-HISTORICAL",
    )

    _detail(bundle, "V-SKU", sku=bundle["sku_a"])
    sku_conflict = _mapping(
        bundle,
        _store_mapping(bundle, "sku-conflict"),
        "V-SKU",
        sku=bundle["sku_b"],
    )

    _detail(bundle, "V-DUPLICATE", sku=bundle["sku_a"])
    duplicate_one = _mapping(
        bundle,
        _store_mapping(bundle, "duplicate-one"),
        "V-DUPLICATE",
        sku=bundle["sku_a"],
    )
    duplicate_two = _mapping(
        bundle,
        _store_mapping(bundle, "duplicate-two"),
        "V-DUPLICATE",
        sku=bundle["sku_a"],
    )

    missing_sku_detail = _detail(bundle, "V-MAPPED-MISSING")
    mapped_missing = _mapping(
        bundle,
        _store_mapping(bundle, "mapped-missing"),
        "V-MAPPED-MISSING",
        sku=bundle["sku_a"],
        status=MarketplaceProductMapping.Status.MAPPED,
        detail=missing_sku_detail,
    )

    linked_detail = _detail(bundle, "V-LINKED-CONFLICT", product_id="P-LINK-CANONICAL")
    linked_inconsistent = _mapping(
        bundle,
        _store_mapping(bundle, "linked-conflict"),
        "V-LINKED-CONFLICT",
        product_id="P-LINK-HISTORICAL",
        detail=linked_detail,
    )

    before_mappings = list(
        MarketplaceProductMapping.objects.order_by("id").values_list(
            "id", "platform_detail_id", "status", "sku_id", "platform_product_id"
        )
    )
    before_details = list(
        PlatformProductDetail.objects.order_by("id").values_list(
            "id", "internal_sku_id", "platform_product_id", "platform_variant_id"
        )
    )

    report = _run_report("--batch-size", "1")

    assert report["command"] == "report_mapping_consolidation"
    assert report["tenant_id"] is None
    assert report["counts"] == {
        "unmatched": 1,
        "multiple_detail": 1,
        "identity_conflict": 2,
        "sku_conflict": 2,
        "duplicate_mapping": 2,
        "mapped_detail_sku_missing": 1,
        "ready": 1,
        "linked": 0,
        "total": 9,
    }
    assert {item["mapping_id"] for item in report["identifiers"]["ready"]} == {ready.id}
    assert {item["mapping_id"] for item in report["identifiers"]["unmatched"]} == {unmatched.id}
    assert {item["mapping_id"] for item in report["identifiers"]["multiple_detail"]} == {multiple.id}
    assert {item["mapping_id"] for item in report["identifiers"]["identity_conflict"]} == {
        identity.id,
        linked_inconsistent.id,
    }
    assert {item["mapping_id"] for item in report["identifiers"]["sku_conflict"]} == {
        sku_conflict.id,
        mapped_missing.id,
    }
    assert {item["mapping_id"] for item in report["identifiers"]["duplicate_mapping"]} == {
        duplicate_one.id,
        duplicate_two.id,
    }
    assert {item["mapping_id"] for item in report["identifiers"]["mapped_detail_sku_missing"]} == {
        mapped_missing.id,
    }
    mapped_missing_item = next(item for item in report["items"] if item["mapping_id"] == mapped_missing.id)
    assert set(mapped_missing_item["categories"]) == {"sku_conflict", "mapped_detail_sku_missing"}
    linked_item = next(item for item in report["items"] if item["mapping_id"] == linked_inconsistent.id)
    assert linked_item["category"] == "identity_conflict"
    multiple_item = next(item for item in report["items"] if item["mapping_id"] == multiple.id)
    assert set(multiple_item["candidate_detail_ids"]) == set(
        PlatformProductDetail.objects.filter(platform_variant_id="V-MULTI").values_list("id", flat=True)
    )

    assert list(
        MarketplaceProductMapping.objects.order_by("id").values_list(
            "id", "platform_detail_id", "status", "sku_id", "platform_product_id"
        )
    ) == before_mappings
    assert list(
        PlatformProductDetail.objects.order_by("id").values_list(
            "id", "internal_sku_id", "platform_product_id", "platform_variant_id"
        )
    ) == before_details
    assert ready.platform_detail_id is None
    assert identity_detail.internal_sku_id is None


def test_report_blocks_one_sided_sku_identity_and_mapped_missing_sku():
    bundle = _tenant_bundle("sku-strict")
    detail_with_sku = _detail(bundle, "V-SKU-ONE-SIDED", sku=bundle["sku_a"])
    missing_mapping_sku = _mapping(
        bundle,
        _store_mapping(bundle, "sku-one-sided"),
        "V-SKU-ONE-SIDED",
    )
    detail_without_sku = _detail(bundle, "V-MAPPED-ONE-SIDED", sku=bundle["sku_a"])
    mapped_missing_mapping_sku = _mapping(
        bundle,
        _store_mapping(bundle, "mapped-one-sided"),
        "V-MAPPED-ONE-SIDED",
        status=MarketplaceProductMapping.Status.MAPPED,
        detail=detail_without_sku,
    )

    report = _run_report()

    assert report["counts"]["ready"] == 0
    assert report["counts"]["sku_conflict"] == 2
    assert report["counts"]["mapped_detail_sku_missing"] == 1
    assert {item["mapping_id"] for item in report["identifiers"]["sku_conflict"]} == {
        missing_mapping_sku.id,
        mapped_missing_mapping_sku.id,
    }
    assert {item["mapping_id"] for item in report["identifiers"]["mapped_detail_sku_missing"]} == {
        mapped_missing_mapping_sku.id,
    }
    assert detail_with_sku.internal_sku_id == bundle["sku_a"].id


def test_report_tenant_filter_excludes_other_tenant_rows():
    first = _tenant_bundle("filter-a")
    second = _tenant_bundle("filter-b")
    first_detail = _detail(first, "V-A", sku=first["sku_a"])
    second_detail = _detail(second, "V-B", sku=second["sku_a"])
    first_mapping = _mapping(
        first,
        _store_mapping(first, "mapped"),
        "V-A",
        sku=first["sku_a"],
    )
    second_mapping = _mapping(
        second,
        _store_mapping(second, "mapped"),
        "V-B",
        sku=second["sku_a"],
    )

    report = _run_report("--tenant-id", str(first["tenant"].id))

    assert report["tenant_id"] == first["tenant"].id
    assert report["counts"]["total"] == 1
    assert report["counts"]["ready"] == 1
    assert {item["mapping_id"] for item in report["identifiers"]["ready"]} == {first_mapping.id}
    assert all(
        item["tenant_id"] == first["tenant"].id
        for item in report["items"]
        for _ in [item]
    )
    assert second_mapping.id not in {item["mapping_id"] for item in report["identifiers"]["ready"]}
    assert first_detail.tenant_id != second_detail.tenant_id


def test_report_rejects_non_positive_tenant_and_batch_size():
    with pytest.raises(Exception, match="tenant-id"):
        _run_report("--tenant-id", "0")
    with pytest.raises(Exception, match="batch-size"):
        _run_report("--batch-size", "0")
