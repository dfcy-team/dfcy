import uuid

from django.conf import settings
from django.db import models


class SyncEnvironment(models.Model):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    resources = models.JSONField(default=list)
    store_ids = models.JSONField(default=list)
    warehouse_ids = models.JSONField(default=list)
    # Server-side source alias, never a URL or credential supplied by a browser.
    source_alias = models.CharField(max_length=40, default="default")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["tenant", "owner", "active"])]


class SnapshotBatch(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "排队中"
        RUNNING = "running", "同步中"
        READY = "ready", "可使用"
        FAILED = "failed", "失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    environment = models.ForeignKey(SyncEnvironment, on_delete=models.PROTECT, related_name="batches")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    resources = models.JSONField(default=list)
    date_from = models.DateField()
    date_to = models.DateField()
    summary = models.JSONField(default=dict)
    error_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["tenant", "status", "created_at"])]


class SyncAudit(models.Model):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    batch = models.ForeignKey(SnapshotBatch, on_delete=models.CASCADE, null=True, related_name="audit")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True)
    event = models.CharField(max_length=48)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]


class SnapshotIdentity(models.Model):
    """Only rows created by the demo importer may be updated on replay."""
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    resource = models.CharField(max_length=64)
    source_id = models.CharField(max_length=64)
    target_id = models.BigIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "resource", "source_id"], name="demo_identity_source_unique")]


class ImportedSnapshotReceipt(models.Model):
    """A work database is initialized once; refresh uses a new clone/database."""
    tenant = models.OneToOneField("tenants.Tenant", on_delete=models.PROTECT)
    manifest_sha256 = models.CharField(max_length=64)
    imported_at = models.DateTimeField(auto_now_add=True)
