"""Private notification material and source-bound delivery records."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from .models import Record
from .cost_models import AppendOnlyRecord


class NotificationChannel(Record):
    name = models.CharField(max_length=120)
    provider = models.CharField(max_length=20, default='worktool', choices=[('worktool', 'WorkTool')])
    sender_name = models.CharField(max_length=120)
    device_name = models.CharField(max_length=120)
    credential_id = models.CharField(max_length=200, blank=True)
    token_id = models.CharField(max_length=200, blank=True)
    credential_version = models.PositiveIntegerField(default=0)
    credential_digest = models.CharField(max_length=64, blank=True)
    enabled = models.BooleanField(default=False)
    enabled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    qualification = models.JSONField(default=dict, blank=True)
    qualified_digest = models.CharField(max_length=64, blank=True)
    connectivity = models.CharField(max_length=12, default='unknown')
    last_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'name'], name='sc2_channel_name')]


class SupplierGroupBinding(Record):
    supplier = models.OneToOneField('masterdata.SupplierMaster', on_delete=models.PROTECT, related_name='sc2_group_binding')
    channel = models.ForeignKey(NotificationChannel, on_delete=models.PROTECT, related_name='bindings')
    group_name = models.CharField(max_length=160)
    target_title = models.CharField(max_length=60)
    official_chat_id = models.CharField(max_length=200, blank=True)
    member_count = models.PositiveIntegerField(null=True, blank=True)
    group_note = models.TextField(blank=True)
    contains_external_member = models.BooleanField(default=False)
    sender_member_confirmed = models.BooleanField(default=False)
    unique_target_confirmed = models.BooleanField(default=False)
    evidence = models.TextField(blank=True)
    verified_digest = models.CharField(max_length=64, blank=True)
    enabled = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['channel', 'target_title'], name='sc2_group_single_supplier')]


class NotificationPart(Record):
    outbox = models.ForeignKey('supply_chain.NotificationOutbox', on_delete=models.PROTECT, related_name='parts')
    kind = models.CharField(max_length=12, choices=[('summary', '摘要'), ('excel', 'Excel'), ('pdf', 'PDF'), ('link', '操作链接')])
    sequence = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=24, default='pending')
    text = models.TextField(blank=True)
    object_name = models.CharField(max_length=200, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    body = models.BinaryField(default=bytes, blank=True)
    sha256 = models.CharField(max_length=64)
    size = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['outbox', 'kind'], name='sc2_notification_part_kind')]
        ordering = ['sequence']


class NotificationAttempt(Record):
    part = models.ForeignKey(NotificationPart, on_delete=models.PROTECT, related_name='attempts')
    channel = models.ForeignKey(NotificationChannel, on_delete=models.PROTECT)
    number = models.PositiveIntegerField()
    outcome = models.CharField(max_length=24, default='sending')
    provider_message_id = models.CharField(max_length=128, null=True, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    target_snapshot = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['part', 'number'], name='sc2_part_attempt_number'),
            models.UniqueConstraint(fields=['channel', 'provider_message_id'], name='sc2_provider_message_id')]


class NotificationEvidence(AppendOnlyRecord):
    part = models.ForeignKey(NotificationPart, on_delete=models.PROTECT, related_name='evidence')
    attempt = models.ForeignKey(NotificationAttempt, on_delete=models.PROTECT)
    result = models.CharField(max_length=20, choices=[('delivered', '群内已核实'), ('not_delivered', '核实未送达')])
    evidence = models.TextField()
    execution_stopped = models.BooleanField(default=False)


class NotificationReceipt(AppendOnlyRecord):
    attempt = models.ForeignKey(NotificationAttempt, on_delete=models.PROTECT, related_name='receipts')
    digest = models.CharField(max_length=64)
    source = models.CharField(max_length=12)
    result = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['attempt', 'digest'], name='sc2_receipt_dedupe')]


class NotificationDownload(Record):
    attempt = models.OneToOneField(NotificationAttempt, on_delete=models.PROTECT, related_name='download_grant')
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    download_count = models.PositiveIntegerField(default=0)


class NotificationThrottle(models.Model):
    """One provider/IP budget across tenants and worker processes."""
    provider = models.CharField(max_length=20, primary_key=True)
    next_at = models.DateTimeField(default=timezone.now)
