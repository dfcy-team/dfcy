"""API-only projections; deliberately separate from imported reconciliation facts."""
from django.conf import settings
from django.db import models


class PlatformApiWithdrawal(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    store = models.ForeignKey('masterdata.StoreMaster', on_delete=models.PROTECT)
    authorization = models.ForeignKey('integrations.MarketplaceStoreAuthorization', on_delete=models.PROTECT)
    source_endpoint = models.CharField(max_length=160)
    external_id = models.CharField(max_length=191)
    transaction_type = models.CharField(max_length=80)
    raw_status = models.CharField(max_length=80, null=True, blank=True)
    currency = models.CharField(max_length=3)
    signed_amount = models.DecimalField(max_digits=28, decimal_places=8)
    original_amount = models.CharField(max_length=80)
    occurred_at_utc = models.DateTimeField()
    observed_at_utc = models.DateTimeField()
    # Allowlisted API fields and explicitly labelled time interpretation.
    # No inferred net, fees, bank receipts, accounts or provider response bodies.
    api_fields = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'store', 'source_endpoint', 'external_id'], name='uniq_api_withdrawal_source')]
        indexes = [models.Index(fields=['tenant', 'store', 'occurred_at_utc'], name='idx_api_withdraw_store_time')]


class PlatformWalletSync(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    actor = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    enabled = models.BooleanField(default=False)
    interval_minutes = models.PositiveIntegerField(default=60)
    activated_at = models.DateTimeField(null=True)
    next_run_at = models.DateTimeField(null=True)
    state = models.CharField(max_length=24, default='idle')
    lease = models.UUIDField(null=True)
    running_until = models.DateTimeField(null=True)
    last_run_at = models.DateTimeField(null=True)
    last_error_code = models.CharField(max_length=80, blank=True)
    summary = models.JSONField(default=dict)


class PlatformWalletCursor(models.Model):
    sync = models.ForeignKey(PlatformWalletSync, on_delete=models.PROTECT)
    store = models.ForeignKey('masterdata.StoreMaster', on_delete=models.PROTECT)
    watermark = models.DateTimeField(null=True)
    last_attempt_at = models.DateTimeField(null=True)
    last_success_at = models.DateTimeField(null=True)
    last_error_code = models.CharField(max_length=80, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['sync', 'store'], name='uniq_wallet_sync_store')]
