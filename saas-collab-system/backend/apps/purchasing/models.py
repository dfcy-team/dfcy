from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CONFIRMED = "confirmed", "Confirmed"
        IN_PRODUCTION = "in_production", "In production"
        SHIPPED = "shipped", "Shipped"
        CANCELLED = "cancelled", "Cancelled"

    class ApprovalStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="purchase_orders")
    po_no = models.CharField(max_length=80)
    sku_code = models.CharField(max_length=80)
    supplier_id = models.BigIntegerField()
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    delivery_date = models.DateField(null=True, blank=True)
    payment_terms = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT)
    approval_status = models.CharField(
        max_length=30,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_purchase_orders",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "po_no"], name="uniq_po_no_per_tenant"),
        ]

    def __str__(self):
        return self.po_no
