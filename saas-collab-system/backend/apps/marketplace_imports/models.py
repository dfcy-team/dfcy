import contextlib
import contextvars

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.integrations.models import MarketplaceProductMapping, MarketplaceStoreMapping, PlatformChoices
from apps.tenants.models import Tenant


_import_service_write = contextvars.ContextVar("marketplace_import_service_write", default=False)


@contextlib.contextmanager
def import_service_write():
    token = _import_service_write.set(True)
    try:
        yield
    finally:
        _import_service_write.reset(token)


class ProtectedImportQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if not _import_service_write.get():
            raise ValidationError("Marketplace import records can only be changed by the import service.")
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        if not _import_service_write.get():
            raise ValidationError("Marketplace import records can only be created by the import service.")
        return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if not _import_service_write.get():
            raise ValidationError("Marketplace import records can only be changed by the import service.")
        return super().bulk_update(objs, fields, batch_size=batch_size)

    def delete(self):
        raise ValidationError("Marketplace import evidence cannot be bulk deleted.")


class ProtectedImportModel(models.Model):
    objects = ProtectedImportQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not _import_service_write.get():
            raise ValidationError("Marketplace import records require the import service.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Marketplace import evidence cannot be deleted.")


class ImportResourceType(models.TextChoices):
    ORDERS = "orders", "Orders"
    INVENTORY = "inventory", "Inventory"


class MarketplaceImportCursor(ProtectedImportModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="marketplace_import_cursors")
    store_mapping = models.ForeignKey(
        MarketplaceStoreMapping,
        on_delete=models.PROTECT,
        related_name="import_cursors",
    )
    resource_type = models.CharField(max_length=20, choices=ImportResourceType.choices)
    cursor = models.CharField(max_length=500, blank=True)
    watermark = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=0)
    last_batch = models.ForeignKey(
        "MarketplaceImportBatch",
        on_delete=models.PROTECT,
        related_name="advanced_cursors",
        null=True,
        blank=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "store_mapping", "resource_type"],
                name="uniq_market_import_cursor",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "resource_type"], name="idx_market_cursor_resource")]

    def clean(self):
        if self.store_mapping_id and self.store_mapping.tenant_id != self.tenant_id:
            raise ValidationError("Import cursor and store mapping must belong to the same tenant.")


class MarketplaceImportBatch(ProtectedImportModel):
    class Mode(models.TextChoices):
        INITIAL = "initial", "Initial"
        INCREMENTAL = "incremental", "Incremental"

    class Status(models.TextChoices):
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    class SourceMode(models.TextChoices):
        SYNTHETIC_CONTRACT = "synthetic_contract", "Synthetic normalized contract"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="marketplace_import_batches")
    store_mapping = models.ForeignKey(
        MarketplaceStoreMapping,
        on_delete=models.PROTECT,
        related_name="import_batches",
    )
    platform = models.CharField(
        max_length=30,
        choices=[(PlatformChoices.SHOPEE, "Shopee"), (PlatformChoices.TIKTOK, "TikTok")],
    )
    resource_type = models.CharField(max_length=20, choices=ImportResourceType.choices)
    import_mode = models.CharField(max_length=20, choices=Mode.choices)
    source_mode = models.CharField(
        max_length=30,
        choices=SourceMode.choices,
        default=SourceMode.SYNTHETIC_CONTRACT,
    )
    contract_version = models.CharField(max_length=40)
    idempotency_key_hash = models.CharField(max_length=64)
    payload_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROCESSING)
    cursor_before = models.CharField(max_length=500, blank=True)
    cursor_after = models.CharField(max_length=500)
    watermark_before = models.DateTimeField(null=True, blank=True)
    watermark_after = models.DateTimeField(null=True, blank=True)
    received_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    controlled_error_code = models.CharField(max_length=80, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_marketplace_import_batches",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "store_mapping", "resource_type", "idempotency_key_hash"],
                name="uniq_market_import_idempotency",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "resource_type", "status"], name="idx_market_batch_status"),
        ]

    def clean(self):
        if self.store_mapping_id and self.store_mapping.tenant_id != self.tenant_id:
            raise ValidationError("Import batch and store mapping must belong to the same tenant.")
        if self.store_mapping_id and self.store_mapping.platform != self.platform:
            raise ValidationError("Import batch platform must come from the store mapping.")


class MarketplaceOrder(ProtectedImportModel):
    class Status(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        READY_TO_SHIP = "ready_to_ship", "Ready to ship"
        SHIPPED = "shipped", "Shipped"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="marketplace_orders")
    store_mapping = models.ForeignKey(MarketplaceStoreMapping, on_delete=models.PROTECT, related_name="orders")
    platform_order_id = models.CharField(max_length=160)
    status = models.CharField(max_length=30, choices=Status.choices)
    currency = models.CharField(max_length=3)
    total_amount = models.DecimalField(max_digits=18, decimal_places=4)
    ordered_at = models.DateTimeField()
    platform_updated_at = models.DateTimeField()
    cancelled_at = models.DateTimeField(null=True, blank=True)
    line_items = models.JSONField(default=list)
    fingerprint = models.CharField(max_length=64)
    last_batch = models.ForeignKey(MarketplaceImportBatch, on_delete=models.PROTECT, related_name="orders")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-ordered_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["store_mapping", "platform_order_id"],
                name="uniq_market_order_platform_id",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status", "ordered_at"], name="idx_market_order_status"),
        ]

    def clean(self):
        errors = {}
        if self.store_mapping_id and self.store_mapping.tenant_id != self.tenant_id:
            errors["store_mapping"] = "Order and store mapping must belong to the same tenant."
        if self.last_batch_id and self.last_batch.tenant_id != self.tenant_id:
            errors["last_batch"] = "Order and import batch must belong to the same tenant."
        if self.currency != self.currency.upper() or len(self.currency) != 3:
            errors["currency"] = "Currency must be an uppercase ISO 4217 code."
        if self.status == self.Status.CANCELLED and not self.cancelled_at:
            errors["cancelled_at"] = "Cancelled orders require cancelled_at."
        if errors:
            raise ValidationError(errors)


