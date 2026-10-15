"""Carrier channels and immutable published tariffs; neither is a shipment."""
from django.core.exceptions import ValidationError
from django.db import models
from .models import Record


class FreightChannel(Record):
    company = models.ForeignKey('supply_chain.FreightCompany', on_delete=models.PROTECT, related_name='transport_channels')
    country = models.ForeignKey('masterdata.CountrySiteMaster', on_delete=models.PROTECT)
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    origin = models.CharField(max_length=160)
    cargo_type = models.CharField(max_length=80)
    transport_mode = models.CharField(max_length=12, choices=[('sea', '海运'), ('air', '空运'), ('road', '陆运'), ('rail', '铁路'), ('other', '其他')])
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'company', 'code'], name='sc2_channel_company_code')]


class FreightQuote(Record):
    channel = models.ForeignKey(FreightChannel, on_delete=models.PROTECT, related_name='quotes')
    sequence = models.PositiveIntegerField()
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    billing_basis = models.CharField(max_length=12, choices=[('cbm', '按方'), ('container', '按柜')])
    fee_per_cbm = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    container_fee = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    container_type = models.CharField(max_length=40, blank=True)
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    prices_include_tax = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    reason = models.CharField(max_length=500)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['channel', 'sequence'], name='sc2_channel_quote_sequence'),
                       models.CheckConstraint(condition=models.Q(tax_percent__gte=0, tax_percent__lte=100), name='sc2_quote_tax_range'),
                       models.CheckConstraint(condition=models.Q(fee_per_cbm__isnull=True) | models.Q(fee_per_cbm__gte=0), name='sc2_quote_cbm_nonnegative'),
                       models.CheckConstraint(condition=models.Q(container_fee__isnull=True) | models.Q(container_fee__gte=0), name='sc2_quote_container_nonnegative')]

    def clean(self):
        super().clean()
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError({'effective_to': '报价截止日期不能早于生效日期。'})
        if self.billing_basis == 'cbm' and self.fee_per_cbm is None:
            raise ValidationError({'fee_per_cbm': '按方计费需要填写每方价格，未知价格不能填成零。'})
        if self.billing_basis == 'container' and (self.container_fee is None or not self.container_type.strip()):
            raise ValidationError('按柜计费需要填写柜型和整柜价格。')

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('已发布报价不能覆盖，请发布新版本。')
        return super().save(*args, **kwargs)
