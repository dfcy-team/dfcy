from django.db import models
from django.conf import settings

from apps.tenants.models import Tenant


class RPATool(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="rpa_tools")
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=80)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    config = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_rpa_tool_code_per_tenant"),
        ]

    def __str__(self):
        return self.name


class RPAAgent(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        DISABLED = "disabled", "Disabled"

    class ExecutionMode(models.TextChoices):
        MOCK = "mock", "Mock"
        DRY_RUN = "dry_run", "Dry run"
        PRODUCTION_DISABLED = "production_disabled", "Production disabled"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="rpa_agents")
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rpa_agent",
    )
    name = models.CharField(max_length=100)
    token_hash = models.CharField(max_length=128)
    device_fingerprint = models.CharField(max_length=128, blank=True)
    ip_whitelist = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    execution_mode = models.CharField(
        max_length=30,
        choices=ExecutionMode.choices,
        default=ExecutionMode.DRY_RUN,
    )
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "name"]

    def __str__(self):
        return self.name


class BigSellerAccount(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="big_seller_accounts")
    name = models.CharField(max_length=100)
    account_identifier = models.CharField(max_length=100)
    credential_ref = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "account_identifier"], name="uniq_bigseller_account_per_tenant"),
        ]

    def __str__(self):
        return self.name


class RPATask(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CLAIMED = "claimed", "Claimed"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        RETRYING = "retrying", "Retrying"
        MANUAL_REQUIRED = "manual_required", "Manual required"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="rpa_tasks")
    task_type = models.CharField(max_length=80)
    business_type = models.CharField(max_length=80)
    business_id = models.CharField(max_length=80)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    priority = models.IntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    screenshot_url = models.URLField(blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    max_retry_count = models.PositiveIntegerField(default=3)
    claimed_by = models.ForeignKey(
        RPAAgent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="claimed_tasks",
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    manual_assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_rpa_manual_tasks",
    )
    manual_reason = models.TextField(blank=True)
    manual_assigned_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"], name="idx_rpa_task_tenant_status"),
            models.Index(fields=["business_type", "business_id"], name="idx_rpa_task_business_ref"),
        ]

    def __str__(self):
        return f"{self.task_type}:{self.business_type}:{self.business_id}"


class RPATaskStepLog(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="rpa_task_step_logs")
    task = models.ForeignKey(RPATask, on_delete=models.CASCADE, related_name="step_logs")
    step_name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=Status.choices)
    message = models.TextField(blank=True)
    screenshot_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.task_id}:{self.step_name}"


class RPATaskAttempt(models.Model):
    class Status(models.TextChoices):
        CLAIMED = "claimed", "Claimed"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        RETRYING = "retrying", "Retrying"
        MANUAL_REQUIRED = "manual_required", "Manual required"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="rpa_task_attempts")
    task = models.ForeignKey(RPATask, on_delete=models.CASCADE, related_name="attempts")
    attempt_no = models.PositiveIntegerField()
    agent = models.ForeignKey(RPAAgent, on_delete=models.PROTECT, related_name="task_attempts")
    started_at = models.DateTimeField()
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.CLAIMED)
    failed_step = models.CharField(max_length=120, blank=True)
    last_success_step = models.CharField(max_length=120, blank=True)
    masked_error = models.TextField(blank=True)
    manual_required = models.BooleanField(default=False)

    class Meta:
        ordering = ["task_id", "attempt_no"]
        constraints = [
            models.UniqueConstraint(fields=["task", "attempt_no"], name="uniq_rpa_task_attempt_no"),
        ]

    def __str__(self):
        return f"{self.task_id}:{self.attempt_no}"


class RPAEvidence(models.Model):
    class EvidenceType(models.TextChoices):
        SCREENSHOT = "screenshot", "Screenshot"
        PAGE_SNAPSHOT = "page_snapshot", "Page snapshot"
        LOG_REFERENCE = "log_reference", "Log reference"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="rpa_evidence")
    task = models.ForeignKey(RPATask, on_delete=models.CASCADE, related_name="evidence")
    attempt = models.ForeignKey(
        RPATaskAttempt,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="evidence",
    )
    evidence_type = models.CharField(max_length=30, choices=EvidenceType.choices)
    placeholder_url = models.CharField(max_length=255)
    payload_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(placeholder_url__startswith="demo")
                    | models.Q(placeholder_url__startswith="example")
                    | models.Q(placeholder_url__startswith="local-placeholder")
                ),
                name="rpa_evidence_placeholder_only",
            ),
        ]


class RPAAccountLock(models.Model):
    class LockStatus(models.TextChoices):
        HELD = "held", "Held"
        RELEASED = "released", "Released"
        EXPIRED = "expired", "Expired"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="rpa_account_locks")
    platform = models.CharField(max_length=40)
    account_alias = models.CharField(max_length=120)
    task = models.ForeignKey(RPATask, on_delete=models.CASCADE, related_name="account_locks")
    lock_status = models.CharField(max_length=20, choices=LockStatus.choices, default=LockStatus.HELD)
    acquired_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["tenant_id", "platform", "account_alias", "-acquired_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform", "account_alias"],
                condition=models.Q(lock_status="held"),
                name="uniq_held_rpa_platform_account",
            ),
        ]


class RPAPageSignature(models.Model):
    class DetectedStatus(models.TextChoices):
        STABLE = "stable", "Stable"
        CHANGED = "changed", "Changed"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="rpa_page_signatures")
    platform = models.CharField(max_length=40)
    page_type = models.CharField(max_length=80)
    signature_hash = models.CharField(max_length=128)
    detected_status = models.CharField(
        max_length=20,
        choices=DetectedStatus.choices,
        default=DetectedStatus.STABLE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["tenant_id", "platform", "page_type", "-created_at"]
