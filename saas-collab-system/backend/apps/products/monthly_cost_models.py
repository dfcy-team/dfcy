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
    other_in_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    other_in_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    other_out_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    sales_cost_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    historical_sold_adjustment = models.DecimalField(max_digits=18, decimal_places=4, default=0)
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
        for field in ("opening_quantity", "receipt_quantity", "outbound_quantity", "other_in_quantity", "other_out_quantity", "other_in_amount"):
            if getattr(self, field) < 0:
                raise ValidationError({field: "Quantity and incoming amounts cannot be negative"})
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


class MonthlyCostAdjustment(models.Model):
    """One late receipt-cost delta; allocation is current-period only and auditable."""
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    sku = models.ForeignKey(ProductSKU, on_delete=models.PROTECT)
    warehouse = models.ForeignKey("masterdata.WarehouseMaster", on_delete=models.PROTECT)
    original_month = models.DateField()
    effective_month = models.DateField()
    receipt_line_id = models.PositiveBigIntegerField()
    source_key = models.CharField(max_length=160)
    delta_amount = models.DecimalField(max_digits=18, decimal_places=4)
    inventory_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    sold_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    status = models.CharField(max_length=20, default="pending")
    evidence = models.JSONField(default=dict)
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant", "source_key"), name="uniq_monthly_adjustment_source")]
        indexes = [models.Index(fields=("tenant", "effective_month", "warehouse"), name="idx_month_adjust_period")]

    def clean(self):
        if self.sku_id and self.sku.tenant_id != self.tenant_id:
            raise ValidationError("Adjustment SKU tenant mismatch")
        if self.warehouse_id and self.warehouse.tenant_id != self.tenant_id:
            raise ValidationError("Adjustment warehouse tenant mismatch")
        if self.original_month.day != 1 or self.effective_month.day != 1 or self.effective_month <= self.original_month:
            raise ValidationError("Late adjustments require a later effective month")
        if self.status == "allocated":
            if self.inventory_amount is None or self.sold_amount is None or self.inventory_amount + self.sold_amount != self.delta_amount:
                raise ValidationError("Adjustment allocation must conserve total amount")

    def save(self, *args, **kwargs):
        self.full_clean()
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            if old.status == "allocated":
                raise ValidationError("Allocated adjustments are immutable; post a new source delta")
        super().save(*args, **kwargs)


class MonthlyCostMovement(models.Model):
    """Normalized non-sale stock facts; provider refs or reviewed imports are required."""
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    sku = models.ForeignKey(ProductSKU, on_delete=models.PROTECT)
    warehouse = models.ForeignKey("masterdata.WarehouseMaster", on_delete=models.PROTECT)
    month = models.DateField()
    source_key = models.CharField(max_length=160)
    kind = models.CharField(max_length=24, choices=[(v,v) for v in ("return", "transfer_in", "transfer_out", "loss", "count_in", "count_out")])
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    evidence = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant", "source_key"), name="uniq_month_cost_movement_source")]
        indexes = [models.Index(fields=("tenant", "month", "warehouse"), name="idx_month_movement_period")]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Stock movement facts are immutable")
        if self.quantity <= 0 or self.month.day != 1 or not self.evidence:
            raise ValidationError("Movement requires positive quantity, month boundary and source evidence")
        if self.sku.tenant_id != self.tenant_id or self.warehouse.tenant_id != self.tenant_id:
            raise ValidationError("Movement tenant mismatch")
        if self.kind in ("return", "transfer_in", "count_in") and (self.amount is None or self.amount < 0):
            raise ValidationError("Incoming movement needs a nonnegative known source amount")
        self.full_clean()
        super().save(*args, **kwargs)


class MonthlyCostInventoryEvidence(models.Model):
    """Immutable full physical warehouse snapshot at an exact business-month boundary."""
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    warehouse = models.ForeignKey("masterdata.WarehouseMaster", on_delete=models.PROTECT)
    boundary = models.DateField(help_text="Month opening date; previous month closing")
    source_key = models.CharField(max_length=160)
    snapshot_at = models.DateTimeField()
    content_hash = models.CharField(max_length=64)
    quantities = models.JSONField(help_text="Internal SKU id to decimal physical quantity")
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant", "warehouse", "boundary", "source_key"), name="uniq_month_cost_stock_evidence")]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Inventory evidence is immutable")
        if self.boundary.day != 1 or self.warehouse.tenant_id != self.tenant_id:
            raise ValidationError("Invalid warehouse or inventory boundary")
        if not self.metadata.get("complete") or self.metadata.get("quantity_basis") != "on_hand":
            raise ValidationError("Complete physical inventory evidence is required")
        self.full_clean()
        super().save(*args, **kwargs)
