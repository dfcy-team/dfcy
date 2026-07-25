from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.tenants.models import Tenant


class ProtectedReleaseQuerySet(models.QuerySet):
    def update(self, **kwargs):
        protected = getattr(self.model, "PROTECTED_FIELDS", {"status"})
        protected_roots = {field.removesuffix("_id") for field in protected}
        if any(key.removesuffix("_id") in protected_roots for key in kwargs):
            raise ValidationError("Release contract fields must be changed through the release service.")
        return super().update(**kwargs)

    def delete(self):
        raise ValidationError("Release workflow records cannot be deleted.")

    def bulk_update(self, objs, fields, batch_size=None):
        protected = getattr(self.model, "PROTECTED_FIELDS", {"status"})
        protected_roots = {field.removesuffix("_id") for field in protected}
        if any(field.removesuffix("_id") in protected_roots for field in fields):
            raise ValidationError("Release contract fields must be changed through the release service.")
        return super().bulk_update(objs, fields, batch_size=batch_size)

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Release workflow records must be created through the release service.")


class ReleaseContract(models.Model):
    objects = ProtectedReleaseQuerySet.as_manager()

    class Environment(models.TextChoices):
        DEVELOPMENT = "development", "Development"
        TEST = "test", "Test"
        PREVIEW = "preview", "Preview"
        PRODUCTION = "production", "Production"

    class RiskLevel(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        REVIEW_PENDING = "review_pending", "Review pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        BUILT = "built", "Built"
        UPLOADED = "uploaded", "Uploaded"
        PLATFORM_REVIEW = "platform_review", "Platform review"
        REVIEW_FAILED = "review_failed", "Review failed"
        SCHEDULED = "scheduled", "Scheduled"
        RELEASING = "releasing", "Releasing"
        RELEASED = "released", "Released"
        RELEASE_FAILED = "release_failed", "Release failed"
        OBSERVING = "observing", "Observing"
        COMPLETED = "completed", "Completed"
        ROLLBACK_REQUIRED = "rollback_required", "Rollback required"
        ROLLED_BACK = "rolled_back", "Rolled back"
        CANCELLED = "cancelled", "Cancelled"

    PROTECTED_FIELDS = {
        "tenant_id",
        "contract_no",
        "application_code",
        "environment",
        "commit_sha",
        "api_contract_version",
        "scope",
        "risk_level",
        "rollback_version",
        "rollback_point",
        "stop_conditions",
        "observation_minutes",
        "status",
        "scheduled_at",
        "completed_at",
        "created_by_id",
        "version",
        "idempotency_key_hash",
    }

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="release_contracts")
    contract_no = models.CharField(max_length=40)
    application_code = models.SlugField(max_length=80)
    environment = models.CharField(max_length=20, choices=Environment.choices)
    commit_sha = models.CharField(max_length=64)
    api_contract_version = models.CharField(max_length=40)
    scope = models.JSONField(default=list)
    risk_level = models.CharField(max_length=20, choices=RiskLevel.choices)
    rollback_version = models.CharField(max_length=120)
    rollback_point = models.CharField(max_length=200)
    stop_conditions = models.JSONField(default=list)
    observation_minutes = models.PositiveIntegerField(default=30)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="release_contracts_created",
    )
    version = models.PositiveIntegerField(default=1)
    idempotency_key_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "contract_no"], name="uniq_release_contract_no"),
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key_hash"],
                name="uniq_release_contract_create_key",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status", "updated_at"], name="idx_release_contract_state"),
        ]

    def save(self, *args, **kwargs):
        if self._state.adding and not getattr(self, "_release_service_write", False):
            raise ValidationError("Release contracts must be created through the release service.")
        if self.pk and not getattr(self, "_release_service_write", False):
            previous = type(self).objects.filter(pk=self.pk).values(*self.PROTECTED_FIELDS).first()
            if previous and any(previous[field] != getattr(self, field) for field in self.PROTECTED_FIELDS):
                raise ValidationError("Release contract fields must be changed through the release service.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Release workflow records cannot be deleted.")


class ReleaseArtifact(models.Model):
    contract = models.OneToOneField(ReleaseContract, on_delete=models.PROTECT, related_name="artifact")
    build_no = models.CharField(max_length=80)
    commit_sha = models.CharField(max_length=64)
    artifact_hash = models.CharField(max_length=64)
    config_version = models.CharField(max_length=80)
    manifest = models.JSONField(default=dict, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="release_artifacts_recorded",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Release artifacts are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Release artifacts are immutable.")


class ReleaseGateResult(models.Model):
    class Status(models.TextChoices):
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"

    contract = models.ForeignKey(ReleaseContract, on_delete=models.PROTECT, related_name="gate_results")
    code = models.SlugField(max_length=80)
    category = models.CharField(max_length=40)
    status = models.CharField(max_length=20, choices=Status.choices)
    evidence_ref = models.CharField(max_length=240)
    evaluated_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="release_gates_recorded",
    )
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["contract", "code"], name="uniq_release_gate_code"),
        ]

    def delete(self, *args, **kwargs):
        raise ValidationError("Release gate results cannot be deleted.")


class ReleaseApproval(models.Model):
    class ApprovalType(models.TextChoices):
        BUSINESS = "business", "Business"
        TECHNICAL = "technical", "Technical"
        SECURITY = "security", "Security"
        ROLLBACK = "rollback", "Rollback"

    class Decision(models.TextChoices):
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    contract = models.ForeignKey(ReleaseContract, on_delete=models.PROTECT, related_name="approvals")
    approval_type = models.CharField(max_length=20, choices=ApprovalType.choices)
    decision = models.CharField(max_length=20, choices=Decision.choices)
    reason = models.CharField(max_length=500)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="release_approvals_decided",
    )
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["approval_type", "decided_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "approval_type"],
                name="uniq_release_approval_type",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Release approvals are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Release approvals are immutable.")


class ReleaseAuditEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Release audit events are immutable.")

    def delete(self):
        raise ValidationError("Release audit events are immutable.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Release audit events are immutable.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Release audit events require the release service.")


class ReleaseAuditEvent(models.Model):
    objects = ReleaseAuditEventQuerySet.as_manager()

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="release_audit_events")
    contract = models.ForeignKey(
        ReleaseContract,
        on_delete=models.PROTECT,
        related_name="audit_events",
        null=True,
        blank=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="release_audit_events",
    )
    action = models.CharField(max_length=50)
    from_status = models.CharField(max_length=30, blank=True)
    to_status = models.CharField(max_length=30, blank=True)
    outcome = models.CharField(max_length=20, default="success")
    reason = models.CharField(max_length=500)
    evidence_refs = models.JSONField(default=list, blank=True)
    idempotency_key_hash = models.CharField(max_length=64)
    request_id = models.CharField(max_length=80)
    contract_version = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        base_manager_name = "objects"
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key_hash"],
                name="uniq_release_audit_key",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "contract", "created_at"], name="idx_release_audit_contract"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding or self.pk:
            raise ValidationError("Release audit events are immutable.")
        kwargs["force_insert"] = True
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Release audit events are immutable.")
