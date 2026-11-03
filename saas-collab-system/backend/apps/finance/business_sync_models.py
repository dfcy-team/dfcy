"""Internal read-only replication provenance, separate from marketplace OAuth."""
from django.conf import settings
from django.db import models


class BusinessSyncSource(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    code = models.SlugField(max_length=80)
    origin = models.URLField()
    client_binding_hash = models.CharField(max_length=64)
    is_enabled = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'code'], name='uniq_business_sync_source')]


class BusinessSyncBatch(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    source = models.ForeignKey(BusinessSyncSource, on_delete=models.PROTECT)
    resource = models.CharField(max_length=40)
    date_from = models.DateField()
    date_to = models.DateField()
    snapshot_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=20, default='importing')
    accounting = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['source', 'resource', 'date_from', 'date_to', 'snapshot_hash'], name='uniq_business_sync_batch')]


class BusinessSyncIdentity(models.Model):
    source = models.ForeignKey(BusinessSyncSource, on_delete=models.PROTECT)
    resource = models.CharField(max_length=40)
    source_record_id = models.PositiveBigIntegerField()
    batch = models.ForeignKey(BusinessSyncBatch, on_delete=models.PROTECT)
    payload_hash = models.CharField(max_length=64)
    target_id = models.PositiveBigIntegerField(null=True)
    status = models.CharField(max_length=20)
    reason = models.CharField(max_length=80, blank=True)
    pending_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['source', 'resource', 'source_record_id'], name='uniq_business_sync_identity'),
            models.UniqueConstraint(fields=['source', 'resource', 'target_id'], name='uniq_business_sync_target')]


def validate_business_origin(instance, resource):
    """Called by model validation as well as the controlled importer."""
    from django.core.exceptions import ValidationError
    batch = instance.internal_sync_batch
    native = instance.authorization_id is not None and instance.source_run_id is not None
    if batch is None:
        if not native:
            raise ValidationError('Marketplace facts require both authorization and source run.')
        return
    if instance.authorization_id is not None or instance.source_run_id is not None:
        raise ValidationError('Internal replication cannot claim marketplace authorization or a platform run.')
    if (batch.tenant_id != instance.tenant_id or batch.source.tenant_id != instance.tenant_id
            or batch.resource != resource or not batch.source.is_enabled):
        raise ValidationError('Internal replication source, resource and tenant must match.')