class MarketplaceRefund(ProtectedImportModel):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="marketplace_refunds")
    order = models.ForeignKey(MarketplaceOrder, on_delete=models.PROTECT, related_name="refunds")
    platform_refund_id = models.CharField(max_length=160)
    status = models.CharField(max_length=20, choices=Status.choices)
    currency = models.CharField(max_length=3)
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    reason_code = models.CharField(max_length=80, blank=True)
    platform_updated_at = models.DateTimeField()
    fingerprint = models.CharField(max_length=64)
    last_batch = models.ForeignKey(MarketplaceImportBatch, on_delete=models.PROTECT, related_name="refunds")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["order", "platform_refund_id"],
                name="uniq_market_refund_platform_id",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "status"], name="idx_market_refund_status")]

    def clean(self):
        errors = {}
        if self.order_id and self.order.tenant_id != self.tenant_id:
            errors["order"] = "Refund and order must belong to the same tenant."
        if self.last_batch_id and self.last_batch.tenant_id != self.tenant_id:
            errors["last_batch"] = "Refund and import batch must belong to the same tenant."
        if self.currency != self.currency.upper() or len(self.currency) != 3:
            errors["currency"] = "Currency must be an uppercase ISO 4217 code."
        if errors:
            raise ValidationError(errors)


class MarketplaceInventorySnapshot(ProtectedImportModel):
    class MappingStatus(models.TextChoices):
        MAPPED = "mapped", "Mapped"
        UNMAPPED = "unmapped", "Unmapped"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="marketplace_inventory_snapshots")
    store_mapping = models.ForeignKey(
        MarketplaceStoreMapping,
        on_delete=models.PROTECT,
        related_name="inventory_snapshots",
    )
    product_mapping = models.ForeignKey(
        MarketplaceProductMapping,
        on_delete=models.PROTECT,
        related_name="inventory_snapshots",
        null=True,
        blank=True,
    )
    mapping_status = models.CharField(max_length=20, choices=MappingStatus.choices)
    platform_variant_id = models.CharField(max_length=160)
    platform_sku = models.CharField(max_length=160, blank=True)
    on_hand = models.IntegerField()
    reserved = models.IntegerField(default=0)
    available = models.IntegerField()
    incoming = models.IntegerField(default=0)
    observed_at = models.DateTimeField()
    fingerprint = models.CharField(max_length=64)
    last_batch = models.ForeignKey(
        MarketplaceImportBatch,
        on_delete=models.PROTECT,
        related_name="inventory_snapshots",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-observed_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["store_mapping", "platform_variant_id", "observed_at"],
                name="uniq_market_inventory_observation",
            ),
            models.CheckConstraint(condition=models.Q(on_hand__gte=0), name="market_inventory_on_hand_gte_0"),
            models.CheckConstraint(condition=models.Q(reserved__gte=0), name="market_inventory_reserved_gte_0"),
            models.CheckConstraint(condition=models.Q(available__gte=0), name="market_inventory_available_gte_0"),
            models.CheckConstraint(condition=models.Q(incoming__gte=0), name="market_inventory_incoming_gte_0"),
        ]
        indexes = [
            models.Index(fields=["tenant", "platform_variant_id", "observed_at"], name="idx_market_inventory_time"),
        ]

    def clean(self):
        errors = {}
        if self.store_mapping_id and self.store_mapping.tenant_id != self.tenant_id:
            errors["store_mapping"] = "Inventory and store mapping must belong to the same tenant."
        if self.product_mapping_id:
            if self.product_mapping.tenant_id != self.tenant_id:
                errors["product_mapping"] = "Inventory product mapping must belong to the same tenant."
            if self.product_mapping.store_mapping_id != self.store_mapping_id:
                errors["product_mapping"] = "Inventory product mapping must belong to the same store mapping."
            if self.product_mapping.platform_variant_id != self.platform_variant_id:
                errors["platform_variant_id"] = "Inventory variant must match the product mapping."
            if self.mapping_status != self.MappingStatus.MAPPED:
                errors["mapping_status"] = "Linked inventory must be marked as mapped."
        elif self.mapping_status != self.MappingStatus.UNMAPPED:
            errors["mapping_status"] = "Inventory without a product mapping must be marked as unmapped."
        if self.last_batch_id and self.last_batch.tenant_id != self.tenant_id:
            errors["last_batch"] = "Inventory and import batch must belong to the same tenant."
        if errors:
            raise ValidationError(errors)
