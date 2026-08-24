from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.masterdata.models import SupplierMaster
from apps.products.models import ProductSKU
from apps.tenants.models import Tenant


_supply_action_write_depth = ContextVar("supply_action_write_depth", default=0)


@contextmanager
def _supply_action_write_context():
    token = _supply_action_write_depth.set(_supply_action_write_depth.get() + 1)
    try:
        yield
    finally:
        _supply_action_write_depth.reset(token)


def _supply_action_write_allowed():
    return _supply_action_write_depth.get() > 0


class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CONFIRMED = "confirmed", "Confirmed"
        IN_PRODUCTION = "in_production", "In production"
        SHIPPED = "shipped", "Shipped"
        CANCELLED = "cancelled", "Cancelled"

    class ApprovalStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="purchase_orders")
    po_no = models.CharField(max_length=80)
    sku_code = models.CharField(max_length=80)
    supplier_id = models.BigIntegerField()
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    delivery_date = models.DateField(null=True, blank=True)
    payment_terms = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT)
    approval_status = models.CharField(
        max_length=30,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_purchase_orders",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "po_no"], name="uniq_po_no_per_tenant"),
        ]

    def __str__(self):
        return self.po_no


class SupplyPurchaseOrderQuerySet(models.QuerySet):
    CONTROLLED_FIELDS = {
        "status",
        "shipping_route",
        "shipping_route_decided_at",
        "shipping_route_decided_by",
        "shipping_route_decided_by_id",
        "accepted_at",
        "production_started_at",
        "production_completed_at",
        "completed_quantity",
        "version",
    }

    def update(self, **kwargs):
        if set(kwargs) & self.CONTROLLED_FIELDS:
            raise ValidationError("Supply purchase order state requires the audited action service.")
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if set(fields) & self.CONTROLLED_FIELDS:
            raise ValidationError("Supply purchase order state requires the audited action service.")
        return super().bulk_update(objs, fields, batch_size=batch_size)

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False, update_conflicts=False, update_fields=None, unique_fields=None):
        raise ValidationError("Supply purchase orders must be created through the validated creation service.")

    def delete(self):
        raise ValidationError("Supply purchase orders are retained as auditable business records.")


class SupplyPurchaseOrderLineQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Supply purchase order lines do not support bulk mutation.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Supply purchase order lines do not support bulk mutation.")

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False, update_conflicts=False, update_fields=None, unique_fields=None):
        raise ValidationError("Supply purchase order lines must be created through the validated creation service.")

    def delete(self):
        raise ValidationError("Supply purchase order lines do not support bulk deletion.")


class AppendOnlySupplyRecordQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Supply-chain audit records are append-only.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Supply-chain audit records are append-only.")

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False, update_conflicts=False, update_fields=None, unique_fields=None):
        raise ValidationError("Supply-chain audit records must be appended through the audited action service.")

    def delete(self):
        raise ValidationError("Supply-chain audit records are append-only.")


