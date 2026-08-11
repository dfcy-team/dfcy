from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import OperationalError, ProgrammingError, models
from django.utils import timezone

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
        # A route correction after packing has reserved/frozen quantities (or
        # a downstream box consumer) would invalidate every batch inheriting
        # the order route. Keep this guard in the aggregate model as a final
        # line of defence for service, admin and ORM callers alike.
        if self.pk:
            current_route = type(self).objects.filter(pk=self.pk).values_list(
                "shipping_route", flat=True
            ).first()
            if current_route is not None and current_route != self.shipping_route:
                try:
                    from apps.packing.models import PackingBatchLineAllocation, PackingBoxConsumption
                    has_allocation = PackingBatchLineAllocation.objects.filter(
                        order_line__order_id=self.pk,
                        state__in=["reserved", "frozen"],
                    ).exists()
                    has_consumption = PackingBoxConsumption.objects.filter(
                        box__batch__batch_orders__order_id=self.pk,
                        state__in=["reserved", "committed"],
                        active_guard=True,
                    ).exists()
                    if has_allocation or has_consumption:
                        raise ValidationError(
                            "Shipping route cannot change while packing quantities or box consumption remain active."
                        )
                except ImportError:
                    pass

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


class SupplyOrderLineFulfillmentQuerySet(models.QuerySet):
    """Prevent aggregate counters from being edited through a raw ORM path."""

    CONTROLLED_FIELDS = {
        "production_completed_quantity",
        "packing_reserved_quantity",
        "packed_quantity",
        "shipped_quantity",
        "warehouse_received_quantity",
        "warehouse_cleared_quantity",
        "version",
    }

    def update(self, **kwargs):
        if set(kwargs) & self.CONTROLLED_FIELDS:
            raise ValidationError("Fulfillment projections require the audited domain service.")
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if set(fields) & self.CONTROLLED_FIELDS:
            raise ValidationError("Fulfillment projections require the audited domain service.")
        return super().bulk_update(objs, fields, batch_size=batch_size)

    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
    ):
        raise ValidationError("Fulfillment projections must be created by the audited domain service.")

    def delete(self):
        raise ValidationError("Fulfillment projections are retained as auditable state.")


