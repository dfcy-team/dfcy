from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.tenants.models import Tenant


class ProductResearch(models.Model):
    class ApprovalStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="product_research_items")
    research_no = models.CharField(max_length=80)
    product_name = models.CharField(max_length=200)
    platform = models.CharField(max_length=50, blank=True)
    competitor_url = models.URLField(blank=True)
    estimated_sales = models.PositiveIntegerField(default=0)
    estimated_gross_margin = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    risk_points = models.JSONField(default=list, blank=True)
    approval_status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_product_research_items",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "research_no"], name="uniq_research_no_per_tenant"),
        ]

    def __str__(self):
        return f"{self.research_no} {self.product_name}"


class ProductSPU(models.Model):
    class LifecycleStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        DISCONTINUED = "discontinued", "Discontinued"

    class SalesStatus(models.TextChoices):
        NOT_LISTED = "not_listed", "Not listed"
        ON_SALE = "on_sale", "On sale"
        PAUSED = "paused", "Paused"
        STOPPED = "stopped", "Stopped"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="product_spus")
    spu_code = models.CharField(max_length=80)
    product_name = models.CharField(max_length=200)
    category = models.CharField(max_length=120, blank=True)
    lifecycle_status = models.CharField(
        max_length=30,
        choices=LifecycleStatus.choices,
        default=LifecycleStatus.DRAFT,
    )
    sales_status = models.CharField(
        max_length=30,
        choices=SalesStatus.choices,
        default=SalesStatus.NOT_LISTED,
    )
    is_code_frozen = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "spu_code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "spu_code"], name="uniq_spu_code_per_tenant"),
        ]

    def __str__(self):
        return self.spu_code


class ProductSKU(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="product_skus")
    spu = models.ForeignKey(ProductSPU, on_delete=models.CASCADE, related_name="skus")
    sku_code = models.CharField(max_length=80)
    size = models.CharField(max_length=80, blank=True)
    material = models.CharField(max_length=120, blank=True)
    selling_points = models.JSONField(default=list, blank=True)
    package_weight = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    package_volume = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    is_code_frozen = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "sku_code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "sku_code"], name="uniq_sku_code_per_tenant"),
        ]

    def __str__(self):
        return self.sku_code


class ProductStatus(models.TextChoices):
    NEW = "new", "New"
    ACTIVE = "active", "Active"
    SLOW_MOVING = "slow_moving", "Slow moving"
    CLEARANCE_CANDIDATE = "clearance_candidate", "Clearance candidate"
    CLEARANCE = "clearance", "Clearance"
    STOPPED = "stopped", "Stopped"
    ARCHIVED = "archived", "Archived"


class ProductStatusSnapshot(models.Model):
    class Source(models.TextChoices):
        API = "api", "API"
        RPA_READBACK = "rpa_readback", "RPA readback"
        MANUAL = "manual", "Manual"
        SYSTEM_RULE = "system_rule", "System rule"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="product_status_snapshots")
    spu = models.ForeignKey(ProductSPU, on_delete=models.CASCADE, related_name="status_snapshots", null=True, blank=True)
    sku = models.ForeignKey(ProductSKU, on_delete=models.CASCADE, related_name="status_snapshots", null=True, blank=True)
    source = models.CharField(max_length=30, choices=Source.choices)
    source_reference = models.CharField(max_length=120, blank=True)
    metrics_payload = models.JSONField(default=dict, blank=True)
    calculated_status = models.CharField(max_length=40, choices=ProductStatus.choices)
    calculated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["tenant_id", "-calculated_at", "-id"]
        indexes = [
            models.Index(fields=["tenant", "source"], name="idx_product_snapshot_source"),
            models.Index(fields=["tenant", "calculated_status"], name="idx_product_snapshot_status"),
        ]

    def __str__(self):
        return f"{self.tenant_id}:{self.calculated_status}:{self.source}"


