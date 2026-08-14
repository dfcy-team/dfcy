from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import CustomUser
from apps.commerce.models import (
    InventorySnapshot,
    RefundReturn,
    RefundReturnItem,
    SalesOrder,
)
from apps.integrations.models import (
    PlatformIntegrationConfig,
    RawPayload,
    SyncJob,
    SyncQualityResult,
    SyncRun,
)
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.tenants.models import Tenant


NOW = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)


def create_scope(code):
    tenant = Tenant.objects.create(name=f"Tenant {code}", code=code)
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code=f"shopee-{code}",
        name="Shopee",
        platform_type="shopee",
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code=f"store-{code}",
        name=f"Store {code}",
        country_code="PH",
        currency="PHP",
        timezone="Asia/Manila",
    )
    return tenant, store


def create_sync_run(tenant, suffix, resource_type=SyncJob.ResourceType.SALES_ORDER):
    user = CustomUser.objects.create_user(
        username=f"integration-{suffix}",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="shopee",
        account_alias=f"account-{suffix}",
        created_by=user,
    )
    job = SyncJob.objects.create(
        tenant=tenant,
        integration_config=config,
        resource_type=resource_type,
        schedule_type=SyncJob.ScheduleType.MANUAL,
    )
    return SyncRun.objects.create(
        tenant=tenant,
        sync_job=job,
        run_id=f"run-{suffix}",
        idempotency_key=f"key-{suffix}",
    )


def create_order(tenant, store, external_order_id="ORDER-1"):
    return SalesOrder.objects.create(**order_values(tenant, store, external_order_id))


def order_values(tenant, store, external_order_id="ORDER-1"):
    return {
        "tenant": tenant,
        "store": store,
        "platform": "shopee",
        "region": "PH",
        "external_order_id": external_order_id,
        "raw_status": "COMPLETED",
        "canonical_status": "completed",
        "created_at_utc": NOW,
        "updated_at_utc": NOW,
        "business_date": date(2026, 8, 14),
        "currency": "PHP",
        "subtotal_amount": Decimal("100.0000"),
        "order_total_amount": Decimal("100.0000"),
    }


def create_raw_payload(tenant, store, run, resource_type, external_id):
    return RawPayload.objects.create(
        tenant=tenant,
        sync_run=run,
        store=store,
        platform="shopee",
        resource_type=resource_type,
        external_id=external_id,
        schema_version=f"{resource_type}.v1",
        content_hash=(external_id.lower().replace("-", "") + "0" * 64)[:64],
        fetched_at=NOW,
    )


@pytest.mark.django_db
def test_order_identity_is_idempotent_and_tenant_scoped():
    tenant, store = create_scope("commerce-a")
    other_tenant, other_store = create_scope("commerce-b")
    create_order(tenant, store)
    create_order(other_tenant, other_store)

    with pytest.raises(ValidationError):
        create_order(tenant, store)


@pytest.mark.django_db
def test_order_rejects_cross_tenant_store_and_negative_money():
    tenant, _ = create_scope("commerce-c")
    _, other_store = create_scope("commerce-d")
    values = order_values(tenant, other_store, "ORDER-X")
    with pytest.raises(ValidationError, match="same tenant"):
        SalesOrder.objects.create(**values)
    assert not SalesOrder.objects.filter(external_order_id="ORDER-X").exists()

    values["store"] = StoreMaster.objects.filter(tenant=tenant).get()
    values["subtotal_amount"] = Decimal("-1.0000")
    with pytest.raises(ValidationError):
        SalesOrder.objects.create(**values)


@pytest.mark.django_db
def test_save_and_bulk_create_enforce_tenant_and_platform_relationships():
    tenant, store = create_scope("commerce-write-a")
    other_tenant, other_store = create_scope("commerce-write-b")

    invalid_save = SalesOrder(**order_values(tenant, other_store, "SAVE-X"))
    with pytest.raises(ValidationError):
        invalid_save.save()

    wrong_platform = SalesOrder(**order_values(tenant, store, "BULK-X"))
    wrong_platform.platform = "tiktok"
    cross_tenant = SalesOrder(**order_values(other_tenant, store, "BULK-Y"))
    with pytest.raises(ValidationError):
        SalesOrder.objects.bulk_create([wrong_platform, cross_tenant])
    assert SalesOrder.objects.filter(external_order_id__in=["SAVE-X", "BULK-X", "BULK-Y"]).count() == 0

    valid = create_order(tenant, store, "UPDATE-X")
    with pytest.raises(ValidationError):
        SalesOrder.objects.filter(pk=valid.pk).update(tenant=other_tenant)
    valid.refresh_from_db()
    assert valid.tenant_id == tenant.id

    base_manager_invalid = SalesOrder(**order_values(other_tenant, store, "BASE-BULK-X"))
    with pytest.raises(ValidationError):
        SalesOrder._base_manager.bulk_create([base_manager_invalid])
    with pytest.raises(ValidationError):
        SalesOrder._base_manager.filter(pk=valid.pk).update(platform="tiktok")
    valid.refresh_from_db()
    assert valid.platform == "shopee"
    assert not SalesOrder.objects.filter(external_order_id="BASE-BULK-X").exists()


