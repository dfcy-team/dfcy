"""Append-only receipt difference decisions, separate from actual cash payments."""
from django.db import models
from .cost_models import AppendOnlyRecord


class ReceiptDifferenceDecision(AppendOnlyRecord):
    shipment = models.ForeignKey('supply_chain.SupplierShipment', on_delete=models.PROTECT, related_name='receipt_difference_decisions')
    source_key = models.CharField(max_length=100)
    option = models.CharField(max_length=40)
    payable_delta = models.DecimalField(max_digits=24, decimal_places=4, default=0)
    source_snapshot = models.JSONField()
    reason = models.TextField()
    request_key = models.CharField(max_length=128)
    reverses = models.OneToOneField('self', null=True, blank=True, on_delete=models.PROTECT, related_name='reversal')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'request_key', 'source_key'], name='sc2_receipt_diff_request')]
        indexes = [models.Index(fields=['tenant', 'shipment', 'source_key'], name='sc2_receipt_diff_source')]
