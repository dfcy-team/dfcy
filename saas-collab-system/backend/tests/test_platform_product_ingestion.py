from decimal import Decimal
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.integrations.models import (
    IntegrationAuditLog,
    MarketplaceStoreAuthorization,
    PlatformIntegrationConfig,
    SyncJob,
    SyncRun,
    authorization_service_write,
    marketplace_identity_key,
    marketplace_store_binding_key,
)
from apps.integrations.adapters import MarketplaceProductAdapter
from apps.integrations.platform_product_ingestion import upsert_platform_product
from apps.integrations.store_mapping_service import create_store_mapping
from apps.listings.models import PlatformProductDetail
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _fixture(*, create_store_mapping_row=True):
    tenant = Tenant.objects.create(name="Ingestion tenant", code="ingestion-tenant")
    user = CustomUser.objects.create_user(
        username="ingestion-user",
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
        code="store-my",
        name="Store MY",
        country_code="MY",
        currency="MYR",
    )
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="shopee",
        account_alias="Shopee ingestion",
        environment=PlatformIntegrationConfig.Environment.PILOT,
        status=PlatformIntegrationConfig.Status.VERIFIED,
        regions=["MY"],
        created_by=user,
    )
    external_id = "shop-my-1"
    identity = marketplace_identity_key("shopee", "MY", external_id)
    with authorization_service_write():
        authorization = MarketplaceStoreAuthorization.objects.create(
            tenant=tenant,
            integration_config=config,
            store=store,
            platform="shopee",
            region="MY",
            platform_store_id=external_id,
            platform_identity_key=identity,
            active_platform_identity_key=identity,
            active_store_binding_key=marketplace_store_binding_key(tenant.id, "shopee", store.id),
            merchant_subject_id="merchant-my",
            credential_id="credential-ref",
            token_id="token-ref",
            credential_mask={"token": "********"},
            status=MarketplaceStoreAuthorization.Status.ACTIVE,
            authorized_at=timezone.now(),
            created_by=user,
            updated_by=user,
        )
    mapping = None
    if create_store_mapping_row:
        mapping = create_store_mapping(
            tenant=tenant,
            actor=user,
            store=store,
            authorization=authorization,
            store_timezone="Asia/Kuala_Lumpur",
            currency="MYR",
        )
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-INGEST", product_name="Ingest product")
    sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="NEW-INGEST",
        legacy_sku_code="OLD-INGEST",
        purchase_price=Decimal("1"),
    )
    other_sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="NEW-OTHER",
        legacy_sku_code="OLD-OTHER",
        purchase_price=Decimal("1"),
    )
    job = SyncJob.objects.create(
        tenant=tenant,
        integration_config=config,
        store_authorization=authorization,
        resource_type=SyncJob.ResourceType.SALES_ORDER,
    )
    return {
        "tenant": tenant,
        "user": user,
        "platform": platform,
        "store": store,
        "config": config,
        "authorization": authorization,
        "store_mapping": mapping,
        "sku": sku,
        "other_sku": other_sku,
        "job": job,
    }


def _record(**overrides):
    value = {
        "platform_product_id": "P-INGEST",
        "platform_variant_id": "V-INGEST",
        "platform_sku": "SELLER-INGEST",
        "new_sku_code": "NEW-INGEST",
        "source_old_sku_code": "OLD-INGEST",
        "title": "Ingest title",
        "platform_updated_at": timezone.now(),
    }
    value.update(overrides)
    return value


def test_exact_new_and_old_codes_auto_associate_canonical_mapping():
    context = _fixture()
    result = upsert_platform_product(context["job"], _record())

    detail = PlatformProductDetail.objects.get(tenant=context["tenant"])
    mapping = detail.marketplace_mapping
    assert result["action"] == "created"
    assert result["sku_state"] == "matched"
    assert detail.internal_sku_id == context["sku"].id
    assert mapping.status == "mapped"
    assert mapping.mapping_source == "api_exact_match"
    assert mapping.manually_confirmed is False
    assert mapping.confidence == 100
    assert IntegrationAuditLog.objects.filter(
        action="product_mapping_api_exact_match",
        tenant=context["tenant"],
    ).exists()


