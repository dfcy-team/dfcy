"""Domain models for the local loose-cargo consolidation aggregate.

The consolidation application deliberately contains no API concerns.  All
business writes go through :mod:`apps.consolidation.services`; model and
queryset guards keep an accidental admin, management command, or ORM update
from silently changing a published arrangement.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from string import hexdigits

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.packing.models import PackingBatch, PackingBox, PackingBoxConsumption
from apps.purchasing.models import SupplyPurchaseOrder, SupplyPurchaseOrderLine
from apps.masterdata.models import SupplierMaster
from apps.tenants.models import Tenant


_consolidation_domain_write_depth = ContextVar("consolidation_domain_write_depth", default=0)


@contextmanager
def _consolidation_domain_write_context():
    token = _consolidation_domain_write_depth.set(_consolidation_domain_write_depth.get() + 1)
    try:
        yield
    finally:
        _consolidation_domain_write_depth.reset(token)


def _consolidation_domain_write_allowed():
    return _consolidation_domain_write_depth.get() > 0


class ProtectedConsolidationQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Consolidation records must be changed through the audited domain service.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Consolidation records must be changed through the audited domain service.")

    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
    ):
        raise ValidationError("Consolidation records must be created through the audited domain service.")

    def delete(self):
        raise ValidationError("Consolidation records are retained as auditable records.")


class AppendOnlyConsolidationQuerySet(ProtectedConsolidationQuerySet):
    pass


class ConsolidationDomainModel(models.Model):
    objects = ProtectedConsolidationQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not _consolidation_domain_write_allowed():
            raise ValidationError("Consolidation records require the audited domain service.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Consolidation records are retained as auditable records.")


class ConsolidationSite(ConsolidationDomainModel):
    """Tenant-owned, versioned site master data."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="consolidation_sites")
    site_code = models.CharField(max_length=80)
    name = models.CharField(max_length=160)
    region_code = models.CharField(max_length=80)
    country_code = models.CharField(max_length=8, blank=True)
    province_state = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=80, blank=True)
    district = models.CharField(max_length=80, blank=True)
    address_line = models.CharField(max_length=255, blank=True)
    postal_code = models.CharField(max_length=32, blank=True)
    timezone = models.CharField(max_length=64, default="Asia/Shanghai")
    contact_name = models.CharField(max_length=100, blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    delivery_instructions = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    effective_from = models.DateTimeField(null=True, blank=True)
    effective_to = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_consolidation_sites",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_consolidation_sites",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "site_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "site_code"],
                name="uniq_consolidation_site_code",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0),
                name="consolidation_site_version_gt_zero",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "region_code", "is_active"],
                name="idx_consolidation_site_scope",
            ),
        ]

    @property
    def code(self):
        """Compatibility alias for callers that use the shorter site code."""

        return self.site_code

    def clean(self):
        if not self.site_code or not self.site_code.strip():
            raise ValidationError({"site_code": "Site code is required."})
        if not self.name or not self.name.strip():
            raise ValidationError({"name": "Site name is required."})
        if not self.region_code or not self.region_code.strip():
            raise ValidationError({"region_code": "Region code is required."})
        if self.version <= 0:
            raise ValidationError({"version": "Site version must be positive."})
        if self.effective_from and self.effective_to and self.effective_to <= self.effective_from:
            raise ValidationError({"effective_to": "Effective end must be after effective start."})
        if self.created_by_id and self.created_by.tenant_id != self.tenant_id:
            raise ValidationError("Site creator must belong to the same tenant.")
        if self.updated_by_id and self.updated_by.tenant_id != self.tenant_id:
            raise ValidationError("Site updater must belong to the same tenant.")

    def __str__(self):
        return f"{self.site_code} ({self.name})"


class ConsolidationSupplierCapability(ConsolidationDomainModel):
    """Explicit supplier capability for handover evidence writes.

    Supplier profile binding controls visibility; this separate, default-false
    capability controls whether the supplier may create/finalize/submit
    handover evidence.  It is intentionally independent from packing's
    ``can_self_pack`` flag.
    """

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="consolidation_supplier_capabilities")
    supplier = models.ForeignKey(SupplierMaster, on_delete=models.CASCADE, related_name="consolidation_capabilities")
    can_submit_handover = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_consolidation_capabilities")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="updated_consolidation_capabilities")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "supplier_id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "supplier"], name="uniq_consolidation_supplier_capability"),
            models.CheckConstraint(condition=models.Q(version__gt=0), name="consolidation_capability_version_gt_zero"),
        ]

    def clean(self):
        if self.supplier_id and self.supplier.tenant_id != self.tenant_id:
            raise ValidationError("Capability supplier and tenant must match.")
        for field in ("created_by", "updated_by"):
            actor = getattr(self, field, None)
            if actor is not None and actor.tenant_id != self.tenant_id:
                raise ValidationError(f"{field} actor must share the capability tenant.")
        if self.version <= 0:
            raise ValidationError("Capability version must be positive.")


