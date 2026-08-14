import hashlib
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.integrations.models import PlatformChoices, payload_resource_family
from apps.tenants.models import Tenant
from apps.common.validated_models import ValidatedWriteModel


class CanonicalOrderStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    FULFILLED = "fulfilled", "Fulfilled"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class MatchStatus(models.TextChoices):
    UNMATCHED = "unmatched", "Unmatched"
    MATCHED = "matched", "Matched"
    CONFIRMED = "confirmed", "Confirmed"


def _validate_tenant_relations(instance, *field_names):
    errors = {}
    for field_name in field_names:
        related = getattr(instance, field_name, None)
        if related is not None and related.tenant_id != instance.tenant_id:
            errors[field_name] = "Related object must belong to the same tenant."
    if errors:
        raise ValidationError(errors)


def _validate_store_platform(instance):
    if instance.store_id and instance.store.platform.platform_type != instance.platform:
        raise ValidationError({"platform": "Platform must match the store platform."})


class SalesOrder(ValidatedWriteModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="commerce_sales_orders")
    store = models.ForeignKey("masterdata.StoreMaster", on_delete=models.PROTECT, related_name="commerce_sales_orders")
    integration_config = models.ForeignKey(
        "integrations.PlatformIntegrationConfig",
        on_delete=models.PROTECT,
        related_name="commerce_sales_orders",
        null=True,
        blank=True,
    )
    source_run = models.ForeignKey(
        "integrations.SyncRun", on_delete=models.SET_NULL, related_name="commerce_sales_orders", null=True, blank=True
    )
    raw_payload = models.ForeignKey(
        "integrations.RawPayload", on_delete=models.SET_NULL, related_name="sales_orders", null=True, blank=True
    )
    platform = models.CharField(max_length=30, choices=PlatformChoices.choices)
    region = models.CharField(max_length=40, blank=True)
    external_order_id = models.CharField(max_length=191)
    raw_status = models.CharField(max_length=80)
    canonical_status = models.CharField(max_length=40, choices=CanonicalOrderStatus.choices)
    fulfillment_type = models.CharField(max_length=40, blank=True)
    created_at_utc = models.DateTimeField()
    paid_at_utc = models.DateTimeField(null=True, blank=True)
    updated_at_utc = models.DateTimeField()
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
    buyer_reference_hash = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "commerce_sales_order"
        ordering = ["-created_at_utc", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform", "store", "external_order_id"], name="uniq_comm_order_ext"
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
                name="comm_order_amounts_nonneg",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "store", "created_at_utc"], name="idx_comm_order_store_time"),
            models.Index(fields=["tenant", "canonical_status", "updated_at_utc"], name="idx_comm_order_status_time"),
        ]

    def clean(self):
        super().clean()
        _validate_tenant_relations(self, "store", "integration_config", "source_run", "raw_payload")
        _validate_store_platform(self)
        errors = {}
        if self.integration_config_id and self.integration_config.platform != self.platform:
            errors["integration_config"] = "Integration configuration must match the order platform."
        if self.source_run_id and self.source_run.sync_job.integration_config.platform != self.platform:
            errors["source_run"] = "Sync run must match the order platform."
        if self.source_run_id and self.source_run.sync_job.resource_type != "sales_order":
            errors["source_run"] = "Order sync run must use the sales_order resource type."
        if self.integration_config_id and self.source_run_id:
            if self.source_run.sync_job.integration_config_id != self.integration_config_id:
                errors["source_run"] = "Sync run must belong to the selected integration configuration."
        if self.raw_payload_id:
            if self.raw_payload.store_id != self.store_id or self.raw_payload.platform != self.platform:
                errors["raw_payload"] = "Raw payload must match the order store and platform."
            if payload_resource_family(self.raw_payload.resource_type) != "sales_order":
                errors["raw_payload"] = "Order raw payload must use the sales_order resource family."
            if self.source_run_id and self.raw_payload.sync_run_id != self.source_run_id:
                errors["raw_payload"] = "Raw payload must belong to the selected sync run."
        if errors:
            raise ValidationError(errors)