def test_readonly_adapter_persists_through_real_ingestion_boundary_without_old_sku_inference():
    context = _fixture()
    job = context["job"]
    job.resource_type = SyncJob.ResourceType.PLATFORM_PRODUCT
    run = SyncRun.objects.create(
        tenant=context["tenant"],
        sync_job=job,
        run_id="run-platform-product-adapter",
        idempotency_key="key-platform-product-adapter",
    )
    adapter = MarketplaceProductAdapter(context["config"])
    adapter.authorization = context["authorization"]
    adapter.bind_run(run)
    normalized = adapter.normalize_record(
        {
            "platform_product_id": "P-ADAPTER",
            "platform_variant_id": "V-ADAPTER",
            # The provider SKU is allowed to match either namespace; this
            # fixture deliberately matches the new SKU only.
            "platform_sku": "NEW-INGEST",
            "title": "Adapter product",
        }
    )
    result = adapter.persist_record(job, normalized)

    detail = PlatformProductDetail.objects.get(platform_variant_id="V-ADAPTER")
    assert result["action"] == "created"
    assert result["sku_state"] == "matched"
    assert detail.internal_sku_id == context["sku"].id
    assert detail.source_old_sku_code == ""


def test_unknown_or_mismatched_codes_retain_pending_detail_and_conflict_mapping():
    context = _fixture()
    pending = upsert_platform_product(
        context["job"],
        _record(
            platform_variant_id="V-PENDING",
            new_sku_code="UNKNOWN-NEW",
            source_old_sku_code="",
        ),
    )
    pending_detail = PlatformProductDetail.objects.get(platform_variant_id="V-PENDING")
    assert pending["sku_state"] == "pending"
    assert pending_detail.internal_sku_id is None
    assert pending_detail.marketplace_mapping.status == "unmapped"
    assert pending_detail.marketplace_mapping.result_code == "SKU_SOURCE_PENDING"

    conflict = upsert_platform_product(
        context["job"],
        _record(
            platform_variant_id="V-CONFLICT",
            new_sku_code="NEW-INGEST",
            source_old_sku_code="OLD-OTHER",
        ),
    )
    conflict_detail = PlatformProductDetail.objects.get(platform_variant_id="V-CONFLICT")
    assert conflict["sku_state"] == "conflict"
    assert conflict_detail.internal_sku_id is None
    assert conflict_detail.marketplace_mapping.status == "conflict"
    assert conflict_detail.marketplace_mapping.result_code == "SKU_SOURCE_CONFLICT"


def test_repeated_ingestion_is_idempotent_and_cross_store_reuse_is_allowed():
    context = _fixture()
    snapshot = _record(platform_updated_at=timezone.now())
    first = upsert_platform_product(context["job"], snapshot)
    second = upsert_platform_product(context["job"], snapshot)
    assert first["action"] == "created"
    assert second["action"] == "skipped"
    assert PlatformProductDetail.objects.filter(tenant=context["tenant"]).count() == 1

    # A second store in the same tenant may reuse the same internal SKU.
    store_two = StoreMaster.objects.create(
        tenant=context["tenant"],
        platform=context["platform"],
        code="store-my-2",
        name="Store MY 2",
        country_code="MY",
        currency="MYR",
    )
    external_id = "shop-my-2"
    identity = marketplace_identity_key("shopee", "MY", external_id)
    with authorization_service_write():
        authorization_two = MarketplaceStoreAuthorization.objects.create(
            tenant=context["tenant"],
            integration_config=context["config"],
            store=store_two,
            platform="shopee",
            region="MY",
            platform_store_id=external_id,
            platform_identity_key=identity,
            active_platform_identity_key=identity,
            active_store_binding_key=marketplace_store_binding_key(context["tenant"].id, "shopee", store_two.id),
            merchant_subject_id="merchant-my-2",
            credential_id="credential-ref-2",
            token_id="token-ref-2",
            credential_mask={"token": "********"},
            status=MarketplaceStoreAuthorization.Status.ACTIVE,
            authorized_at=timezone.now(),
            created_by=context["user"],
            updated_by=context["user"],
        )
    create_store_mapping(
        tenant=context["tenant"],
        actor=context["user"],
        store=store_two,
        authorization=authorization_two,
        store_timezone="Asia/Kuala_Lumpur",
        currency="MYR",
    )
    job_two = SyncJob.objects.create(
        tenant=context["tenant"],
        integration_config=context["config"],
        store_authorization=authorization_two,
        resource_type=SyncJob.ResourceType.REFUND_RETURN,
    )
    second_store = upsert_platform_product(job_two, _record(platform_variant_id="V-INGEST-2"))
    assert second_store["sku_state"] == "matched"
    assert PlatformProductDetail.objects.filter(
        tenant=context["tenant"], internal_sku=context["sku"]
    ).count() == 2