class SupplyPurchaseOrder(models.Model):
    """SC-F1 purchase-order aggregate.

    This model intentionally coexists with the legacy single-line PurchaseOrder.
    Source UUIDs are trace metadata and never replace the target MySQL primary key.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        IN_PRODUCTION = "in_production", "In production"
        PRODUCTION_COMPLETED = "production_completed", "Production completed"
        READY_TO_SHIP = "ready_to_ship", "Ready to ship"
        SHIPPING_REVIEW_PENDING = "shipping_review_pending", "Shipping review pending"
        SHIPPING = "shipping", "Shipping"
        SHIPPED = "shipped", "Shipped"

    class ShippingRoute(models.TextChoices):
        UNDECIDED = "undecided", "Undecided"
        LOOSE_CARGO = "loose_cargo", "Loose cargo"
        CONTAINER_CARGO = "container_cargo", "Container cargo"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="supply_purchase_orders")
    supplier = models.ForeignKey(
        SupplierMaster,
        on_delete=models.PROTECT,
        related_name="supply_purchase_orders",
    )
    order_no = models.CharField(max_length=80)
    order_date = models.DateField()
    expected_delivery_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=8, default="CNY")
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=40, choices=Status.choices, default=Status.PENDING)
    shipping_route = models.CharField(
        max_length=24,
        choices=ShippingRoute.choices,
        default=ShippingRoute.UNDECIDED,
    )
    shipping_route_decided_at = models.DateTimeField(null=True, blank=True)
    shipping_route_decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="shipping_route_decisions",
    )
    completed_quantity = models.PositiveBigIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    creation_idempotency_key = models.CharField(max_length=128, null=True, blank=True)
    creation_request_hash = models.CharField(max_length=64, blank=True)
    source_system = models.CharField(max_length=80, null=True, blank=True)
    source_table = models.CharField(max_length=80, null=True, blank=True)
    source_record_id = models.CharField(max_length=128, null=True, blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    source_payload_hash = models.CharField(max_length=64, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    production_started_at = models.DateTimeField(null=True, blank=True)
    production_completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_supply_purchase_orders",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SupplyPurchaseOrderQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "-order_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "order_no"],
                name="uniq_supply_po_no_tenant",
            ),
            models.UniqueConstraint(
                fields=["tenant", "source_system", "source_table", "source_record_id"],
                name="uniq_supply_po_source",
            ),
            models.UniqueConstraint(
                fields=["tenant", "creation_idempotency_key"],
                name="uniq_supply_po_create_key",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        shipping_route="undecided",
                        shipping_route_decided_at__isnull=True,
                        shipping_route_decided_by__isnull=True,
                    )
                    | (
                        models.Q(shipping_route__in=["loose_cargo", "container_cargo"])
                        & models.Q(shipping_route_decided_at__isnull=False)
                        & models.Q(shipping_route_decided_by__isnull=False)
                    )
                ),
                name="supply_po_route_decision_consistent",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "supplier", "status"],
                name="idx_supply_po_scope",
            ),
            models.Index(
                fields=["tenant", "status", "expected_delivery_date"],
                name="idx_supply_po_status",
            ),
        ]

    def clean(self):
        if self.supplier_id and self.supplier.tenant_id != self.tenant_id:
            raise ValidationError("Supply purchase order and supplier must belong to the same tenant.")
        if self.created_by_id and self.created_by.tenant_id != self.tenant_id:
            raise ValidationError("Supply purchase order creator must belong to the same tenant.")
        if (
            self.shipping_route_decided_by_id
            and self.shipping_route_decided_by.tenant_id != self.tenant_id
        ):
            raise ValidationError("Shipping-route decision actor must belong to the same tenant.")
        if self.shipping_route == self.ShippingRoute.UNDECIDED:
            if self.shipping_route_decided_at or self.shipping_route_decided_by_id:
                raise ValidationError("An undecided shipping route cannot have decision metadata.")
        elif not self.shipping_route_decided_at or not self.shipping_route_decided_by_id:
            raise ValidationError("A decided shipping route requires decision actor and time.")
        source_values = (self.source_system, self.source_table, self.source_record_id)
        if any(source_values) and not all(source_values):
            raise ValidationError("Source system, table, and record ID must be provided together.")
        if self.currency:
            self.currency = self.currency.upper()

    def save(self, *args, **kwargs):
        if not self.pk and not _supply_action_write_allowed():
            controlled_initial_state = {
                "status": self.Status.PENDING,
                "shipping_route": self.ShippingRoute.UNDECIDED,
                "shipping_route_decided_at": None,
                "shipping_route_decided_by_id": None,
                "accepted_at": None,
                "production_started_at": None,
                "production_completed_at": None,
                "completed_quantity": 0,
                "version": 1,
            }
            if any(
                getattr(self, field) != expected
                for field, expected in controlled_initial_state.items()
            ):
                raise ValidationError(
                    "Supply purchase order controlled state must start at canonical defaults; "
                    "later state changes require the audited action service."
                )
        if self.pk:
            current = type(self).objects.filter(pk=self.pk).values(
                *SupplyPurchaseOrderQuerySet.CONTROLLED_FIELDS
            ).first()
            if (
                current
                and any(current[field] != getattr(self, field) for field in current)
                and not _supply_action_write_allowed()
            ):
                raise ValidationError("Supply purchase order state requires the audited action service.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Supply purchase orders are retained as auditable business records.")

    @property
    def total_quantity(self):
        return sum(line.quantity for line in self.lines.all())

    def __str__(self):
        return self.order_no


class SupplyPurchaseOrderLine(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="supply_purchase_order_lines")
    order = models.ForeignKey(SupplyPurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveIntegerField()
    sku = models.ForeignKey(ProductSKU, on_delete=models.PROTECT, related_name="supply_purchase_order_lines")
    sku_code_snapshot = models.CharField(max_length=80)
    product_name_snapshot = models.CharField(max_length=200, blank=True)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=14, decimal_places=4)
    expected_delivery_date = models.DateField(null=True, blank=True)
    source_record_id = models.CharField(max_length=128, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SupplyPurchaseOrderLineQuerySet.as_manager()

    class Meta:
        ordering = ["order_id", "line_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "line_no"],
                name="uniq_supply_po_line_no",
            ),
            models.UniqueConstraint(
                fields=["order", "source_record_id"],
                name="uniq_supply_po_line_source",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="supply_po_line_qty_gt_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="supply_po_line_price_gte_zero",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "sku"],
                name="idx_supply_po_line_sku",
            ),
        ]

    def clean(self):
        if self.order_id and self.order.tenant_id != self.tenant_id:
            raise ValidationError("Supply purchase order line and order must belong to the same tenant.")
        if self.sku_id and self.sku.tenant_id != self.tenant_id:
            raise ValidationError("Supply purchase order line and SKU must belong to the same tenant.")
        if self.quantity <= 0:
            raise ValidationError("Supply purchase order line quantity must be greater than zero.")
        if self.sku_id and not self.sku_code_snapshot:
            self.sku_code_snapshot = self.sku.sku_code

    def save(self, *args, **kwargs):
        order_status = (
            SupplyPurchaseOrder.objects.filter(pk=self.order_id)
            .values_list("status", flat=True)
            .first()
        )
        if order_status != SupplyPurchaseOrder.Status.PENDING:
            raise ValidationError("Supply purchase order lines are immutable after the order is accepted.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        order_status = (
            SupplyPurchaseOrder.objects.filter(pk=self.order_id)
            .values_list("status", flat=True)
            .first()
        )
        if order_status != SupplyPurchaseOrder.Status.PENDING:
            raise ValidationError("Supply purchase order lines are immutable after the order is accepted.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.order.order_no}:{self.line_no}"


class SupplyProductionProgress(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="supply_production_progress")
    order = models.ForeignKey(SupplyPurchaseOrder, on_delete=models.CASCADE, related_name="progress_entries")
    completed_quantity = models.PositiveBigIntegerField()
    progress_percent = models.DecimalField(max_digits=5, decimal_places=2)
    note = models.TextField(blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="supply_production_progress_entries",
    )
    request_id = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlySupplyRecordQuerySet.as_manager()

    class Meta:
        ordering = ["order_id", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "request_id"],
                name="uniq_supply_progress_request",
            ),
            models.CheckConstraint(
                condition=models.Q(progress_percent__gte=0) & models.Q(progress_percent__lte=100),
                name="supply_progress_percent_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "order", "created_at"],
                name="idx_supply_progress_order",
            ),
        ]

    def clean(self):
        if self.order_id and self.order.tenant_id != self.tenant_id:
            raise ValidationError("Production progress and order must belong to the same tenant.")
        if self.actor_id and self.actor.tenant_id != self.tenant_id:
            raise ValidationError("Production progress actor must belong to the same tenant.")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Production progress records are append-only.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Production progress records are append-only.")


class SupplyPurchaseOrderEvent(models.Model):
    class Action(models.TextChoices):
        ACCEPT = "accept", "Accept"
        START_PRODUCTION = "start_production", "Start production"
        UPDATE_PROGRESS = "update_progress", "Update progress"
        COMPLETE_PRODUCTION = "complete_production", "Complete production"
        ASSIGN_SHIPPING_ROUTE = "assign_shipping_route", "Assign shipping route"
        CHANGE_SHIPPING_ROUTE = "change_shipping_route", "Change shipping route"

    class ActorType(models.TextChoices):
        INTERNAL = "internal", "Internal"
        SUPPLIER = "supplier", "Supplier"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="supply_purchase_order_events")
    order = models.ForeignKey(SupplyPurchaseOrder, on_delete=models.CASCADE, related_name="events")
    action = models.CharField(max_length=40, choices=Action.choices)
    idempotency_key = models.CharField(max_length=128)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="supply_purchase_order_events",
    )
    actor_type = models.CharField(max_length=20, choices=ActorType.choices)
    before_status = models.CharField(max_length=40, choices=SupplyPurchaseOrder.Status.choices)
    after_status = models.CharField(max_length=40, choices=SupplyPurchaseOrder.Status.choices)
    before_shipping_route = models.CharField(
        max_length=24,
        choices=SupplyPurchaseOrder.ShippingRoute.choices,
        default=SupplyPurchaseOrder.ShippingRoute.UNDECIDED,
    )
    after_shipping_route = models.CharField(
        max_length=24,
        choices=SupplyPurchaseOrder.ShippingRoute.choices,
        default=SupplyPurchaseOrder.ShippingRoute.UNDECIDED,
    )
    payload = models.JSONField(default=dict, blank=True)
    request_hash = models.CharField(max_length=64, blank=True)
    response_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlySupplyRecordQuerySet.as_manager()

    class Meta:
        ordering = ["order_id", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "idempotency_key"],
                name="uniq_supply_po_idempotency",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "action", "created_at"],
                name="idx_supply_po_event",
            ),
        ]

    def clean(self):
        if self.order_id and self.order.tenant_id != self.tenant_id:
            raise ValidationError("Supply purchase order event and order must belong to the same tenant.")
        if self.actor_id and self.actor.tenant_id != self.tenant_id:
            raise ValidationError("Supply purchase order event actor must belong to the same tenant.")

    def save(self, *args, **kwargs):
        if not _supply_action_write_allowed():
            raise ValidationError("Supply purchase order events require the audited action service.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Supply purchase order events are append-only.")
