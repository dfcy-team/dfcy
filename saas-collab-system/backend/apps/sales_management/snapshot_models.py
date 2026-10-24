from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class SalesNineSnapshot(models.Model):
    INTEGRITY_UNVERIFIED = "unverified"

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.PROTECT, related_name="sales_nine_snapshots"
    )
    store = models.ForeignKey(
        "masterdata.StoreMaster", on_delete=models.PROTECT, related_name="sales_nine_snapshots"
    )
    business_date = models.DateField()
    timezone_name = models.CharField(max_length=64)
    target_at = models.DateTimeField()
    captured_at = models.DateTimeField(default=timezone.now)
    groups = models.JSONField(default=list, blank=True)
    integrity_status = models.CharField(max_length=20, default=INTEGRITY_UNVERIFIED, editable=False)
    integrity_reason = models.CharField(
        max_length=255,
        default="Source completeness watermark is unavailable; captured values are observed, not certified complete.",
        editable=False,
    )

    class Meta:
        db_table = "sales_nine_snapshot"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "store", "business_date"], name="uniq_sales_nine_snapshot_day"
            )
        ]
        indexes = [models.Index(fields=["tenant", "business_date"], name="idx_sales_nine_tenant_day")]

    def clean(self):
        super().clean()
        if self.tenant_id and self.store_id and self.store.tenant_id != self.tenant_id:
            raise ValidationError({"store": "Snapshot tenant must match store tenant."})
        if self.integrity_status != self.INTEGRITY_UNVERIFIED:
            raise ValidationError({"integrity_status": "Sales nine snapshots are always unverified."})

    def save(self, *args, **kwargs):
        if self.pk and not kwargs.get("force_insert", False):
            raise ValidationError("Sales nine snapshots are immutable once created.")
        self.integrity_status = self.INTEGRITY_UNVERIFIED
        # Database uniqueness remains authoritative and race-safe for get_or_create.
        self.full_clean(validate_unique=False, validate_constraints=False)
        return super().save(*args, **kwargs)
