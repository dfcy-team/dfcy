"""Local return tracking, separate from platform refunds and warehouse stock."""
from django.conf import settings
from django.db import models


class AftersalesCase(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    store = models.ForeignKey('masterdata.StoreMaster', on_delete=models.PROTECT)
    source_key = models.CharField(max_length=80)
    order = models.ForeignKey('commerce.SalesOrder', null=True, on_delete=models.PROTECT)
    refund = models.OneToOneField('commerce.RefundReturn', null=True, on_delete=models.PROTECT)
    requires_return = models.BooleanField(null=True)
    expected_skus = models.JSONField(default=dict)
    expectation_reviewed = models.BooleanField(default=False)
    tracking_no = models.CharField(max_length=191, blank=True)
    warehouse = models.ForeignKey('masterdata.WarehouseMaster', null=True, on_delete=models.PROTECT)
    pending_since = models.DateTimeField(null=True)
    due_at = models.DateTimeField(null=True)
    timed_out_at = models.DateTimeField(null=True)
    last_checked_at = models.DateTimeField(null=True)
    return_status = models.CharField(max_length=24, default='unknown')
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'source_key'], name='uniq_aftersales_source')]
        indexes = [models.Index(fields=['tenant', 'store', 'return_status'], name='idx_aftersales_store_state'),
                   models.Index(fields=['return_status', 'due_at'], name='idx_aftersales_due')]


class WarehouseReturnReceipt(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    warehouse = models.ForeignKey('masterdata.WarehouseMaster', on_delete=models.PROTECT)
    return_no = models.CharField(max_length=191)
    platform_order_no = models.CharField(max_length=191, blank=True)
    erp_no = models.CharField(max_length=191, blank=True)
    tracking_no = models.CharField(max_length=191, blank=True)
    provider_status = models.CharField(max_length=40, blank=True)
    received_at = models.DateTimeField(null=True)
    source = models.CharField(max_length=16, default='api')
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'warehouse', 'return_no'], name='uniq_wh_return_receipt')]
        indexes = [models.Index(fields=['tenant', 'platform_order_no'], name='idx_wh_return_order')]


class WarehouseReturnLine(models.Model):
    receipt = models.ForeignKey(WarehouseReturnReceipt, on_delete=models.PROTECT, related_name='lines')
    sku = models.CharField(max_length=191)
    received_quantity = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['receipt', 'sku'], name='uniq_wh_return_sku')]


class ReturnAllocation(models.Model):
    line = models.ForeignKey(WarehouseReturnLine, on_delete=models.PROTECT, related_name='allocations')
    case = models.ForeignKey(AftersalesCase, on_delete=models.PROTECT, related_name='allocations')
    case_sku = models.CharField(max_length=191)
    quantity = models.PositiveIntegerField()
    manual = models.BooleanField(default=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['line', 'case', 'case_sku'], name='uniq_return_allocation'),
                       models.CheckConstraint(condition=models.Q(quantity__gt=0), name='return_allocation_positive')]


class AftersalesSyncSettings(models.Model):
    tenant = models.OneToOneField('tenants.Tenant', on_delete=models.PROTECT)
    # No default binding or automatic activation, including existing authorized warehouses.
    authorization = models.ForeignKey('integrations.WarehouseAuthorization', null=True, on_delete=models.PROTECT)
    interval_minutes = models.PositiveIntegerField(default=60)
    is_enabled = models.BooleanField(default=False)
    next_run_at = models.DateTimeField(null=True)
    last_run_at = models.DateTimeField(null=True)
    last_error_code = models.CharField(max_length=80, blank=True)
    running_until = models.DateTimeField(null=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(interval_minutes__gte=5, interval_minutes__lte=10080),
                                             name='aftersales_interval_bounds')]
