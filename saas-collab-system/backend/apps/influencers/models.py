from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction

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


class OutreachTask(TenantValidatedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    task_no = models.CharField(max_length=80)
    influencer = models.ForeignKey(Influencer, on_delete=models.PROTECT, related_name="outreach_tasks")
    store = models.ForeignKey(StoreMaster, on_delete=models.PROTECT, related_name="influencer_outreach_tasks")
    spu = models.ForeignKey(ProductSPU, on_delete=models.PROTECT, null=True, blank=True, related_name="influencer_outreach_tasks")
    dispatcher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="dispatched_outreach_tasks")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_outreach_tasks")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    started_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=40, default="manual")
    external_id = models.CharField(max_length=160, blank=True, null=True)
    version = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)
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


class SampleFulfillment(TenantValidatedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    fulfillment_no = models.CharField(max_length=80)
    request_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    outreach_task = models.ForeignKey(OutreachTask, on_delete=models.PROTECT, related_name="sample_fulfillments")
    influencer = models.ForeignKey(Influencer, on_delete=models.PROTECT, related_name="sample_fulfillments")
    store = models.ForeignKey(StoreMaster, on_delete=models.PROTECT, related_name="influencer_sample_fulfillments")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_sample_fulfillments")
    source = models.CharField(max_length=40, default="manual")
    external_id = models.CharField(max_length=160, blank=True, null=True)
    version = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("outreach_task", "influencer", "store", "owner")

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
        if self.outreach_task_id and self.influencer_id and self.outreach_task.influencer_id != self.influencer_id:
            raise ValidationError({"influencer": "Influencer must match the outreach task."})


class SampleItem(TenantValidatedModel):
    fulfillment = models.ForeignKey(SampleFulfillment, on_delete=models.CASCADE, related_name="items")
    sku = models.ForeignKey(ProductSKU, on_delete=models.PROTECT, null=True, blank=True, related_name="sample_items")
    external_product_id = models.CharField(max_length=120, blank=True)
    site_code = models.CharField(max_length=16)
    requested_sku = models.CharField(max_length=120, blank=True)
    product_name = models.CharField(max_length=240, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    unit_cost = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    currency = models.CharField(max_length=8, blank=True)
    price_match_status = models.CharField(max_length=20, default="not_imported")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("fulfillment", "sku")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "fulfillment", "requested_sku"], name="uniq_sample_item_requested_sku")]


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
