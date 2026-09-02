from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import models

from apps.accounts.models import CustomUser
from apps.commerce.models import (
    InboundRecord,
    InventorySnapshot,
    RefundReturn,
    RefundReturnItem,
    SalesOrder,
    SalesOrderItem,
    ShipmentRecord,
)
from apps.integrations.models import PlatformIntegrationConfig, SyncJob, SyncRun
from apps.masterdata.models import PlatformMaster, StoreMaster, WarehouseMaster
from apps.tenants.models import Tenant


NOW = datetime(2026, 8, 17, 8, 0, tzinfo=UTC)
HASH = "a" * 64


def create_tenant_scope(code="facts"):
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
    warehouse = WarehouseMaster.objects.create(
        tenant=tenant,
        code=f"warehouse-{code}",
        name=f"Warehouse {code}",
        country_code="PH",
        warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY,
    )
    return tenant, platform, store, warehouse


def create_run(tenant, resource_type, suffix, platform="shopee"):
    user = CustomUser.objects.create_user(
        username=f"source-{suffix}",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    authorization = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform=platform,
        account_alias=f"account-{suffix}",
        created_by=user,
    )
    job = SyncJob.objects.create(
        tenant=tenant,
        integration_config=authorization,
        resource_type=resource_type,
    )
    run = SyncRun.objects.create(
        tenant=tenant,
        sync_job=job,
        run_id=f"run-{suffix}",
        idempotency_key=f"key-{suffix}",
    )
    return authorization, run


def create_order(tenant, platform, store, suffix="1"):
    authorization, run = create_run(tenant, "sales_order", f"order-{suffix}")
    return SalesOrder.objects.create(
        tenant=tenant,
        platform=platform,
        store=store,
        authorization=authorization,
        source_run=run,
        external_order_id=f"ORDER-{suffix}",
        region="PH",
        raw_status="COMPLETED",
        normalized_status="completed",
        status_mapping_version="1.0",
        created_at_utc=NOW,
        updated_at_utc=NOW,
        business_date=date(2026, 8, 17),
        currency="PHP",
        subtotal_amount=Decimal("100.1234"),
        order_total_amount=Decimal("100.1234"),
        payload_hash=HASH,
    )


def test_only_seven_commerce_business_models_and_exact_table_names():
    expected = {
        SalesOrder: "sales_order",
        SalesOrderItem: "sales_order_item",
        InventorySnapshot: "inventory_snapshot",
        InboundRecord: "inbound_record",
        ShipmentRecord: "shipment_record",
        RefundReturn: "refund_return",
        RefundReturnItem: "refund_return_item",
    }
    assert {model._meta.db_table for model in expected} == set(expected.values())
    for model, table_name in expected.items():
        assert model._meta.db_table == table_name

    registered_models = apps.get_app_config("commerce").models
    for forbidden in (
        "marketplaceproductmapping",
        "marketplaceskumapping",
        "ingestionbatch",
        "ingestionrecord",
    ):
        assert forbidden not in registered_models


@pytest.mark.django_db
def test_order_identity_decimal_precision_and_protected_lineage():
    tenant, platform, store, _ = create_tenant_scope("order")
    order = create_order(tenant, platform, store)
    duplicate_values = {
        field.name: getattr(order, field.name)
        for field in order._meta.fields
        if field.name not in {"id", "ingested_at"}
    }
    with pytest.raises(ValidationError):
        SalesOrder.objects.create(**duplicate_values)

    for field_name in (
        "subtotal_amount",
        "seller_discount_amount",
        "platform_discount_amount",
        "shipping_amount",
        "tax_amount",
        "order_total_amount",
    ):
        field = SalesOrder._meta.get_field(field_name)
        assert (field.max_digits, field.decimal_places) == (20, 4)

    for field_name in ("tenant", "platform", "store", "authorization", "source_run"):
        assert SalesOrder._meta.get_field(field_name).remote_field.on_delete is models.PROTECT


@pytest.mark.django_db
def test_inventory_and_inbound_require_wms_lineage_and_keep_history():
    tenant, _, _, warehouse = create_tenant_scope("wms")
    _, inventory_run = create_run(tenant, "inventory_snapshot", "inventory", platform="jifeng_wms")
    first = InventorySnapshot.objects.create(
        tenant=tenant,
        site_code="PH",
        warehouse=warehouse,
        source_run=inventory_run,
        source_sku="SKU-001",
        seller_sku="SKU-001",
        available_qty=5,
        snapshot_at_utc=NOW,
        payload_hash=HASH,
    )
    InventorySnapshot.objects.create(
        tenant=tenant,
        site_code="PH",
        warehouse=warehouse,
        source_run=inventory_run,
        source_sku="SKU-001",
        seller_sku="SKU-001",
        available_qty=4,
        snapshot_at_utc=datetime(2026, 8, 17, 9, 0, tzinfo=UTC),
        payload_hash="b" * 64,
    )
    assert InventorySnapshot.objects.filter(tenant=tenant, source_sku="SKU-001").count() == 2
    assert first.available_qty == 5

    _, inbound_run = create_run(tenant, "inbound", "inbound", platform="jifeng_wms")
    inbound = InboundRecord.objects.create(
        tenant=tenant,
        site_code="PH",
        warehouse=warehouse,
        source_run=inbound_run,
        external_inbound_id="IN-001",
        external_line_id="1",
        inbound_type="return",
        source_sku="SKU-001",
        planned_quantity=1,
        received_quantity=1,
        status="received",
        updated_at_utc=NOW,
    )
    assert inbound.refund_returns.count() == 0


@pytest.mark.django_db
def test_refund_tri_state_optional_logistics_and_positive_item_quantity():
    tenant, platform, store, warehouse = create_tenant_scope("refund")
    order = create_order(tenant, platform, store, "refund")
    _, refund_run = create_run(tenant, "refund_return", "refund")
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
        refund_amount=Decimal("10.0000"),
        requires_physical_return=None,
        is_partial_quantity_return=True,
        is_refund_amount_adjusted=False,
        payload_hash=HASH,
    )
    assert refund.inbound_record_id is None
    assert refund.shipment_record_id is None
    assert refund.requires_physical_return is None
    for field_name in (
        "requires_physical_return",
        "is_partial_quantity_return",
        "is_refund_amount_adjusted",
    ):
        assert RefundReturn._meta.get_field(field_name).null is True

    with pytest.raises(ValidationError):
        RefundReturnItem.objects.create(
            refund_return=refund,
            external_return_item_id="RETURN-LINE-1",
            quantity=0,
            currency="PHP",
            refund_amount=Decimal("10.0000"),
        )
