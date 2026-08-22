from django.conf import settings
from django.db import models

from apps.masterdata.models import PlatformMaster, StoreMaster, SupplierMaster
from apps.products.models import ProductCategory, ProductResearch, ProductSPU
from apps.tenants.models import Tenant


class DevelopmentProject(models.Model):
    class Source(models.TextChoices):
        OPERATION = "operation", "Operation submission"
        INTERNAL = "internal", "Internal development"
        SUPPLIER = "supplier", "Supplier recommendation"

    class Stage(models.TextChoices):
        INITIATED = "initiated", "Initiated"
        DESIGN = "design", "Design"
        SAMPLING = "sampling", "Sampling"
        REVIEW = "review", "Review"
        FINALIZED = "finalized", "Finalized"
        DELIVERED = "delivered", "Delivered"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ON_HOLD = "on_hold", "On hold"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="development_projects")
    project_no = models.CharField(max_length=80)
    requirement = models.ForeignKey(ProductResearch, on_delete=models.PROTECT, related_name="development_projects", null=True, blank=True)
    development_source = models.CharField(max_length=30, choices=Source.choices)
    product_name = models.CharField(max_length=200)
    category = models.CharField(max_length=120, blank=True)
    category_node = models.ForeignKey(
        ProductCategory,
        on_delete=models.PROTECT,
        related_name="development_projects",
        null=True,
        blank=True,
    )
    target_sites = models.JSONField(default=list, blank=True)
    stage = models.CharField(max_length=20, choices=Stage.choices, default=Stage.INITIATED)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assigned_development_projects")
    supplier = models.ForeignKey(SupplierMaster, on_delete=models.PROTECT, related_name="development_projects", null=True, blank=True)
    target_purchase_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    estimated_margin_rate = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    finalized_product = models.ForeignKey(ProductSPU, on_delete=models.PROTECT, related_name="development_projects", null=True, blank=True)
    planned_launch_date = models.DateField(null=True, blank=True)
    actual_launch_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_development_projects")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "-created_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "project_no"], name="uniq_dev_project_no_tenant")]
        indexes = [
            models.Index(fields=["tenant", "stage", "status"], name="idx_dev_project_stage"),
            models.Index(fields=["tenant", "assigned_to"], name="idx_dev_project_owner"),
        ]


class DevelopmentProjectStage(models.Model):
    project = models.ForeignKey(DevelopmentProject, on_delete=models.CASCADE, related_name="stage_records")
    stage = models.CharField(max_length=20, choices=DevelopmentProject.Stage.choices)
    entered_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    deliverables = models.JSONField(default=dict, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="approved_development_stages", null=True, blank=True)
    approval_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["project_id", "entered_at"]
        indexes = [models.Index(fields=["project", "stage"], name="idx_dev_stage_project")]


class DevelopmentCostEstimate(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        APPROVED = "approved", "Approved"

    project = models.ForeignKey(DevelopmentProject, on_delete=models.CASCADE, related_name="cost_estimates")
    site = models.CharField(max_length=40)
    material_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    processing_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    packaging_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    first_leg_shipping = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    platform_commission_rate = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    tariff_rate = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    other_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    target_selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    estimated_margin = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    estimated_margin_rate = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="approved_development_costs", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["project_id", "site", "-version"]
        constraints = [models.UniqueConstraint(fields=["project", "site", "version"], name="uniq_dev_cost_version")]


class DevelopmentSample(models.Model):
    class Evaluation(models.TextChoices):
        PENDING = "pending", "Pending"
        PASS = "pass", "Pass"
        FAIL = "fail", "Fail"
        CONDITIONAL = "conditional", "Conditional"

    project = models.ForeignKey(DevelopmentProject, on_delete=models.CASCADE, related_name="samples")
    supplier = models.ForeignKey(SupplierMaster, on_delete=models.PROTECT, related_name="development_samples")
    sample_no = models.CharField(max_length=80)
    sent_date = models.DateField(null=True, blank=True)
    received_date = models.DateField(null=True, blank=True)
    evaluation_result = models.CharField(max_length=20, choices=Evaluation.choices, default=Evaluation.PENDING)
    evaluation_notes = models.TextField(blank=True)
    photos = models.JSONField(default=list, blank=True)
    unit_price_quoted = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    moq = models.PositiveIntegerField(null=True, blank=True)
    lead_time_days = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["project_id", "-created_at"]
        constraints = [models.UniqueConstraint(fields=["project", "sample_no"], name="uniq_dev_sample_no")]


class DevelopmentRequirementChangeLog(models.Model):
    requirement = models.ForeignKey(ProductResearch, on_delete=models.CASCADE, related_name="development_change_logs")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="development_requirement_changes")
    changed_at = models.DateTimeField(auto_now_add=True)
    change_type = models.CharField(max_length=30)
    field_name = models.CharField(max_length=80, blank=True)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)

    class Meta:
        ordering = ["requirement_id", "-changed_at"]
        indexes = [models.Index(fields=["requirement", "changed_at"], name="idx_dev_req_change")]


