from contextlib import contextmanager
from contextvars import ContextVar
from string import hexdigits

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.masterdata.models import SupplierMaster
from apps.purchasing.models import SupplyPurchaseOrder, SupplyPurchaseOrderLine
from apps.tenants.models import Tenant


_packing_domain_write_depth = ContextVar("packing_domain_write_depth", default=0)


@contextmanager
def _packing_domain_write_context():
    token = _packing_domain_write_depth.set(_packing_domain_write_depth.get() + 1)
    try:
        yield
    finally:
        _packing_domain_write_depth.reset(token)


def _packing_domain_write_allowed():
    return _packing_domain_write_depth.get() > 0


class ProtectedPackingQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Packing records must be changed through the audited domain service.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Packing records must be changed through the audited domain service.")

    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
    ):
        raise ValidationError("Packing records must be created through the audited domain service.")

    def delete(self):
        raise ValidationError("Packing records must be retained or changed through the audited domain service.")


class PackingDomainModel(models.Model):
    objects = ProtectedPackingQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not _packing_domain_write_allowed():
            raise ValidationError("Packing records must be changed through the audited domain service.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if not _packing_domain_write_allowed():
            raise ValidationError("Packing records must be retained or changed through the audited domain service.")
        return super().delete(*args, **kwargs)


class PackingStandardVersion(PackingDomainModel):
    code = models.SlugField(max_length=60)
    version = models.PositiveIntegerField()
    title = models.CharField(max_length=160)
    rules = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["code", "version"],
                name="uniq_pack_standard_version",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0),
                name="pack_standard_version_gt_zero",
            ),
        ]

    def __str__(self):
        return f"{self.code}:v{self.version}"


class PackingSupplierCapability(PackingDomainModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="packing_supplier_capabilities")
    supplier = models.OneToOneField(
        SupplierMaster,
        on_delete=models.CASCADE,
        related_name="packing_capability",
    )
    can_self_pack = models.BooleanField(default=False)
    can_mix_order_packing = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_packing_supplier_capabilities",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "supplier_id"]

    def clean(self):
        if self.supplier_id and self.supplier.tenant_id != self.tenant_id:
            raise ValidationError("Packing capability and supplier must belong to the same tenant.")
        if self.updated_by_id and self.updated_by.tenant_id != self.tenant_id:
            raise ValidationError("Packing capability updater must belong to the same tenant.")


class PackingBatch(PackingDomainModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="packing_batches")
    supplier = models.ForeignKey(
        SupplierMaster,
        on_delete=models.PROTECT,
        related_name="packing_batches",
    )
    standard_version = models.ForeignKey(
        PackingStandardVersion,
        on_delete=models.PROTECT,
        related_name="packing_batches",
    )
    batch_no = models.CharField(max_length=80)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT)
    note = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)
    creation_idempotency_key = models.CharField(max_length=128)
    creation_request_hash = models.CharField(max_length=64)
    source_system = models.CharField(max_length=80, null=True, blank=True)
    source_table = models.CharField(max_length=80, null=True, blank=True)
    source_record_id = models.CharField(max_length=128, null=True, blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    source_payload_hash = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_packing_batches",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "batch_no"],
                name="uniq_pack_batch_no_tenant",
            ),
            models.UniqueConstraint(
                fields=["tenant", "creation_idempotency_key"],
                name="uniq_pack_batch_create_key",
            ),
            models.UniqueConstraint(
                fields=["tenant", "source_system", "source_table", "source_record_id"],
                name="uniq_pack_batch_source",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0),
                name="pack_batch_version_gt_zero",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "supplier", "status"],
                name="idx_pack_batch_scope",
            ),
        ]

    def clean(self):
        if self.supplier_id and self.supplier.tenant_id != self.tenant_id:
            raise ValidationError("Packing batch and supplier must belong to the same tenant.")
        if self.created_by_id and self.created_by.tenant_id != self.tenant_id:
            raise ValidationError("Packing batch creator must belong to the same tenant.")
        source_values = (self.source_system, self.source_table, self.source_record_id)
        if any(source_values) and not all(source_values):
            raise ValidationError("Source system, table, and record ID must be provided together.")
        if self.source_payload_hash and (
            len(self.source_payload_hash) != 64
            or any(character not in hexdigits for character in self.source_payload_hash)
        ):
            raise ValidationError("Source payload hash must be a 64-character hexadecimal value.")

    def __str__(self):
        return self.batch_no


