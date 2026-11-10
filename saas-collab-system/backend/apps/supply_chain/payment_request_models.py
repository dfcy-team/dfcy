from django.db import models
from django.db.models.functions import JSONObject
from .models import BusinessEvent, Record


def active_vouchers(queryset):
    removed = BusinessEvent.objects.filter(
        tenant_id=models.OuterRef("tenant_id"),
        aggregate_type=queryset.model._meta.model_name,
        aggregate_id=models.OuterRef("pk"),
        action="request_voucher_removed",
    )
    return queryset.filter(~models.Exists(removed))


class SupplyPaymentBatch(Record):
    """One approval and one evidence set covering several source payment requests."""
    STATUSES = [(x, x) for x in ('draft', 'submitted', 'paid', 'cancelled')]
    payee_account = models.ForeignKey('supply_chain.PayeeAccount', on_delete=models.PROTECT, related_name='payment_batches')
    account_snapshot = models.JSONField(default=dict)
    currency = models.CharField(max_length=3, blank=True, default='', db_default='')
    reason = models.TextField()
    status = models.CharField(max_length=16, choices=STATUSES, default='draft')
    approval = models.OneToOneField('workflows.ApprovalRequest', on_delete=models.PROTECT, null=True, blank=True, related_name='supply_payment_batch')
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    notification_status = models.CharField(max_length=24, default='not_queued')
    notification_error = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'idempotency_key'], name='sc2_paybatch_idem')]
        indexes = [models.Index(fields=['tenant', 'status', '-created_at'], name='sc2_paybatch_list')]


class SupplyPaymentBatchVoucher(Record):
    batch = models.ForeignKey(SupplyPaymentBatch, on_delete=models.PROTECT, related_name='vouchers')
    file_name = models.CharField(max_length=200)
    media_type = models.CharField(max_length=32)
    byte_size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=128)
    content = models.BinaryField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'batch', 'idempotency_key'], name='sc2_paybatch_voucher_idem')]


class SupplyPaymentRequest(Record):
    STATUSES = [(x, x) for x in ('draft', 'submitted', 'paid', 'cancelled')]
    KINDS = [(x, x) for x in ('purchase', 'shipment', 'domestic_freight', 'batch', 'inbound')]
    kind = models.CharField(max_length=24, choices=KINDS)
    source_id = models.PositiveBigIntegerField()
    amount = models.DecimalField(max_digits=24, decimal_places=4)
    payee_account = models.ForeignKey('supply_chain.PayeeAccount', on_delete=models.PROTECT, related_name='payment_requests')
    account_snapshot = models.JSONField(default=dict)
    currency = models.CharField(max_length=3, blank=True, default='', db_default='')
    fee_item = models.ForeignKey('supply_chain.PaymentItem', on_delete=models.PROTECT, null=True, blank=True, related_name='payment_requests')
    plan = models.ForeignKey('supply_chain.PaymentPlanRecord', on_delete=models.PROTECT, null=True, blank=True, related_name='payment_requests')
    plan_line_id = models.CharField(max_length=64, blank=True, default='', db_default='')
    plan_snapshot = models.JSONField(default=dict, db_default=JSONObject(), blank=True)
    item_snapshot = models.JSONField(default=dict, blank=True)
    reason = models.TextField()
    batch = models.ForeignKey(SupplyPaymentBatch, on_delete=models.PROTECT, null=True, blank=True, related_name='lines')
    status = models.CharField(max_length=16, choices=STATUSES, default='draft')
    approval = models.OneToOneField('workflows.ApprovalRequest', on_delete=models.PROTECT, null=True, blank=True, related_name='supply_payment_request')
    payment = models.OneToOneField('supply_chain.PaymentRecord', on_delete=models.PROTECT, null=True, blank=True, related_name='payment_request')
    version = models.PositiveIntegerField(default=1)
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    notification_status = models.CharField(max_length=24, default='not_queued')
    notification_error = models.TextField(blank=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name='sc2_payreq_amount_positive'),
            models.UniqueConstraint(fields=['tenant', 'idempotency_key'], name='sc2_payreq_idem')]
        indexes = [models.Index(fields=['tenant', 'kind', 'source_id', 'status'], name='sc2_payreq_source')]


class SupplyPaymentRequestVoucher(Record):
    request = models.ForeignKey(SupplyPaymentRequest, on_delete=models.PROTECT, related_name='vouchers')
    file_name = models.CharField(max_length=200)
    media_type = models.CharField(max_length=32)
    byte_size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=128)
    content = models.BinaryField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'request', 'idempotency_key'], name='sc2_payreq_voucher_idem')]


class SupplyPaymentRequestAttachment(Record):
    request = models.ForeignKey(SupplyPaymentRequest, on_delete=models.PROTECT, related_name='attachments')
    file_name = models.CharField(max_length=200)
    media_type = models.CharField(max_length=32)
    byte_size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=128)
    content = models.BinaryField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'request', 'idempotency_key'], name='sc2_payreq_attachment_idem')]
