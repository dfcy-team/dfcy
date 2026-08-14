from django.db import models
from django.core.exceptions import ValidationError

from apps.tenants.models import Tenant
from apps.common.validated_models import ValidatedWriteModel
from django.conf import settings


class PlatformChoices(models.TextChoices):
    BIGSELLER = "bigseller", "BigSeller"
    SHOPEE = "shopee", "Shopee"
    TIKTOK = "tiktok", "TikTok"
    MOCK = "mock", "Mock"
    OTHER = "other", "Other"


PAYLOAD_RESOURCE_FAMILIES = {
    "sales_order": "sales_order",
    "order_list": "sales_order",
    "order_detail": "sales_order",
    "refund_return": "refund_return",
    "refund": "refund_return",
    "return": "refund_return",
    "refund_detail": "refund_return",
    "inventory": "inventory",
}


def payload_resource_family(resource_type):
    return PAYLOAD_RESOURCE_FAMILIES.get(resource_type)


class PlatformIntegrationConfig(models.Model):
    class Environment(models.TextChoices):
        MOCK = "mock", "Mock"
        SANDBOX = "sandbox", "Sandbox"
        PRODUCTION = "production", "Production"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DISABLED = "disabled", "Disabled"
        PENDING_REVIEW = "pending_review", "Pending review"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="platform_integration_configs")
    platform = models.CharField(max_length=30, choices=PlatformChoices.choices)
    account_alias = models.CharField(max_length=120)
    environment = models.CharField(max_length=20, choices=Environment.choices, default=Environment.MOCK)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DISABLED)
    credential_ciphertext = models.TextField(blank=True)
    credential_key_version = models.CharField(max_length=40, blank=True)
    credential_fingerprint = models.CharField(max_length=64, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_platform_integration_configs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "platform", "account_alias"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform", "account_alias", "environment"],
                name="uniq_platform_integration_per_tenant",
            ),
        ]

    def __str__(self):
        return f"{self.tenant.code}:{self.platform}:{self.account_alias}"


class IntegrationAuditLog(models.Model):
    class Result(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        BLOCKED = "blocked", "Blocked"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="integration_audit_logs")
    integration_config = models.ForeignKey(
        PlatformIntegrationConfig,
        on_delete=models.CASCADE,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=80)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="integration_audit_logs",
    )
    result = models.CharField(max_length=20, choices=Result.choices)
    masked_detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.integration_config_id}:{self.action}:{self.result}"


class SyncJob(models.Model):
    class ResourceType(models.TextChoices):
        SALES_ORDER = "sales_order", "Sales order"
        REFUND_RETURN = "refund_return", "Refund or return"
        INVENTORY = "inventory", "Inventory"
        SETTLEMENT_BILL = "settlement_bill", "Settlement bill"
        WITHDRAWAL = "withdrawal", "Withdrawal"
        MOCK_RECORD = "mock_record", "Mock record"

    class ScheduleType(models.TextChoices):
        MANUAL = "manual", "Manual"
        INTERVAL = "interval", "Interval"
        CRON = "cron", "Cron"

    class Status(models.TextChoices):
        IDLE = "idle", "Idle"
        RUNNING = "running", "Running"
        DISABLED = "disabled", "Disabled"
        FAILED = "failed", "Failed"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="sync_jobs")
    integration_config = models.ForeignKey(
        PlatformIntegrationConfig,
        on_delete=models.PROTECT,
        related_name="sync_jobs",
    )
    resource_type = models.CharField(max_length=40, choices=ResourceType.choices)
    schedule_type = models.CharField(max_length=20, choices=ScheduleType.choices, default=ScheduleType.MANUAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IDLE)
    is_enabled = models.BooleanField(default=True)
    max_retry_count = models.PositiveIntegerField(default=3)
    backoff_base_seconds = models.PositiveIntegerField(default=1)
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    lock_token = models.CharField(max_length=80, blank=True)
    lock_acquired_at = models.DateTimeField(null=True, blank=True)
    lock_expires_at = models.DateTimeField(null=True, blank=True)
    lock_heartbeat_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "resource_type", "id"]
        indexes = [
            models.Index(fields=["tenant", "status"], name="idx_sync_job_tenant_status"),
            models.Index(fields=["tenant", "resource_type"], name="idx_sync_job_tenant_resource"),
        ]

    def __str__(self):
        return f"{self.integration_config_id}:{self.resource_type}:{self.status}"


class SyncRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="sync_runs")
    sync_job = models.ForeignKey(SyncJob, on_delete=models.CASCADE, related_name="runs")
    run_id = models.CharField(max_length=80)
    idempotency_key = models.CharField(max_length=160)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    fetched_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    retry_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=80, blank=True)
    masked_error_message = models.TextField(blank=True)
    masked_log = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "sync_job", "idempotency_key"],
                name="uniq_sync_run_job_idempotency",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"], name="idx_sync_run_tenant_status"),
            models.Index(fields=["run_id"], name="idx_sync_run_run_id"),
        ]

    def __str__(self):
        return f"{self.run_id}:{self.status}"


class SyncCursor(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="sync_cursors")
    sync_job = models.ForeignKey(SyncJob, on_delete=models.CASCADE, related_name="cursors")
    cursor_key = models.CharField(max_length=80)
    cursor_value = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "sync_job_id", "cursor_key"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "sync_job", "cursor_key"], name="uniq_sync_cursor_key"),
        ]

    def __str__(self):
        return f"{self.sync_job_id}:{self.cursor_key}"


class RawPayload(ValidatedWriteModel):
    class PIIClassification(models.TextChoices):
        NONE = "none", "None"
        MASKED = "masked", "Masked"
        RESTRICTED = "restricted", "Restricted"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="integration_raw_payloads")
    sync_run = models.ForeignKey(SyncRun, on_delete=models.SET_NULL, related_name="raw_payloads", null=True, blank=True)
    store = models.ForeignKey(
        "masterdata.StoreMaster",
        on_delete=models.PROTECT,
        related_name="integration_raw_payloads",
    )
    platform = models.CharField(max_length=30, choices=PlatformChoices.choices)
    resource_type = models.CharField(max_length=40)
    external_id = models.CharField(max_length=191, blank=True)
    schema_version = models.CharField(max_length=40)
    content_hash = models.CharField(max_length=64)
    object_reference = models.CharField(max_length=500, blank=True)
    pii_classification = models.CharField(
        max_length=20,
        choices=PIIClassification.choices,
        default=PIIClassification.RESTRICTED,
    )
    fetched_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fetched_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform", "store", "resource_type", "external_id", "content_hash"],
                name="uniq_raw_payload_identity",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "resource_type", "fetched_at"], name="idx_raw_payload_resource"),
            models.Index(fields=["tenant", "expires_at"], name="idx_raw_payload_expiry"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.store_id and self.store.tenant_id != self.tenant_id:
            errors["store"] = "Store must belong to the payload tenant."
        if self.store_id and self.store.platform.platform_type != self.platform:
            errors["platform"] = "Payload platform must match the store platform."
        if self.sync_run_id and self.sync_run.tenant_id != self.tenant_id:
            errors["sync_run"] = "Sync run must belong to the payload tenant."
        if self.sync_run_id and self.sync_run.sync_job.integration_config.platform != self.platform:
            errors["sync_run"] = "Sync run platform must match the payload platform."
        resource_family = payload_resource_family(self.resource_type)
        if self.sync_run_id and resource_family != self.sync_run.sync_job.resource_type:
            errors["resource_type"] = "Payload resource must match the sync job resource type."
        if errors:
            raise ValidationError(errors)


class SyncQualityResult(ValidatedWriteModel):
    class Status(models.TextChoices):
        PASS = "pass", "Pass"
        WARN = "warn", "Warn"
        FAIL = "fail", "Fail"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="integration_quality_results")
    sync_run = models.ForeignKey(SyncRun, on_delete=models.CASCADE, related_name="quality_results")
    resource_type = models.CharField(max_length=40)
    check_code = models.CharField(max_length=80)
    status = models.CharField(max_length=20, choices=Status.choices)
    expected_count = models.PositiveBigIntegerField(default=0)
    actual_count = models.PositiveBigIntegerField(default=0)
    missing_count = models.PositiveBigIntegerField(default=0)
    duplicate_count = models.PositiveBigIntegerField(default=0)
    invalid_count = models.PositiveBigIntegerField(default=0)
    detail = models.JSONField(default=dict, blank=True)
    checked_at = models.DateTimeField()

    class Meta:
        ordering = ["-checked_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "sync_run", "resource_type", "check_code"],
                name="uniq_sync_quality_check",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status", "checked_at"], name="idx_sync_quality_status"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.sync_run_id and self.sync_run.tenant_id != self.tenant_id:
            errors["sync_run"] = "Sync run must belong to the quality-result tenant."
        if self.sync_run_id and self.sync_run.sync_job.resource_type != self.resource_type:
            errors["resource_type"] = "Quality-result resource must match the sync job."
        if errors:
            raise ValidationError(errors)


class WebhookEvent(models.Model):
    class SignatureStatus(models.TextChoices):
        MOCK_VALID = "mock_valid", "Mock valid"
        INVALID = "invalid", "Invalid"
        NOT_CONFIGURED = "not_configured", "Not configured"

    class ProcessingStatus(models.TextChoices):
        RECEIVED = "received", "Received"
        PROCESSED = "processed", "Processed"
        DUPLICATE = "duplicate", "Duplicate"
        FAILED = "failed", "Failed"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="webhook_events")
    platform = models.CharField(max_length=30, choices=PlatformChoices.choices)
    event_id = models.CharField(max_length=120)
    event_type = models.CharField(max_length=80)
    signature_status = models.CharField(max_length=30, choices=SignatureStatus.choices)
    processing_status = models.CharField(
        max_length=30,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.RECEIVED,
    )
    payload_hash = models.CharField(max_length=64)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "platform", "event_id"], name="uniq_webhook_event_per_tenant"),
        ]

    def __str__(self):
        return f"{self.platform}:{self.event_id}:{self.processing_status}"