@pytest.mark.django_db
def test_refund_supports_multiple_items_and_optional_order_link():
    tenant, store = create_scope("commerce-e")
    refund = RefundReturn.objects.create(
        tenant=tenant,
        store=store,
        order=None,
        platform="shopee",
        external_refund_id="REFUND-1",
        external_return_id="RETURN-1",
        case_type="return_refund",
        raw_status="RETURN_OR_REFUND_REQUEST_PENDING",
        canonical_status="pending",
        requested_at_utc=NOW,
        source_updated_at_utc=NOW,
        currency="PHP",
        refund_amount=Decimal("20.0000"),
    )
    for index in range(2):
        RefundReturnItem.objects.create(
            refund_return=refund,
            external_return_item_id=f"RETURN-ITEM-{index}",
            platform_product_id=f"PRODUCT-{index}",
            quantity=1,
            currency="PHP",
            refund_amount=Decimal("10.0000"),
        )
    assert refund.items.count() == 2


@pytest.mark.django_db
def test_raw_payload_stores_only_reference_and_is_idempotent():
    tenant, store = create_scope("commerce-f")
    run = create_sync_run(tenant, "f")
    payload = RawPayload.objects.create(
        tenant=tenant,
        sync_run=run,
        store=store,
        platform="shopee",
        resource_type="order_detail",
        external_id="ORDER-1",
        schema_version="sales_order.v1",
        content_hash="a" * 64,
        object_reference="encrypted://orders/object-1",
        fetched_at=NOW,
    )
    assert not hasattr(payload, "payload")

    with pytest.raises(ValidationError):
        RawPayload.objects.create(
            tenant=tenant,
            sync_run=run,
            store=store,
            platform="shopee",
            resource_type="order_detail",
            external_id="ORDER-1",
            schema_version="sales_order.v1",
            content_hash="a" * 64,
            fetched_at=NOW,
        )

    other_tenant, _ = create_scope("commerce-raw-other")
    with pytest.raises(ValidationError):
        RawPayload.objects.bulk_create(
            [
                RawPayload(
                    tenant=other_tenant,
                    sync_run=run,
                    store=store,
                    platform="tiktok",
                    resource_type="order_detail",
                    external_id="ORDER-CROSS",
                    schema_version="sales_order.v1",
                    content_hash="c" * 64,
                    fetched_at=NOW,
                )
            ]
        )
    assert not RawPayload.objects.filter(external_id="ORDER-CROSS").exists()

    with pytest.raises(ValidationError, match="resource"):
        RawPayload.objects.create(
            tenant=tenant,
            sync_run=run,
            store=store,
            platform="shopee",
            resource_type="inventory",
            external_id="INVENTORY-WRONG-RUN",
            schema_version="inventory.v1",
            content_hash="d" * 64,
            fetched_at=NOW,
        )
    assert not RawPayload.objects.filter(external_id="INVENTORY-WRONG-RUN").exists()


@pytest.mark.django_db
def test_deleting_sync_run_sets_nullable_references_to_null():
    tenant, store = create_scope("commerce-delete-run")
    run = create_sync_run(tenant, "delete-run")
    payload = create_raw_payload(tenant, store, run, "order_detail", "ORDER-DELETE-RUN")
    order = SalesOrder.objects.create(
        **order_values(tenant, store, "ORDER-DELETE-RUN"),
        integration_config=run.sync_job.integration_config,
        source_run=run,
        raw_payload=payload,
    )

    run.delete()

    payload.refresh_from_db()
    order.refresh_from_db()
    assert payload.sync_run_id is None
    assert order.source_run_id is None

    payload.delete()

    order.refresh_from_db()
    assert order.raw_payload_id is None


