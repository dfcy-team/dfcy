import re

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.validated_models import ValidatedWriteModel
from apps.tenants.models import Tenant


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class NormalizedOrderStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    FULFILLED = "fulfilled", "Fulfilled"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


def _validate_tenant_relations(instance, *field_names):
    errors = {}
    for field_name in field_names:
        related = getattr(instance, field_name, None)
        if related is not None and related.tenant_id != instance.tenant_id:
            errors[field_name] = "Related object must belong to the same tenant."
    return errors


def _validate_store_platform(instance):
    if instance.store_id and instance.platform_id and instance.store.platform_id != instance.platform_id:
        return {"platform": "Platform must match the store platform."}
    return {}


def _validate_source_run(instance, resource_type, platform_type=None):
    if not instance.source_run_id:
        return {}
    errors = {}
    job = instance.source_run.sync_job
    if job.resource_type != resource_type:
        errors["source_run"] = f"Sync run must use the {resource_type} resource type."
    elif platform_type and job.integration_config.platform != platform_type:
        errors["source_run"] = "Sync run platform must match the business record source."
    return errors


def _validate_hash(value):
    return bool(SHA256_PATTERN.fullmatch(value or ""))


def _validate_utc_fields(instance, *field_names):
    errors = {}
    for field_name in field_names:
        value = getattr(instance, field_name, None)
        if value is not None and (timezone.is_naive(value) or value.utcoffset().total_seconds() != 0):
            errors[field_name] = "A timezone-aware UTC timestamp is required."
    return errors


class SalesOrder(ValidatedWriteModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="commerce_fact_sales_orders")
    platform = models.ForeignKey(
        "masterdata.PlatformMaster", on_delete=models.PROTECT, related_name="commerce_fact_sales_orders"
    )
    store = models.ForeignKey(
        "masterdata.StoreMaster", on_delete=models.PROTECT, related_name="commerce_fact_sales_orders"
    )
    authorization = models.ForeignKey(
        "integrations.PlatformIntegrationConfig",
        on_delete=models.PROTECT,
        related_name="commerce_fact_sales_orders",
    )
    source_run = models.ForeignKey(
        "integrations.SyncRun",
        on_delete=models.PROTECT,
        related_name="commerce_fact_sales_orders",
        db_index=False,
    )
    external_order_id = models.CharField(max_length=191)
    region = models.CharField(max_length=40, blank=True)
    raw_status = models.CharField(max_length=80)
    normalized_status = models.CharField(max_length=40, choices=NormalizedOrderStatus.choices)
    status_mapping_version = models.CharField(max_length=40)
    created_at_utc = models.DateTimeField()
    updated_at_utc = models.DateTimeField()
    paid_at_utc = models.DateTimeField(null=True, blank=True)
    cancelled_at_utc = models.DateTimeField(null=True, blank=True)
    completed_at_utc = models.DateTimeField(null=True, blank=True)
    business_date = models.DateField()
    ingested_at = models.DateTimeField(auto_now_add=True)
    currency = models.CharField(max_length=8)
    subtotal_amount = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    seller_discount_amount = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    platform_discount_amount = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    shipping_amount = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    tax_amount = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    order_total_amount = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    payload_hash = models.CharField(max_length=64)

    class Meta:
        db_table = "sales_order"
        ordering = ["-created_at_utc", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform", "store", "external_order_id"],
                name="uniq_sales_order_external",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(subtotal_amount__gte=0)
                    & models.Q(seller_discount_amount__gte=0)
                    & models.Q(platform_discount_amount__gte=0)
                    & models.Q(shipping_amount__gte=0)
                    & models.Q(tax_amount__gte=0)
                    & models.Q(order_total_amount__gte=0)
                ),
                name="sales_order_amounts_nonneg",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "store", "created_at_utc"], name="idx_sales_order_store_time"),
            models.Index(
                fields=["tenant", "normalized_status", "updated_at_utc"],
                name="idx_sales_order_status_time",
            ),
            models.Index(fields=["source_run"], name="idx_sales_order_source_run"),
        ]

    def clean(self):
        super().clean()
        errors = _validate_tenant_relations(self, "platform", "store", "authorization", "source_run")
        errors.update(_validate_store_platform(self))
        errors.update(_validate_source_run(self, "sales_order", self.platform.platform_type if self.platform_id else None))
        errors.update(
            _validate_utc_fields(
                self,
                "created_at_utc",
                "updated_at_utc",
                "paid_at_utc",
                "cancelled_at_utc",
                "completed_at_utc",
            )
        )
        if self.authorization_id and self.platform_id:
            if self.authorization.platform != self.platform.platform_type:
                errors["authorization"] = "Authorization must match the order platform."
        if self.source_run_id and self.authorization_id:
            if self.source_run.sync_job.integration_config_id != self.authorization_id:
                errors["source_run"] = "Sync run must belong to the selected authorization."
        if self.currency != self.currency.upper():
            errors["currency"] = "Currency must use an uppercase code."
        if not _validate_hash(self.payload_hash):
            errors["payload_hash"] = "Payload hash must be a lowercase SHA-256 hexadecimal value."
        if errors:
            raise ValidationError(errors)


