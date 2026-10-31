"""Tenant scoped configurable payment item profiles."""
from django.db import models
from .models import Record


class PaymentItem(Record):
    PARTY_CHOICES = [("supplier", "供应商"), ("carrier", "承运商"), ("both", "供应商和承运商")]
    NATURE_CHOICES = [("corporate", "公司"), ("personal", "个人")]
    ALLOCATION_CHOICES = [("volume", "体积"), ("weight", "重量"), ("mixed", "混合")]
    name = models.CharField(max_length=100)
    party_type = models.CharField(max_length=16, choices=PARTY_CHOICES, default="both")
    default_nature = models.CharField(max_length=16, choices=NATURE_CHOICES, default="corporate")
    default_tax_rate = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True, default=None)
    counts_as_cost = models.BooleanField(default=True)
    default_allocation = models.CharField(max_length=16, choices=ALLOCATION_CHOICES, default="volume")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [models.CheckConstraint(condition=models.Q(default_tax_rate__isnull=True) | models.Q(default_tax_rate__gte=0, default_tax_rate__lte=100), name='sc2_item_tax_rate_range'), models.UniqueConstraint(fields=["tenant", "name"], name="sc2_payment_item_tenant_name")]
