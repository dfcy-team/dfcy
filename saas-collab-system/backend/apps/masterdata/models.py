from django.db import models

from apps.tenants.models import Tenant


class StatusChoices(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


class PlatformMaster(models.Model):
    class PlatformType(models.TextChoices):
        BIGSELLER = "bigseller", "BigSeller"
        SHOPEE = "shopee", "Shopee"
        TIKTOK = "tiktok", "TikTok"
        OTHER = "other", "Other"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="platform_masters")
    code = models.SlugField(max_length=60)
    name = models.CharField(max_length=120)
    platform_type = models.CharField(max_length=30, choices=PlatformType.choices)
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "code"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_platform_master_code")]


class StoreMaster(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="store_masters")
    platform = models.ForeignKey(PlatformMaster, on_delete=models.PROTECT, related_name="stores")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=120)
    country_code = models.CharField(max_length=8)
    currency = models.CharField(max_length=8)
    timezone = models.CharField(max_length=60, default="UTC")
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "code"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_store_master_code")]


class WarehouseMaster(models.Model):
    class WarehouseType(models.TextChoices):
        OWNED = "owned", "Owned"
        THIRD_PARTY = "third_party", "Third party"
        PLATFORM = "platform", "Platform"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="warehouse_masters")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=120)
    country_code = models.CharField(max_length=8)
    warehouse_type = models.CharField(max_length=30, choices=WarehouseType.choices)
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "code"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_warehouse_master_code")]


class SupplierMaster(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="supplier_masters")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    contact_alias = models.CharField(max_length=80, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "code"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_supplier_master_code")]