class ProductStatusRecommendation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        REJECTED = "rejected", "Rejected"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="product_status_recommendations")
    spu = models.ForeignKey(
        ProductSPU,
        on_delete=models.CASCADE,
        related_name="status_recommendations",
        null=True,
        blank=True,
    )
    sku = models.ForeignKey(
        ProductSKU,
        on_delete=models.CASCADE,
        related_name="status_recommendations",
        null=True,
        blank=True,
    )
    recommended_status = models.CharField(max_length=40, choices=ProductStatus.choices)
    reason_code = models.CharField(max_length=80)
    reason_detail = models.TextField(blank=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    source_snapshot = models.ForeignKey(
        ProductStatusSnapshot,
        on_delete=models.PROTECT,
        related_name="recommendations",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="confirmed_product_status_recommendations",
        null=True,
        blank=True,
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["tenant_id", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["tenant", "status"], name="idx_product_reco_status"),
            models.Index(fields=["tenant", "recommended_status"], name="idx_product_reco_target"),
        ]

    def __str__(self):
        return f"{self.tenant_id}:{self.recommended_status}:{self.status}"


class ProductStatusTransition(models.Model):
    class TriggerType(models.TextChoices):
        MANUAL_CONFIRM = "manual_confirm", "Manual confirm"
        MANUAL_REJECT = "manual_reject", "Manual reject"
        SYSTEM_RULE = "system_rule", "System rule"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="product_status_transitions")
    spu = models.ForeignKey(ProductSPU, on_delete=models.CASCADE, related_name="status_transitions", null=True, blank=True)
    sku = models.ForeignKey(ProductSKU, on_delete=models.CASCADE, related_name="status_transitions", null=True, blank=True)
    from_status = models.CharField(max_length=40, choices=ProductStatus.choices)
    to_status = models.CharField(max_length=40, choices=ProductStatus.choices)
    trigger_type = models.CharField(max_length=30, choices=TriggerType.choices)
    recommendation = models.ForeignKey(
        ProductStatusRecommendation,
        on_delete=models.PROTECT,
        related_name="transitions",
        null=True,
        blank=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_product_status_transitions",
    )
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["tenant_id", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["recommendation"],
                name="uniq_product_status_transition_recommendation",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "from_status", "to_status"], name="idx_product_transition_status"),
        ]

    def __str__(self):
        return f"{self.from_status}->{self.to_status}"


class ProductLifecycleStage(models.TextChoices):
    NEW_OBSERVATION = "new_observation", "New observation"
    GROWTH = "growth", "Growth"
    STABLE = "stable", "Stable"
    SLOW_MOVING_OBSERVATION = "slow_moving_observation", "Slow moving observation"
    CLEARANCE_CANDIDATE = "clearance_candidate", "Clearance candidate"
    CLEARANCE = "clearance", "Clearance"
    STOPPED = "stopped", "Stopped"
    ARCHIVED = "archived", "Archived"


class ProductLifecycleReviewQuerySet(models.QuerySet):
    REVIEW_FIELDS = {"status", "reviewed_by", "reviewed_by_id", "reviewed_at"}
    IMMUTABLE_FIELDS = {
        "tenant", "tenant_id", "spu", "spu_id", "sku", "sku_id", "current_stage",
        "recommended_stage", "review_period_start", "review_period_end", "reason_code",
        "reason_detail", "confidence", "source_metrics", "source_type", "rule_version",
        "dedup_key",
    }

    def update(self, **kwargs):
        if set(kwargs) & self.REVIEW_FIELDS:
            raise ValidationError("Lifecycle decisions require the audited decision service.")
        if set(kwargs) & self.IMMUTABLE_FIELDS:
            raise ValidationError("Lifecycle review evidence is immutable.")
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if set(fields) & self.REVIEW_FIELDS:
            raise ValidationError("Lifecycle decisions require the audited decision service.")
        if set(fields) & self.IMMUTABLE_FIELDS:
            raise ValidationError("Lifecycle review evidence is immutable.")
        return super().bulk_update(objs, fields, batch_size=batch_size)


