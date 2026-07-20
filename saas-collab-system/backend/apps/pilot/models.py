from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.tenants.models import Tenant


class PilotEnvironment(models.Model):
    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    status = models.CharField(max_length=20, default="controlled")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]


class PilotTargetAlias(models.Model):
    """Tenant-owned allow-list entry for controlled verification targets."""

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="pilot_target_aliases")
    environment = models.ForeignKey(PilotEnvironment, on_delete=models.PROTECT, related_name="target_aliases")
    alias = models.SlugField(max_length=64)
    status = models.CharField(max_length=20, default="controlled")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "environment_id", "alias"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "environment", "alias"], name="uniq_pilot_target_alias"),
        ]


class PilotEvidenceReference(models.Model):
    """Tenant-owned registry entry for masked, internal evidence references."""

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="pilot_evidence_references")
    environment = models.ForeignKey(PilotEnvironment, on_delete=models.PROTECT, related_name="evidence_references")
    reference = models.CharField(max_length=200)
    status = models.CharField(max_length=20, default="controlled")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "environment_id", "reference"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "environment", "reference"], name="uniq_pilot_evidence_ref"),
        ]


class ReadinessGate(models.Model):
    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        IN_PROGRESS = "in_progress", "In progress"
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        BLOCKED = "blocked", "Blocked"
        EXPIRED = "expired", "Expired"

    environment = models.ForeignKey(PilotEnvironment, on_delete=models.PROTECT, related_name="readiness_gates")
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=120)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_STARTED)
    evidence_ref = models.CharField(max_length=160, blank=True)
    message = models.CharField(max_length=300, blank=True)
    evaluated_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["environment_id", "code"]
        constraints = [models.UniqueConstraint(fields=["environment", "code"], name="uniq_pilot_readiness_gate")]


class TopologyService(models.Model):
    environment = models.ForeignKey(PilotEnvironment, on_delete=models.PROTECT, related_name="topology_services")
    service_name = models.CharField(max_length=40)
    host_role = models.CharField(max_length=30)
    network_zone = models.CharField(max_length=30)
    exposure = models.CharField(max_length=20)
    host_ref_masked = models.CharField(max_length=120)
    port_hint = models.CharField(max_length=40, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["environment_id", "host_role", "service_name"]
        constraints = [models.UniqueConstraint(fields=["environment", "service_name"], name="uniq_pilot_topology_service")]


class CapacityObservation(models.Model):
    class Status(models.TextChoices):
        NORMAL = "normal", "Normal"
        WARNING = "warning", "Warning"
        CRITICAL = "critical", "Critical"
        UNKNOWN = "unknown", "Unknown"
        STALE = "stale", "Stale"

    environment = models.ForeignKey(PilotEnvironment, on_delete=models.PROTECT, related_name="capacity_observations")
    service_name = models.CharField(max_length=40)
    metric_code = models.CharField(max_length=40)
    value = models.FloatField(null=True, blank=True)
    unit = models.CharField(max_length=20)
    warning_threshold = models.FloatField(null=True, blank=True)
    critical_threshold = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNKNOWN)
    source = models.CharField(max_length=80, default="fixed_demo")
    observed_at = models.DateTimeField()

    class Meta:
        ordering = ["-observed_at", "service_name", "metric_code", "id"]
        indexes = [models.Index(fields=["environment", "metric_code", "observed_at"], name="idx_pilot_capacity")]


class ProtectedStateQuerySet(models.QuerySet):
    def update(self, **kwargs):
        protected = getattr(self.model, "PROTECTED_WORKFLOW_FIELDS", {"status"})
        protected_roots = {field.removesuffix("_id") for field in protected}
        if any(key.removesuffix("_id") in protected_roots for key in kwargs):
            raise ValidationError("Workflow fields must be changed through the dedicated transition service.")
        return super().update(**kwargs)

    def delete(self):
        raise ValidationError("Pilot workflow records cannot be deleted.")

    def bulk_update(self, objs, fields, batch_size=None):
        protected = getattr(self.model, "PROTECTED_WORKFLOW_FIELDS", {"status"})
        protected_roots = {field.removesuffix("_id") for field in protected}
        if any(field.removesuffix("_id") in protected_roots for field in fields):
            raise ValidationError("Workflow fields must be changed through the dedicated transition service.")
        return super().bulk_update(objs, fields, batch_size=batch_size)

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Pilot workflow records must be created through the controlled service.")


