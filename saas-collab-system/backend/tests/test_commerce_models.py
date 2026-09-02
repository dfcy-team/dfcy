from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError

from apps.accounts.models import CustomUser
from apps.commerce.models import (
    InboundRecord,
    RefundReturn,
    RefundReturnItem,
    SalesOrder,
    SalesOrderItem,
    ShipmentRecord,
)
from apps.integrations.models import PlatformIntegrationConfig, SyncJob, SyncRun
from apps.masterdata.models import PlatformMaster, StoreMaster, WarehouseMaster
from apps.sales_management.services import upsert_normalized_order
from apps.tenants.models import Tenant


NOW = datetime(2026, 8, 17, 8, 0, tzinfo=UTC)


def scope(code, platform_type="shopee", country="PH"):
    tenant = Tenant.objects.create(name=code, code=code)
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code=f"{platform_type}-{code}",
        name=platform_type,
        platform_type=platform_type,
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code=f"store-{code}",
        name=code,
        country_code=country,
        currency="PHP",
        timezone="Asia/Manila",
    )
    warehouse = WarehouseMaster.objects.create(
        tenant=tenant,
        code=f"warehouse-{code}",
        name=code,
        country_code=country,
        warehouse_type="third_party",
    )
    return tenant, platform, store, warehouse


def run_for(tenant, resource_type, suffix, platform="shopee"):
    user = CustomUser.objects.create_user(username=f"user-{suffix}", tenant=tenant, user_type="internal")
    authorization = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform=platform,
        account_alias=f"auth-{suffix}",
        created_by=user,
    )
    job = SyncJob.objects.create(tenant=tenant, integration_config=authorization, resource_type=resource_type)
    run = SyncRun.objects.create(tenant=tenant, sync_job=job, run_id=f"run-{suffix}", idempotency_key=f"key-{suffix}")
    return authorization, run


def order_payload(store, updated_at=NOW, total="100.1234"):
    return {
        "contract_version": "1.0",
        "store_id": store.id,
        "external_order_id": "ORDER-001",
        "region": store.country_code,
        "raw_status": "COMPLETED",
        "normalized_status": "completed",
        "created_at_utc": NOW.isoformat(),
        "updated_at_utc": updated_at.isoformat(),
        "business_date": date(2026, 8, 17),
        "currency": "PHP",
        "subtotal_amount": total,
        "order_total_amount": total,
        "lines": [
            {
                "external_line_id": "LINE-001",
                "platform_product_id": "000123456789012345",
                "platform_variant_id": "000987654321098765",
                "seller_sku": "SKU-001",
                "quantity": 2,
                "sale_unit_price": "50.0617",
                "line_total_amount": total,
                "currency": "PHP",
            }
        ],
    }


@pytest.mark.django_db
def test_duplicate_replay_is_idempotent_and_older_event_cannot_overwrite():
    tenant, _, store, _ = scope("replay")
    _, run = run_for(tenant, "sales_order", "replay")
    first = upsert_normalized_order(tenant=tenant, payload=order_payload(store), source_run=run)
    repeated = upsert_normalized_order(tenant=tenant, payload=order_payload(store), source_run=run)
    old_payload = order_payload(store, updated_at=NOW - timedelta(hours=1), total="1.0000")
    old = upsert_normalized_order(tenant=tenant, payload=old_payload, source_run=run)

    assert first.pk == repeated.pk == old.pk
    assert SalesOrder.objects.filter(tenant=tenant).count() == 1
    assert SalesOrderItem.objects.filter(sales_order=first).count() == 1
    first.refresh_from_db()
    assert first.order_total_amount == Decimal("100.1234")


@pytest.mark.django_db
def test_external_id_is_tenant_platform_and_store_scoped():
    tenant, _, first_store, _ = scope("identity")
    second_platform = PlatformMaster.objects.create(
        tenant=tenant, code="tiktok-identity", name="TikTok", platform_type="tiktok"
    )
    second_store = StoreMaster.objects.create(
        tenant=tenant,
        platform=second_platform,
        code="store-identity-2",
        name="second",
        country_code="PH",
        currency="PHP",
        timezone="Asia/Manila",
    )
    _, shopee_run = run_for(tenant, "sales_order", "identity-shopee")
    _, tiktok_run = run_for(tenant, "sales_order", "identity-tiktok", platform="tiktok")
    upsert_normalized_order(tenant=tenant, payload=order_payload(first_store), source_run=shopee_run)
    upsert_normalized_order(tenant=tenant, payload=order_payload(second_store), source_run=tiktok_run)
    assert SalesOrder.objects.filter(tenant=tenant, external_order_id="ORDER-001").count() == 2


