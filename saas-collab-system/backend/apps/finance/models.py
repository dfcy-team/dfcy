from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.tenants.models import Tenant


class PlatformStatement(models.Model):
    class SourceType(models.TextChoices):
        DEMO = "demo", "Demo"
        MANUAL_IMPORT = "manual_import", "Manual import"
        FIXTURE = "fixture", "Fixture"

    class Status(models.TextChoices):
        IMPORTED = "imported", "Imported"
        MATCHING = "matching", "Matching"
        MATCHED = "matched", "Matched"
        EXCEPTION = "exception", "Exception"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="platform_statements")
    platform = models.CharField(max_length=40)
    statement_no = models.CharField(max_length=80)
    period_start = models.DateField()
    period_end = models.DateField()
    currency = models.CharField(max_length=10, default="USD")
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2)
    fee_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=12, decimal_places=2)
    source_type = models.CharField(max_length=30, choices=SourceType.choices, default=SourceType.DEMO)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.IMPORTED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["tenant_id", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "statement_no"], name="uniq_statement_no_per_tenant"),
        ]


class WithdrawalRecord(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="withdrawal_records")
    platform = models.CharField(max_length=40)
    withdrawal_no = models.CharField(max_length=80)
    currency = models.CharField(max_length=10, default="USD")
    requested_amount = models.DecimalField(max_digits=12, decimal_places=2)
    expected_amount = models.DecimalField(max_digits=12, decimal_places=2)
    requested_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.REQUESTED)

    class Meta:
        ordering = ["tenant_id", "-requested_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "withdrawal_no"], name="uniq_withdrawal_no_per_tenant"),
        ]


class BankReceiptImport(models.Model):
    class Status(models.TextChoices):
        IMPORTED = "imported", "Imported"
        MATCHED = "matched", "Matched"
        EXCEPTION = "exception", "Exception"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="bank_receipt_imports")
    import_batch_no = models.CharField(max_length=80)
    masked_account = models.CharField(max_length=80)
    currency = models.CharField(max_length=10, default="USD")
    receipt_amount = models.DecimalField(max_digits=12, decimal_places=2)
    receipt_date = models.DateField()
    reference_no = models.CharField(max_length=120)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.IMPORTED)

    class Meta:
        ordering = ["tenant_id", "-receipt_date", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "reference_no"], name="uniq_receipt_reference_per_tenant"),
        ]


class ReconciliationMatchQuerySet(models.QuerySet):
    REVIEW_FIELDS = {"status", "reviewed_by", "reviewed_by_id", "reviewed_at"}

    def update(self, **kwargs):
        if self.REVIEW_FIELDS & set(kwargs):
            raise ValidationError("Reconciliation state changes require the audited service.")
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if self.REVIEW_FIELDS & set(fields):
            raise ValidationError("Reconciliation state changes require the audited service.")
        return super().bulk_update(objs, fields, batch_size=batch_size)

    def bulk_create(self, objs, **kwargs):
        if any(
            obj.status != ReconciliationMatch.Status.SUGGESTED
            or obj.reviewed_by_id
            or obj.reviewed_at
            for obj in objs
        ):
            raise ValidationError("Reconciliation state changes require the audited service.")
        return super().bulk_create(objs, **kwargs)


class ReconciliationMatch(models.Model):
    class MatchType(models.TextChoices):
        AUTO_SUGGESTED = "auto_suggested", "Auto suggested"
        MANUAL = "manual", "Manual"

    class Status(models.TextChoices):
        SUGGESTED = "suggested", "Suggested"
        CONFIRMED = "confirmed", "Confirmed"
        REJECTED = "rejected", "Rejected"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="reconciliation_matches")
    statement = models.ForeignKey(PlatformStatement, on_delete=models.PROTECT, related_name="reconciliation_matches")
    withdrawal = models.ForeignKey(WithdrawalRecord, on_delete=models.PROTECT, related_name="reconciliation_matches")
    bank_receipt = models.ForeignKey(BankReceiptImport, on_delete=models.PROTECT, related_name="reconciliation_matches")
    match_type = models.CharField(max_length=30, choices=MatchType.choices, default=MatchType.AUTO_SUGGESTED)
    matched_amount = models.DecimalField(max_digits=12, decimal_places=2)
    difference_amount = models.DecimalField(max_digits=12, decimal_places=2)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.SUGGESTED)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_reconciliation_matches",
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=64, blank=True)
    objects = ReconciliationMatchQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="uniq_finance_match_idempotency",
            ),
        ]

    def clean(self):
        if self._state.adding and (
            self.status != self.Status.SUGGESTED or self.reviewed_by_id or self.reviewed_at
        ):
            raise ValidationError("New reconciliation matches must start as unreviewed suggestions.")
        related = (self.statement, self.withdrawal, self.bank_receipt)
        if any(item.tenant_id != self.tenant_id for item in related):
            raise ValidationError("Reconciliation sources must belong to the same tenant.")
        if self.reviewed_by_id and (
            self.reviewed_by.tenant_id != self.tenant_id or self.reviewed_by.user_type != "internal"
        ):
            raise ValidationError("Reviewer must be an internal user in the same tenant.")

    def save(self, *args, **kwargs):
        if self.pk and not getattr(self, "_review_service_write", False):
            current = type(self).objects.filter(pk=self.pk).values(
                "status", "reviewed_by_id", "reviewed_at"
            ).first()
            if current and any(
                current[field] != getattr(self, field)
                for field in ("status", "reviewed_by_id", "reviewed_at")
            ):
                raise ValidationError("Reconciliation state changes require the audited service.")
        self.full_clean()
        try:
            super().save(*args, **kwargs)
        finally:
            self._review_service_write = False


