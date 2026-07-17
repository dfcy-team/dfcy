from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.tenants.models import Tenant


class ApprovalRequest(models.Model):
    class ApprovalType(models.TextChoices):
        PURCHASE = "purchase", "Purchase"
        PRICE = "price", "Price"
        LISTING = "listing", "Listing"
        CLEARANCE = "clearance", "Clearance"
        FINANCE = "finance", "Finance"
        REPORT_EXPORT = "report_export", "Report export"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="workflow_approvals")
    approval_type = models.CharField(max_length=40, choices=ApprovalType.choices)
    title = models.CharField(max_length=200)
    business_type = models.CharField(max_length=80)
    business_id = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_workflow_approvals",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_workflow_approvals",
        null=True,
        blank=True,
    )
    reason = models.TextField(blank=True)
    decision_note = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["tenant_id", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="uniq_workflow_approval_idempotency"),
        ]
        indexes = [models.Index(fields=["tenant", "approval_type", "status"], name="idx_workflow_approval")]

    def clean(self):
        if self.requested_by_id and self.requested_by.tenant_id != self.tenant_id:
            raise ValidationError("Approval requester must belong to the same tenant.")
        if self.reviewed_by_id and self.reviewed_by.tenant_id != self.tenant_id:
            raise ValidationError("Approval reviewer must belong to the same tenant.")


class BusinessException(models.Model):
    class Module(models.TextChoices):
        PRODUCT = "product", "Product"
        PURCHASING = "purchasing", "Purchasing"
        SUPPLIER = "supplier", "Supplier"
        LISTING = "listing", "Listing"
        FINANCE = "finance", "Finance"
        RPA = "rpa", "RPA"
        INTEGRATION = "integration", "Integration"

    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ASSIGNED = "assigned", "Assigned"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="workflow_exceptions")
    module = models.CharField(max_length=40, choices=Module.choices)
    title = models.CharField(max_length=200)
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.MEDIUM)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    business_type = models.CharField(max_length=80, blank=True)
    business_id = models.CharField(max_length=100, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_workflow_exceptions",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_workflow_exceptions",
    )
    description = models.TextField(blank=True)
    resolution = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["tenant_id", "-created_at", "-id"]
        indexes = [models.Index(fields=["tenant", "module", "status"], name="idx_workflow_exception")]

    def clean(self):
        if self.created_by_id and self.created_by.tenant_id != self.tenant_id:
            raise ValidationError("Exception creator must belong to the same tenant.")
        if self.assigned_to_id and self.assigned_to.tenant_id != self.tenant_id:
            raise ValidationError("Exception assignee must belong to the same tenant.")


class CollaborationEvent(models.Model):
    class Channel(models.TextChoices):
        WECHAT = "wechat", "WeChat mock"
        FEISHU = "feishu", "Feishu mock"

    class Status(models.TextChoices):
        PENDING_CONFIRMATION = "pending_confirmation", "Pending confirmation"
        CONFIRMED = "confirmed", "Confirmed"
        REJECTED = "rejected", "Rejected"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="workflow_collaboration_events")
    channel = models.CharField(max_length=20, choices=Channel.choices)
    event_id = models.CharField(max_length=120)
    event_type = models.CharField(max_length=80)
    payload_hash = models.CharField(max_length=64)
    masked_summary = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING_CONFIRMATION)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="confirmed_workflow_collaboration_events",
        null=True,
        blank=True,
    )
    decision_note = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["tenant_id", "-received_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "channel", "event_id"], name="uniq_workflow_collab_event"),
        ]
        indexes = [models.Index(fields=["tenant", "channel", "status"], name="idx_workflow_collab")]


class WorkflowAuditEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Workflow audit events are immutable.")

    def delete(self):
        raise ValidationError("Workflow audit events are immutable.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Workflow audit events are immutable.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Workflow audit events require the audited workflow service.")


class WorkflowAuditEvent(models.Model):
    objects = WorkflowAuditEventQuerySet.as_manager()

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="workflow_audit_events")
    resource_type = models.CharField(max_length=40)
    resource_id = models.CharField(max_length=100)
    action = models.CharField(max_length=40)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workflow_audit_events",
        null=True,
        blank=True,
    )
    from_status = models.CharField(max_length=30, blank=True)
    to_status = models.CharField(max_length=30, blank=True)
    masked_detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        base_manager_name = "objects"
        ordering = ["tenant_id", "created_at", "id"]
        indexes = [models.Index(fields=["tenant", "resource_type", "resource_id"], name="idx_workflow_audit")]

    def save(self, *args, **kwargs):
        if not self._state.adding or (self.pk is not None and type(self).objects.filter(pk=self.pk).exists()):
            raise ValidationError("Workflow audit events are immutable.")
        kwargs["force_insert"] = True
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Workflow audit events are immutable.")