@pytest.mark.django_db
def test_partial_adjusted_refund_supports_multiple_items_without_physical_return():
    tenant, platform, store, _ = scope("refunds")
    authorization, order_run = run_for(tenant, "sales_order", "refund-order")
    order = SalesOrder.objects.create(
        tenant=tenant,
        platform=platform,
        store=store,
        authorization=authorization,
        source_run=order_run,
        external_order_id="ORDER-R",
        region="PH",
        raw_status="COMPLETED",
        normalized_status="completed",
        status_mapping_version="1.0",
        created_at_utc=NOW,
        updated_at_utc=NOW,
        business_date=NOW.date(),
        currency="PHP",
        order_total_amount="100.0000",
        payload_hash="a" * 64,
    )
    _, refund_run = run_for(tenant, "refund_return", "refund-fact")
    refund = RefundReturn.objects.create(
        tenant=tenant,
        platform=platform,
        store=store,
        sales_order=order,
        source_run=refund_run,
        external_return_id="RETURN-001",
        external_refund_id="REFUND-001",
        case_type="refund_only",
        raw_status="COMPLETED",
        normalized_status="completed",
        requested_at_utc=NOW,
        updated_at_utc=NOW,
        currency="PHP",
        refund_amount="25.0000",
        requires_physical_return=False,
        is_partial_quantity_return=True,
        is_refund_amount_adjusted=True,
        payload_hash="b" * 64,
    )
    for index in range(2):
        RefundReturnItem.objects.create(
            refund_return=refund,
            external_return_item_id=f"RETURN-LINE-{index}",
            seller_sku=f"SKU-{index}",
            quantity=1,
            currency="PHP",
            refund_amount="12.5000",
        )
    assert refund.items.count() == 2
    assert refund.inbound_record_id is None
    assert refund.shipment_record_id is None


@pytest.mark.django_db
def test_logistics_can_link_to_refund_but_never_create_refund_facts():
    tenant, platform, store, warehouse = scope("logistics")
    _, inbound_run = run_for(tenant, "inbound", "return-inbound", platform="jifeng_wms")
    inbound = InboundRecord.objects.create(
        tenant=tenant,
        site_code="PH",
        warehouse=warehouse,
        source_run=inbound_run,
        external_inbound_id="IN-1",
        external_line_id="1",
        inbound_type="return",
        source_sku="SKU-1",
        planned_quantity=1,
        received_quantity=1,
        status="received",
        updated_at_utc=NOW,
    )
    _, shipment_run = run_for(tenant, "shipment", "return-shipment")
    shipment = ShipmentRecord.objects.create(
        tenant=tenant,
        platform=platform,
        store=store,
        source_run=shipment_run,
        external_shipment_id="SHIP-1",
        external_line_id="1",
        shipment_type="return",
        source_sku="SKU-1",
        tracking_reference_masked="***1234",
        quantity=1,
        status="delivered",
        updated_at_utc=NOW,
    )
    assert RefundReturn.objects.count() == 0
    assert inbound.refund_returns.count() == 0
    assert shipment.refund_returns.count() == 0


@pytest.mark.django_db
def test_fact_foreign_keys_are_protected():
    tenant, _, store, _ = scope("protect")
    _, run = run_for(tenant, "sales_order", "protect")
    upsert_normalized_order(tenant=tenant, payload=order_payload(store), source_run=run)
    with pytest.raises(ProtectedError):
        store.delete()
    with pytest.raises(ProtectedError):
        run.delete()


@pytest.mark.django_db
def test_cross_tenant_relations_are_rejected():
    tenant, platform, store, _ = scope("tenant-a")
    other, _, _, _ = scope("tenant-b")
    authorization, run = run_for(other, "sales_order", "wrong-tenant")
    with pytest.raises(ValidationError, match="same tenant"):
        SalesOrder.objects.create(
            tenant=tenant,
            platform=platform,
            store=store,
            authorization=authorization,
            source_run=run,
            external_order_id="ORDER-X",
            raw_status="PENDING",
            normalized_status="pending",
            status_mapping_version="1.0",
            created_at_utc=NOW,
            updated_at_utc=NOW,
            business_date=NOW.date(),
            currency="PHP",
            payload_hash="c" * 64,
        )
