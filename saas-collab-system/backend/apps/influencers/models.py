from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.masterdata.models import StoreMaster
from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant


class ProtectedInfluencerQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Influencer profiles must be updated through audited services.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Bulk create is disabled for influencer profiles.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Bulk update is disabled for influencer profiles.")


class Influencer(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    class CooperationStatus(models.TextChoices):
        PROSPECT = "prospect", "Prospect"
        CONTACTED = "contacted", "Contacted"
        COOPERATING = "cooperating", "Cooperating"
        PAUSED = "paused", "Paused"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="influencers")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=120)
    platform = models.CharField(max_length=40)
    handle = models.CharField(max_length=120, blank=True)
    category = models.CharField(max_length=80, blank=True)
    follower_count = models.PositiveBigIntegerField(default=0)
    contact_name = models.CharField(max_length=80, blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    contact_email = models.EmailField(blank=True)
    cooperation_status = models.CharField(max_length=20, choices=CooperationStatus.choices, default=CooperationStatus.PROSPECT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = ProtectedInfluencerQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "code"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_influencer_code_per_tenant")]


class TenantValidatedQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Tenant-owned influencer records must be updated through validated services.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Bulk create is disabled for tenant-owned influencer records.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Bulk update is disabled for tenant-owned influencer records.")


class TenantValidatedModel(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    objects = TenantValidatedQuerySet.as_manager()

    class Meta:
        abstract = True

    tenant_relation_fields = ()

    def clean(self):
        super().clean()
        for field_name in self.tenant_relation_fields:
            related = getattr(self, field_name, None)
            if related is not None and related.tenant_id != self.tenant_id:
                raise ValidationError({field_name: "Related object must belong to the same tenant."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class StateMachineTenantModel(TenantValidatedModel):
    """Prevent ordinary ORM saves from changing audited workflow state."""

    class Meta:
        abstract = True

    protected_state_fields = ()
    initial_state_values = {}

    def _assert_state_fields_unchanged(self):
        if self._state.adding or not self.pk:
            invalid = {
                field: "Workflow records must be created in their initial state."
                for field, expected in self.initial_state_values.items()
                if getattr(self, field) != expected
            }
            if invalid:
                raise ValidationError(invalid)
            return
        persisted = type(self).objects.filter(pk=self.pk).values(*self.protected_state_fields).first()
        if persisted is None:
            return
        changed = [field for field in self.protected_state_fields if getattr(self, field) != persisted[field]]
        if changed:
            raise ValidationError({field: "Use the audited state-machine service." for field in changed})

    def save(self, *args, **kwargs):
        self._assert_state_fields_unchanged()
        return super().save(*args, **kwargs)

    def save_base(self, *args, **kwargs):
        self._assert_state_fields_unchanged()
        return super().save_base(*args, **kwargs)


class InfluencerRestriction(TenantValidatedModel):
    influencer = models.ForeignKey(Influencer, on_delete=models.CASCADE, related_name="restrictions")
    is_blacklisted = models.BooleanField(default=True)
    reason = models.CharField(max_length=240, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="influencer_restrictions")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("influencer", "created_by")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "influencer"], name="uniq_influencer_restriction")]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            Influencer.objects.select_for_update().get(pk=self.influencer_id, tenant_id=self.tenant_id)
            return super().save(*args, **kwargs)


class OutreachTask(StateMachineTenantModel):
    protected_state_fields = (
        "status",
        "version",
        "started_at",
        "finalized_at",
        "dispatch_time",
        "outreach_at",
        "is_deleted",
        "deleted_at",
    )
    initial_state_values = {
        "status": "pending",
        "version": 1,
        "started_at": None,
        "finalized_at": None,
        "outreach_at": None,
        "is_deleted": False,
        "deleted_at": None,
    }

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    task_no = models.CharField(max_length=80)
    task_name = models.CharField(max_length=160, blank=True)
    influencer = models.ForeignKey(
        Influencer,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="outreach_tasks",
    )
    store = models.ForeignKey(StoreMaster, on_delete=models.PROTECT, related_name="influencer_outreach_tasks")
    spu = models.ForeignKey(ProductSPU, on_delete=models.PROTECT, null=True, blank=True, related_name="influencer_outreach_tasks")
    external_product_id = models.CharField(max_length=120, blank=True)
    sku_prefix = models.CharField(max_length=120, blank=True)
    product_name_snapshot = models.CharField(max_length=240, blank=True)
    product_match_status = models.CharField(max_length=20, default="pending")
    product_match_source = models.CharField(max_length=40, blank=True)
    product_matched_at = models.DateTimeField(null=True, blank=True)
    priority = models.CharField(max_length=20, default="normal")
    target_count = models.PositiveIntegerField(default=0)
    dispatcher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="dispatched_outreach_tasks")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_outreach_tasks")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    dispatch_time = models.DateTimeField(default=timezone.now)
    outreach_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=40, default="manual")
    external_id = models.CharField(max_length=160, blank=True, null=True)
    version = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("influencer", "store", "spu", "dispatcher", "owner")

    class Meta:
        ordering = ["tenant_id", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "task_no"], name="uniq_outreach_task_no"),
            models.UniqueConstraint(fields=["tenant", "source", "external_id"], name="uniq_outreach_external"),
        ]
        indexes = [models.Index(fields=["tenant", "owner", "status"], name="idx_outreach_owner_status")]

    @property
    def linked_count(self):
        if not self.pk:
            return 0
        return self.targets.filter(tenant_id=self.tenant_id, is_deleted=False).count()