class ProductSalesSnapshot(models.Model):
    class Source(models.TextChoices):
        MANUAL = "manual_import", "Manual import"
        ERP = "erp_sync", "ERP sync"
        SHOPEE = "api_shopee", "Shopee API"
        LAZADA = "api_lazada", "Lazada API"
        TIKTOK = "api_tiktok", "TikTok API"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="product_sales_snapshots")
    product = models.ForeignKey(ProductSPU, on_delete=models.CASCADE, related_name="sales_snapshots")
    site = models.CharField(max_length=40)
    platform = models.CharField(max_length=30)
    snapshot_date = models.DateField()
    daily_sales_qty = models.PositiveIntegerField(default=0)
    daily_sales_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    daily_sales_amount_usd = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cumulative_sales_qty = models.PositiveIntegerField(default=0)
    cumulative_sales_amount_usd = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    current_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    category_rank = models.PositiveIntegerField(null=True, blank=True)
    review_count = models.PositiveIntegerField(default=0)
    rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    ad_spend = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    data_source = models.CharField(max_length=30, choices=Source.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["tenant_id", "-snapshot_date"]
        constraints = [models.UniqueConstraint(fields=["tenant", "product", "site", "snapshot_date"], name="uniq_sales_snapshot_day")]
        indexes = [models.Index(fields=["tenant", "snapshot_date"], name="idx_sales_snapshot_date")]


class DevelopmentPerformanceReview(models.Model):
    class Conclusion(models.TextChoices):
        SUCCESS = "success", "Success"
        PARTIAL = "partial", "Partial"
        FAIL = "fail", "Fail"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="development_performance_reviews")
    requirement = models.ForeignKey(ProductResearch, on_delete=models.PROTECT, related_name="performance_reviews", null=True, blank=True)
    project = models.ForeignKey(DevelopmentProject, on_delete=models.PROTECT, related_name="performance_reviews")
    product = models.ForeignKey(ProductSPU, on_delete=models.PROTECT, related_name="development_performance_reviews")
    review_period = models.CharField(max_length=40)
    review_date = models.DateField()
    actual_sales_qty = models.PositiveIntegerField(default=0)
    estimated_sales_qty = models.PositiveIntegerField(default=0)
    hit_rate = models.DecimalField(max_digits=9, decimal_places=4, null=True, blank=True)
    actual_margin_rate = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    estimated_margin_rate = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    margin_deviation = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    conclusion = models.CharField(max_length=20, choices=Conclusion.choices)
    failure_reason = models.TextField(blank=True)
    lessons_learned = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="development_performance_reviews")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["tenant_id", "-review_date"]
        constraints = [models.UniqueConstraint(fields=["project", "review_period"], name="uniq_dev_review_period")]


class ProductSalesSummary(models.Model):
    """Read-only projection backed by ``v_product_sales_summary``."""

    summary_key = models.CharField(primary_key=True, max_length=128)
    product = models.ForeignKey(
        ProductSPU,
        db_column="product_id",
        on_delete=models.DO_NOTHING,
        related_name="sales_summary_projections",
    )
    tenant = models.ForeignKey(Tenant, db_column="tenant_id", on_delete=models.DO_NOTHING)
    site = models.CharField(max_length=40)
    first_sale_date = models.DateField()
    days_listed = models.PositiveIntegerField()
    sales_30d_qty = models.PositiveIntegerField()
    sales_30d_amount_usd = models.DecimalField(max_digits=18, decimal_places=2)
    sales_90d_qty = models.PositiveIntegerField()
    sales_90d_amount_usd = models.DecimalField(max_digits=18, decimal_places=2)
    avg_daily_sales_qty = models.DecimalField(max_digits=18, decimal_places=4)
    total_ad_spend = models.DecimalField(max_digits=18, decimal_places=2)
    roi = models.DecimalField(max_digits=18, decimal_places=4, null=True)

    class Meta:
        managed = False
        db_table = "v_product_sales_summary"
        ordering = ["tenant_id", "product_id", "site"]


