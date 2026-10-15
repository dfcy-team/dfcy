"""Audited allocation of WMS receipt facts; never adjusts warehouse inventory."""
from django.db import models
from .models import Record


class WmsReceiptAllocation(Record):
    receipt_line = models.ForeignKey('supply_chain.InternalStockReceiptLine', on_delete=models.PROTECT, related_name='wms_allocations')
    wms_line = models.ForeignKey('commerce.InboundRecord', on_delete=models.PROTECT, related_name='supply_allocations')
    quantity = models.PositiveIntegerField()
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    creation_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'creation_key'], name='sc2_wms_allocation_key'),
                       models.CheckConstraint(condition=models.Q(quantity__gt=0), name='sc2_wms_alloc_positive')]