class PackingBatchOrder(PackingDomainModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="packing_batch_orders")
    batch = models.ForeignKey(PackingBatch, on_delete=models.CASCADE, related_name="batch_orders")
    order = models.ForeignKey(
        SupplyPurchaseOrder,
        on_delete=models.PROTECT,
        related_name="packing_batch_links",
    )
    # MySQL permits multiple NULL values in a unique key. Active rows use TRUE;
    # cancellation changes the marker to NULL, preserving unlimited history.
    active_guard = models.BooleanField(null=True, default=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["batch_id", "order_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "order"],
                name="uniq_pack_batch_order",
            ),
            models.UniqueConstraint(
                fields=["order", "active_guard"],
                name="uniq_pack_active_order",
            ),
            models.CheckConstraint(
                condition=models.Q(active_guard=True) | models.Q(active_guard__isnull=True),
                name="pack_active_guard_true_null",
            ),
        ]

    def clean(self):
        if self.batch_id and self.batch.tenant_id != self.tenant_id:
            raise ValidationError("Packing batch link and batch must belong to the same tenant.")
        if self.order_id and self.order.tenant_id != self.tenant_id:
            raise ValidationError("Packing batch link and order must belong to the same tenant.")
        if self.batch_id and self.order_id and self.batch.supplier_id != self.order.supplier_id:
            raise ValidationError("Packing batch and order must belong to the same supplier.")


class PackingBox(PackingDomainModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="packing_boxes")
    batch = models.ForeignKey(PackingBatch, on_delete=models.CASCADE, related_name="boxes")
    sequence = models.PositiveIntegerField()
    box_no = models.CharField(max_length=100)
    weight = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    volume = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["batch_id", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "sequence"],
                name="uniq_pack_box_sequence",
            ),
            models.UniqueConstraint(
                fields=["tenant", "box_no"],
                name="uniq_pack_box_no_tenant",
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gt=0),
                name="pack_box_sequence_gt_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(weight__isnull=True) | models.Q(weight__gt=0),
                name="pack_box_weight_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(volume__isnull=True) | models.Q(volume__gt=0),
                name="pack_box_volume_positive",
            ),
        ]

    def clean(self):
        if self.batch_id and self.batch.tenant_id != self.tenant_id:
            raise ValidationError("Packing box and batch must belong to the same tenant.")

    def __str__(self):
        return self.box_no


class PackingBoxItem(PackingDomainModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="packing_box_items")
    box = models.ForeignKey(PackingBox, on_delete=models.CASCADE, related_name="items")
    order_line = models.ForeignKey(
        SupplyPurchaseOrderLine,
        on_delete=models.PROTECT,
        related_name="packing_items",
    )
    quantity = models.PositiveIntegerField()
    order_no_snapshot = models.CharField(max_length=80)
    sku_code_snapshot = models.CharField(max_length=80)
    product_name_snapshot = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["box_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["box", "order_line"],
                name="uniq_pack_box_order_line",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="pack_box_item_qty_gt_zero",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "order_line"],
                name="idx_pack_item_order_line",
            ),
        ]

    def clean(self):
        if self.box_id and self.box.tenant_id != self.tenant_id:
            raise ValidationError("Packing item and box must belong to the same tenant.")
        if self.order_line_id and self.order_line.tenant_id != self.tenant_id:
            raise ValidationError("Packing item and order line must belong to the same tenant.")
        if self.box_id and self.order_line_id:
            linked = PackingBatchOrder.objects.filter(
                batch_id=self.box.batch_id,
                order_id=self.order_line.order_id,
                active_guard=True,
            ).exists()
            if not linked:
                raise ValidationError("Packing item order line is not linked to the batch.")


class PackingChangeRequest(PackingDomainModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="packing_change_requests")
    batch = models.ForeignKey(PackingBatch, on_delete=models.CASCADE, related_name="change_requests")
    expected_version = models.PositiveIntegerField()
    reason = models.TextField()
    proposed_boxes = models.JSONField(default=list)
    request_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_packing_change_requests",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_packing_change_requests",
    )
    review_note = models.TextField(blank=True)
    applied_version = models.PositiveIntegerField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["batch_id", "-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(expected_version__gt=0),
                name="pack_change_expected_gt_zero",
            ),
        ]

    def clean(self):
        if self.batch_id and self.batch.tenant_id != self.tenant_id:
            raise ValidationError("Packing change request and batch must belong to the same tenant.")
        if self.submitted_by_id and self.submitted_by.tenant_id != self.tenant_id:
            raise ValidationError("Packing change submitter must belong to the same tenant.")
        if self.reviewed_by_id and self.reviewed_by.tenant_id != self.tenant_id:
            raise ValidationError("Packing change reviewer must belong to the same tenant.")
        if self.reviewed_by_id and self.reviewed_by_id == self.submitted_by_id:
            raise ValidationError("Packing change requests require a different reviewer.")
        if not self.reason.strip():
            raise ValidationError("Packing change reason is required.")


