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
