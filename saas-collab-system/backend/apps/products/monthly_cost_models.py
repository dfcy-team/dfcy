from django.core.exceptions import ValidationError
from django.db import models

from apps.tenants.models import Tenant
from .models import ProductSKU


class MonthlyProductCost(models.Model):
    """Mutable estimate until finalized; each revision is retained in version_no."""

    class Status(models.TextChoices):
        ESTIMATED = "estimated", "Estimated"
        PENDING_REVIEW = "pending_review", "Pending review"
        FINALIZED = "finalized", "Finalized"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="monthly_product_costs")
    sku = models.ForeignKey(ProductSKU, on_delete=models.PROTECT, related_name="monthly_costs")
    warehouse = models.ForeignKey("masterdata.WarehouseMaster", on_delete=models.PROTECT, related_name="monthly_product_costs")
    month = models.DateField(help_text="First day of the business month")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ESTIMATED)
    version_no = models.PositiveIntegerField(default=0)
    opening_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    opening_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    receipt_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    receipt_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    adjustment_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    outbound_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    closing_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    closing_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    unit_cost = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    is_complete = models.BooleanField(default=False)
    missing_reason = models.CharField(max_length=255, blank=True)
    watermark = models.JSONField(default=dict, blank=True)
    calculated_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "sku", "warehouse", "month"), name="uniq_month_cost_tenant_sku_wh_month"),
            models.CheckConstraint(condition=models.Q(month__day=1), name="monthly_cost_month_first_day"),
        ]
        indexes = [models.Index(fields=("tenant", "month", "status"), name="idx_month_cost_tenant_status")]

    def clean(self):
        if self.month and self.month.day != 1:
            raise ValidationError({"month": "month must be the first day of a month"})
        if self.sku_id and self.sku.tenant_id != self.tenant_id:
            raise ValidationError({"sku": "SKU must belong to tenant"})
        if self.warehouse_id and self.warehouse.tenant_id != self.tenant_id:
            raise ValidationError({"warehouse": "Warehouse must belong to tenant"})
        for field in ("opening_amount", "receipt_amount"):
            value = getattr(self, field)
            if value is not None and value < 0:
                raise ValidationError({field: "Cost amounts cannot be negative"})
        if self.is_complete and any(getattr(self, field) is None for field in ("opening_amount", "receipt_amount", "adjustment_amount")):
            raise ValidationError("Complete cost requires known amount inputs")
        if self.pk and type(self).objects.filter(pk=self.pk, status=self.Status.FINALIZED).exists():
            raise ValidationError("Finalized monthly costs are immutable")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class MonthlyProductCostEvent(models.Model):
    """Idempotency ledger for source movements included in monthly cost."""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="monthly_product_cost_events")
    monthly_cost = models.ForeignKey(MonthlyProductCost, on_delete=models.CASCADE, related_name="source_events")
    source_type = models.CharField(max_length=40)
    source_key = models.CharField(max_length=160)
    quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant", "source_type", "source_key"), name="uniq_month_cost_source_event")]


class MonthlyProductCostVersion(models.Model):
    monthly_cost = models.ForeignKey(MonthlyProductCost, on_delete=models.PROTECT, related_name="versions")
    version_no = models.PositiveIntegerField()
    snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("monthly_cost", "version_no"), name="uniq_month_cost_version")]