class SupplyOrderLineFulfillment(models.Model):
    """Current, rebuildable projection for one purchase-order line.

    The projection is deliberately separate from ``SupplyPurchaseOrder``'s
    legacy order-level ``completed_quantity`` field.  F2 services lock and
    update this row together with its order line; the append-only event table
    below is the audit source used to rebuild it.
    """

    class MigrationClassification(models.TextChoices):
        NATIVE = "native", "Native"
        LEGACY_ZERO = "legacy_zero", "Legacy zero production"
        LEGACY_FULL_ORDER = "legacy_full_order", "Legacy full order"
        LEGACY_PARTIAL_MANUAL = "legacy_partial_manual", "Legacy partial requires manual allocation"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="supply_order_line_fulfillments",
    )
    order = models.ForeignKey(
        SupplyPurchaseOrder,
        on_delete=models.CASCADE,
        related_name="fulfillment_projections",
    )
    order_line = models.OneToOneField(
        SupplyPurchaseOrderLine,
        on_delete=models.CASCADE,
        related_name="fulfillment",
    )
    ordered_quantity = models.PositiveBigIntegerField()
    production_completed_quantity = models.PositiveBigIntegerField(default=0)
    packing_reserved_quantity = models.PositiveBigIntegerField(default=0)
    packed_quantity = models.PositiveBigIntegerField(default=0)
    shipped_quantity = models.PositiveBigIntegerField(default=0)
    warehouse_received_quantity = models.PositiveBigIntegerField(default=0)
    warehouse_cleared_quantity = models.PositiveBigIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    migration_classification = models.CharField(
        max_length=32,
        choices=MigrationClassification.choices,
        default=MigrationClassification.NATIVE,
    )
    needs_manual_allocation = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SupplyOrderLineFulfillmentQuerySet.as_manager()

    class Meta:
        ordering = ["order_id", "order_line_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "order_line"],
                name="uniq_fulfillment_tenant_line",
            ),
            models.CheckConstraint(
                condition=models.Q(ordered_quantity__gt=0),
                name="fulfillment_ordered_gt_zero",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(production_completed_quantity__gte=0)
                    & models.Q(production_completed_quantity__lte=models.F("ordered_quantity"))
                ),
                name="fulfillment_production_lte_ordered",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(packing_reserved_quantity__gte=0)
                    & models.Q(packed_quantity__gte=0)
                    & models.Q(packing_reserved_quantity__lte=models.F("production_completed_quantity"))
                    & models.Q(packed_quantity__lte=models.F("production_completed_quantity"))
                    & models.Q(packing_reserved_quantity__lte=models.F("production_completed_quantity") - models.F("packed_quantity"))
                ),
                name="fulfillment_reserved_packed_lte_production",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(shipped_quantity__gte=0)
                    & models.Q(warehouse_received_quantity__gte=0)
                    & models.Q(warehouse_cleared_quantity__gte=0)
                    & models.Q(shipped_quantity__lte=models.F("packed_quantity"))
                    & models.Q(warehouse_received_quantity__lte=models.F("shipped_quantity"))
                    & models.Q(warehouse_cleared_quantity__lte=models.F("warehouse_received_quantity"))
                ),
                name="fulfillment_downstream_order",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0),
                name="fulfillment_version_gt_zero",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "order", "order_line"],
                name="idx_fulfillment_scope",
            ),
        ]

    def clean(self):
        if self.order_line_id and self.order_line.order_id != self.order_id:
            raise ValidationError("Fulfillment projection line must belong to its order.")
        if self.order_id and self.order.tenant_id != self.tenant_id:
            raise ValidationError("Fulfillment projection and order must share a tenant.")
        if self.order_line_id and self.order_line.tenant_id != self.tenant_id:
            raise ValidationError("Fulfillment projection and line must share a tenant.")
        if self.ordered_quantity <= 0:
            raise ValidationError("Fulfillment ordered quantity must be greater than zero.")
        if self.production_completed_quantity > self.ordered_quantity:
            raise ValidationError("Production quantity cannot exceed ordered quantity.")
        if self.packing_reserved_quantity + self.packed_quantity > self.production_completed_quantity:
            raise ValidationError("Reserved plus packed quantity cannot exceed production quantity.")
        if self.packed_quantity < self.shipped_quantity:
            raise ValidationError("Shipped quantity cannot exceed packed quantity.")
        if self.shipped_quantity < self.warehouse_received_quantity:
            raise ValidationError("Warehouse received quantity cannot exceed shipped quantity.")
        if self.warehouse_received_quantity < self.warehouse_cleared_quantity:
            raise ValidationError("Warehouse cleared quantity cannot exceed warehouse received quantity.")

    def save(self, *args, **kwargs):
        if not _supply_action_write_allowed():
            raise ValidationError("Fulfillment projections require the audited domain service.")
        if self.pk:
            current = type(self).objects.filter(pk=self.pk).values(*SupplyOrderLineFulfillmentQuerySet.CONTROLLED_FIELDS).first()
            if current and any(current[field] != getattr(self, field) for field in current):
                # The context is intentionally the only write gate.  Calling
                # code still has to use the service lock and append an event.
                pass
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Fulfillment projections are retained as auditable state.")


class SupplyFulfillmentEvent(models.Model):
    """Append-only quantity event used to rebuild line projections."""

    class Stage(models.TextChoices):
        PRODUCTION = "production", "Production"
        PACKING = "packing", "Packing"
        SHIPPING = "shipping", "Shipping"
        WAREHOUSE_RECEIVED = "warehouse_received", "Warehouse received"
        WAREHOUSE_CLEARED = "warehouse_cleared", "Warehouse cleared"

    class Action(models.TextChoices):
        PRODUCTION_COMPLETE = "production_complete", "Production complete"
        RESERVE_PACKING = "reserve_packing", "Reserve packing"
        RELEASE_PACKING = "release_packing", "Release packing"
        FREEZE_PACKING = "freeze_packing", "Freeze packing"
        REVERSE_PACKING = "reverse_packing", "Reverse packing"
        SHIP = "ship", "Ship"
        RECEIVE = "receive", "Receive"
        CLEAR = "clear", "Clear"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="supply_fulfillment_events",
    )
    order = models.ForeignKey(
        SupplyPurchaseOrder,
        on_delete=models.CASCADE,
        related_name="fulfillment_events",
    )
    order_line = models.ForeignKey(
        SupplyPurchaseOrderLine,
        on_delete=models.PROTECT,
        related_name="fulfillment_events",
    )
    stage = models.CharField(max_length=32, choices=Stage.choices)
    delta_quantity = models.BigIntegerField()
    source_type = models.CharField(max_length=64)
    source_id = models.CharField(max_length=128)
    source_version = models.PositiveIntegerField(default=1)
    action = models.CharField(max_length=40, choices=Action.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="supply_fulfillment_events",
    )
    channel = models.CharField(max_length=32, default="internal")
    reason = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=255)
    before_snapshot = models.JSONField(default=dict)
    after_snapshot = models.JSONField(default=dict)
    reverse_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reversals",
    )
    occurred_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlySupplyRecordQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                name="uniq_fulfillment_event_idempotency",
            ),
            models.UniqueConstraint(
                fields=[
                    "tenant",
                    "source_type",
                    "source_id",
                    "source_version",
                    "order_line",
                    "stage",
                    "action",
                ],
                name="uniq_fulfillment_event_source_version",
            ),
            models.CheckConstraint(
                condition=~models.Q(delta_quantity=0),
                name="fulfillment_event_delta_nonzero",
            ),
            models.CheckConstraint(
                condition=models.Q(source_id__gt=""),
                name="fulfillment_event_source_nonempty",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "order_line", "stage", "created_at"],
                name="idx_fulfillment_event_line",
            ),
        ]

    def clean(self):
        if self.order_line_id and self.order_line.order_id != self.order_id:
            raise ValidationError("Fulfillment event line must belong to its order.")
        if self.order_id and self.order.tenant_id != self.tenant_id:
            raise ValidationError("Fulfillment event and order must share a tenant.")
        if self.order_line_id and self.order_line.tenant_id != self.tenant_id:
            raise ValidationError("Fulfillment event and line must share a tenant.")
        if self.actor_id and self.actor.tenant_id != self.tenant_id:
            raise ValidationError("Fulfillment event actor must share a tenant.")
        if not self.source_id:
            raise ValidationError("Fulfillment event source ID is required.")
        if self.delta_quantity == 0:
            raise ValidationError("Fulfillment event delta cannot be zero.")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Fulfillment events are append-only.")
        if not _supply_action_write_allowed():
            raise ValidationError("Fulfillment events require the audited domain service.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Fulfillment events are append-only.")