class ProtectedStateModel(models.Model):
    objects = ProtectedStateQuerySet.as_manager()
    PROTECTED_WORKFLOW_FIELDS = {"status"}

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk and not getattr(self, "_pilot_state_service_write", False):
            protected = self.PROTECTED_WORKFLOW_FIELDS
            previous = type(self).objects.filter(pk=self.pk).values(*protected).first()
            if previous is not None and any(previous[field] != getattr(self, field) for field in protected):
                raise ValidationError("Workflow fields must be changed through the dedicated transition service.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Pilot workflow records cannot be deleted.")


class RecoveryPlan(ProtectedStateModel):
    PROTECTED_WORKFLOW_FIELDS = {
        "tenant_id", "environment_id", "name", "rpo_minutes", "rto_minutes", "backup_summary",
        "backup_checksum_masked", "approval_ref", "status", "scheduled_at", "created_by_id",
        "approved_by_id", "version", "idempotency_key_hash", "reason",
    }
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        REVIEW_PENDING = "review_pending", "Review pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        SCHEDULED = "scheduled", "Scheduled"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        MANUAL_REQUIRED = "manual_required", "Manual required"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="pilot_recovery_plans")
    environment = models.ForeignKey(PilotEnvironment, on_delete=models.PROTECT, related_name="recovery_plans")
    name = models.CharField(max_length=120)
    rpo_minutes = models.PositiveIntegerField()
    rto_minutes = models.PositiveIntegerField()
    backup_summary = models.CharField(max_length=500)
    backup_checksum_masked = models.CharField(max_length=128)
    approval_ref = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pilot_recovery_plans_created")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="pilot_recovery_plans_approved")
    version = models.PositiveIntegerField(default=1)
    idempotency_key_hash = models.CharField(max_length=64)
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["tenant", "idempotency_key_hash"], name="uniq_recovery_plan_idempotency")]


class RecoveryDrill(ProtectedStateModel):
    PROTECTED_WORKFLOW_FIELDS = {
        "tenant_id", "recovery_plan_id", "status", "started_at", "finished_at", "actual_rpo_minutes",
        "actual_rto_minutes", "result_summary", "evidence_refs", "version",
    }
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="pilot_recovery_drills")
    recovery_plan = models.ForeignKey(RecoveryPlan, on_delete=models.PROTECT, related_name="drills")
    status = models.CharField(max_length=30, choices=RecoveryPlan.Status.choices, default=RecoveryPlan.Status.RUNNING)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    actual_rpo_minutes = models.PositiveIntegerField(null=True, blank=True)
    actual_rto_minutes = models.PositiveIntegerField(null=True, blank=True)
    result_summary = models.CharField(max_length=1000, blank=True)
    evidence_refs = models.JSONField(default=list, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-started_at", "-id"]


class ReleasePlan(ProtectedStateModel):
    PROTECTED_WORKFLOW_FIELDS = {
        "tenant_id", "environment_id", "release_channel", "commit_sha", "tag", "demo_tenant_refs",
        "observation_minutes", "stop_conditions", "rollback_point", "database_compatibility",
        "approval_ref", "rollback_approval_ref", "rollback_approved_by_id", "rollback_approved_at",
        "rollback_approval_expires_at", "status", "manual_context", "scheduled_at", "created_by_id",
        "approved_by_id", "version", "idempotency_key_hash", "reason", "result_summary", "evidence_refs",
    }
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        REVIEW_PENDING = "review_pending", "Review pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        SCHEDULED = "scheduled", "Scheduled"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        ROLLBACK_REQUIRED = "rollback_required", "Rollback required"
        ROLLED_BACK = "rolled_back", "Rolled back"
        MANUAL_REQUIRED = "manual_required", "Manual required"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="pilot_release_plans")
    environment = models.ForeignKey(PilotEnvironment, on_delete=models.PROTECT, related_name="release_plans")
    release_channel = models.CharField(max_length=30)
    commit_sha = models.CharField(max_length=64)
    tag = models.CharField(max_length=120, blank=True)
    demo_tenant_refs = models.JSONField(default=list)
    observation_minutes = models.PositiveIntegerField()
    stop_conditions = models.JSONField(default=list)
    rollback_point = models.CharField(max_length=200)
    database_compatibility = models.CharField(max_length=20)
    approval_ref = models.CharField(max_length=160, blank=True)
    rollback_approval_ref = models.CharField(max_length=160, blank=True, null=True, unique=True)
    rollback_approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="pilot_rollbacks_approved")
    rollback_approved_at = models.DateTimeField(null=True, blank=True)
    rollback_approval_expires_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT)
    manual_context = models.CharField(max_length=20, blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pilot_release_plans_created")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="pilot_release_plans_approved")
    version = models.PositiveIntegerField(default=1)
    idempotency_key_hash = models.CharField(max_length=64)
    reason = models.CharField(max_length=500)
    result_summary = models.CharField(max_length=1000, blank=True)
    evidence_refs = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["tenant", "idempotency_key_hash"], name="uniq_release_plan_idempotency")]


