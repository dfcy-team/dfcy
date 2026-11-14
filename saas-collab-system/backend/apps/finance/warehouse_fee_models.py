import uuid

from django.conf import settings
from django.db import models


class WarehouseFee(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    kind = models.CharField(max_length=10, choices=[('order', '订单处理费'), ('other', '仓库其他处理费')])
    country = models.CharField(max_length=8)
    warehouse = models.ForeignKey('masterdata.WarehouseMaster', on_delete=models.PROTECT, null=True, blank=True)
    store = models.ForeignKey('masterdata.StoreMaster', on_delete=models.PROTECT, null=True, blank=True)
    order = models.ForeignKey('commerce.SalesOrder', on_delete=models.PROTECT, null=True, blank=True)
    external_order_id = models.CharField(max_length=191, blank=True)
    bill_number = models.CharField(max_length=191)
    bill_month = models.CharField(max_length=7)
    fee_item = models.CharField(max_length=80)
    reference = models.CharField(max_length=191)
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    currency = models.CharField(max_length=8)
    original_amount = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    original_currency = models.CharField(max_length=8, blank=True)
    exchange_rate = models.DecimalField(max_digits=24, decimal_places=10, null=True, blank=True)
    rate_date = models.DateField(null=True, blank=True)
    rate_source = models.CharField(max_length=191, blank=True)
    occurred_on = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=16, default='draft')
    match_status = models.CharField(max_length=20, default='unmatched')
    version = models.PositiveIntegerField(default=1)
    business_key = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64)
    source = models.JSONField(default=dict)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'business_key'], name='uniq_warehouse_fee_business')]
        indexes = [models.Index(fields=['tenant', 'kind', 'bill_month'], name='idx_wh_fee_month'),
                   models.Index(fields=['tenant', 'store', 'external_order_id'], name='idx_wh_fee_order')]


class WarehouseFeeImportBatch(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=10)
    file_hash = models.CharField(max_length=64)
    file_name = models.CharField(max_length=191)
    results = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'imported_by', 'kind', 'file_hash'], name='uniq_wh_fee_import_file')]


class WarehouseBillUpload(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    file_name = models.CharField(max_length=191)
    file_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=24, default='queued')
    version = models.PositiveIntegerField(default=1)
    overrides = models.JSONField(default=dict)
    summary = models.JSONField(default=dict)
    error = models.CharField(max_length=500, blank=True)
    processed = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'uploaded_by', 'file_hash'], name='uniq_wh_bill_upload')]


class WarehouseBillRow(models.Model):
    upload = models.ForeignKey(WarehouseBillUpload, on_delete=models.CASCADE, related_name='rows')
    number = models.PositiveIntegerField()
    data = models.JSONField(default=dict)
    source = models.JSONField(default=dict)
    error = models.TextField(blank=True)
    status = models.CharField(max_length=16, default='valid')
    fee = models.ForeignKey(WarehouseFee, on_delete=models.PROTECT, null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['upload', 'number'], name='uniq_wh_bill_row')]
        indexes = [models.Index(fields=['upload', 'status', 'number'], name='idx_wh_bill_row_status')]


class WarehouseBillFormatRule(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    warehouse = models.ForeignKey('masterdata.WarehouseMaster', on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    version = models.PositiveIntegerField(default=2)
    config = models.JSONField(default=dict)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'warehouse', 'name'], name='uniq_wh_bill_format_name')]
