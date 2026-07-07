from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class OperationLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="operation_logs")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operation_logs",
    )
    module = models.CharField(max_length=80)
    action = models.CharField(max_length=80)
    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=100, blank=True)
    before_data = models.JSONField(default=dict, blank=True)
    after_data = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "module", "action"], name="idx_operation_log_action"),
            models.Index(fields=["object_type", "object_id"], name="idx_operation_log_object"),
        ]

    def __str__(self):
        return f"{self.module}:{self.action}"


class ApprovalLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="approval_logs")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_logs",
    )
    business_type = models.CharField(max_length=80)
    business_id = models.CharField(max_length=100)
    action = models.CharField(max_length=80)
    status = models.CharField(max_length=40)
    comment = models.TextField(blank=True)
    before_data = models.JSONField(default=dict, blank=True)
    after_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.business_type}:{self.action}:{self.status}"


class NotificationMessage(models.Model):
    class Status(models.TextChoices):
        UNREAD = "unread", "Unread"
        READ = "read", "Read"
        ARCHIVED = "archived", "Archived"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="notification_messages")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_messages",
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    message_type = models.CharField(max_length=60, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNREAD)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class DataImportLog(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        PARTIAL_SUCCESS = "partial_success", "Partial success"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="data_import_logs")
    import_type = models.CharField(max_length=80)
    file_name = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    total_count = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    error_summary = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="data_import_logs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.import_type}:{self.status}"


class SystemExceptionLog(models.Model):
    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"
        CRITICAL = "critical", "Critical"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="system_exception_logs",
    )
    module = models.CharField(max_length=80)
    exception_type = models.CharField(max_length=120)
    message = models.TextField()
    traceback = models.TextField(blank=True)
    context = models.JSONField(default=dict, blank=True)
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.ERROR)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.module}:{self.exception_type}"
