"""Tenant and business-flow scoped native approval configuration and outbox."""
import uuid
from django.db import models
from apps.tenants.models import Tenant


class FeishuApprovalMapping(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    flow_key = models.CharField(max_length=64)
    business_type = models.CharField(max_length=80)
    approval_code = models.CharField(max_length=80)
    definition = models.JSONField(default=dict)
    definition_hash = models.CharField(max_length=64)
    reviewer_open_id = models.CharField(max_length=120)
    reviewer_id = models.PositiveBigIntegerField()
    fixed_assignees_verified = models.BooleanField(default=False)
    subscription_verified = models.BooleanField(default=False)
    enabled = models.BooleanField(default=False)
    finance_node_id = models.CharField(max_length=120, blank=True)
    finance_date_widget_id = models.CharField(max_length=120, blank=True)
    finance_voucher_widget_id = models.CharField(max_length=120, blank=True)
    finance_attachment_hosts = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'flow_key', 'business_type'], name='feishu_native_flow_unique')]


class FeishuApprovalInstance(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    approval = models.OneToOneField('workflows.ApprovalRequest', on_delete=models.PROTECT, related_name='feishu_native')
    mapping = models.ForeignKey(FeishuApprovalMapping, on_delete=models.PROTECT)
    submission_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    approval_code = models.CharField(max_length=80)
    instance_code = models.CharField(max_length=120, null=True, blank=True)
    app_id = models.CharField(max_length=120)
    reviewer_open_id = models.CharField(max_length=120)
    payload = models.JSONField(default=dict)
    definition_hash = models.CharField(max_length=64)
    finance_snapshot = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=24, default='queued')
    provider_status = models.CharField(max_length=24, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=80, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'instance_code'], name='feishu_native_instance_unique')]


class FeishuApprovalEvent(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    event_id = models.CharField(max_length=120)
    event = models.JSONField(default=dict)
    status = models.CharField(max_length=24, default='queued')
    attempts = models.PositiveIntegerField(default=0)
    lease_until = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'event_id'], name='feishu_native_event_unique')]


class FeishuFinanceHandoff(models.Model):
    instance = models.OneToOneField(FeishuApprovalInstance, on_delete=models.PROTECT, related_name='finance_handoff')
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    handler = models.ForeignKey('accounts.CustomUser', on_delete=models.PROTECT)
    status = models.CharField(max_length=24, default='awaiting_finance')
    actual_payment_date = models.DateField(null=True, blank=True)
    voucher_manifest = models.JSONField(default=list, blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    last_error = models.CharField(max_length=80, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
