from django.core.exceptions import ValidationError
from django.db import models

from apps.tenants.models import Tenant


class ApiContract(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        MOCK = "mock", "Mock"
        SANDBOX = "sandbox", "Sandbox"
        CONNECTED = "connected", "Connected"
        DEGRADED = "degraded", "Degraded"
        DISABLED = "disabled", "Disabled"
        STALE = "stale", "Stale"

    class Compatibility(models.TextChoices):
        CURRENT = "current", "Current"
        DEPRECATED = "deprecated", "Deprecated"
        PENDING = "pending", "Pending"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="governance_api_contracts",
    )
    module = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=240)
    owner = models.CharField(max_length=120)
    version = models.CharField(max_length=40)
    permission_code = models.CharField(max_length=120)
    data_scope_keys = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    compatibility = models.CharField(max_length=20, choices=Compatibility.choices, default=Compatibility.CURRENT)
    deprecation_at = models.DateTimeField(null=True, blank=True)
    request_fields = models.JSONField(default=list, blank=True)
    response_fields = models.JSONField(default=list, blank=True)
    error_codes = models.JSONField(default=list, blank=True)
    change_history = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["module", "path", "method", "id"]
        constraints = [
            models.UniqueConstraint(fields=["method", "path", "version"], name="uniq_governance_contract_version"),
        ]


class AssistantDefinition(models.Model):
    class Status(models.TextChoices):
        PLACEHOLDER = "placeholder", "Placeholder"
        REVIEW_PENDING = "review_pending", "Review pending"
        SANDBOX = "sandbox", "Sandbox"
        DISABLED = "disabled", "Disabled"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="governance_assistants",
    )
    code = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=160)
    description = models.TextField()
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PLACEHOLDER)
    data_class = models.CharField(max_length=40, default="public_demo")
    allowed_tools = models.JSONField(default=list, blank=True)
    output_types = models.JSONField(default=list, blank=True)
    limitations = models.JSONField(default=list, blank=True)
    human_confirmation_required = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code", "id"]


class AssistantEvaluationJobQuerySet(models.QuerySet):
    """Execution records are append-only except through the task service."""

    def update(self, **kwargs):
        raise ValidationError("Assistant evaluation jobs must be changed through the execution service.")

    def delete(self):
        raise ValidationError("Assistant evaluation jobs cannot be deleted.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Assistant evaluation jobs must be changed through the execution service.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Assistant evaluation jobs must be created through the execution service.")


class AssistantEvaluationJob(models.Model):
    """Durable, tenant-scoped asynchronous assistant evaluation."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    objects = AssistantEvaluationJobQuerySet.as_manager()

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="governance_assistant_evaluation_jobs",
    )
    assistant = models.ForeignKey(
        AssistantDefinition,
        on_delete=models.PROTECT,
        related_name="evaluation_jobs",
    )
    requested_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.PROTECT,
        related_name="governance_assistant_evaluation_jobs_requested",
    )
    scenario = models.CharField(max_length=40)
    demo_input_ref = models.SlugField(max_length=110)
    # Synthetic public-demo cases are retained only for the lifetime of the
    # durable job so a Celery worker can resume/inspect the exact request. The
    # API never accepts credentials, URLs, or business-data classes here.
    test_input = models.TextField(blank=True)
    expected_output = models.TextField(blank=True)
    reason = models.CharField(max_length=500)
    assistant_version = models.PositiveIntegerField()
    idempotency_key_hash = models.CharField(max_length=64)
    request_fingerprint = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    attempts = models.PositiveSmallIntegerField(default=0)
    celery_task_id = models.CharField(max_length=255, blank=True)
    response_id = models.CharField(max_length=255, blank=True)
    model = models.CharField(max_length=120, blank=True)
    token_usage = models.JSONField(default=dict, blank=True)
    result = models.TextField(blank=True)
    assistant_output = models.TextField(blank=True)
    passed = models.BooleanField(null=True, blank=True)
    score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    findings = models.JSONField(default=list, blank=True)
    result_summary = models.CharField(max_length=1000, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.CharField(max_length=1000, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key_hash"],
                name="uniq_assistant_eval_idempotency",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status", "created_at"], name="idx_assistant_eval_status"),
        ]

    def save(self, *args, **kwargs):
        if self.pk and not getattr(self, "_execution_service_write", False):
            raise ValidationError("Assistant evaluation jobs must be changed through the execution service.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Assistant evaluation jobs cannot be deleted.")