def _ensure_order_line_fulfillment_projections(order):
    """Create missing line projections without guessing partial production.

    This helper is intentionally idempotent and is called by the audited
    purchase-order save path and by F2 packing services before taking quantity
    locks.  A partially completed legacy order is marked for manual line
    allocation rather than being split heuristically.
    """

    lines = list(order.lines.all().order_by("pk"))
    if not lines:
        return []
    total = sum(line.quantity for line in lines)
    completed = int(order.completed_quantity or 0)
    if completed <= 0:
        classification = SupplyOrderLineFulfillment.MigrationClassification.LEGACY_ZERO
        line_quantities = {line.id: 0 for line in lines}
        manual = False
    elif completed >= total:
        classification = SupplyOrderLineFulfillment.MigrationClassification.LEGACY_FULL_ORDER
        line_quantities = {line.id: line.quantity for line in lines}
        manual = False
    else:
        classification = SupplyOrderLineFulfillment.MigrationClassification.LEGACY_PARTIAL_MANUAL
        line_quantities = {line.id: 0 for line in lines}
        manual = True

    projections = []
    with _supply_action_write_context():
        for line in lines:
            projection, created = SupplyOrderLineFulfillment.objects.get_or_create(
                order_line=line,
                defaults={
                    "tenant": order.tenant,
                    "order": order,
                    "ordered_quantity": line.quantity,
                    "production_completed_quantity": line_quantities[line.id],
                    "migration_classification": classification,
                    "needs_manual_allocation": manual,
                },
            )
            if not created:
                # Do not overwrite a projection that has already participated
                # in F2 events.  Only fill missing/legacy metadata.
                changed = []
                if projection.ordered_quantity != line.quantity:
                    projection.ordered_quantity = line.quantity
                    changed.append("ordered_quantity")
                if projection.migration_classification == SupplyOrderLineFulfillment.MigrationClassification.NATIVE:
                    projection.migration_classification = classification
                    projection.needs_manual_allocation = manual
                    changed += ["migration_classification", "needs_manual_allocation"]
                if changed:
                    projection.save(update_fields=changed + ["updated_at"])
            projections.append(projection)
    return projections