class OutreachTarget(StateMachineTenantModel):
    """A tenant-scoped influencer link owned by one outreach task."""

    protected_state_fields = (
        "first_linked_at",
        "outreach_result",
        "version",
        "is_deleted",
        "deleted_at",
    )
    initial_state_values = {
        "outreach_result": "pending",
        "version": 1,
        "is_deleted": False,
        "deleted_at": None,
    }

    class OutreachResult(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        REJECTED = "rejected", "Rejected"
        NO_RESPONSE = "no_response", "No response"
        BLOCKED = "blocked", "Blocked"

    task = models.ForeignKey(OutreachTask, on_delete=models.PROTECT, related_name="targets")
    influencer = models.ForeignKey(Influencer, on_delete=models.PROTECT, related_name="outreach_targets")
    first_linked_at = models.DateTimeField(default=timezone.now)
    outreach_result = models.CharField(
        max_length=20, choices=OutreachResult.choices, default=OutreachResult.PENDING
    )
    version = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("task", "influencer")

    class Meta:
        ordering = ["tenant_id", "task_id", "first_linked_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "task", "influencer"],
                name="uniq_outreach_target_relation",
            )
        ]
        indexes = [models.Index(fields=["tenant", "task", "is_deleted"], name="idx_target_task_active")]

    def clean(self):
        super().clean()
        if self._state.adding and self.task_id:
            task = OutreachTask.objects.filter(pk=self.task_id).values(
                "is_deleted", "status"
            ).first()
            if task is not None and task["is_deleted"]:
                raise ValidationError({"task": "Deleted outreach tasks cannot receive targets."})
            if task is not None and task["status"] in {
                OutreachTask.Status.COMPLETED,
                OutreachTask.Status.CANCELLED,
            }:
                raise ValidationError({"task": "Terminal outreach tasks cannot receive targets."})
        if self.is_deleted and self.deleted_at is None:
            raise ValidationError({"deleted_at": "Deleted outreach targets require deleted_at."})
        if not self.is_deleted and self.deleted_at is not None:
            raise ValidationError({"deleted_at": "Active outreach targets cannot have deleted_at."})
        if self.task_id and not self._state.adding:
            task_status = OutreachTask.objects.filter(pk=self.task_id).values_list(
                "status", flat=True
            ).first()
            if task_status in {OutreachTask.Status.COMPLETED, OutreachTask.Status.CANCELLED}:
                raise ValidationError({"task": "Terminal outreach tasks cannot change targets."})


