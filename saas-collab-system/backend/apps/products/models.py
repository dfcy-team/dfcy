from django.conf import settings
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
