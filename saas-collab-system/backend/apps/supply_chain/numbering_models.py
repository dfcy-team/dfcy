"""Tenant scoped business document numbering rules and counters."""
from django.db import models

from .models import Record


class DocumentNumberRule(Record):
    KIND_CHOICES = [
        ("operating_order", "运营订货单"),
        ("purchase_order", "采购单"),
        ("supplier_shipment", "供应商发货单"),
        ("dispatch_batch", "集运批次"),
        ("inbound_order", "入库单"),
        ("corporate_contract", "对公采购合同"),
        ("personal_contract", "对私采购合同"),
    ]
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    enabled = models.BooleanField(default=False)
    include_country = models.BooleanField(default=False)
    country_prefixes = models.JSONField(default=dict, blank=True)
    prefix = models.CharField(max_length=12)
    date_format = models.CharField(max_length=8, choices=[("YYYYMMDD", "YYYYMMDD"), ("YYMMDD", "YYMMDD"), ("YYYYMM", "YYYYMM"), ("YYYY", "YYYY"), ("none", "none")])
    separator = models.CharField(max_length=4, choices=[("-", "-"), ("_", "_"), ("none", "none")])
    sequence_width = models.PositiveSmallIntegerField(default=4)
    reset_period = models.CharField(max_length=8, choices=[("day", "day"), ("month", "month"), ("year", "year"), ("never", "never")])

    def clean(self):
        super().clean()
        from .numbering import validate_rule
        validate_rule({field: getattr(self, field) for field in ("enabled", "include_country", "country_prefixes", "prefix", "date_format", "separator", "sequence_width", "reset_period")} | {"tenant_id": self.tenant_id})

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "kind"], name="sc2_number_rule_tenant_kind")]


class DocumentNumberCounter(Record):
    kind = models.CharField(max_length=32, choices=DocumentNumberRule.KIND_CHOICES)
    country_code = models.CharField(max_length=8, blank=True, default="")
    period_key = models.CharField(max_length=32)
    value = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "kind", "country_code", "period_key"], name="sc2_number_counter_period")]
        constraints += [models.CheckConstraint(condition=models.Q(value__gte=0), name="sc2_number_counter_nonnegative")]