class SalesOrderItem(ValidatedWriteModel):
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="items")
    internal_spu = models.ForeignKey(
        "products.ProductSPU", on_delete=models.PROTECT, related_name="commerce_fact_order_items", null=True, blank=True
    )
    internal_sku = models.ForeignKey(
        "products.ProductSKU", on_delete=models.PROTECT, related_name="commerce_fact_order_items", null=True, blank=True
    )
    external_line_id = models.CharField(max_length=191)
    platform_product_id = models.CharField(max_length=191)
    platform_variant_id = models.CharField(max_length=191, blank=True)
    seller_sku = models.CharField(max_length=191, blank=True)
    item_name_snapshot = models.CharField(max_length=240, blank=True)
    variation_snapshot = models.CharField(max_length=240, blank=True)
    quantity = models.PositiveIntegerField()
    original_unit_price = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    sale_unit_price = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    discount_amount = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    tax_amount = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    line_total_amount = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    currency = models.CharField(max_length=8)
    raw_line_status = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sales_order_item"
        ordering = ["sales_order_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["sales_order", "external_line_id"], name="uniq_sales_order_item_ext"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(quantity__gt=0)
                    & models.Q(original_unit_price__gte=0)
                    & models.Q(sale_unit_price__gte=0)
                    & models.Q(discount_amount__gte=0)
                    & models.Q(tax_amount__gte=0)
                    & models.Q(line_total_amount__gte=0)
                ),
                name="sales_order_item_values",
            ),
        ]
        indexes = [
            models.Index(fields=["sales_order", "seller_sku"], name="idx_sales_item_seller_sku"),
        ]

    def clean(self):
        super().clean()
        tenant_id = self.sales_order.tenant_id
        errors = {}
        if self.internal_spu_id and self.internal_spu.tenant_id != tenant_id:
            errors["internal_spu"] = "SPU must belong to the order tenant."
        if self.internal_sku_id and self.internal_sku.tenant_id != tenant_id:
            errors["internal_sku"] = "SKU must belong to the order tenant."
        if self.internal_spu_id and self.internal_sku_id and self.internal_sku.spu_id != self.internal_spu_id:
            errors["internal_sku"] = "SKU must belong to the selected SPU."
        if self.currency != self.sales_order.currency:
            errors["currency"] = "Order item currency must match the order currency."
        if errors:
            raise ValidationError(errors)


