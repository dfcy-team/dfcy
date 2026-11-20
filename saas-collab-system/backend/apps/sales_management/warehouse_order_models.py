"""Order enrichment state, independent of sales and financial facts."""
import uuid

from django.conf import settings
from django.db import models


class OrderWarehouseLookup(models.Model):
    order = models.OneToOneField('commerce.SalesOrder', on_delete=models.CASCADE,
                                related_name='warehouse_lookup')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    warehouse = models.ForeignKey('masterdata.WarehouseMaster', null=True, on_delete=models.PROTECT)
    revision = models.UUIDField(default=uuid.uuid4)
    order_status = models.JSONField(default=list)
    status = models.CharField(max_length=24, default='pending', db_index=True)
    message = models.CharField(max_length=300, blank=True)
    snapshot = models.JSONField(default=dict)
    checks = models.JSONField(default=list)
    lease = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    checked_at = models.DateTimeField(null=True)
    snapshot_at = models.DateTimeField(null=True)

    next_query_at = models.DateTimeField(null=True, db_index=True)
    retry_count = models.PositiveSmallIntegerField(default=0)
    followup_required = models.BooleanField(default=False)
    polling_until = models.DateTimeField(null=True)

    class Meta:
        db_table = 'sales_order_warehouse_lookup'


class WarehouseOutboundLine(models.Model):
    lookup = models.ForeignKey(OrderWarehouseLookup, on_delete=models.CASCADE, related_name='outbound_lines')
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    warehouse = models.ForeignKey('masterdata.WarehouseMaster', on_delete=models.PROTECT)
    site_code = models.CharField(max_length=8)
    document = models.CharField(max_length=191)
    document_key = models.CharField(max_length=64)
    identity_key = models.CharField(max_length=64)
    shipped_at = models.DateTimeField()
    warehouse_sku = models.CharField(max_length=191, blank=True)
    source_sku = models.CharField(max_length=191, blank=True)
    quantity = models.PositiveBigIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['lookup', 'identity_key'],
                                    name='uniq_wh_outbound_lookup_line'),
        ]
        indexes = [
            models.Index(fields=['tenant', 'warehouse', 'shipped_at'], name='wh_outbound_scope_time_idx'),
            models.Index(fields=['tenant', 'warehouse', 'document_key'], name='wh_outbound_scope_doc_idx'),
            models.Index(fields=['tenant', 'site_code', 'shipped_at'], name='wh_outbound_site_time_idx'),
        ]