class ReconciliationExceptionQuerySet(models.QuerySet):
    RESOLUTION_FIELDS = {"status", "assigned_to", "assigned_to_id", "resolution_note", "resolved_at"}

    def update(self, **kwargs):
        if self.RESOLUTION_FIELDS & set(kwargs):
            raise ValidationError("Reconciliation exception changes require the audited service.")
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if self.RESOLUTION_FIELDS & set(fields):
            raise ValidationError("Reconciliation exception changes require the audited service.")
        return super().bulk_update(objs, fields, batch_size=batch_size)

    def bulk_create(self, objs, **kwargs):
        if any(
            obj.status != ReconciliationException.Status.OPEN
            or obj.assigned_to_id
            or obj.resolution_note
            or obj.resolved_at
            for obj in objs
        ):
            raise ValidationError("Reconciliation exception changes require the audited service.")
        return super().bulk_create(objs, **kwargs)


class ReconciliationException(models.Model):
    class ExceptionType(models.TextChoices):
        AMOUNT_DIFFERENCE = "amount_difference", "Amount difference"
        CURRENCY_MISMATCH = "currency_mismatch", "Currency mismatch"
        MISSING_RECEIPT = "missing_receipt", "Missing receipt"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="reconciliation_exceptions")
    reconciliation_match = models.ForeignKey(
        ReconciliationMatch,
        on_delete=models.CASCADE,
        related_name="exceptions",
    )
    exception_type = models.CharField(max_length=40, choices=ExceptionType.choices)
    difference_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_reconciliation_exceptions",
        null=True,
        blank=True,
    )
    resolution_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    objects = ReconciliationExceptionQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "-created_at"]

    def clean(self):
        if self._state.adding and (
            self.status != self.Status.OPEN
            or self.assigned_to_id
            or self.resolution_note
            or self.resolved_at
        ):
            raise ValidationError("New reconciliation exceptions must start open and unassigned.")
        if self.reconciliation_match.tenant_id != self.tenant_id:
            raise ValidationError("Reconciliation exception and match must belong to the same tenant.")
        if self.assigned_to_id and (
            self.assigned_to.tenant_id != self.tenant_id or self.assigned_to.user_type != "internal"
        ):
            raise ValidationError("Exception assignee must be an internal user in the same tenant.")

    def save(self, *args, **kwargs):
        if self.pk and not getattr(self, "_resolution_service_write", False):
            current = type(self).objects.filter(pk=self.pk).values(
                "status", "assigned_to_id", "resolution_note", "resolved_at"
            ).first()
            if current and any(
                current[field] != getattr(self, field)
                for field in ("status", "assigned_to_id", "resolution_note", "resolved_at")
            ):
                raise ValidationError("Reconciliation exception changes require the audited service.")
        self.full_clean()
        try:
            super().save(*args, **kwargs)
        finally:
            self._resolution_service_write = False


class FinanceAuditLogQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Finance audit logs are immutable.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Finance audit logs are immutable.")

    def delete(self):
        raise ValidationError("Finance audit logs are immutable.")


class FinanceAuditLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="finance_audit_logs")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="finance_audit_logs")
    action = models.CharField(max_length=80)
    object_type = models.CharField(max_length=80)
    object_id = models.CharField(max_length=80)
    masked_detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = FinanceAuditLogQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "-created_at"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Finance audit logs are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Finance audit logs are immutable.")