def test_older_platform_snapshot_cannot_overwrite_newer_facts():
    context = _fixture()
    newer = timezone.now()
    upsert_platform_product(
        context["job"],
        _record(title="New title", platform_updated_at=newer),
    )
    older = upsert_platform_product(
        context["job"],
        _record(title="Old title", platform_updated_at=newer - timedelta(days=1)),
    )
    detail = PlatformProductDetail.objects.get(platform_variant_id="V-INGEST")
    assert older["action"] == "skipped"
    assert older["stale_snapshot"] is True
    assert detail.title == "New title"


def test_existing_api_exact_identity_is_preserved_when_refresh_proposes_other_sku():
    context = _fixture()
    upsert_platform_product(context["job"], _record())
    result = upsert_platform_product(
        context["job"],
        _record(
            new_sku_code="NEW-OTHER",
            source_old_sku_code="OLD-OTHER",
            title="Updated source title",
            platform_updated_at=timezone.now(),
        ),
    )
    detail = PlatformProductDetail.objects.get(platform_variant_id="V-INGEST")
    mapping = detail.marketplace_mapping
    assert result["sku_state"] == "conflict"
    assert detail.internal_sku_id == context["sku"].id
    assert mapping.sku_id == context["sku"].id
    assert mapping.status == "conflict"
    assert mapping.result_code == "SKU_SOURCE_CONFLICT"
    assert detail.title == "Updated source title"


def test_missing_store_mapping_keeps_detail_pending_without_fabricating_mapping():
    context = _fixture(create_store_mapping_row=False)
    result = upsert_platform_product(context["job"], _record())
    detail = PlatformProductDetail.objects.get(tenant=context["tenant"])
    assert result["sku_state"] == "matched"
    assert result["mapping_id"] is not None
    assert result["mapping_state"] == "matched"
    assert detail.internal_sku_id == context["sku"].id


def test_generic_platform_sku_uses_unique_union_not_legacy_assumption():
    context = _fixture()
    result = upsert_platform_product(
        context["job"],
        _record(new_sku_code="", source_old_sku_code="", platform_sku="NEW-INGEST"),
    )
    assert result["sku_state"] == "matched"
    assert PlatformProductDetail.objects.get(tenant=context["tenant"]).internal_sku_id == context["sku"].id


def test_status_only_snapshot_updates_status_and_time_without_touching_identity_or_mapping():
    context = _fixture()
    original_time = timezone.now()
    upsert_platform_product(
        context["job"],
        _record(
            title="Canonical title",
            platform_sku="SELLER-CANONICAL",
            sales_status="ACTIVE",
            platform_updated_at=original_time,
        ),
    )
    detail_before = PlatformProductDetail.objects.get(platform_variant_id="V-INGEST")
    status_time = original_time + timedelta(minutes=1)
    result = upsert_platform_product(
        context["job"],
        {
            "status_only": True,
            "platform_product_id": "P-INGEST",
            "platform_variant_id": "V-INGEST",
            "sales_status": "FREEZE",
            "platform_updated_at": status_time,
            # A partial provider event must not be allowed to replace these.
            "title": "Partial title must be ignored",
            "platform_sku": "PROPOSED-SELLER",
            "new_sku_code": "NEW-OTHER",
            "source_old_sku_code": "OLD-OTHER",
        },
    )
    detail = PlatformProductDetail.objects.get(pk=detail_before.pk)
    mapping = detail.marketplace_mapping
    assert result["action"] == "updated" and result["status_only"] is True
    assert detail.sales_status == "FREEZE"
    assert detail.platform_updated_at == status_time
    assert detail.title == "Canonical title"
    assert detail.platform_sku == "SELLER-CANONICAL"
    assert detail.internal_sku_id == context["sku"].id
    assert detail.source_old_sku_code == "OLD-INGEST"
    assert mapping.status == "mapped" and mapping.sku_id == context["sku"].id
    assert IntegrationAuditLog.objects.filter(
        action="platform_product_status_only_update",
        result=IntegrationAuditLog.Result.SUCCESS,
        tenant=context["tenant"],
    ).exists()