@pytest.mark.django_db
def test_fact_models_reject_raw_payload_from_wrong_resource_family():
    tenant, store = create_scope("commerce-payload-family")
    sales_run = create_sync_run(tenant, "payload-sales")
    refund_run = create_sync_run(tenant, "payload-refund", SyncJob.ResourceType.REFUND_RETURN)
    inventory_run = create_sync_run(tenant, "payload-inventory", SyncJob.ResourceType.INVENTORY)
    order_payload = create_raw_payload(tenant, store, sales_run, "order_detail", "PAYLOAD-ORDER")
    refund_payload = create_raw_payload(tenant, store, refund_run, "refund_detail", "PAYLOAD-REFUND")
    inventory_payload = create_raw_payload(tenant, store, inventory_run, "inventory", "PAYLOAD-INVENTORY")

    with pytest.raises(ValidationError, match="resource family"):
        SalesOrder.objects.create(
            **order_values(tenant, store, "ORDER-WRONG-PAYLOAD"),
            raw_payload=inventory_payload,
        )
    with pytest.raises(ValidationError, match="resource family"):
        RefundReturn.objects.create(
            tenant=tenant,
            store=store,
            raw_payload=order_payload,
            platform="shopee",
            external_return_id="RETURN-WRONG-PAYLOAD",
            case_type="refund",
            raw_status="PENDING",
            canonical_status="pending",
            requested_at_utc=NOW,
            source_updated_at_utc=NOW,
            currency="PHP",
        )
    with pytest.raises(ValidationError, match="resource family"):
        InventorySnapshot.objects.create(
            tenant=tenant,
            store=store,
            raw_payload=refund_payload,
            platform="shopee",
            seller_sku="SKU-WRONG-PAYLOAD",
            snapshot_at_utc=NOW,
        )

    assert not SalesOrder.objects.filter(external_order_id="ORDER-WRONG-PAYLOAD").exists()
    assert not RefundReturn.objects.filter(external_return_id="RETURN-WRONG-PAYLOAD").exists()
    assert not InventorySnapshot.objects.filter(seller_sku="SKU-WRONG-PAYLOAD").exists()


@pytest.mark.django_db
def test_quality_result_and_inventory_snapshot_are_run_scoped_and_idempotent():
    tenant, store = create_scope("commerce-g")
    sales_run = create_sync_run(tenant, "g-sales")
    run = create_sync_run(tenant, "g-inventory", SyncJob.ResourceType.INVENTORY)
    SyncQualityResult.objects.create(
        tenant=tenant,
        sync_run=sales_run,
        resource_type="sales_order",
        check_code="missing_currency",
        status="pass",
        actual_count=10,
        checked_at=NOW,
    )
    with pytest.raises(ValidationError):
        SyncQualityResult.objects.create(
            tenant=tenant,
            sync_run=sales_run,
            resource_type="inventory",
            check_code="wrong-resource",
            status="pass",
            checked_at=NOW,
        )
    first = InventorySnapshot.objects.create(
        tenant=tenant,
        store=store,
        source_run=run,
        platform="shopee",
        seller_sku="SKU-1",
        snapshot_key="caller-controlled-a",
        on_hand_qty=5,
        available_qty=4,
        reserved_qty=1,
        snapshot_at_utc=NOW,
    )
    assert len(first.snapshot_key) == 64
    assert first.snapshot_key != "caller-controlled-a"
    with pytest.raises(ValidationError):
        InventorySnapshot.objects.create(
            tenant=tenant,
            store=store,
            source_run=run,
            platform="shopee",
            seller_sku="SKU-1",
            snapshot_key="caller-controlled-b",
            snapshot_at_utc=NOW,
        )
    assert InventorySnapshot.objects.filter(tenant=tenant, store=store, snapshot_at_utc=NOW).count() == 1

    previous_key = first.snapshot_key
    first.seller_sku = "SKU-UPDATED"
    first.save(update_fields=["seller_sku"])
    first.refresh_from_db()
    assert first.snapshot_key != previous_key

    bulk_key = first.snapshot_key
    first.platform_variant_id = "VARIANT-BULK"
    InventorySnapshot.objects.bulk_update([first], ["platform_variant_id"])
    first.refresh_from_db()
    assert first.snapshot_key != bulk_key

    with pytest.raises(ValidationError, match="resource type"):
        InventorySnapshot.objects.create(
            tenant=tenant,
            store=store,
            source_run=sales_run,
            platform="shopee",
            seller_sku="SKU-SALES-RUN",
            snapshot_at_utc=NOW,
        )


@pytest.mark.django_db
def test_refund_rejects_cross_store_and_cross_platform_order_links():
    tenant, store = create_scope("commerce-refund-a")
    other_platform = PlatformMaster.objects.create(
        tenant=tenant,
        code="tiktok-refund-a",
        name="TikTok Shop",
        platform_type="tiktok",
    )
    other_store = StoreMaster.objects.create(
        tenant=tenant,
        platform=other_platform,
        code="store-refund-other",
        name="Other store",
        country_code="PH",
        currency="PHP",
        timezone="Asia/Manila",
    )
    order = create_order(tenant, store, "ORDER-REFUND")
    with pytest.raises(ValidationError):
        RefundReturn.objects.create(
            tenant=tenant,
            store=other_store,
            order=order,
            platform="tiktok",
            external_return_id="RETURN-CROSS",
            case_type="refund",
            raw_status="PENDING",
            canonical_status="pending",
            requested_at_utc=NOW,
            source_updated_at_utc=NOW,
            currency="PHP",
        )
    assert not RefundReturn.objects.filter(external_return_id="RETURN-CROSS").exists()
