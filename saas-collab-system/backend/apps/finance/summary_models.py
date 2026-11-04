"""Accepted financial input batches and shared, revisioned accounting settings."""
from django.conf import settings
from django.db import models


class FinanceSummaryDataset(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    label = models.CharField(max_length=160)
    source_hash = models.CharField(max_length=64)
    document_file = models.CharField(max_length=100)
    metadata = models.JSONField(default=dict)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'source_hash'], name='uniq_summary_tenant_source')]
        indexes = [models.Index(fields=['tenant', 'active'], name='idx_summary_tenant_active')]


class FinanceSummaryState(models.Model):
    dataset = models.OneToOneField(FinanceSummaryDataset, on_delete=models.PROTECT, related_name='accounting_state')
    values = models.JSONField(default=dict)
    revision = models.PositiveIntegerField(default=0)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    updated_at = models.DateTimeField(auto_now=True)


class FinanceSummaryInput(models.Model):
    """Reviewed source rows absent from provider business tables (rates/reports)."""
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    store = models.ForeignKey('masterdata.StoreMaster', null=True, on_delete=models.PROTECT)
    kind = models.CharField(max_length=24, choices=[('exchange_rate', '汇率'), ('adjustment', '调整报表')])
    source_key = models.CharField(max_length=191)
    period = models.CharField(max_length=10)
    payload = models.JSONField()
    source_hash = models.CharField(max_length=64)
    source_description = models.CharField(max_length=500)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'kind', 'source_key'], name='uniq_summary_input_source')]
        indexes = [models.Index(fields=['tenant', 'kind', 'period'], name='idx_summary_input_period')]


class FinanceSummaryCalculation(models.Model):
    """Durable work requests and hash-verified, version-specific derived results."""
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    dataset = models.ForeignKey(FinanceSummaryDataset, on_delete=models.PROTECT, related_name='calculations')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    cache_key = models.CharField(max_length=64, unique=True)
    kind = models.CharField(max_length=10, choices=[('query', 'Query'), ('rebuild', 'Rebuild')])
    revision = models.PositiveIntegerField()
    request = models.JSONField(default=dict)
    status = models.CharField(max_length=16, default='queued')
    result = models.BinaryField(null=True)
    result_hash = models.CharField(max_length=64, blank=True)
    result_dataset = models.ForeignKey(FinanceSummaryDataset, null=True, on_delete=models.PROTECT, related_name='+')
    lease = models.UUIDField(null=True)
    running_until = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        indexes = [models.Index(fields=['status', 'running_until'], name='idx_summary_calc_dispatch')]
