"""Country operating demand belongs to sales, distinct from platform customer orders."""
from django.db import models
from django.core.exceptions import ValidationError
from apps.supply_chain.models import Record


class OperatingOrder(Record):
    number = models.CharField(max_length=80)
    country = models.ForeignKey('masterdata.CountrySiteMaster', on_delete=models.PROTECT)
    country_code_snapshot = models.CharField(max_length=8)
    source_kind = models.CharField(max_length=16, choices=[('new_goods', '新货'), ('cycle', '周期订货'), ('season', '季节订货')])
    status = models.CharField(max_length=16, choices=[('draft', '草稿'), ('submitted', '已提交'), ('cancelled', '已取消')], default='draft')
    order_date = models.DateField()
    notes = models.TextField(blank=True)
    campaign = models.CharField(max_length=120, blank=True)
    demand_start = models.DateField(null=True, blank=True)
    demand_end = models.DateField(null=True, blank=True)
    plan_revision = models.CharField(max_length=40, blank=True)
    calculation_snapshot = models.JSONField(default=dict, blank=True)
    creation_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'number'], name='op_country_order_number'),
                       models.UniqueConstraint(fields=['tenant', 'creation_key'], name='op_country_create_key')]
        ordering = ['-id']


class OperatingOrderLine(Record):
    order = models.ForeignKey(OperatingOrder, on_delete=models.PROTECT, related_name='lines')
    sku = models.ForeignKey('products.ProductSKU', on_delete=models.PROTECT)
    sku_code_snapshot = models.CharField(max_length=80)
    product_name_snapshot = models.CharField(max_length=255, blank=True)
    quantity = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0), name='op_order_qty_positive')]
        ordering = ['id']


class OperatingSuggestion(Record):
    token = models.CharField(max_length=64, unique=True)
    country = models.ForeignKey('masterdata.CountrySiteMaster', on_delete=models.PROTECT)
    snapshot = models.JSONField()
    expires_at = models.DateTimeField()

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('已生成的计算依据必须保留，不能改写。')
        return super().save(*args, **kwargs)