class SalesOrderItem(ValidatedWriteModel):
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="items")
    internal_spu = models.ForeignKey(
        "products.ProductSPU", on_delete=models.PROTECT, related_name="commerce_order_items", null=True, blank=True
    )
    internal_sku = models.ForeignKey(
        "products.ProductSKU", on_delete=models.PROTECT, related_name="commerce_order_items", null=True, blank=True
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

    class Meta:
        db_table = "commerce_sales_order_item"
        ordering = ["order_id", "id"]
        constraints = [
            models.UniqueConstraint(fields=["order", "external_line_id"], name="uniq_comm_order_line_ext"),
            models.CheckConstraint(
                condition=(
                    models.Q(original_unit_price__gte=0)
                    & models.Q(sale_unit_price__gte=0)
                    & models.Q(discount_amount__gte=0)
                    & models.Q(tax_amount__gte=0)
                    & models.Q(line_total_amount__gte=0)
                ),
                name="comm_order_item_amt_nonneg",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.internal_spu_id and self.internal_spu.tenant_id != self.order.tenant_id:
            errors["internal_spu"] = "SPU must belong to the order tenant."
        if self.internal_sku_id and self.internal_sku.tenant_id != self.order.tenant_id:
            errors["internal_sku"] = "SKU must belong to the order tenant."
        if self.internal_spu_id and self.internal_sku_id and self.internal_sku.spu_id != self.internal_spu_id:
            errors["internal_sku"] = "SKU must belong to the selected SPU."
        if errors:
            raise ValidationError(errors)


class RefundReturn(ValidatedWriteModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="commerce_refund_returns")
    store = models.ForeignKey("masterdata.StoreMaster", on_delete=models.PROTECT, related_name="commerce_refund_returns")
    order = models.ForeignKey(SalesOrder, on_delete=models.SET_NULL, related_name="refund_returns", null=True, blank=True)
    source_run = models.ForeignKey(
        "integrations.SyncRun", on_delete=models.SET_NULL, related_name="commerce_refund_returns", null=True, blank=True
    )
    raw_payload = models.ForeignKey(
        "integrations.RawPayload", on_delete=models.SET_NULL, related_name="refund_returns", null=True, blank=True
    )
    platform = models.CharField(max_length=30, choices=PlatformChoices.choices)
    external_refund_id = models.CharField(max_length=191, blank=True)
    external_return_id = models.CharField(max_length=191)
    case_type = models.CharField(max_length=40)
    raw_status = models.CharField(max_length=80)
    canonical_status = models.CharField(max_length=40)
    arbitration_status = models.CharField(max_length=40, blank=True)
    reason_code = models.CharField(max_length=80, blank=True)
    reason_text = models.CharField(max_length=240, blank=True)
    responsible_party = models.CharField(max_length=40, blank=True)
    requested_at_utc = models.DateTimeField()
    approved_at_utc = models.DateTimeField(null=True, blank=True)
    completed_at_utc = models.DateTimeField(null=True, blank=True)
    source_updated_at_utc = models.DateTimeField()
    currency = models.CharField(max_length=8)
    refund_amount = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    refund_subtotal = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    refund_shipping_fee = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    refund_tax = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    return_tracking_reference_hash = models.CharField(max_length=64, blank=True)
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "commerce_refund_return"
        ordering = ["-requested_at_utc", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform", "store", "external_return_id"], name="uniq_comm_return_ext"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(refund_amount__gte=0)
                    & models.Q(refund_subtotal__gte=0)
                    & models.Q(refund_shipping_fee__gte=0)
                    & models.Q(refund_tax__gte=0)
                ),
                name="comm_return_amounts_nonneg",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "store", "requested_at_utc"], name="idx_comm_return_store_time"),
            models.Index(fields=["tenant", "canonical_status"], name="idx_comm_return_status"),
            models.Index(fields=["tenant", "source_updated_at_utc"], name="idx_comm_return_updated"),
        ]

    def clean(self):
        super().clean()
        _validate_tenant_relations(self, "store", "order", "source_run", "raw_payload")
        _validate_store_platform(self)
        errors = {}
        if self.order_id and self.order.store_id != self.store_id:
            errors["order"] = "Refund order must belong to the same store."
        if self.order_id and self.order.platform != self.platform:
            errors["order"] = "Refund order must use the same platform."
        if self.source_run_id and self.source_run.sync_job.integration_config.platform != self.platform:
            errors["source_run"] = "Sync run must match the refund platform."
        if self.source_run_id and self.source_run.sync_job.resource_type != "refund_return":
            errors["source_run"] = "Refund sync run must use the refund_return resource type."
        if self.raw_payload_id:
            if self.raw_payload.store_id != self.store_id or self.raw_payload.platform != self.platform:
                errors["raw_payload"] = "Raw payload must match the refund store and platform."
            if payload_resource_family(self.raw_payload.resource_type) != "refund_return":
                errors["raw_payload"] = "Refund raw payload must use the refund_return resource family."
            if self.source_run_id and self.raw_payload.sync_run_id != self.source_run_id:
                errors["raw_payload"] = "Raw payload must belong to the selected sync run."
        if errors:
            raise ValidationError(errors)


