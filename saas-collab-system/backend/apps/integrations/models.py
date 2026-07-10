from django.db import models

from apps.tenants.models import Tenant
from django.conf import settings


class PlatformChoices(models.TextChoices):
    BIGSELLER = "bigseller", "BigSeller"
    SHOPEE = "shopee", "Shopee"
    TIKTOK = "tiktok", "TikTok"
    MOCK = "mock", "Mock"
    OTHER = "other", "Other"


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
