from django.conf import settings
from django.db import models

from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant


class ListingTemplate(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="listing_templates")
    template_no = models.CharField(max_length=80)
    name = models.CharField(max_length=160)
    platform = models.ForeignKey(PlatformMaster, on_delete=models.PROTECT, related_name="listing_templates")
    country_code = models.CharField(max_length=8)
    category_code = models.CharField(max_length=120, blank=True)
    field_schema = models.JSONField(default=dict)
    default_values = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_listing_templates")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "template_no", "-version"]
        constraints = [models.UniqueConstraint(fields=["tenant", "template_no", "version"], name="uniq_listing_template_ver")]
        indexes = [models.Index(fields=["tenant", "platform", "country_code"], name="idx_listing_template_site")]


class ListingProfile(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        READY = "ready", "Ready"
        PENDING_APPROVAL = "pending_approval", "Pending approval"
        APPROVED = "approved", "Approved"
        PUBLISHING = "publishing", "Publishing"
        PUBLISHED = "published", "Published"
        FAILED = "failed", "Failed"
        ARCHIVED = "archived", "Archived"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="listing_profiles")
    profile_no = models.CharField(max_length=80)
    product = models.ForeignKey(ProductSPU, on_delete=models.PROTECT, related_name="listing_profiles")
    store = models.ForeignKey(StoreMaster, on_delete=models.PROTECT, related_name="listing_profiles")
    template = models.ForeignKey(ListingTemplate, on_delete=models.PROTECT, related_name="profiles", null=True, blank=True)
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    category_code = models.CharField(max_length=120, blank=True)
    attributes = models.JSONField(default=dict, blank=True)
    media = models.JSONField(default=list, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=8)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT)
    validation_errors = models.JSONField(default=list, blank=True)
    external_listing_id = models.CharField(max_length=160, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="approved_listing_profiles", null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_listing_profiles")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "-updated_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "profile_no"], name="uniq_listing_profile_no")]
        indexes = [
            models.Index(fields=["tenant", "store", "status"], name="idx_listing_store_status"),
            models.Index(fields=["tenant", "product"], name="idx_listing_product"),
        ]


class PlatformCategoryMapping(models.Model):
    """Tenant-owned mapping between an internal category and a platform node.

    The mapping is deliberately metadata only.  It does not call a platform API;
    publication adapters can consume the stable mapping snapshot later.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="listing_category_mappings")
    platform = models.ForeignKey(PlatformMaster, on_delete=models.PROTECT, related_name="listing_category_mappings")
    country_code = models.CharField(max_length=8, blank=True)
    source_category_code = models.CharField(max_length=120)
    source_category_name = models.CharField(max_length=200, blank=True)
    target_category_code = models.CharField(max_length=160)
    target_category_name = models.CharField(max_length=200, blank=True)
    mapping_version = models.PositiveIntegerField(default=1)
    metadata = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_listing_category_mappings")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "platform_id", "country_code", "source_category_code", "-mapping_version"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform", "country_code", "source_category_code", "mapping_version"],
                name="uniq_listing_category_mapping_ver",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "platform", "country_code", "status"], name="idx_listing_category_map"),
        ]


class ListingAttributeMapping(models.Model):
    """Map an internal product attribute to a platform/template field."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="listing_attribute_mappings")
    platform = models.ForeignKey(PlatformMaster, on_delete=models.PROTECT, related_name="listing_attribute_mappings")
    template = models.ForeignKey(
        ListingTemplate,
        on_delete=models.CASCADE,
        related_name="attribute_mappings",
        null=True,
        blank=True,
    )
    country_code = models.CharField(max_length=8, blank=True)
    source_attribute_code = models.CharField(max_length=120)
    source_attribute_name = models.CharField(max_length=200, blank=True)
    target_attribute_code = models.CharField(max_length=160)
    target_attribute_name = models.CharField(max_length=200, blank=True)
    value_mapping = models.JSONField(default=dict, blank=True)
    is_required = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_listing_attribute_mappings")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "platform_id", "country_code", "source_attribute_code", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform", "template", "country_code", "source_attribute_code"],
                name="uniq_listing_attribute_mapping",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "platform", "country_code", "status"], name="idx_listing_attr_map"),
        ]


class ListingVariant(models.Model):
    profile = models.ForeignKey(ListingProfile, on_delete=models.CASCADE, related_name="variants")
    sku = models.ForeignKey(ProductSKU, on_delete=models.PROTECT, related_name="listing_variants")
    seller_sku = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    stock_quantity = models.PositiveIntegerField(default=0)
    attributes = models.JSONField(default=dict, blank=True)
    external_variant_id = models.CharField(max_length=160, blank=True)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["profile_id", "seller_sku"]
        constraints = [models.UniqueConstraint(fields=["profile", "seller_sku"], name="uniq_listing_seller_sku")]