class SampleFulfillment(StateMachineTenantModel):
    protected_state_fields = ("status", "version", "finalized_at", "sample_sent_at", "shipped_at")
    initial_state_values = {
        "status": "pending",
        "version": 1,
        "finalized_at": None,
        "shipped_at": None,
    }

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        CREATING = "creating", "Creating"
        PUBLISHED = "published", "Published"
        LIVE_CREATOR = "live_creator", "Live creator"
        OVERDUE = "overdue", "Overdue"
        BLANK = "blank", "Blank"

    fulfillment_no = models.CharField(max_length=80)
    request_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    outreach_task = models.ForeignKey(OutreachTask, on_delete=models.PROTECT, related_name="sample_fulfillments")
    outreach_target = models.ForeignKey(
        OutreachTarget,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sample_fulfillments",
    )
    influencer = models.ForeignKey(Influencer, on_delete=models.PROTECT, related_name="sample_fulfillments")
    store = models.ForeignKey(StoreMaster, on_delete=models.PROTECT, related_name="influencer_sample_fulfillments")
    product_name_snapshot = models.CharField(max_length=240, blank=True)
    external_product_id = models.CharField(max_length=120, blank=True)
    sample_order_no = models.CharField(max_length=120, blank=True)
    sample_sent_at = models.DateTimeField(default=timezone.now)
    shipped_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_sample_fulfillments")
    source = models.CharField(max_length=40, default="manual")
    external_id = models.CharField(max_length=160, blank=True, null=True)
    version = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)
    sku_quantity = models.PositiveIntegerField(default=0)
    sales_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    calculated_cost = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    pricing_status = models.CharField(max_length=20, default="pending")
    priced_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("outreach_task", "outreach_target", "influencer", "store", "owner")

    class Meta:
        ordering = ["tenant_id", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "fulfillment_no"], name="uniq_sample_fulfillment_no"),
            models.UniqueConstraint(fields=["tenant", "request_key"], name="uniq_sample_request_key"),
            models.UniqueConstraint(fields=["tenant", "source", "external_id"], name="uniq_sample_external"),
        ]
        indexes = [models.Index(fields=["tenant", "owner", "status"], name="idx_sample_owner_status")]

    def clean(self):
        super().clean()
        if self._state.adding and not self.outreach_target_id:
            raise ValidationError({"outreach_target": "A target is required for new sample fulfillments."})
        if not self.outreach_task_id:
            return
        task = OutreachTask.objects.filter(pk=self.outreach_task_id).values(
            "tenant_id", "influencer_id", "store_id", "owner_id", "external_product_id",
            "is_deleted", "status"
        ).first()
        if task is None:
            raise ValidationError({"outreach_task": "Outreach task does not exist."})
        if task["tenant_id"] != self.tenant_id:
            raise ValidationError({"outreach_task": "Outreach task must belong to the same tenant."})
        if task["is_deleted"] and self._state.adding:
            raise ValidationError({"outreach_task": "Deleted outreach tasks cannot receive samples."})
        if task["status"] in {OutreachTask.Status.COMPLETED, OutreachTask.Status.CANCELLED} and self._state.adding:
            raise ValidationError({"outreach_task": "Terminal outreach tasks cannot receive samples."})
        if self.store_id and task["store_id"] != self.store_id:
            raise ValidationError({"store": "Store must match the outreach task."})
        if self.owner_id and task["owner_id"] != self.owner_id:
            raise ValidationError({"owner": "Owner must match the outreach task."})
        if task["external_product_id"] and self.external_product_id != task["external_product_id"]:
            raise ValidationError({"external_product_id": "Product must match the outreach task."})
        if self.outreach_target_id:
            target = OutreachTarget.objects.filter(pk=self.outreach_target_id).values(
                "tenant_id", "task_id", "influencer_id", "is_deleted"
            ).first()
            if target is None or target["tenant_id"] != self.tenant_id:
                raise ValidationError({"outreach_target": "Outreach target must belong to the same tenant."})
            if target["task_id"] != self.outreach_task_id:
                raise ValidationError({"outreach_target": "Outreach target must belong to the outreach task."})
            if target["influencer_id"] != self.influencer_id:
                raise ValidationError({"influencer": "Influencer must match the outreach target."})
            if target["is_deleted"] and self._state.adding:
                raise ValidationError({"outreach_target": "Deleted outreach targets cannot receive samples."})


