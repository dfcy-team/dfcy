from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant


class ReplenishmentRecommendationQuerySet(models.QuerySet):
    REVIEW_FIELDS = {"status", "reviewed_by", "reviewed_by_id", "reviewed_at", "review_reason"}

    def update(self, **kwargs):
        if set(kwargs) & self.REVIEW_FIELDS:
            raise ValidationError("Recommendation review changes require the audited review service.")
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if set(fields) & self.REVIEW_FIELDS:
            raise ValidationError("Recommendation review changes require the audited review service.")
        return super().bulk_update(objs, fields, batch_size=batch_size)


class ReplenishmentRecommendation(models.Model):
    class Status(models.TextChoices):
        SUGGESTED = "suggested", "Suggested"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="replenishment_recommendations")
    spu = models.ForeignKey(ProductSPU, on_delete=models.PROTECT, related_name="replenishment_recommendations", null=True, blank=True)
    sku = models.ForeignKey(ProductSKU, on_delete=models.PROTECT, related_name="replenishment_recommendations", null=True, blank=True)
    available_stock = models.DecimalField(max_digits=16, decimal_places=4)
    in_transit_stock = models.DecimalField(max_digits=16, decimal_places=4)
    average_daily_sales = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True)
    safety_stock_days = models.PositiveIntegerField()
    supplier_lead_days = models.PositiveIntegerField()
    replenishment_cycle_days = models.PositiveIntegerField()
    suggested_quantity = models.PositiveIntegerField(default=0)
    suggested_date = models.DateField()
    confidence = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    reason_code = models.CharField(max_length=80)
    reason_detail = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUGGESTED)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_replenishment_recommendations",
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.TextField(blank=True)
    source_summary = models.JSONField(default=dict)
    formula_version = models.CharField(max_length=40, default="replenishment-v1")
    dedup_key = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = ReplenishmentRecommendationQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "dedup_key"], name="uniq_replenishment_dedup"),
            models.CheckConstraint(
                condition=models.Q(spu__isnull=False) | models.Q(sku__isnull=False),
                name="replenishment_has_product",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status", "created_at"], name="idx_replenishment_status"),
            models.Index(fields=["tenant", "sku", "suggested_date"], name="idx_replenishment_sku"),
        ]

    def clean(self):
        if self.spu_id and self.spu.tenant_id != self.tenant_id:
            raise ValidationError("Recommendation and SPU must belong to the same tenant.")
        if self.sku_id and self.sku.tenant_id != self.tenant_id:
            raise ValidationError("Recommendation and SKU must belong to the same tenant.")
        if self.sku_id and self.spu_id and self.sku.spu_id != self.spu_id:
            raise ValidationError("Recommendation SKU must belong to the supplied SPU.")
        if self.reviewed_by_id and (
            self.reviewed_by.tenant_id != self.tenant_id or self.reviewed_by.user_type != "internal"
        ):
            raise ValidationError("Reviewer must be an internal user in the same tenant.")

    def save(self, *args, **kwargs):
        if self.pk and not getattr(self, "_review_service_write", False):
            current = type(self).objects.filter(pk=self.pk).values(
                "status", "reviewed_by_id", "reviewed_at", "review_reason"
            ).first()
            if current and any(
                current[field] != getattr(self, field)
                for field in ("status", "reviewed_by_id", "reviewed_at", "review_reason")
            ):
                raise ValidationError("Recommendation review changes require the audited review service.")
        self.full_clean()
        try:
            super().save(*args, **kwargs)
        finally:
            self._review_service_write = False