def test_status_only_unknown_or_mismatched_variant_is_audited_and_skipped():
    context = _fixture()
    upsert_platform_product(context["job"], _record(sales_status="ACTIVE"))
    unknown = upsert_platform_product(
        context["job"],
        {
            "status_only": True,
            "platform_product_id": "P-UNKNOWN",
            "platform_variant_id": "V-UNKNOWN",
            "sales_status": "DELETED",
        },
    )
    mismatched = upsert_platform_product(
        context["job"],
        {
            "status_only": True,
            "platform_product_id": "P-OTHER",
            "platform_variant_id": "V-INGEST",
            "sales_status": "DELETED",
        },
    )
    detail = PlatformProductDetail.objects.get(platform_variant_id="V-INGEST")
    assert unknown["action"] == "skipped"
    assert unknown["result_code"] == "STATUS_ONLY_UNKNOWN_VARIANT"
    assert mismatched["action"] == "skipped"
    assert mismatched["result_code"] == "STATUS_ONLY_PRODUCT_MISMATCH"
    assert PlatformProductDetail.objects.filter(tenant=context["tenant"]).count() == 1
    assert detail.sales_status == "ACTIVE"
    assert IntegrationAuditLog.objects.filter(
        action="platform_product_status_only_skip",
        result=IntegrationAuditLog.Result.BLOCKED,
        tenant=context["tenant"],
    ).count() >= 2


def test_status_only_product_snapshot_without_variant_updates_all_known_variants():
    context = _fixture()
    current_time = timezone.now()
    upsert_platform_product(
        context["job"],
        _record(
            platform_variant_id="V-INGEST-1",
            title="Variant one",
            sales_status="ACTIVE",
            platform_updated_at=current_time,
        ),
    )
    upsert_platform_product(
        context["job"],
        _record(
            platform_variant_id="V-INGEST-2",
            title="Variant two",
            sales_status="ACTIVE",
            platform_updated_at=current_time,
        ),
    )
    result = upsert_platform_product(
        context["job"],
        {
            "status_only": True,
            "platform_product_id": "P-INGEST",
            "sales_status": "DELETED",
            "platform_updated_at": current_time + timedelta(minutes=1),
        },
    )
    details = list(
        PlatformProductDetail.objects.filter(
            tenant=context["tenant"], platform_product_id="P-INGEST"
        ).order_by("platform_variant_id")
    )
    assert result["action"] == "updated"
    assert result["updated_detail_count"] == 2
    assert [detail.sales_status for detail in details] == ["DELETED", "DELETED"]
    assert [detail.title for detail in details] == ["Variant one", "Variant two"]
    assert all(detail.internal_sku_id == context["sku"].id for detail in details)


def test_status_only_older_snapshot_cannot_rewind_sales_status():
    context = _fixture()
    current_time = timezone.now()
    upsert_platform_product(
        context["job"],
        _record(sales_status="FREEZE", platform_updated_at=current_time),
    )
    result = upsert_platform_product(
        context["job"],
        {
            "status_only": True,
            "platform_product_id": "P-INGEST",
            "platform_variant_id": "V-INGEST",
            "sales_status": "ACTIVE",
            "platform_updated_at": current_time - timedelta(minutes=1),
        },
    )
    detail = PlatformProductDetail.objects.get(platform_variant_id="V-INGEST")
    assert result["stale_snapshot"] is True
    assert result["result_code"] == "STALE_PLATFORM_SNAPSHOT"
    assert detail.sales_status == "FREEZE"