class RefundReturnItem(ValidatedWriteModel):
    refund_return = models.ForeignKey(RefundReturn, on_delete=models.CASCADE, related_name="items")
    order_item = models.ForeignKey(
        SalesOrderItem, on_delete=models.SET_NULL, related_name="refund_items", null=True, blank=True
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

    class Meta:
        db_table = "commerce_refund_return_item"
        ordering = ["refund_return_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["refund_return", "external_return_item_id"], name="uniq_comm_return_item_ext"
            ),
            models.CheckConstraint(condition=models.Q(refund_amount__gte=0), name="comm_return_item_amt_nonneg"),
        ]

    def clean(self):
        super().clean()
        tenant_id = self.refund_return.tenant_id
        errors = {}
        if self.order_item_id and self.order_item.order.tenant_id != tenant_id:
            errors["order_item"] = "Order item must belong to the refund tenant."
        if self.order_item_id:
            if not self.refund_return.order_id or self.order_item.order_id != self.refund_return.order_id:
                errors["order_item"] = "Order item must belong to the refund order."
        if self.internal_sku_id and self.internal_sku.tenant_id != tenant_id:
            errors["internal_sku"] = "SKU must belong to the refund tenant."
        if self.internal_sku_id and self.order_item_id and self.order_item.internal_sku_id:
            if self.internal_sku_id != self.order_item.internal_sku_id:
                errors["internal_sku"] = "Refund SKU must match the linked order item."
        if errors:
            raise ValidationError(errors)