class ListingPublicationJob(models.Model):
    class Action(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        PAUSE = "pause", "Pause"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    class ExecutionChannel(models.TextChoices):
        API = "api", "API"
        RPA = "rpa", "RPA"
        MANUAL = "manual", "Manual"

    class ExecutionMode(models.TextChoices):
        DRY_RUN = "dry_run", "Dry run"
        PRODUCTION = "production", "Production"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="listing_publication_jobs")
    profile = models.ForeignKey(ListingProfile, on_delete=models.PROTECT, related_name="publication_jobs")
    action = models.CharField(max_length=20, choices=Action.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    idempotency_key = models.CharField(max_length=128)
    payload_snapshot = models.JSONField(default=dict)
    response_snapshot = models.JSONField(default=dict, blank=True)
    execution_channel = models.CharField(
        max_length=20,
        choices=ExecutionChannel.choices,
        default=ExecutionChannel.RPA,
    )
    execution_mode = models.CharField(
        max_length=20,
        choices=ExecutionMode.choices,
        default=ExecutionMode.DRY_RUN,
    )
    confirmed_production = models.BooleanField(default=False)
    # Kept as a nullable relation so existing publication records remain valid.
    rpa_task = models.ForeignKey(
        "rpa.RPATask",
        on_delete=models.SET_NULL,
        related_name="listing_publication_jobs",
        null=True,
        blank=True,
    )
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.TextField(blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_listing_jobs")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["tenant_id", "-created_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="uniq_listing_job_key")]
        indexes = [models.Index(fields=["tenant", "status", "created_at"], name="idx_listing_job_status")]


class ListingTask(models.Model):
    """Execution envelope for a listing publication or update.

    A task is intentionally separate from the publication job: the job is the
    idempotent business request while this record tracks the chosen API/RPA
    execution channel and lifecycle.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    class ExecutionChannel(models.TextChoices):
        API = "api", "API"
        RPA = "rpa", "RPA"
        MANUAL = "manual", "Manual"

    class ExecutionMode(models.TextChoices):
        DRY_RUN = "dry_run", "Dry run"
        PRODUCTION = "production", "Production"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="listing_tasks")
    task_no = models.CharField(max_length=100)
    profile = models.ForeignKey(ListingProfile, on_delete=models.PROTECT, related_name="listing_tasks", null=True, blank=True)
    publication_job = models.OneToOneField(
        ListingPublicationJob,
        on_delete=models.CASCADE,
        related_name="listing_task",
        null=True,
        blank=True,
    )
    execution_channel = models.CharField(max_length=20, choices=ExecutionChannel.choices, default=ExecutionChannel.RPA)
    execution_mode = models.CharField(max_length=20, choices=ExecutionMode.choices, default=ExecutionMode.DRY_RUN)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    idempotency_key = models.CharField(max_length=128)
    payload_snapshot = models.JSONField(default=dict)
    result_snapshot = models.JSONField(default=dict, blank=True)
    current_step = models.CharField(max_length=120, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.TextField(blank=True)
    confirmed_production = models.BooleanField(default=False)
    rpa_task = models.ForeignKey(
        "rpa.RPATask",
        on_delete=models.SET_NULL,
        related_name="listing_tasks",
        null=True,
        blank=True,
    )
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_listing_tasks")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "task_no"], name="uniq_listing_task_no"),
            models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="uniq_listing_task_key"),
        ]
        indexes = [
            models.Index(fields=["tenant", "status", "created_at"], name="idx_listing_task_status"),
            models.Index(fields=["tenant", "execution_channel", "execution_mode"], name="idx_listing_task_channel"),
        ]


class ListingTaskStepLog(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="listing_task_step_logs")
    task = models.ForeignKey(ListingTask, on_delete=models.CASCADE, related_name="step_logs")
    step_no = models.PositiveIntegerField(default=1)
    step_name = models.CharField(max_length=120)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    message = models.TextField(blank=True)
    detail = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["task_id", "step_no", "id"]
        constraints = [
            models.UniqueConstraint(fields=["task", "step_no"], name="uniq_listing_task_step_no"),
        ]


class ListingTaskErrorLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="listing_task_error_logs")
    task = models.ForeignKey(ListingTask, on_delete=models.CASCADE, related_name="error_logs")
    step = models.ForeignKey(ListingTaskStepLog, on_delete=models.SET_NULL, related_name="error_logs", null=True, blank=True)
    error_code = models.CharField(max_length=80)
    message = models.TextField()
    detail = models.JSONField(default=dict, blank=True)
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="resolved_listing_task_errors",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["task_id", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["tenant", "is_resolved", "created_at"], name="idx_listing_task_error"),
        ]


class ListingChangeLog(models.Model):
    profile = models.ForeignKey(ListingProfile, on_delete=models.CASCADE, related_name="change_logs")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="listing_changes")
    action = models.CharField(max_length=40)
    before_snapshot = models.JSONField(default=dict, blank=True)
    after_snapshot = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["profile_id", "-created_at"]
        indexes = [models.Index(fields=["profile", "created_at"], name="idx_listing_change")]


# Stable aliases used by integrations and older UI prototypes.
ListingPlatformCategoryMapping = PlatformCategoryMapping
ListingProductAttributeMapping = ListingAttributeMapping
ListingTaskStep = ListingTaskStepLog
ListingTaskError = ListingTaskErrorLog
ListingPublicationTask = ListingTask
