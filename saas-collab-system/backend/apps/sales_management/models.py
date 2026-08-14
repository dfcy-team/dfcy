from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.tenants.models import Tenant


class SalesOrder(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="sales_orders")
    platform = models.CharField(max_length=40)
    region = models.CharField(max_length=40, blank=True)
    store_id = models.CharField(max_length=120)
    source_order_id = models.CharField(max_length=160)
    system_order_no = models.CharField(max_length=160)
    order_status = models.CharField(max_length=40, default="pending")
    fulfillment_status = models.CharField(max_length=40, default="pending")
    refund_status = models.CharField(max_length=40, default="none")
    currency = models.CharField(max_length=12)
    gross_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    net_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    discount_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    shipping_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    buyer_region = models.CharField(max_length=120, blank=True)
    ordered_at = models.DateTimeField()
    source_updated_at = models.DateTimeField()
    source_batch = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-ordered_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform", "store_id", "source_order_id"],
                name="uniq_sales_order_source",
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "ordered_at"], name="idx_sales_order_date"),
            models.Index(fields=["tenant", "store_id"], name="idx_sales_order_store"),
        ]


class SalesOrderLine(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="sales_order_lines")
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="lines")
    source_line_id = models.CharField(max_length=160)
    spu = models.CharField(max_length=120, blank=True)
    sku = models.CharField(max_length=120)
    product_name = models.CharField(max_length=240, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    discount_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    shipping_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    source_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["order_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "order", "source_line_id"],
                name="uniq_sales_order_line",
            )
        ]

    def clean(self):
        if self.order_id and self.tenant_id != self.order.tenant_id:
            raise ValidationError("Order line tenant must match its order tenant.")


class SalesReturn(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="sales_returns")
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="returns")
    platform = models.CharField(max_length=40)
    region = models.CharField(max_length=40, blank=True)
    store_id = models.CharField(max_length=120)
    source_return_id = models.CharField(max_length=160)
    return_type = models.CharField(max_length=40, default="refund")
    status = models.CharField(max_length=40, default="pending")
    sku = models.CharField(max_length=120, blank=True)
    quantity = models.PositiveIntegerField(default=0)
    requested_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    refunded_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    currency = models.CharField(max_length=12)
    source_reason = models.CharField(max_length=240, blank=True)
    normalized_reason = models.CharField(max_length=120, blank=True)
    requested_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    source_updated_at = models.DateTimeField()
    source_batch = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["-requested_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform", "store_id", "source_return_id"],
                name="uniq_sales_return_source",
            )
        ]

    def clean(self):
        if self.order_id and self.tenant_id != self.order.tenant_id:
            raise ValidationError("Sales return tenant must match its order tenant.")


class StoreSalesFact(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="store_sales_facts")
    platform = models.CharField(max_length=40)
    region = models.CharField(max_length=40, blank=True)
    store_id = models.CharField(max_length=120)
    period_start = models.DateField()
    period_end = models.DateField()
    currency = models.CharField(max_length=12)
    gross_sales = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    net_sales = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    order_count = models.PositiveIntegerField(default=0)
    units_sold = models.PositiveIntegerField(default=0)
    refund_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    source_updated_at = models.DateTimeField()
    source_batch = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["-period_end", "platform", "store_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform", "store_id", "period_start", "period_end", "currency"],
                name="uniq_store_sales_fact",
            )
        ]


class SKUSalesFact(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="sku_sales_facts")
    platform = models.CharField(max_length=40)
    region = models.CharField(max_length=40, blank=True)
    store_id = models.CharField(max_length=120)
    period_start = models.DateField()
    period_end = models.DateField()
    spu = models.CharField(max_length=120, blank=True)
    sku = models.CharField(max_length=120)
    product_name = models.CharField(max_length=240, blank=True)
    category = models.CharField(max_length=120, blank=True)
    currency = models.CharField(max_length=12)
    units_sold = models.PositiveIntegerField(default=0)
    gross_sales = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    net_sales = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    order_count = models.PositiveIntegerField(default=0)
    refund_units = models.PositiveIntegerField(default=0)
    last_sold_at = models.DateTimeField(null=True, blank=True)
    inventory_risk = models.CharField(max_length=40, blank=True)
    inventory_source = models.CharField(max_length=120, blank=True)
    inventory_updated_at = models.DateTimeField(null=True, blank=True)
    source_updated_at = models.DateTimeField()
    source_batch = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["-period_end", "-gross_sales", "sku"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform", "store_id", "sku", "period_start", "period_end", "currency"],
                name="uniq_sku_sales_fact",
            )
        ]


class SyncSource(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="sales_sync_sources")
    platform = models.CharField(max_length=40)
    region = models.CharField(max_length=40, blank=True)
    store_id = models.CharField(max_length=120)
    credential_id = models.CharField(max_length=120, blank=True)
    credential_mask = models.CharField(max_length=120, blank=True)
    credential_version = models.PositiveIntegerField(default=1)
    authorization_status = models.CharField(max_length=40, default="pending")
    credential_expires_at = models.DateTimeField(null=True, blank=True)
    run_status = models.CharField(max_length=40, default="pending")
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    sync_cursor = models.CharField(max_length=200, blank=True)
    data_delay_seconds = models.PositiveIntegerField(default=0)
    error_summary = models.CharField(max_length=240, blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["platform", "region", "store_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform", "store_id"],
                name="uniq_sales_sync_source",
            )
        ]


class DataQualityIssue(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="sales_quality_issues")
    issue_key = models.CharField(max_length=180)
    issue_type = models.CharField(max_length=80)
    severity = models.CharField(max_length=20, default="medium")
    status = models.CharField(max_length=20, default="open")
    platform = models.CharField(max_length=40, blank=True)
    region = models.CharField(max_length=40, blank=True)
    store_id = models.CharField(max_length=120, blank=True)
    entity_type = models.CharField(max_length=80, blank=True)
    source_record_id = models.CharField(max_length=160, blank=True)
    message = models.CharField(max_length=300)
    detected_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["status", "-detected_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "issue_key"], name="uniq_sales_quality_issue")
        ]


class SalesExportRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="sales_export_requests")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sales_export_requests")
    request_key = models.CharField(max_length=120)
    request_fingerprint = models.CharField(max_length=64, default="")
    export_type = models.CharField(max_length=40)
    filters = models.JSONField(default=dict)
    data_scope = models.JSONField(default=list)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    record_count = models.PositiveIntegerField(default=0)
    file_reference = models.CharField(max_length=240, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "requested_by", "request_key"],
                name="uniq_sales_export_request",
            )
        ]


class SyncRerunRequest(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="sales_sync_rerun_requests")
    sync_source = models.ForeignKey(SyncSource, on_delete=models.PROTECT, related_name="rerun_requests")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sales_sync_rerun_requests")
    request_key = models.CharField(max_length=120)
    request_fingerprint = models.CharField(max_length=64, default="")
    reason = models.CharField(max_length=240)
    data_scope = models.JSONField(default=list)
    status = models.CharField(max_length=20, default="requested")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "requested_by", "request_key"],
                name="uniq_sales_sync_rerun",
            )
        ]

    def clean(self):
        if self.sync_source_id and self.tenant_id != self.sync_source.tenant_id:
            raise ValidationError("Sync rerun tenant must match its source tenant.")