class InventorySnapshot(ValidatedWriteModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="commerce_inventory_snapshots")
    store = models.ForeignKey("masterdata.StoreMaster", on_delete=models.PROTECT, related_name="commerce_inventory_snapshots")
    warehouse = models.ForeignKey(
        "masterdata.WarehouseMaster", on_delete=models.PROTECT, related_name="commerce_inventory_snapshots", null=True, blank=True
    )
    internal_sku = models.ForeignKey(
        "products.ProductSKU", on_delete=models.PROTECT, related_name="commerce_inventory_snapshots", null=True, blank=True
    )
    source_run = models.ForeignKey(
        "integrations.SyncRun", on_delete=models.SET_NULL, related_name="commerce_inventory_snapshots", null=True, blank=True
    )
    raw_payload = models.ForeignKey(
        "integrations.RawPayload", on_delete=models.SET_NULL, related_name="inventory_snapshots", null=True, blank=True
    )
    platform = models.CharField(max_length=30, choices=PlatformChoices.choices)
    platform_product_id = models.CharField(max_length=191, blank=True)
    platform_variant_id = models.CharField(max_length=191, blank=True)
    seller_sku = models.CharField(max_length=191, blank=True)
    snapshot_key = models.CharField(max_length=64, blank=True, editable=False)
    on_hand_qty = models.PositiveBigIntegerField(default=0)
    available_qty = models.PositiveBigIntegerField(default=0)
    reserved_qty = models.PositiveBigIntegerField(default=0)
    in_transit_qty = models.PositiveBigIntegerField(default=0)
    pending_putaway_qty = models.PositiveBigIntegerField(default=0)
    defective_qty = models.PositiveBigIntegerField(default=0)
    snapshot_at_utc = models.DateTimeField()
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "commerce_inventory_snapshot"
        ordering = ["-snapshot_at_utc", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "snapshot_key", "snapshot_at_utc"], name="uniq_comm_inventory_snapshot"
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "store", "snapshot_at_utc"], name="idx_comm_inventory_store"),
            models.Index(fields=["tenant", "seller_sku", "snapshot_at_utc"], name="idx_comm_inventory_sku"),
        ]

    def clean(self):
        super().clean()
        _validate_tenant_relations(self, "store", "warehouse", "internal_sku", "source_run", "raw_payload")
        _validate_store_platform(self)
        dimensions = {
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "warehouse_id": self.warehouse_id,
            "internal_sku_id": self.internal_sku_id,
            "platform": self.platform.strip().lower(),
            "platform_product_id": self.platform_product_id.strip(),
            "platform_variant_id": self.platform_variant_id.strip(),
            "seller_sku": self.seller_sku.strip(),
        }
        self.snapshot_key = hashlib.sha256(
            json.dumps(dimensions, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        errors = {}
        if self.source_run_id and self.source_run.sync_job.integration_config.platform != self.platform:
            errors["source_run"] = "Sync run must match the inventory platform."
        if self.source_run_id and self.source_run.sync_job.resource_type != "inventory":
            errors["source_run"] = "Inventory sync run must use the inventory resource type."
        if self.raw_payload_id:
            if self.raw_payload.store_id != self.store_id or self.raw_payload.platform != self.platform:
                errors["raw_payload"] = "Raw payload must match the inventory store and platform."
            if payload_resource_family(self.raw_payload.resource_type) != "inventory":
                errors["raw_payload"] = "Inventory raw payload must use the inventory resource family."
            if self.source_run_id and self.raw_payload.sync_run_id != self.source_run_id:
                errors["raw_payload"] = "Raw payload must belong to the selected sync run."
        if errors:
            raise ValidationError(errors)

    def validated_update_fields(self, update_fields):
        if update_fields is None:
            return None
        return set(update_fields) | {"snapshot_key"}


class MarketplaceProductMapping(ValidatedWriteModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="commerce_product_mappings")
    store = models.ForeignKey("masterdata.StoreMaster", on_delete=models.PROTECT, related_name="commerce_product_mappings")
    internal_spu = models.ForeignKey(
        "products.ProductSPU", on_delete=models.PROTECT, related_name="commerce_marketplace_mappings", null=True, blank=True
    )
    platform = models.CharField(max_length=30, choices=PlatformChoices.choices)
    platform_product_id = models.CharField(max_length=191)
    seller_sku = models.CharField(max_length=191, blank=True)
    match_status = models.CharField(max_length=20, choices=MatchStatus.choices, default=MatchStatus.UNMATCHED)
    match_method = models.CharField(max_length=40, blank=True)
    confidence = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="confirmed_commerce_products", null=True, blank=True
    )
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "commerce_marketplace_product_mapping"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "store", "platform", "platform_product_id"], name="uniq_comm_product_mapping"
            ),
        ]

    def clean(self):
        super().clean()
        _validate_tenant_relations(self, "store", "internal_spu", "confirmed_by")
        _validate_store_platform(self)


class MarketplaceSkuMapping(ValidatedWriteModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="commerce_sku_mappings")
    store = models.ForeignKey("masterdata.StoreMaster", on_delete=models.PROTECT, related_name="commerce_sku_mappings")
    internal_sku = models.ForeignKey(
        "products.ProductSKU", on_delete=models.PROTECT, related_name="commerce_marketplace_mappings", null=True, blank=True
    )
    platform = models.CharField(max_length=30, choices=PlatformChoices.choices)
    platform_product_id = models.CharField(max_length=191)
    platform_variant_id = models.CharField(max_length=191)
    seller_sku = models.CharField(max_length=191, blank=True)
    match_status = models.CharField(max_length=20, choices=MatchStatus.choices, default=MatchStatus.UNMATCHED)
    match_method = models.CharField(max_length=40, blank=True)
    confidence = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="confirmed_commerce_skus", null=True, blank=True
    )
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "commerce_marketplace_sku_mapping"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "store", "platform", "platform_variant_id"], name="uniq_comm_sku_mapping"
            ),
        ]

    def clean(self):
        super().clean()
        _validate_tenant_relations(self, "store", "internal_sku", "confirmed_by")
        _validate_store_platform(self)