def _converge_completed_order_line_fulfillment_projections(
    order,
    *,
    actor,
    idempotency_key,
):
    """Converge legacy/manual line projections after a controlled completion.

    The legacy order only stored one aggregate production counter.  Once that
    counter reaches the order total we can safely assign the full quantity to
    every line *only when no packing history or occupancy exists*.  Existing
    packing activity is treated as an explicit migration/manual-allocation
    conflict instead of being silently overwritten.
    """

    lines = list(order.lines.all().order_by("pk"))
    if not lines:
        return []
    total = sum(int(line.quantity) for line in lines)
    if int(order.completed_quantity or 0) < total:
        raise ValidationError("Line projection convergence requires a fully completed order.")

    # Import packing lazily so purchasing migrations and app loading do not
    # introduce a model cycle.  Missing tables are tolerated during bootstrap;
    # the append-only fulfillment event history remains the authoritative guard
    # once both apps are migrated.
    try:
        from apps.packing.models import PackingBatchLineAllocation, PackingBoxConsumption
    except (ImportError, LookupError):
        PackingBatchLineAllocation = None
        PackingBoxConsumption = None

    projections = []
    with _supply_action_write_context():
        for line in lines:
            projection, _ = SupplyOrderLineFulfillment.objects.get_or_create(
                order_line=line,
                defaults={
                    "tenant": order.tenant,
                    "order": order,
                    "ordered_quantity": line.quantity,
                    "production_completed_quantity": 0,
                    "migration_classification": SupplyOrderLineFulfillment.MigrationClassification.LEGACY_PARTIAL_MANUAL,
                    "needs_manual_allocation": True,
                },
            )
            locked = SupplyOrderLineFulfillment.objects.select_for_update().get(pk=projection.pk)

            packing_event_exists = SupplyFulfillmentEvent.objects.filter(
                tenant=order.tenant,
                order_line=line,
                stage=SupplyFulfillmentEvent.Stage.PACKING,
            ).exists()
            packing_allocation_exists = False
            packing_consumption_exists = False
            try:
                if PackingBatchLineAllocation is not None:
                    packing_allocation_exists = PackingBatchLineAllocation.objects.filter(
                        tenant=order.tenant,
                        order_line=line,
                    ).exists()
                if PackingBoxConsumption is not None:
                    packing_consumption_exists = PackingBoxConsumption.objects.filter(
                        tenant=order.tenant,
                        box__batch__batch_orders__order_id=order.id,
                        state__in=["reserved", "committed"],
                        active_guard=True,
                    ).exists()
            except (OperationalError, ProgrammingError):
                # During a rolling migration the historical event/counter
                # checks above are still safe; absent packing tables cannot
                # falsely block production completion.
                packing_allocation_exists = False
                packing_consumption_exists = False

            has_quantity_activity = any(
                int(value) > 0
                for value in (
                    locked.packing_reserved_quantity,
                    locked.packed_quantity,
                    locked.shipped_quantity,
                    locked.warehouse_received_quantity,
                    locked.warehouse_cleared_quantity,
                )
            )
            if (
                packing_event_exists
                or packing_allocation_exists
                or packing_consumption_exists
                or has_quantity_activity
            ):
                if locked.needs_manual_allocation or locked.production_completed_quantity < line.quantity:
                    raise ValidationError(
                        "Completed production cannot overwrite a line projection with packing history or occupancy; manual allocation is required."
                    )
                # A native projection that already reached the line quantity
                # is already converged; its immutable packing history is safe.
                if locked.production_completed_quantity >= line.quantity:
                    projections.append(locked)
                    continue

            if locked.production_completed_quantity > line.quantity:
                raise ValidationError("Line production projection exceeds the ordered quantity.")
            if locked.production_completed_quantity == line.quantity and not locked.needs_manual_allocation:
                projections.append(locked)
                continue

            before_quantity = int(locked.production_completed_quantity)
            before = {
                "production_completed_quantity": before_quantity,
                "packing_reserved_quantity": int(locked.packing_reserved_quantity),
                "packed_quantity": int(locked.packed_quantity),
                "shipped_quantity": int(locked.shipped_quantity),
                "version": int(locked.version),
            }
            locked.production_completed_quantity = int(line.quantity)
            locked.migration_classification = SupplyOrderLineFulfillment.MigrationClassification.LEGACY_FULL_ORDER
            locked.needs_manual_allocation = False
            locked.version += 1
            locked.save(
                update_fields=[
                    "production_completed_quantity",
                    "migration_classification",
                    "needs_manual_allocation",
                    "version",
                    "updated_at",
                ]
            )
            delta = int(line.quantity) - before_quantity
            if delta:
                event_key = (
                    f"{idempotency_key}:line:{line.id}:action:"
                    f"{SupplyFulfillmentEvent.Action.PRODUCTION_COMPLETE}"
                )
                existing = SupplyFulfillmentEvent.objects.filter(
                    tenant=order.tenant,
                    idempotency_key=event_key,
                ).first()
                if existing is None:
                    SupplyFulfillmentEvent.objects.create(
                        tenant=order.tenant,
                        order=order,
                        order_line=line,
                        stage=SupplyFulfillmentEvent.Stage.PRODUCTION,
                        delta_quantity=delta,
                        source_type="supply_purchase_order",
                        source_id=str(order.id),
                        source_version=int(order.version),
                        action=SupplyFulfillmentEvent.Action.PRODUCTION_COMPLETE,
                        actor=actor,
                        channel="internal",
                        reason="Controlled production completion projection convergence",
                        idempotency_key=event_key,
                        before_snapshot=before,
                        after_snapshot={
                            "production_completed_quantity": int(locked.production_completed_quantity),
                            "packing_reserved_quantity": int(locked.packing_reserved_quantity),
                            "packed_quantity": int(locked.packed_quantity),
                            "shipped_quantity": int(locked.shipped_quantity),
                            "version": int(locked.version),
                        },
                        occurred_at=timezone.now(),
                    )
            projections.append(locked)
    return projections