class SampleItem(TenantValidatedModel):
    fulfillment = models.ForeignKey(SampleFulfillment, on_delete=models.CASCADE, related_name="items")
    sku = models.ForeignKey(ProductSKU, on_delete=models.PROTECT, null=True, blank=True, related_name="sample_items")
    external_product_id = models.CharField(max_length=120, blank=True)
    site_code = models.CharField(max_length=16)
    requested_sku = models.CharField(max_length=120, null=True, blank=True)
    product_name = models.CharField(max_length=240, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    unit_cost = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    currency = models.CharField(max_length=8, blank=True)
    price_match_status = models.CharField(max_length=20, default="not_imported")
    normalized_sku = models.CharField(max_length=160, blank=True)
    matched_sku_code = models.CharField(max_length=80, blank=True)
    matched_legacy_sku_code = models.CharField(max_length=160, blank=True)
    sales_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    cost_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    cost_match_status = models.CharField(max_length=20, default="pending")
    price_source = models.CharField(max_length=40, blank=True)
    cost_source = models.CharField(max_length=40, blank=True)
    price_snapshot_at = models.DateTimeField(null=True, blank=True)
    cost_snapshot_at = models.DateTimeField(null=True, blank=True)
    match_notes = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("fulfillment", "sku")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "fulfillment", "requested_sku"], name="uniq_sample_item_requested_sku")]

    def clean(self):
        super().clean()
        if self.requested_sku is not None:
            self.requested_sku = self.requested_sku.strip() or None


class FulfillmentStatusEvent(TenantValidatedModel):
    fulfillment = models.ForeignKey(SampleFulfillment, on_delete=models.CASCADE, related_name="status_events")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sample_status_events")
    reason = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    tenant_relation_fields = ("fulfillment", "actor")

    class Meta:
        ordering = ["created_at", "id"]


class ImportBatch(TenantValidatedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        ROLLED_BACK = "rolled_back", "Rolled back"

    source = models.CharField(max_length=40)
    batch_key = models.CharField(max_length=128)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    row_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="influencer_import_batches")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    tenant_relation_fields = ("created_by",)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "source", "batch_key"], name="uniq_influencer_import_batch")]


class StoreProductListing(TenantValidatedModel):
    store = models.ForeignKey(StoreMaster, on_delete=models.PROTECT, related_name="influencer_product_listings")
    spu = models.ForeignKey(ProductSPU, on_delete=models.PROTECT, null=True, blank=True, related_name="store_listings")
    external_product_id = models.CharField(max_length=120)
    parent_sku = models.CharField(max_length=120, blank=True)
    product_name = models.CharField(max_length=240)
    site_code = models.CharField(max_length=16)
    source = models.CharField(max_length=40)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("store", "spu")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "store", "site_code", "external_product_id"], name="uniq_store_external_product")]
        indexes = [models.Index(fields=["tenant", "external_product_id"], name="idx_listing_product_id")]


class SkuPriceSnapshot(TenantValidatedModel):
    listing = models.ForeignKey(StoreProductListing, on_delete=models.CASCADE, related_name="sku_prices")
    sku = models.ForeignKey(ProductSKU, on_delete=models.PROTECT, null=True, blank=True, related_name="store_price_snapshots")
    external_sku = models.CharField(max_length=120)
    variant_id = models.CharField(max_length=120, blank=True)
    variant_name = models.CharField(max_length=160, blank=True)
    original_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    promotion_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    effective_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    inbound_cost = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    currency = models.CharField(max_length=8)
    stock = models.IntegerField(null=True, blank=True)
    source = models.CharField(max_length=40)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    cost_updated_at = models.DateTimeField(null=True, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)
    tenant_relation_fields = ("listing", "sku")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "listing", "external_sku", "variant_id"], name="uniq_listing_external_sku")]
        indexes = [models.Index(fields=["tenant", "external_sku"], name="idx_snapshot_external_sku")]


class ExternalSourceRecord(TenantValidatedModel):
    batch = models.ForeignKey(ImportBatch, on_delete=models.PROTECT, related_name="source_records")
    source = models.CharField(max_length=40)
    external_id = models.CharField(max_length=160)
    record_type = models.CharField(max_length=60)
    payload_hash = models.CharField(max_length=64)
    target_model = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=80, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)
    tenant_relation_fields = ("batch",)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "source", "record_type", "external_id"], name="uniq_influencer_source_record")]