class UIP8WorkflowModel(ProtectedStateModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="+")
    environment = models.ForeignKey(PilotEnvironment, on_delete=models.PROTECT, related_name="+")
    code = models.CharField(max_length=80)
    status = models.CharField(max_length=30, default="draft")
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    review_reason = models.CharField(max_length=1000, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    idempotency_key_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self._state.adding and not getattr(self, "_pilot_state_service_write", False):
            raise ValidationError("UI-P8 workflow records must be created through the controlled service.")
        super().save(*args, **kwargs)


class SecurityReview(UIP8WorkflowModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"

    class ReviewType(models.TextChoices):
        PLATFORM_ACCESS = "platform_access", "Platform access"
        CREDENTIAL_CUSTODY = "credential_custody", "Credential custody"
        NETWORK_BOUNDARY = "network_boundary", "Network boundary"
        DATA_PRIVACY = "data_privacy", "Data privacy"
        RUNNER_SECURITY = "runner_security", "Runner security"
        FINANCE_BOUNDARY = "finance_boundary", "Finance boundary"

    PROTECTED_WORKFLOW_FIELDS = {
        "tenant_id", "environment_id", "code", "review_type", "scope_summary", "risk_level",
        "finance_scope", "evidence_refs", "expires_at", "expired_at", "status", "creator_id",
        "owner_id", "reviewer_id", "review_reason", "reviewed_at", "version", "idempotency_key_hash",
    }
    review_type = models.CharField(max_length=30, choices=ReviewType.choices)
    scope_summary = models.CharField(max_length=1000)
    risk_level = models.CharField(max_length=10, choices=((value, value.title()) for value in ("low", "medium", "high", "critical")))
    finance_scope = models.JSONField(null=True, blank=True)
    evidence_refs = models.JSONField(default=list)
    expires_at = models.DateTimeField()
    expired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_p8_security_code"),
            models.UniqueConstraint(fields=["tenant", "idempotency_key_hash"], name="uniq_p8_security_idem"),
        ]


class VerificationRun(UIP8WorkflowModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        MANUAL_REQUIRED = "manual_required", "Manual required"
        CANCELLED = "cancelled", "Cancelled"

    PROTECTED_WORKFLOW_FIELDS = {
        "tenant_id", "environment_id", "code", "category", "target_alias", "data_class",
        "planned_start_at", "planned_end_at", "success_criteria", "evidence_refs", "status",
        "result_summary", "started_at", "finished_at", "error_code", "error_message", "creator_id",
        "owner_id", "reviewer_id", "recorder_id", "review_reason", "reviewed_at", "version",
        "idempotency_key_hash",
    }
    category = models.CharField(max_length=30)
    target_alias = models.SlugField(max_length=64)
    data_class = models.CharField(max_length=20)
    planned_start_at = models.DateTimeField()
    planned_end_at = models.DateTimeField()
    success_criteria = models.JSONField(default=list)
    evidence_refs = models.JSONField(default=list)
    result_summary = models.CharField(max_length=1000, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.CharField(max_length=1000, blank=True)
    recorder = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_p8_verification_code"),
            models.UniqueConstraint(fields=["tenant", "idempotency_key_hash"], name="uniq_p8_verification_idem"),
        ]


class PerformanceRun(UIP8WorkflowModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        MANUAL_REQUIRED = "manual_required", "Manual required"
        CANCELLED = "cancelled", "Cancelled"

    PROTECTED_WORKFLOW_FIELDS = {
        "tenant_id", "environment_id", "code", "scenario", "workload_profile", "max_rps",
        "concurrency", "duration_seconds", "thresholds", "evidence_refs", "status", "p50_ms",
        "p95_ms", "error_rate", "cpu_percent", "memory_percent", "result_summary", "creator_id",
        "owner_id", "reviewer_id", "recorder_id", "review_reason", "reviewed_at", "version",
        "idempotency_key_hash",
    }
    scenario = models.CharField(max_length=200)
    workload_profile = models.CharField(max_length=20)
    max_rps = models.PositiveIntegerField()
    concurrency = models.PositiveIntegerField()
    duration_seconds = models.PositiveIntegerField()
    thresholds = models.JSONField(default=dict)
    evidence_refs = models.JSONField(default=list)
    p50_ms = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    p95_ms = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    error_rate = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)
    cpu_percent = models.DecimalField(max_digits=7, decimal_places=3, null=True, blank=True)
    memory_percent = models.DecimalField(max_digits=7, decimal_places=3, null=True, blank=True)
    result_summary = models.CharField(max_length=1000, blank=True)
    recorder = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_p8_performance_code"),
            models.UniqueConstraint(fields=["tenant", "idempotency_key_hash"], name="uniq_p8_performance_idem"),
        ]


class EntryDecision(UIP8WorkflowModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"

    PROTECTED_WORKFLOW_FIELDS = {
        "tenant_id", "environment_id", "code", "decision", "scope_summary", "security_review_ids",
        "verification_run_ids", "performance_run_ids", "recovery_plan_ids", "release_plan_ids",
        "expires_at", "expired_at", "status", "evidence_snapshot", "evidence_hash", "blockers",
        "warnings", "contract_version", "creator_id", "owner_id", "reviewer_id", "review_reason",
        "reviewed_at", "version", "idempotency_key_hash",
    }
    decision = models.CharField(max_length=10, choices=(("go", "Go"), ("no_go", "No go")))
    scope_summary = models.CharField(max_length=1000)
    security_review_ids = models.JSONField(default=list)
    verification_run_ids = models.JSONField(default=list)
    performance_run_ids = models.JSONField(default=list)
    recovery_plan_ids = models.JSONField(default=list)
    release_plan_ids = models.JSONField(default=list)
    expires_at = models.DateTimeField()
    expired_at = models.DateTimeField(null=True, blank=True)
    evidence_snapshot = models.JSONField(null=True, blank=True)
    evidence_hash = models.CharField(max_length=64, blank=True)
    blockers = models.JSONField(default=list)
    warnings = models.JSONField(default=list)
    contract_version = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_p8_entry_code"),
            models.UniqueConstraint(fields=["tenant", "idempotency_key_hash"], name="uniq_p8_entry_idem"),
        ]


class PilotAuditEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Pilot audit events are immutable.")

    def delete(self):
        raise ValidationError("Pilot audit events are immutable.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Pilot audit events are immutable.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Pilot audit events require the transition service.")


class PilotAuditEvent(models.Model):
    class Outcome(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    objects = PilotAuditEventQuerySet.as_manager()

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="pilot_audit_events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="pilot_audit_events")
    actor_type = models.CharField(max_length=20, default="user")
    recovery_plan = models.ForeignKey(RecoveryPlan, on_delete=models.PROTECT, null=True, blank=True, related_name="audit_events")
    release_plan = models.ForeignKey(ReleasePlan, on_delete=models.PROTECT, null=True, blank=True, related_name="audit_events")
    object_type = models.CharField(max_length=40)
    object_id = models.CharField(max_length=100)
    action = models.CharField(max_length=50)
    outcome = models.CharField(max_length=10, choices=Outcome.choices, default=Outcome.SUCCESS)
    error_code = models.CharField(max_length=80, blank=True)
    permission_code = models.CharField(max_length=120)
    from_status = models.CharField(max_length=30, blank=True)
    to_status = models.CharField(max_length=30, blank=True)
    reason = models.CharField(max_length=500)
    approval_ref = models.CharField(max_length=160, blank=True)
    rollback_approval_ref = models.CharField(max_length=160, blank=True)
    idempotency_key_hash = models.CharField(max_length=64)
    request_id = models.CharField(max_length=120, blank=True)
    version = models.PositiveIntegerField()
    evidence_refs = models.JSONField(default=list, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        base_manager_name = "objects"
        ordering = ["occurred_at", "id"]
        constraints = [models.UniqueConstraint(fields=["tenant", "idempotency_key_hash"], name="uniq_pilot_audit_idempotency")]

    def save(self, *args, **kwargs):
        if not self._state.adding or (self.pk and type(self).objects.filter(pk=self.pk).exists()):
            raise ValidationError("Pilot audit events are immutable.")
        kwargs["force_insert"] = True
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Pilot audit events are immutable.")
