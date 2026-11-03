"""Read-only query snapshots are separate from posted business records."""
from django.conf import settings
from django.db import models


class SnapshotQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValueError("Lazada query snapshots are append-only.")

    def delete(self):
        raise ValueError("Lazada query snapshots are append-only.")


class LazadaApiSnapshot(models.Model):
    objects = SnapshotQuerySet.as_manager()
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    authorization = models.ForeignKey("integrations.MarketplaceStoreAuthorization", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    operation = models.CharField(max_length=60)
    parameters = models.JSONField(default=dict)
    response = models.JSONField(default=dict)
    response_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=20)
    error_code = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["tenant", "authorization", "created_at"], name="idx_laz_api_snapshot")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Lazada query snapshots are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Lazada query snapshots are append-only.")


class LazadaAdvertisingDailySpend(models.Model):
    """Sponsored Max report spend, not a financial debit or a revenue fact."""
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    store = models.ForeignKey("masterdata.StoreMaster", on_delete=models.PROTECT)
    report_date = models.DateField()
    currency = models.CharField(max_length=8)
    report_timezone = models.CharField(max_length=64)
    spend = models.DecimalField(max_digits=20, decimal_places=4)
    dimensions = models.JSONField(default=dict)
    source_snapshot = models.ForeignKey(LazadaApiSnapshot, on_delete=models.PROTECT, related_name="daily_spend_rows")
    overview_snapshot = models.ForeignKey(LazadaApiSnapshot, on_delete=models.PROTECT, related_name="overview_spend_rows")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "store", "report_date"], name="uniq_lazada_ads_store_day"),
            models.CheckConstraint(condition=models.Q(spend__gte=0), name="lazada_ads_spend_nonnegative"),
        ]
        indexes = [models.Index(fields=["tenant", "report_date", "store"], name="idx_lazada_ads_date")]