class DevelopmentProductArchive(models.Model):
    """Virtual trial archive that only becomes a product after confirmation."""

    class Status(models.TextChoices):
        TRIAL = "trial", "Virtual trial"
        CONFIRMED = "confirmed", "Trial confirmed"
        FORMALIZED = "formalized", "Formal product linked"
        CANCELLED = "cancelled", "Cancelled"

    class TestResult(models.TextChoices):
        PENDING = "pending", "Pending"
        PASS = "pass", "Pass"
        FAIL = "fail", "Fail"
        CONDITIONAL = "conditional", "Conditional"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="development_product_archives")
    project = models.OneToOneField(DevelopmentProject, on_delete=models.PROTECT, related_name="product_archive")
    archive_no = models.CharField(max_length=80)
    product_name = models.CharField(max_length=200)
    # Development identifiers intentionally use a separate namespace from the
    # official product coding service.  The code is supplied by the developer
    # and becomes the first segment of the deterministic trial SKU.
    development_spu_code = models.CharField(max_length=80, blank=True)
    season_code = models.CharField(max_length=1, default="0", blank=True)
    category = models.CharField(max_length=120, blank=True)
    category_node = models.ForeignKey(
        ProductCategory,
        on_delete=models.PROTECT,
        related_name="development_product_archives",
        null=True,
        blank=True,
    )
    # Structured master-data references are authoritative for new records.  The
    # string snapshots below remain for backwards compatibility with archives
    # created before platform/store master data was introduced.
    platform_master = models.ForeignKey(
        PlatformMaster,
        on_delete=models.PROTECT,
        related_name="development_product_archives",
        null=True,
        blank=True,
    )
    store_master = models.ForeignKey(
        StoreMaster,
        on_delete=models.PROTECT,
        related_name="development_product_archives",
        null=True,
        blank=True,
    )
    platform = models.CharField(max_length=50, default="internal")
    site = models.CharField(max_length=40, default="internal")
    inventory_mode = models.CharField(max_length=20, default="virtual", editable=False)
    virtual_inventory_sku = models.CharField(max_length=100)
    virtual_inventory_qty = models.PositiveIntegerField(default=0)
    test_result = models.CharField(max_length=20, choices=TestResult.choices, default=TestResult.PENDING)
    test_notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIAL)
    formal_product = models.OneToOneField(
        ProductSPU,
        on_delete=models.PROTECT,
        related_name="development_product_archive",
        null=True,
        blank=True,
    )
    # A trial product is safe to expose to platform-test tooling because it is
    # always a draft/not-listed product. Formalization creates a separate
    # official SPU and preserves this trial-to-formal mapping.
    trial_product = models.ForeignKey(
        ProductSPU,
        on_delete=models.PROTECT,
        related_name="development_trial_archives",
        null=True,
        blank=True,
    )
    trial_sku = models.ForeignKey(
        "products.ProductSKU",
        on_delete=models.PROTECT,
        related_name="development_trial_archives",
        null=True,
        blank=True,
    )
    formal_sku = models.ForeignKey(
        "products.ProductSKU",
        on_delete=models.PROTECT,
        related_name="formalized_development_archives",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_development_product_archives",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_development_product_archives",
        null=True,
        blank=True,
    )
    trial_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="confirmed_development_product_archives",
        null=True,
        blank=True,
    )
    trial_confirmed_at = models.DateTimeField(null=True, blank=True)
    formalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="formalized_development_product_archives",
        null=True,
        blank=True,
    )
    formalized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "archive_no"], name="uniq_dev_product_archive_no"),
            models.UniqueConstraint(
                fields=["tenant", "development_spu_code"],
                condition=~models.Q(development_spu_code=""),
                name="uniq_dev_archive_dev_spu_code",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"], name="idx_dev_product_archive_status"),
            models.Index(fields=["tenant", "platform", "site"], name="idx_dev_product_archive_market"),
            models.Index(fields=["tenant", "platform_master"], name="idx_dev_archive_platform_ref"),
            models.Index(fields=["tenant", "store_master"], name="idx_dev_archive_store_ref"),
        ]

    @property
    def is_virtual(self):
        return self.status in {self.Status.TRIAL, self.Status.CONFIRMED}


class DevelopmentProductArchiveEvent(models.Model):
    archive = models.ForeignKey(DevelopmentProductArchive, on_delete=models.CASCADE, related_name="events")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="development_product_archive_events")
    action = models.CharField(max_length=40)
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="development_product_archive_events",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["archive_id", "created_at", "id"]
        indexes = [
            models.Index(fields=["tenant", "archive", "created_at"], name="idx_dev_product_archive_event"),
        ]
