from django.conf import settings
from django.db import models


class PendingOrderDetail(models.Model):
    order = models.OneToOneField("commerce.SalesOrder", on_delete=models.PROTECT, related_name="pending_internal_detail")
    version = models.PositiveIntegerField(default=1)
    original_lines = models.JSONField(default=list)
    lines = models.JSONField(default=list)
    source_hash = models.CharField(max_length=64)
    adjusted = models.BooleanField(default=False)
    outbound_reference = models.CharField(max_length=191, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class OrderRegistration(models.Model):
    class Kind(models.TextChoices):
        EXCHANGE = "exchange", "换货登记"
        PROMOTION = "promotion", "订单推广登记"
        GCASH = "gcash", "GCash退款登记"

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    store = models.ForeignKey("masterdata.StoreMaster", on_delete=models.PROTECT)
    order = models.ForeignKey("commerce.SalesOrder", on_delete=models.PROTECT, null=True, blank=True, related_name="registrations")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=24, default="draft")
    version = models.PositiveIntegerField(default=1)
    payload = models.JSONField(default=dict)
    snapshot = models.JSONField(default=dict)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    approval = models.OneToOneField("workflows.ApprovalRequest", on_delete=models.PROTECT, null=True, blank=True)
    # NULL permits closed applications; a concrete order has just one open exchange.
    active_exchange_order = models.OneToOneField("commerce.SalesOrder", on_delete=models.PROTECT, null=True, blank=True, related_name="active_exchange_registration")
    transaction_key = models.CharField(max_length=64, unique=True, null=True, blank=True)
    idempotency_key = models.CharField(max_length=100)
    request_hash = models.CharField(max_length=64)
    batch_key = models.CharField(max_length=100, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="deleted_order_registrations")
    delete_reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="uniq_registration_request")]
        indexes = [models.Index(fields=["tenant", "store", "kind", "status"], name="idx_registration_store")]


class RegistrationEvidence(models.Model):
    registration = models.ForeignKey(OrderRegistration, on_delete=models.PROTECT, related_name="evidence")
    name = models.CharField(max_length=180)
    media_type = models.CharField(max_length=40)
    sha256 = models.CharField(max_length=64)
    content = models.BinaryField()
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["registration", "sha256"], name="uniq_registration_evidence")]


class RegistrationImportBatch(models.Model):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    kind = models.CharField(max_length=20, choices=OrderRegistration.Kind.choices)
    file_hash = models.CharField(max_length=64)
    file_name = models.CharField(max_length=255, blank=True)
    attachment_name = models.CharField(max_length=255, blank=True)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    results = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "kind", "file_hash", "imported_by"], name="uniq_registration_batch")]