class APIIntegrationConfig(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        DISABLED = "disabled", "Disabled"

    class Environment(models.TextChoices):
        MOCK = "mock", "Mock"
        SANDBOX = "sandbox", "Sandbox"
        PRODUCTION = "production", "Production"

    class CredentialStatus(models.TextChoices):
        PLACEHOLDER = "placeholder", "Placeholder"
        ACTIVE = "active", "Active"
        ROTATION_REQUIRED = "rotation_required", "Rotation required"
        REVOKED = "revoked", "Revoked"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="api_integration_configs")
    platform = models.CharField(max_length=30, choices=PlatformChoices.choices)
    shop_code = models.CharField(max_length=80)
    api_base_url = models.URLField()
    environment = models.CharField(max_length=20, choices=Environment.choices, default=Environment.MOCK)
    auth_scheme = models.CharField(max_length=40, default="hmac_sha256")
    credential_ref = models.CharField(max_length=160, blank=True)
    api_key_encrypted = models.TextField(blank=True)
    api_secret_encrypted = models.TextField(blank=True)
    credential_key_version = models.CharField(max_length=40, blank=True)
    credential_status = models.CharField(
        max_length=30,
        choices=CredentialStatus.choices,
        default=CredentialStatus.PLACEHOLDER,
    )
    credential_expires_at = models.DateTimeField(null=True, blank=True)
    last_rotated_at = models.DateTimeField(null=True, blank=True)
    least_privilege_scope = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "platform", "shop_code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "platform", "shop_code"], name="uniq_api_config_shop_per_tenant"),
        ]

    def __str__(self):
        return f"{self.tenant.code}:{self.platform}:{self.shop_code}"


class APISyncTask(models.Model):
    class SyncType(models.TextChoices):
        SALES_ORDER = "sales_order", "Sales order"
        INVENTORY = "inventory", "Inventory"
        INBOUND = "inbound", "Inbound"
        SHIPMENT = "shipment", "Shipment"
        SETTLEMENT_BILL = "settlement_bill", "Settlement bill"
        WITHDRAWAL = "withdrawal", "Withdrawal"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        PARTIAL_SUCCESS = "partial_success", "Partial success"
        FAILED = "failed", "Failed"
        RETRYING = "retrying", "Retrying"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="api_sync_tasks")
    platform = models.CharField(max_length=30, choices=PlatformChoices.choices)
    sync_type = models.CharField(max_length=40, choices=SyncType.choices)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    next_sync_at = models.DateTimeField(null=True, blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    max_retry_count = models.PositiveIntegerField(default=3)
    config = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "platform", "sync_type"]
        indexes = [
            models.Index(fields=["tenant", "platform", "sync_type"], name="idx_api_task_tenant_type"),
            models.Index(fields=["status", "next_sync_at"], name="idx_api_task_schedule"),
        ]

    def __str__(self):
        return f"{self.platform}:{self.sync_type}:{self.status}"


class APISyncLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="api_sync_logs")
    task = models.ForeignKey(APISyncTask, on_delete=models.CASCADE, related_name="logs")
    status = models.CharField(max_length=30, choices=APISyncTask.Status.choices)
    request_url = models.URLField(blank=True)
    request_payload = models.JSONField(default=dict, blank=True)
    response_summary = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]

    def __str__(self):
        return f"{self.task_id}:{self.status}"


class APIDataQualityCheck(models.Model):
    class Status(models.TextChoices):
        PASSED = "passed", "Passed"
        WARNING = "warning", "Warning"
        FAILED = "failed", "Failed"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="api_data_quality_checks")
    sync_log = models.ForeignKey(APISyncLog, on_delete=models.CASCADE, related_name="quality_checks")
    check_type = models.CharField(max_length=80)
    status = models.CharField(max_length=20, choices=Status.choices)
    message = models.TextField(blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["sync_log_id", "check_type"]

    def __str__(self):
        return f"{self.check_type}:{self.status}"
