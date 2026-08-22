"""Typed loose-cargo shipment aggregates.

The existing ``suppliers.SupplierShipment`` model is a historical supplier
self-report and is intentionally not referenced here.  All shipment writes
are routed through :mod:`apps.shipping.services`; model/queryset guards keep
ORM shortcuts from bypassing the append-only audit trail.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from string import hexdigits

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.consolidation.models import ConsolidationBoxAllocation, LooseCargoConsolidation
from apps.packing.models import PackingBox, PackingBoxConsumption
from apps.tenants.models import Tenant


_shipping_domain_write_depth = ContextVar("shipping_domain_write_depth", default=0)


@contextmanager
def _shipping_domain_write_context():
    token = _shipping_domain_write_depth.set(_shipping_domain_write_depth.get() + 1)
    try:
        yield
    finally:
        _shipping_domain_write_depth.reset(token)


def _shipping_domain_write_allowed():
    return _shipping_domain_write_depth.get() > 0


class ProtectedShippingQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Shipment records must be changed through the audited domain service.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Shipment records must be changed through the audited domain service.")

    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
    ):
        raise ValidationError("Shipment records must be created through the audited domain service.")

    def delete(self):
        raise ValidationError("Shipment history is append-only.")


class AppendOnlyShippingQuerySet(ProtectedShippingQuerySet):
    pass


class ShippingDomainModel(models.Model):
    objects = ProtectedShippingQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not _shipping_domain_write_allowed():
            raise ValidationError("Shipment records require the audited domain service.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Shipment history is append-only.")


class LooseCargoShipment(ShippingDomainModel):
    class RouteType(models.TextChoices):
        LOOSE_CARGO_GROUPAGE = "loose_cargo_groupage", "Loose cargo groupage"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        LOADING = "loading", "Loading"
        CUSTOMS_DECLARED = "customs_declared", "Customs declared"
        DISPATCHED = "dispatched", "Dispatched"
        PORT_ARRIVED = "port_arrived", "Port arrived"
        WAREHOUSE_ARRIVED = "warehouse_arrived", "Warehouse arrived"
        WAREHOUSE_CLEARED = "warehouse_cleared", "Warehouse cleared"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="loose_cargo_shipments")
    shipment_no = models.CharField(max_length=80)
    route_type = models.CharField(max_length=32, choices=RouteType.choices, default=RouteType.LOOSE_CARGO_GROUPAGE)
    region_code = models.CharField(max_length=80)
    origin_site_id_snapshot = models.PositiveBigIntegerField(null=True, blank=True)
    origin_site_snapshot = models.JSONField(default=dict, blank=True)
    destination_country_code = models.CharField(max_length=8, blank=True)
    destination_port_code = models.CharField(max_length=32, blank=True)
    destination_warehouse_code = models.CharField(max_length=64, blank=True)
    note = models.TextField(blank=True)
    forwarder_reference = models.CharField(max_length=128, blank=True)
    groupage_reference = models.CharField(max_length=128, blank=True)
    container_reference = models.CharField(max_length=128, blank=True)
    customs_reference = models.CharField(max_length=128, blank=True)
    transport_reference = models.CharField(max_length=128, blank=True)
    planned_dispatch_at = models.DateTimeField(null=True, blank=True)
    actual_dispatch_at = models.DateTimeField(null=True, blank=True)
    port_arrived_at = models.DateTimeField(null=True, blank=True)
    warehouse_arrived_at = models.DateTimeField(null=True, blank=True)
    cleared_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=28, choices=Status.choices, default=Status.DRAFT)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_shipments")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="updated_shipments")
    customs_declared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="customs_declared_shipments",
    )
    dispatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="dispatched_shipments",
    )
    port_arrived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="port_arrived_shipments",
    )
    warehouse_arrived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="warehouse_arrived_shipments",
    )
    cleared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="cleared_shipments",
    )
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="cancelled_shipments",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "shipment_no"], name="uniq_shipping_shipment_no"),
            models.CheckConstraint(condition=models.Q(version__gt=0), name="shipping_shipment_version_gt_zero"),
            models.CheckConstraint(
                condition=models.Q(route_type="loose_cargo_groupage"),
                name="shipping_shipment_route_loose",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "region_code", "status"], name="idx_shipping_scope"),
        ]

    def clean(self):
        if not self.shipment_no or not self.shipment_no.strip():
            raise ValidationError({"shipment_no": "Shipment number is required."})
        if not self.region_code or not self.region_code.strip():
            raise ValidationError({"region_code": "Shipment region is required."})
        if self.version <= 0:
            raise ValidationError({"version": "Shipment version must be positive."})
        for field in (
            "created_by", "updated_by", "customs_declared_by", "dispatched_by", "port_arrived_by",
            "warehouse_arrived_by", "cleared_by", "cancelled_by",
        ):
            actor = getattr(self, field, None)
            if actor is not None and actor.tenant_id != self.tenant_id:
                raise ValidationError(f"{field} actor must share the shipment tenant.")
        if self.actual_dispatch_at and self.planned_dispatch_at and self.actual_dispatch_at < self.planned_dispatch_at:
            # Planning dates are advisory; retain only a defensive check when
            # both are explicitly provided by a domain action.
            pass


class ShipmentBoxAllocation(ShippingDomainModel):
    class State(models.TextChoices):
        RESERVED = "reserved", "Reserved"
        TRANSFERRED = "transferred", "Transferred"
        DISPATCHED = "dispatched", "Dispatched"
        ARRIVED_PORT = "arrived_port", "Arrived at port"
        ARRIVED_WAREHOUSE = "arrived_warehouse", "Arrived at warehouse"
        CLEARED = "cleared", "Cleared"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="shipment_box_allocations")
    shipment = models.ForeignKey(LooseCargoShipment, on_delete=models.CASCADE, related_name="box_allocations")
    consolidation = models.ForeignKey(
        LooseCargoConsolidation, on_delete=models.PROTECT, related_name="shipment_allocations",
    )
    consolidation_allocation = models.ForeignKey(
        ConsolidationBoxAllocation, on_delete=models.PROTECT, related_name="shipment_box_allocations",
    )
    box = models.ForeignKey(PackingBox, on_delete=models.PROTECT, related_name="shipment_allocations")
    packing_box_consumption = models.ForeignKey(
        PackingBoxConsumption, on_delete=models.PROTECT, related_name="shipment_allocations",
    )
    source_consolidation_version = models.PositiveIntegerField()
    source_release_version = models.PositiveIntegerField()
    supplier_id_snapshot = models.PositiveBigIntegerField(null=True, blank=True)
    order_ids_snapshot = models.JSONField(default=list, blank=True)
    order_nos_snapshot = models.JSONField(default=list, blank=True)
    batch_id_snapshot = models.PositiveBigIntegerField(null=True, blank=True)
    batch_no_snapshot = models.CharField(max_length=80, blank=True)
    box_no_snapshot = models.CharField(max_length=100)
    quantity_snapshot = models.PositiveBigIntegerField(default=0)
    weight_snapshot = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    volume_snapshot = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    snapshot = models.JSONField(default=dict, blank=True)
    state = models.CharField(max_length=24, choices=State.choices, default=State.TRANSFERRED)
    version = models.PositiveIntegerField(default=1)
    transferred_at = models.DateTimeField(auto_now_add=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    arrived_port_at = models.DateTimeField(null=True, blank=True)
    arrived_warehouse_at = models.DateTimeField(null=True, blank=True)
    cleared_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_shipment_allocations")
    dispatched_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="dispatched_shipment_allocations")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["shipment_id", "box_id", "id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "box"], name="uniq_shipping_active_box"),
            models.UniqueConstraint(fields=["tenant", "consolidation_allocation"], name="uniq_shipping_source_allocation"),
            models.CheckConstraint(condition=models.Q(version__gt=0), name="shipping_allocation_version_gt_zero"),
            models.CheckConstraint(condition=models.Q(quantity_snapshot__gt=0), name="shipping_allocation_qty_gt_zero"),
            models.CheckConstraint(condition=models.Q(source_release_version__gt=0), name="shipping_source_release_version_gt_zero"),
        ]
        indexes = [
            models.Index(fields=["tenant", "shipment", "state"], name="idx_shipping_allocation_state"),
            models.Index(fields=["tenant", "consolidation", "state"], name="idx_shipping_source_scope"),
        ]

    def clean(self):
        if self.shipment_id and self.shipment.tenant_id != self.tenant_id:
            raise ValidationError("Shipment allocation and shipment must share a tenant.")
        if self.consolidation_id and self.consolidation.tenant_id != self.tenant_id:
            raise ValidationError("Shipment allocation and consolidation must share a tenant.")
        if self.consolidation_allocation_id:
            source = self.consolidation_allocation
            if source.tenant_id != self.tenant_id or source.consolidation_id != self.consolidation_id:
                raise ValidationError("Shipment source allocation binding is invalid.")
            if self.box_id and source.box_id != self.box_id:
                raise ValidationError("Shipment source allocation must reference the same box.")
        if self.box_id and self.box.tenant_id != self.tenant_id:
            raise ValidationError("Shipment box must share a tenant.")
        if self.packing_box_consumption_id:
            consumption = self.packing_box_consumption
            if consumption.tenant_id != self.tenant_id or consumption.box_id != self.box_id:
                raise ValidationError("Shipment consumption must belong to the allocated tenant and box.")
            if consumption.consumer_type != PackingBoxConsumption.ConsumerType.SHIPMENT:
                raise ValidationError("Shipment allocation must reference a shipment consumption.")
        if self.quantity_snapshot <= 0 or self.version <= 0:
            raise ValidationError("Shipment allocation quantity/version must be positive.")
        if self.source_release_version <= 0:
            raise ValidationError("Shipment allocation requires a positive source release version.")
        if not isinstance(self.order_ids_snapshot, list) or not isinstance(self.order_nos_snapshot, list):
            raise ValidationError("Shipment order snapshots must be JSON lists.")
        if self.state == self.State.DISPATCHED and self.dispatched_at is None:
            raise ValidationError("Dispatched allocation requires a dispatch timestamp.")


class ShipmentEvent(ShippingDomainModel):
    class Action(models.TextChoices):
        CREATE = "create", "Create shipment"
        UPDATE = "update", "Update shipment"
        ALLOCATE = "allocate", "Allocate boxes"
        CUSTOMS_DECLARE = "customs_declare", "Customs declare"
        DISPATCH = "dispatch", "Dispatch"
        PORT_ARRIVAL = "port_arrival", "Port arrival"
        WAREHOUSE_ARRIVAL = "warehouse_arrival", "Warehouse arrival"
        CLEARANCE = "clearance", "Warehouse clearance"
        EXCEPTION = "exception", "Shipment exception"
        CANCEL = "cancel", "Cancel shipment"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="shipment_events")
    shipment = models.ForeignKey(LooseCargoShipment, null=True, blank=True, on_delete=models.PROTECT, related_name="events")
    allocation = models.ForeignKey(ShipmentBoxAllocation, null=True, blank=True, on_delete=models.PROTECT, related_name="events")
    box = models.ForeignKey(PackingBox, null=True, blank=True, on_delete=models.PROTECT, related_name="shipment_events")
    action = models.CharField(max_length=32, choices=Action.choices)
    actor_type = models.CharField(max_length=32)
    actor_id = models.PositiveBigIntegerField()
    channel = models.CharField(max_length=32, default="internal")
    expected_version = models.PositiveIntegerField(null=True, blank=True)
    source_version = models.PositiveIntegerField(null=True, blank=True)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    external_reference = models.CharField(max_length=128, blank=True)
    reason = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    occurred_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyShippingQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="uniq_shipping_event_key"),
            models.CheckConstraint(
                condition=models.Q(request_hash__regex=r"^[0-9a-fA-F]{64}$"),
                name="shipping_event_hash_hex",
            ),
            models.CheckConstraint(condition=models.Q(actor_id__gt=0), name="shipping_event_actor_positive"),
        ]
        indexes = [
            models.Index(fields=["tenant", "shipment", "action", "created_at"], name="idx_shipping_event"),
        ]

    def clean(self):
        if self.shipment_id and self.shipment.tenant_id != self.tenant_id:
            raise ValidationError("Shipment event and shipment must share a tenant.")
        if self.allocation_id and self.allocation.tenant_id != self.tenant_id:
            raise ValidationError("Shipment event and allocation must share a tenant.")
        if self.box_id and self.box.tenant_id != self.tenant_id:
            raise ValidationError("Shipment event and box must share a tenant.")
        if not self.actor_type or self.actor_id <= 0:
            raise ValidationError("Shipment event actor is required.")
        if len(self.request_hash or "") != 64 or any(char not in hexdigits for char in self.request_hash):
            raise ValidationError("Shipment event request hash must be SHA-256 hexadecimal.")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Shipment events are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Shipment events are append-only.")


# Vocabulary aliases for future API adapters.
ShipmentAction = ShipmentEvent
