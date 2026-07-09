from django.db import models

from apps.tenants.models import Tenant


class SupplierTask(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In progress"
        PARTIAL = "partial", "Partial"
        COMPLETED = "completed", "Completed"
        EXCEPTION = "exception", "Exception"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="supplier_tasks")
    supplier_id = models.BigIntegerField()
    task_no = models.CharField(max_length=80)
    sku_code = models.CharField(max_length=80)
    production_quantity = models.PositiveIntegerField(default=0)
    completed_quantity = models.PositiveIntegerField(default=0)
    expected_ship_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    is_overdue = models.BooleanField(default=False)
    feedback_note = models.TextField(blank=True)
    exception_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "expected_ship_date", "task_no"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "task_no"], name="uniq_supplier_task_no_per_tenant"),
        ]

    def __str__(self):
        return self.task_no


class SupplierShipment(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        RECEIVED = "received", "Received"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="supplier_shipments")
    supplier_id = models.BigIntegerField()
    shipment_no = models.CharField(max_length=80)
    sku_code = models.CharField(max_length=80)
    ship_quantity = models.PositiveIntegerField(default=0)
    carton_count = models.PositiveIntegerField(default=0)
    weight = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    volume = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    shipping_mark = models.CharField(max_length=120, blank=True)
    tracking_no = models.CharField(max_length=120, blank=True)
    attachment_placeholder = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.SUBMITTED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "shipment_no"], name="uniq_supplier_shipment_no_per_tenant"),
        ]

    def __str__(self):
        return self.shipment_no
