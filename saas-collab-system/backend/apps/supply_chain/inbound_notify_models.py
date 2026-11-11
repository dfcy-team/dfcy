from django.db import models
from django.utils import timezone


class InboundNotificationConfig(models.Model):
    tenant = models.OneToOneField('tenants.Tenant', on_delete=models.CASCADE, related_name='inbound_notification_config')
    chat_id = models.CharField(max_length=191, blank=True)
    chat_name = models.CharField(max_length=191, blank=True)
    country_codes = models.JSONField(default=list)
    all_countries = models.BooleanField(default=False)
    enabled = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    updated_by = models.ForeignKey('accounts.CustomUser', null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)


class InboundNotificationOutbox(models.Model):
    STATUSES = [('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed'), ('needs_review', 'Needs review'), ('skipped', 'Skipped')]
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE)
    inbound = models.ForeignKey('supply_chain.InboundOrder', on_delete=models.PROTECT)
    event_key = models.CharField(max_length=64, unique=True)
    chat_id = models.CharField(max_length=191)
    chat_name = models.CharField(max_length=191, blank=True)
    payload = models.JSONField(default=dict)
    app_id = models.CharField(max_length=191, blank=True)
    app_domain = models.CharField(max_length=20, blank=True)
    country_code = models.CharField(max_length=8)
    status = models.CharField(max_length=24, choices=STATUSES, default='pending')
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    lease_until = models.DateTimeField(null=True, blank=True)
    receipt_id = models.CharField(max_length=191, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'inbound'], name='sc2_inbound_notify_once')]