class InventorySnapshot(ValidatedWriteModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="commerce_inventory_snapshots")
    site_code = models.CharField(max_length=20)
    warehouse = models.ForeignKey(
        "masterdata.WarehouseMaster", on_delete=models.PROTECT, related_name="commerce_inventory_snapshots"
    )
    internal_sku = models.ForeignKey(
        "products.ProductSKU",
        on_delete=models.PROTECT,
        related_name="commerce_inventory_snapshots",
        null=True,
        blank=True,
    )
    source_run = models.ForeignKey(
        "integrations.SyncRun",
        on_delete=models.PROTECT,
        related_name="commerce_inventory_snapshots",
        db_index=False,
    )
    source_sku = models.CharField(max_length=191)
    platform_product_id = models.CharField(max_length=191, blank=True)
    platform_variant_id = models.CharField(max_length=191, blank=True)
    seller_sku = models.CharField(max_length=191, blank=True)
    on_hand_qty = models.PositiveBigIntegerField(default=0)
    available_qty = models.PositiveBigIntegerField(default=0)
    reserved_qty = models.PositiveBigIntegerField(default=0)
    in_transit_qty = models.PositiveBigIntegerField(default=0)
    pending_putaway_qty = models.PositiveBigIntegerField(default=0)
    defective_qty = models.PositiveBigIntegerField(default=0)
    snapshot_at_utc = models.DateTimeField()
    payload_hash = models.CharField(max_length=64)
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inventory_snapshot"
        ordering = ["-snapshot_at_utc", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "site_code", "warehouse", "source_sku", "snapshot_at_utc"],
                name="uniq_inventory_snapshot",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(on_hand_qty__gte=0)
                    & models.Q(available_qty__gte=0)
                    & models.Q(reserved_qty__gte=0)
                    & models.Q(in_transit_qty__gte=0)
                    & models.Q(pending_putaway_qty__gte=0)
                    & models.Q(defective_qty__gte=0)
                ),
                name="inventory_qty_nonnegative",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "site_code", "snapshot_at_utc"], name="idx_inventory_site_time"),
            models.Index(fields=["tenant", "source_sku", "snapshot_at_utc"], name="idx_inventory_sku_time"),
            models.Index(fields=["source_run"], name="idx_inventory_source_run"),
        ]

    def clean(self):
        super().clean()
        errors = _validate_tenant_relations(self, "warehouse", "internal_sku", "source_run")
        errors.update(_validate_source_run(self, "inventory_snapshot", "jifeng_wms"))
        errors.update(_validate_utc_fields(self, "snapshot_at_utc"))
        if self.warehouse_id and self.site_code.upper() != self.warehouse.country_code.upper():
            errors["site_code"] = "Site code must match the warehouse country code."
        if not _validate_hash(self.payload_hash):
            errors["payload_hash"] = "Payload hash must be a lowercase SHA-256 hexadecimal value."
        if errors:
            raise ValidationError(errors)


class InboundRecord(ValidatedWriteModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="commerce_inbound_records")
    site_code = models.CharField(max_length=20)
    warehouse = models.ForeignKey(
        "masterdata.WarehouseMaster", on_delete=models.PROTECT, related_name="commerce_inbound_records"
    )
    internal_sku = models.ForeignKey(
        "products.ProductSKU", on_delete=models.PROTECT, related_name="commerce_inbound_records", null=True, blank=True
    )
    source_run = models.ForeignKey(
        "integrations.SyncRun", on_delete=models.PROTECT, related_name="commerce_inbound_records", db_index=False
    )
    external_inbound_id = models.CharField(max_length=191)
    external_line_id = models.CharField(max_length=191)
    inbound_type = models.CharField(max_length=40)
    source_sku = models.CharField(max_length=191)
    planned_quantity = models.PositiveBigIntegerField(default=0)
    received_quantity = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=40)
    expected_at_utc = models.DateTimeField(null=True, blank=True)
    received_at_utc = models.DateTimeField(null=True, blank=True)
    updated_at_utc = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inbound_record"
        ordering = ["-updated_at_utc", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "site_code", "warehouse", "external_inbound_id", "external_line_id"],
                name="uniq_inbound_record_line",
            ),
            models.CheckConstraint(
                condition=models.Q(planned_quantity__gte=0) & models.Q(received_quantity__gte=0),
                name="inbound_qty_nonnegative",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "site_code", "updated_at_utc"], name="idx_inbound_site_time"),
            models.Index(fields=["tenant", "source_sku", "updated_at_utc"], name="idx_inbound_sku_time"),
            models.Index(fields=["source_run"], name="idx_inbound_source_run"),
        ]

    def clean(self):
        super().clean()
        errors = _validate_tenant_relations(self, "warehouse", "internal_sku", "source_run")
        errors.update(_validate_source_run(self, "inbound", "jifeng_wms"))
        errors.update(_validate_utc_fields(self, "expected_at_utc", "received_at_utc", "updated_at_utc"))
        if self.warehouse_id and self.site_code.upper() != self.warehouse.country_code.upper():
            errors["site_code"] = "Site code must match the warehouse country code."
        if errors:
            raise ValidationError(errors)