class ProductLifecycleReview(models.Model):
    class Status(models.TextChoices):
        SUGGESTED = "suggested", "Suggested"
        CONFIRMED = "confirmed", "Confirmed"
        REJECTED = "rejected", "Rejected"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="product_lifecycle_reviews")
    spu = models.ForeignKey(ProductSPU, on_delete=models.PROTECT, related_name="lifecycle_reviews", null=True, blank=True)
    sku = models.ForeignKey(ProductSKU, on_delete=models.PROTECT, related_name="lifecycle_reviews", null=True, blank=True)
    current_stage = models.CharField(max_length=40, choices=ProductLifecycleStage.choices)
    recommended_stage = models.CharField(max_length=40, choices=ProductLifecycleStage.choices)
    review_period_start = models.DateField()
    review_period_end = models.DateField()
    reason_code = models.CharField(max_length=80)
    reason_detail = models.TextField()
    confidence = models.DecimalField(max_digits=5, decimal_places=4)
    source_metrics = models.JSONField(default=dict)
    source_type = models.CharField(
        max_length=30,
        choices=(("mock", "Mock"), ("api", "API"), ("rpa_readback", "RPA readback"), ("manual", "Manual")),
        default="mock",
    )
    rule_version = models.CharField(max_length=40, default="lifecycle-v1")
    dedup_key = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUGGESTED)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_product_lifecycle_reviews",
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = ProductLifecycleReviewQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "-review_period_end", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "dedup_key"], name="uniq_lifecycle_review_dedup"),
            models.CheckConstraint(condition=models.Q(spu__isnull=False) | models.Q(sku__isnull=False), name="lifecycle_review_has_product"),
            models.CheckConstraint(condition=models.Q(review_period_start__lte=models.F("review_period_end")), name="lifecycle_review_valid_period"),
        ]
        indexes = [
            models.Index(fields=["tenant", "status", "review_period_end"], name="idx_lifecycle_review_status"),
            models.Index(fields=["tenant", "sku", "recommended_stage"], name="idx_lifecycle_review_sku"),
        ]

    def clean(self):
        if self.spu_id and self.spu.tenant_id != self.tenant_id:
            raise ValidationError("Lifecycle review and SPU must belong to the same tenant.")
        if self.sku_id and self.sku.tenant_id != self.tenant_id:
            raise ValidationError("Lifecycle review and SKU must belong to the same tenant.")
        if self.sku_id and self.spu_id and self.sku.spu_id != self.spu_id:
            raise ValidationError("Lifecycle review SKU must belong to the supplied SPU.")
        if self.current_stage == self.recommended_stage:
            raise ValidationError("Lifecycle recommendation must propose a stage change.")

    def save(self, *args, **kwargs):
        if self.pk:
            evidence_fields = ProductLifecycleReviewQuerySet.IMMUTABLE_FIELDS - {"tenant", "spu", "sku"}
            current = type(self).objects.filter(pk=self.pk).values(
                "status", "reviewed_by_id", "reviewed_at", *evidence_fields
            ).first()
            if current and any(current[field] != getattr(self, field) for field in evidence_fields):
                raise ValidationError("Lifecycle review evidence is immutable.")
            if current and any(
                current[field] != getattr(self, field)
                for field in ("status", "reviewed_by_id", "reviewed_at")
            ) and not getattr(self, "_decision_service_write", False):
                raise ValidationError("Lifecycle decisions require the audited decision service.")
        self.full_clean()
        try:
            super().save(*args, **kwargs)
        finally:
            self._decision_service_write = False


class ProductLifecycleDecisionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Lifecycle decisions are immutable and require the audited decision service.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Lifecycle decisions are immutable and require the audited decision service.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Lifecycle decisions require the audited decision service.")


class ProductLifecycleDecision(models.Model):
    class Decision(models.TextChoices):
        CONFIRM = "confirm", "Confirm"
        REJECT = "reject", "Reject"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="product_lifecycle_decisions")
    review = models.OneToOneField(ProductLifecycleReview, on_delete=models.PROTECT, related_name="decision_record")
    decision = models.CharField(max_length=20, choices=Decision.choices)
    from_stage = models.CharField(max_length=40, choices=ProductLifecycleStage.choices)
    to_stage = models.CharField(max_length=40, choices=ProductLifecycleStage.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="product_lifecycle_decisions")
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ProductLifecycleDecisionQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "-created_at", "-id"]
        indexes = [models.Index(fields=["tenant", "to_stage", "created_at"], name="idx_lifecycle_decision_stage")]

    def clean(self):
        if self.review_id and self.review.tenant_id != self.tenant_id:
            raise ValidationError("Lifecycle decision and review must belong to the same tenant.")
        if self.actor_id and (self.actor.tenant_id != self.tenant_id or self.actor.user_type != "internal"):
            raise ValidationError("Lifecycle decision actor must be an internal user in the same tenant.")

    def save(self, *args, **kwargs):
        if not getattr(self, "_decision_service_write", False):
            raise ValidationError("Lifecycle decisions require the audited decision service.")
        self.full_clean()
        try:
            super().save(*args, **kwargs)
        finally:
            self._decision_service_write = False
