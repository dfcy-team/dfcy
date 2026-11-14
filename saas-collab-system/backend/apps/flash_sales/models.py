import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class TenantRecord(models.Model):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class StoreConfig(TenantRecord):
    store = models.OneToOneField("masterdata.StoreMaster", on_delete=models.PROTECT)
    enabled = models.BooleanField(default=False)
    stock = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(999999)])
    runs = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(999999)])
    notification_mode = models.CharField(max_length=12, default="owner", choices=[
        ("owner", "店铺负责人"), ("custom", "自定义人员"), ("fallback", "使用兜底"),
    ])
    recipients = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="flash_store_configs")
    version = models.PositiveIntegerField(default=1)
    deleted_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)


class TenantControl(TenantRecord):
    tenant = models.OneToOneField("tenants.Tenant", on_delete=models.PROTECT)
    fallback_users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="flash_fallbacks")
    # Import and deployment do not transfer ownership from the old scheduler.
    scheduler_owner = models.CharField(max_length=80, default="paused")
    cutover_watermark = models.DateTimeField(null=True, blank=True)
    last_dispatch_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)


class Plan(TenantRecord):
    name = models.CharField(max_length=120)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=8, choices=[("once", "单次"), ("daily", "每日")])
    local_date = models.DateField(null=True, blank=True)
    local_time = models.TimeField()
    stores = models.ManyToManyField("masterdata.StoreMaster", related_name="flash_plans")
    enabled = models.BooleanField(default=False)
    next_due = models.DateTimeField(null=True, blank=True, db_index=True)
    version = models.PositiveIntegerField(default=1)
    deleted_at = models.DateTimeField(null=True, blank=True)


class Batch(TenantRecord):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_id = models.CharField(max_length=120)
    payload_hash = models.CharField(max_length=64)
    source = models.CharField(max_length=16)
    operation = models.CharField(max_length=16, default="run")
    plan = models.ForeignKey(Plan, null=True, blank=True, on_delete=models.PROTECT)
    plan_version = models.PositiveIntegerField(null=True, blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    stop_requested = models.BooleanField(default=False)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "request_id"], name="flash_batch_request_unique")]
        indexes = [models.Index(fields=["tenant", "created_at"], name="flash_batch_tenant_created")]


class StoreTask(TenantRecord):
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="tasks")
    store = models.ForeignKey("masterdata.StoreMaster", on_delete=models.PROTECT)
    snapshot = models.JSONField(default=dict)
    state = models.JSONField(default=dict)
    status = models.CharField(max_length=24, default="queued", db_index=True)
    requested = models.PositiveIntegerField(default=1)
    completed = models.PositiveIntegerField(default=0)
    retry_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    execution_ms = models.PositiveBigIntegerField(default=0)
    waiting_ms = models.PositiveBigIntegerField(default=0)
    message = models.CharField(max_length=500, blank=True)
    fence = models.UUIDField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["batch", "store"], name="flash_batch_store_unique")]
        indexes = [models.Index(fields=["tenant", "store", "status"], name="flash_task_store_status")]


class StoreLock(TenantRecord):
    store = models.OneToOneField("masterdata.StoreMaster", on_delete=models.PROTECT)
    task = models.OneToOneField(StoreTask, null=True, blank=True, on_delete=models.PROTECT)


class ExecutionPool(models.Model):
    # One global row serializes claims across tenants and all worker processes.
    key = models.CharField(primary_key=True, max_length=20, default="shopee")


class Activity(TenantRecord):
    store = models.ForeignKey("masterdata.StoreMaster", on_delete=models.PROTECT)
    platform_id = models.CharField(max_length=80)
    slot_id = models.CharField(max_length=80)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    platform_status = models.IntegerField()
    item_count = models.PositiveIntegerField(null=True)
    enabled_count = models.PositiveIntegerField(null=True)
    synced_at = models.DateTimeField()
    items = models.JSONField(default=list)
    details_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "store", "platform_id"], name="flash_activity_identity")]
        indexes = [models.Index(fields=["tenant", "store", "starts_at"], name="flash_activity_store_time")]


class Preview(TenantRecord):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    store = models.ForeignKey("masterdata.StoreMaster", on_delete=models.PROTECT)
    source_id = models.CharField(max_length=80)
    source_hash = models.CharField(max_length=64)
    target = models.JSONField(default=dict)
    items = models.JSONField(default=list)
    expires_at = models.DateTimeField()
    batch = models.OneToOneField(Batch, null=True, blank=True, on_delete=models.PROTECT)


class Intent(TenantRecord):
    task = models.ForeignKey(StoreTask, on_delete=models.PROTECT, related_name="intents")
    store = models.ForeignKey("masterdata.StoreMaster", on_delete=models.PROTECT)
    slot_id = models.CharField(max_length=80)
    reservation_key = models.CharField(max_length=180, unique=True, null=True, blank=True)
    target = models.JSONField(default=dict)
    source_id = models.CharField(max_length=80, blank=True)
    platform_id = models.CharField(max_length=80, blank=True)
    items = models.JSONField(default=list)
    result = models.JSONField(default=dict)
    status = models.CharField(max_length=24, default="prepared")
    owns_activity = models.BooleanField(default=False)
    # Slot occupancy is retained even after worker lease expiry.
    absence_evidence = models.JSONField(default=dict)

class WriteOperation(TenantRecord):
    intent = models.ForeignKey(Intent, on_delete=models.PROTECT, related_name="writes")
    key = models.CharField(max_length=120)
    endpoint = models.CharField(max_length=80)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=24, default="prepared")
    submitted_at = models.DateTimeField(null=True, blank=True)
    response = models.JSONField(default=dict)
    readback = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["intent", "key"], name="flash_write_intent_key")]


class Notification(TenantRecord):
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="notifications")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    snapshot = models.JSONField(default=dict)
    status = models.CharField(max_length=24, default="pending")
    message_id = models.CharField(max_length=120, blank=True)
    message = models.CharField(max_length=500, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["batch", "recipient"], name="flash_notification_recipient")]


class ImportMapping(TenantRecord):
    namespace = models.CharField(max_length=100)
    kind = models.CharField(max_length=30)
    source_id = models.CharField(max_length=120)
    source_hash = models.CharField(max_length=64)
    target_id = models.CharField(max_length=120)
    source_state = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "namespace", "kind", "source_id"], name="flash_import_source_identity")]


class AppPacer(models.Model):
    key = models.CharField(primary_key=True, max_length=64)
    next_request_at = models.DateTimeField()