class ShipmentRecord(ValidatedWriteModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="commerce_shipment_records")
    platform = models.ForeignKey(
        "masterdata.PlatformMaster", on_delete=models.PROTECT, related_name="commerce_shipment_records"
    )
    store = models.ForeignKey(
        "masterdata.StoreMaster", on_delete=models.PROTECT, related_name="commerce_shipment_records"
    )
    sales_order = models.ForeignKey(
        SalesOrder, on_delete=models.PROTECT, related_name="shipment_records", null=True, blank=True
    )
    sales_order_item = models.ForeignKey(
        SalesOrderItem, on_delete=models.PROTECT, related_name="shipment_records", null=True, blank=True
    )
    internal_sku = models.ForeignKey(
        "products.ProductSKU", on_delete=models.PROTECT, related_name="commerce_shipment_records", null=True, blank=True
    )
    source_run = models.ForeignKey(
        "integrations.SyncRun", on_delete=models.PROTECT, related_name="commerce_shipment_records", db_index=False
    )
    external_shipment_id = models.CharField(max_length=191)
    external_line_id = models.CharField(max_length=191)
    shipment_type = models.CharField(max_length=40)
    source_sku = models.CharField(max_length=191)
    carrier_code = models.CharField(max_length=80, blank=True)
    tracking_reference_masked = models.CharField(max_length=120, blank=True)
    quantity = models.PositiveBigIntegerField()
    status = models.CharField(max_length=40)
    shipped_at_utc = models.DateTimeField(null=True, blank=True)
    delivered_at_utc = models.DateTimeField(null=True, blank=True)
    updated_at_utc = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "shipment_record"
        ordering = ["-updated_at_utc", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform", "store", "external_shipment_id", "external_line_id"],
                name="uniq_shipment_record_line",
            ),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="shipment_quantity_positive"),
        ]
        indexes = [
            models.Index(fields=["tenant", "store", "updated_at_utc"], name="idx_shipment_store_time"),
            models.Index(fields=["tenant", "source_sku", "updated_at_utc"], name="idx_shipment_sku_time"),
            models.Index(fields=["source_run"], name="idx_shipment_source_run"),
        ]

    def clean(self):
        super().clean()
        errors = _validate_tenant_relations(
            self, "platform", "store", "sales_order", "internal_sku", "source_run"
        )
        errors.update(_validate_store_platform(self))
        errors.update(_validate_source_run(self, "shipment", self.platform.platform_type if self.platform_id else None))
        errors.update(_validate_utc_fields(self, "shipped_at_utc", "delivered_at_utc", "updated_at_utc"))
        if self.sales_order_id:
            if self.sales_order.store_id != self.store_id or self.sales_order.platform_id != self.platform_id:
                errors["sales_order"] = "Shipment order must match the shipment store and platform."
        if self.sales_order_item_id:
            if not self.sales_order_id or self.sales_order_item.sales_order_id != self.sales_order_id:
                errors["sales_order_item"] = "Shipment item must belong to the selected order."
        if self.internal_sku_id and self.sales_order_item_id and self.sales_order_item.internal_sku_id:
            if self.internal_sku_id != self.sales_order_item.internal_sku_id:
                errors["internal_sku"] = "Shipment SKU must match the selected order item."
        if errors:
            raise ValidationError(errors)


class RefundReturn(ValidatedWriteModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="commerce_refund_returns")
    platform = models.ForeignKey(
        "masterdata.PlatformMaster", on_delete=models.PROTECT, related_name="commerce_refund_returns"
    )
    store = models.ForeignKey(
        "masterdata.StoreMaster", on_delete=models.PROTECT, related_name="commerce_refund_returns"
    )
    sales_order = models.ForeignKey(
        SalesOrder, on_delete=models.PROTECT, related_name="refund_returns", null=True, blank=True
    )
    inbound_record = models.ForeignKey(
        InboundRecord, on_delete=models.PROTECT, related_name="refund_returns", null=True, blank=True
    )
    shipment_record = models.ForeignKey(
        ShipmentRecord, on_delete=models.PROTECT, related_name="refund_returns", null=True, blank=True
    )
    source_run = models.ForeignKey(
        "integrations.SyncRun", on_delete=models.PROTECT, related_name="commerce_refund_returns", db_index=False
    )
    external_return_id = models.CharField(max_length=191)
    external_refund_id = models.CharField(max_length=191, blank=True)
    case_type = models.CharField(max_length=40)
    raw_status = models.CharField(max_length=80)
    normalized_status = models.CharField(max_length=40)
    arbitration_status = models.CharField(max_length=40, blank=True)
    reason_code = models.CharField(max_length=80, blank=True)
    requested_at_utc = models.DateTimeField()
    updated_at_utc = models.DateTimeField()
    completed_at_utc = models.DateTimeField(null=True, blank=True)
    currency = models.CharField(max_length=8)
    refund_amount = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    refund_subtotal = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    refund_shipping_fee = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    refund_tax = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    requires_physical_return = models.BooleanField(null=True, blank=True)
    is_partial_quantity_return = models.BooleanField(null=True, blank=True)
    is_refund_amount_adjusted = models.BooleanField(null=True, blank=True)
    payload_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "refund_return"
        ordering = ["-requested_at_utc", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform", "store", "external_return_id"],
                name="uniq_refund_return_external",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(refund_amount__gte=0)
                    & models.Q(refund_subtotal__gte=0)
                    & models.Q(refund_shipping_fee__gte=0)
                    & models.Q(refund_tax__gte=0)
                ),
                name="refund_return_amounts_nonneg",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "store", "requested_at_utc"], name="idx_refund_store_time"),
            models.Index(fields=["tenant", "normalized_status", "updated_at_utc"], name="idx_refund_status_time"),
            models.Index(fields=["source_run"], name="idx_refund_source_run"),
        ]

    def clean(self):
        super().clean()
        errors = _validate_tenant_relations(
            self, "platform", "store", "sales_order", "inbound_record", "shipment_record", "source_run"
        )
        errors.update(_validate_store_platform(self))
        errors.update(_validate_source_run(self, "refund_return", self.platform.platform_type if self.platform_id else None))
        errors.update(_validate_utc_fields(self, "requested_at_utc", "updated_at_utc", "completed_at_utc"))
        if self.sales_order_id:
            if self.sales_order.store_id != self.store_id or self.sales_order.platform_id != self.platform_id:
                errors["sales_order"] = "Refund order must match the refund store and platform."
            elif self.sales_order.currency != self.currency:
                errors["currency"] = "Refund currency must match the linked order currency."
        if self.inbound_record_id and self.inbound_record.site_code.upper() != self.store.country_code.upper():
            errors["inbound_record"] = "Return inbound site must match the refund store country."
        if self.shipment_record_id:
            if self.shipment_record.store_id != self.store_id or self.shipment_record.platform_id != self.platform_id:
                errors["shipment_record"] = "Return shipment must match the refund store and platform."
        if not _validate_hash(self.payload_hash):
            errors["payload_hash"] = "Payload hash must be a lowercase SHA-256 hexadecimal value."
        if errors:
            raise ValidationError(errors)