class PackingEvent(PackingDomainModel):
    class Action(models.TextChoices):
        CREATE_BATCH = "create_batch", "Create batch"
        ADD_BOX = "add_box", "Add box"
        UPDATE_BOX = "update_box", "Update box"
        REMOVE_BOX = "remove_box", "Remove box"
        COMPLETE_BATCH = "complete_batch", "Complete batch"
        CANCEL_BATCH = "cancel_batch", "Cancel batch"
        SUBMIT_CHANGE = "submit_change", "Submit change"
        APPROVE_CHANGE = "approve_change", "Approve change"
        REJECT_CHANGE = "reject_change", "Reject change"
        APPLY_CHANGE = "apply_change", "Apply change"
        GENERATE_LABEL = "generate_label", "Generate label"

    class ActorType(models.TextChoices):
        INTERNAL = "internal", "Internal"
        SUPPLIER = "supplier", "Supplier"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="packing_events")
    batch = models.ForeignKey(PackingBatch, on_delete=models.CASCADE, related_name="events")
    action = models.CharField(max_length=40, choices=Action.choices)
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="packing_events",
    )
    actor_type = models.CharField(max_length=20, choices=ActorType.choices)
    before_status = models.CharField(max_length=30, choices=PackingBatch.Status.choices)
    after_status = models.CharField(max_length=30, choices=PackingBatch.Status.choices)
    batch_version = models.PositiveIntegerField()
    payload = models.JSONField(default=dict, blank=True)
    response_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["batch_id", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "idempotency_key"],
                name="uniq_pack_event_idempotency",
            ),
            models.CheckConstraint(
                condition=models.Q(batch_version__gt=0),
                name="pack_event_version_gt_zero",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "action", "created_at"],
                name="idx_pack_event_action",
            ),
        ]

    def clean(self):
        if self.batch_id and self.batch.tenant_id != self.tenant_id:
            raise ValidationError("Packing event and batch must belong to the same tenant.")
        if self.actor_id and self.actor.tenant_id != self.tenant_id:
            raise ValidationError("Packing event actor must belong to the same tenant.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Packing events are append-only.")


class PackingApiIdempotencyRecord(PackingDomainModel):
    class Channel(models.TextChoices):
        INTERNAL = "internal", "Internal"
        SUPPLIER_WEB = "supplier_web", "Supplier web"
        MINIAPP = "miniapp", "Mini Program"

    class ResponseKind(models.TextChoices):
        JSON = "json", "JSON"
        LABEL = "label", "Label"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="packing_api_idempotency_records",
    )
    scope_key = models.CharField(max_length=255)
    idempotency_key = models.CharField(max_length=128)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="packing_api_idempotency_records",
    )
    channel = models.CharField(max_length=20, choices=Channel.choices)
    action = models.CharField(max_length=40)
    resource_key = models.CharField(max_length=255)
    request_hash = models.CharField(max_length=64)
    http_status = models.PositiveSmallIntegerField()
    response_kind = models.CharField(max_length=10, choices=ResponseKind.choices)
    response_body = models.JSONField(null=True, blank=True)
    label_snapshot = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["tenant_id", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "scope_key", "idempotency_key"],
                name="uniq_pack_api_scope_key",
            ),
            models.CheckConstraint(
                condition=models.Q(http_status__gte=200) & models.Q(http_status__lt=300),
                name="pack_api_http_success",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "idempotency_key"],
                name="idx_pack_api_tenant_key",
            ),
        ]

    def clean(self):
        if self.actor_id and self.actor.tenant_id != self.tenant_id:
            raise ValidationError("Packing API idempotency actor must belong to the same tenant.")
        if not self.scope_key or not self.resource_key:
            raise ValidationError("Packing API idempotency scope and resource keys are required.")
        if len(self.request_hash) != 64 or any(
            character not in hexdigits for character in self.request_hash
        ):
            raise ValidationError("Packing API request hash must be a SHA-256 hexadecimal digest.")
        if self.response_kind == self.ResponseKind.JSON:
            if self.response_body is None or self.label_snapshot is not None:
                raise ValidationError("JSON idempotency records require only a response body.")
        elif self.response_kind == self.ResponseKind.LABEL:
            if self.label_snapshot is None or self.response_body is not None:
                raise ValidationError("Label idempotency records require only a label snapshot.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Packing API idempotency records are append-only.")