class LooseCargoConsolidation(ConsolidationDomainModel):
    """An internal arrangement of complete loose-cargo packing boxes."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        RELEASED = "released", "Released"
        RECEIVING = "receiving", "Receiving"
        READY_FOR_SHIPMENT = "ready_for_shipment", "Ready for shipment"
        TRANSFERRED = "transferred", "Transferred"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="loose_cargo_consolidations")
    consolidation_no = models.CharField(max_length=80)
    region_code = models.CharField(max_length=80)
    site = models.ForeignKey(
        ConsolidationSite,
        on_delete=models.PROTECT,
        related_name="consolidations",
    )
    site_code_snapshot = models.CharField(max_length=80, blank=True)
    site_name_snapshot = models.CharField(max_length=160, blank=True)
    site_region_code_snapshot = models.CharField(max_length=80, blank=True)
    site_country_code_snapshot = models.CharField(max_length=8, blank=True)
    site_province_state_snapshot = models.CharField(max_length=80, blank=True)
    site_city_snapshot = models.CharField(max_length=80, blank=True)
    site_district_snapshot = models.CharField(max_length=80, blank=True)
    site_address_line_snapshot = models.CharField(max_length=255, blank=True)
    site_postal_code_snapshot = models.CharField(max_length=32, blank=True)
    site_timezone_snapshot = models.CharField(max_length=64, blank=True)
    site_contact_name_snapshot = models.CharField(max_length=100, blank=True)
    site_contact_phone_snapshot = models.CharField(max_length=32, blank=True)
    site_delivery_instructions_snapshot = models.TextField(blank=True)
    site_snapshot = models.JSONField(default=dict, blank=True)
    collection_cutoff_at = models.DateTimeField(null=True, blank=True)
    expected_dispatch_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT)
    version = models.PositiveIntegerField(default=1)
    note = models.TextField(blank=True)
    external_forwarder_ref = models.CharField(max_length=128, blank=True)
    external_groupage_ref = models.CharField(max_length=128, blank=True)
    release_site_snapshot = models.JSONField(default=dict, blank=True)
    release_allocation_snapshot = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_consolidations",
    )
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="released_consolidations",
    )
    released_at = models.DateTimeField(null=True, blank=True)
    ready_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ready_consolidations",
    )
    ready_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="cancelled_consolidations",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "consolidation_no"],
                name="uniq_consolidation_no_tenant",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0),
                name="consolidation_version_gt_zero",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "region_code", "status"],
                name="idx_consolidation_scope",
            ),
        ]

    def clean(self):
        if self.site_id and self.site.tenant_id != self.tenant_id:
            raise ValidationError("Consolidation site and consolidation must share a tenant.")
        if self.created_by_id and self.created_by.tenant_id != self.tenant_id:
            raise ValidationError("Consolidation creator must share a tenant.")
        for field in ("released_by", "ready_by", "cancelled_by"):
            actor = getattr(self, field, None)
            if actor is not None and actor.tenant_id != self.tenant_id:
                raise ValidationError(f"{field} actor must share a tenant.")
        if not self.consolidation_no or not self.consolidation_no.strip():
            raise ValidationError({"consolidation_no": "Consolidation number is required."})
        if not self.region_code or not self.region_code.strip():
            raise ValidationError({"region_code": "Region code is required."})
        if self.version <= 0:
            raise ValidationError({"version": "Consolidation version must be positive."})
        if self.collection_cutoff_at and self.expected_dispatch_at:
            if self.expected_dispatch_at < self.collection_cutoff_at:
                raise ValidationError("Dispatch time cannot precede the collection cutoff.")

    @property
    def active_allocations(self):
        return self.allocations.exclude(state=ConsolidationBoxAllocation.State.RELEASED)

    def __str__(self):
        return self.consolidation_no


class ConsolidationBoxAllocation(ConsolidationDomainModel):
    """Historical relation between a consolidation and one complete box."""

    class State(models.TextChoices):
        ALLOCATED = "allocated", "Allocated"
        HANDOVER_SUBMITTED = "handover_submitted", "Handover submitted"
        RECEIVED = "received", "Received"
        TRANSFERRED = "transferred", "Transferred"
        EXCEPTION = "exception", "Exception"
        RELEASED = "released", "Released"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="consolidation_box_allocations")
    consolidation = models.ForeignKey(
        LooseCargoConsolidation,
        on_delete=models.CASCADE,
        related_name="allocations",
    )
    box = models.ForeignKey(
        PackingBox,
        on_delete=models.PROTECT,
        related_name="consolidation_allocations",
    )
    packing_box_consumption = models.ForeignKey(
        PackingBoxConsumption,
        on_delete=models.PROTECT,
        related_name="consolidation_allocations",
    )
    supplier_id_snapshot = models.PositiveBigIntegerField(null=True, blank=True)
    order_id_snapshot = models.PositiveBigIntegerField(null=True, blank=True)
    order_no_snapshot = models.CharField(max_length=80, blank=True)
    # A completed packing batch may contain several orders from the same
    # supplier.  Keep the legacy singular columns for old consumers, but make
    # the immutable aggregate snapshot lossless and deterministic for new
    # data-scope/audit consumers.
    order_ids_snapshot = models.JSONField(default=list, blank=True)
    order_nos_snapshot = models.JSONField(default=list, blank=True)
    batch_id_snapshot = models.PositiveBigIntegerField(null=True, blank=True)
    batch_no_snapshot = models.CharField(max_length=80, blank=True)
    box_no_snapshot = models.CharField(max_length=100)
    quantity_snapshot = models.PositiveBigIntegerField(default=0)
    weight_snapshot = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    volume_snapshot = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    snapshot = models.JSONField(default=dict, blank=True)
    state = models.CharField(max_length=24, choices=State.choices, default=State.ALLOCATED)
    version = models.PositiveIntegerField(default=1)
    handover_method = models.CharField(max_length=40, blank=True)
    handover_reference = models.CharField(max_length=128, blank=True)
    # Structured immutable evidence collection.  The legacy scalar below is
    # retained only for old readers; new writes use this bounded, sorted JSON
    # list so nine large bigint IDs cannot overflow a varchar or lose members.
    evidence_ids = models.JSONField(default=list, blank=True)
    handover_evidence_id = models.CharField(max_length=128, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="submitted_consolidation_handovers",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="received_consolidation_boxes",
    )
    received_at = models.DateTimeField(null=True, blank=True)
    exception_code = models.CharField(max_length=40, blank=True)
    exception_note = models.TextField(blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_consolidation_allocations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["consolidation_id", "box_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["consolidation", "box"],
                name="uniq_consolidation_box",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0),
                name="consolidation_allocation_version_gt_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity_snapshot__gt=0),
                name="consolidation_allocation_qty_gt_zero",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "box", "state"],
                name="idx_consolidation_box_state",
            ),
        ]

    def clean(self):
        if self.consolidation_id and self.consolidation.tenant_id != self.tenant_id:
            raise ValidationError("Allocation and consolidation must share a tenant.")
        if self.box_id and self.box.tenant_id != self.tenant_id:
            raise ValidationError("Allocation and box must share a tenant.")
        if self.packing_box_consumption_id:
            consumption = self.packing_box_consumption
            if consumption.tenant_id != self.tenant_id:
                raise ValidationError("Allocation consumption must share a tenant.")
            if consumption.box_id != self.box_id:
                raise ValidationError("Allocation consumption must belong to the allocated box.")
            if consumption.consumer_type != PackingBoxConsumption.ConsumerType.CONSOLIDATION:
                raise ValidationError("Allocation must use a consolidation box consumption.")
            if self.consolidation_id and consumption.consumer_id != self.consolidation_id:
                raise ValidationError("Allocation consumption must point to this consolidation.")
        for field in ("created_by", "submitted_by", "received_by"):
            actor = getattr(self, field, None)
            if actor is not None and actor.tenant_id != self.tenant_id:
                raise ValidationError(f"{field} actor must share a tenant.")
        if self.quantity_snapshot <= 0:
            raise ValidationError("Allocated complete-box quantity must be positive.")
        if self.evidence_ids is None:
            self.evidence_ids = []
        if not isinstance(self.evidence_ids, list):
            raise ValidationError("Evidence IDs must be a JSON list.")
        try:
            normalized_evidence_ids = sorted({int(value) for value in self.evidence_ids})
        except (TypeError, ValueError) as exc:
            raise ValidationError("Evidence IDs must contain positive integers.") from exc
        if any(value <= 0 for value in normalized_evidence_ids) or len(normalized_evidence_ids) > 9:
            raise ValidationError("An allocation can retain at most nine positive evidence IDs.")
        if normalized_evidence_ids != self.evidence_ids:
            raise ValidationError("Evidence IDs must be a sorted, duplicate-free list.")
        if self.state == self.State.RELEASED and self.released_at is None:
            raise ValidationError("Released allocations require a release timestamp.")
        if self.state == self.State.RECEIVED and self.received_at is None:
            raise ValidationError("Received allocations require a receive timestamp.")
        if self.box_id:
            batch = self.box.batch
            if batch.status != PackingBatch.Status.COMPLETED:
                raise ValidationError("Only boxes from completed packing batches can be consolidated.")
            if self.batch_id_snapshot and self.batch_id_snapshot != batch.id:
                raise ValidationError("Batch snapshot does not match the physical box.")
            if self.box_no_snapshot and self.box_no_snapshot != self.box.box_no:
                raise ValidationError("Box snapshot does not match the physical box.")
            # A complete box is loose cargo only when every linked order uses
            # the frozen loose-cargo route.  Empty completed batches are
            # already rejected by packing completion, but the loop remains
            # defensive for historical rows.
            order_ids = list(
                SupplyPurchaseOrder.objects.filter(
                    tenant=self.tenant,
                    packing_batch_links__batch_id=batch.id,
                ).values_list("id", flat=True)
            )
            if order_ids and SupplyPurchaseOrder.objects.filter(
                tenant=self.tenant,
                pk__in=order_ids,
            ).exclude(shipping_route=SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO).exists():
                raise ValidationError("Only loose-cargo packing boxes can be consolidated.")


class ConsolidationEvent(ConsolidationDomainModel):
    """Append-only domain event and tenant-global idempotency ledger."""

    class Action(models.TextChoices):
        SITE_CREATE = "site_create", "Create site"
        SITE_UPDATE = "site_update", "Update site"
        SITE_DEACTIVATE = "site_deactivate", "Deactivate site"
        CAPABILITY_UPDATE = "capability_update", "Update supplier capability"
        CREATE = "create", "Create consolidation"
        UPDATE = "update", "Update consolidation"
        ALLOCATE = "allocate", "Allocate box"
        REMOVE = "remove", "Remove box"
        RELEASE = "release", "Release consolidation"
        RECEIVE = "receive", "Receive box"
        TRANSFER = "transfer", "Transfer box to shipment"
        HANDOVER_SUBMIT = "handover_submit", "Submit handover evidence"
        EXCEPTION = "exception", "Mark exception"
        CONTROLLED_RELEASE = "controlled_release", "Controlled release"
        READY = "ready", "Ready for shipment"
        CANCEL = "cancel", "Cancel consolidation"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="consolidation_events")
    site = models.ForeignKey(
        ConsolidationSite,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="events",
    )
    consolidation = models.ForeignKey(
        LooseCargoConsolidation,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="events",
    )
    allocation = models.ForeignKey(
        ConsolidationBoxAllocation,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="events",
    )
    box = models.ForeignKey(
        PackingBox,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="consolidation_events",
    )
    action = models.CharField(max_length=40, choices=Action.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="consolidation_events",
    )
    channel = models.CharField(max_length=32, default="internal")
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)
    evidence_reference = models.CharField(max_length=128, blank=True)
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    expected_version = models.PositiveIntegerField(null=True, blank=True)
    source_type = models.CharField(max_length=64, blank=True)
    source_id = models.CharField(max_length=128, blank=True)
    source_version = models.PositiveIntegerField(null=True, blank=True)
    occurred_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyConsolidationQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                name="uniq_consolidation_event_key",
            ),
            models.CheckConstraint(
                condition=models.Q(request_hash__regex=r"^[0-9a-fA-F]{64}$"),
                name="consolidation_event_hash_hex",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "consolidation", "action", "created_at"],
                name="idx_consolidation_event_action",
            ),
            models.Index(
                fields=["tenant", "source_type", "source_id", "source_version"],
                name="idx_consolidation_event_source",
            ),
        ]

    def clean(self):
        if self.site_id and self.site.tenant_id != self.tenant_id:
            raise ValidationError("Site event and tenant must match.")
        if self.consolidation_id and self.consolidation.tenant_id != self.tenant_id:
            raise ValidationError("Consolidation event and tenant must match.")
        if self.allocation_id and self.allocation.tenant_id != self.tenant_id:
            raise ValidationError("Allocation event and tenant must match.")
        if self.box_id and self.box.tenant_id != self.tenant_id:
            raise ValidationError("Box event and tenant must match.")
        if self.actor_id and self.actor.tenant_id != self.tenant_id:
            raise ValidationError("Consolidation event actor must match tenant.")
        if not self.idempotency_key or len(self.idempotency_key) > 128:
            raise ValidationError("Consolidation event idempotency key is invalid.")
        if (
            len(self.request_hash or "") != 64
            or any(character not in hexdigits for character in self.request_hash)
        ):
            raise ValidationError("Consolidation event request hash must be SHA-256 hexadecimal.")
        if self.source_version is not None and self.source_version <= 0:
            raise ValidationError("Consolidation event source version must be positive.")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Consolidation events are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Consolidation events are append-only.")