class RefundReturnItem(ValidatedWriteModel):
    refund_return = models.ForeignKey(RefundReturn, on_delete=models.PROTECT, related_name="items")
    sales_order_item = models.ForeignKey(
        SalesOrderItem, on_delete=models.PROTECT, related_name="refund_items", null=True, blank=True
    )
    internal_sku = models.ForeignKey(
        "products.ProductSKU", on_delete=models.PROTECT, related_name="commerce_refund_items", null=True, blank=True
    )
    external_return_item_id = models.CharField(max_length=191)
    external_order_item_id = models.CharField(max_length=191, blank=True)
    platform_product_id = models.CharField(max_length=191, blank=True)
    platform_variant_id = models.CharField(max_length=191, blank=True)
    seller_sku = models.CharField(max_length=191, blank=True)
    item_name_snapshot = models.CharField(max_length=240, blank=True)
    quantity = models.PositiveIntegerField()
    currency = models.CharField(max_length=8)
    refund_amount = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "refund_return_item"
        ordering = ["refund_return_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["refund_return", "external_return_item_id"],
                name="uniq_refund_return_item_ext",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0) & models.Q(refund_amount__gte=0),
                name="refund_item_values_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["refund_return", "seller_sku"], name="idx_refund_item_seller_sku"),
        ]

    def clean(self):
        super().clean()
        tenant_id = self.refund_return.tenant_id
        errors = {}
        if self.sales_order_item_id:
            if self.sales_order_item.sales_order.tenant_id != tenant_id:
                errors["sales_order_item"] = "Order item must belong to the refund tenant."
            elif not self.refund_return.sales_order_id:
                errors["sales_order_item"] = "A linked order item requires a linked refund order."
            elif self.sales_order_item.sales_order_id != self.refund_return.sales_order_id:
                errors["sales_order_item"] = "Order item must belong to the refund order."
        if self.internal_sku_id and self.internal_sku.tenant_id != tenant_id:
            errors["internal_sku"] = "SKU must belong to the refund tenant."
        if self.internal_sku_id and self.sales_order_item_id and self.sales_order_item.internal_sku_id:
            if self.internal_sku_id != self.sales_order_item.internal_sku_id:
                errors["internal_sku"] = "Refund SKU must match the linked order item."
        if self.currency != self.refund_return.currency:
            errors["currency"] = "Refund item currency must match the refund currency."
        if self.sales_order_item_id and self.external_order_item_id:
            if self.external_order_item_id != self.sales_order_item.external_line_id:
                errors["external_order_item_id"] = "External order item ID must match the linked order item."
        if errors:
            raise ValidationError(errors)
