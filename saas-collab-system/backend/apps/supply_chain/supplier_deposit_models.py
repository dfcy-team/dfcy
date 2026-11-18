from django.db import models

from .cost_models import AppendOnlyRecord


class SupplierDepositEntry(AppendOnlyRecord):
    class Kind(models.TextChoices):
        DEPOSIT = 'deposit', '支付定金'
        REFUND = 'refund', '退回定金'
        TRANSFER = 'transfer', '转采购预付款'

    supplier = models.ForeignKey('masterdata.SupplierMaster', on_delete=models.PROTECT)
    currency = models.CharField(max_length=3)
    amount = models.DecimalField(max_digits=24, decimal_places=4)
    date = models.DateField()
    reference = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    deposit = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='movements')
    payment = models.OneToOneField('supply_chain.PaymentRecord', null=True, blank=True,
        on_delete=models.PROTECT, related_name='supplier_deposit_transfer')
    request_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)

    class Meta:
        ordering = ['-date', '-pk']
        indexes = [models.Index(fields=['tenant', 'supplier', 'currency'], name='sc2_supdep_supplier_ccy')]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name='sc2_supdep_positive'),
            models.CheckConstraint(condition=(
                models.Q(kind='deposit', deposit__isnull=True, payment__isnull=True)
                | models.Q(kind='refund', deposit__isnull=False, payment__isnull=True)
                | models.Q(kind='transfer', deposit__isnull=False, payment__isnull=False)
            ), name='sc2_supdep_kind_shape'),
            models.UniqueConstraint(fields=['tenant', 'request_key'], name='sc2_supdep_request'),
            models.UniqueConstraint(fields=['supplier', 'currency', 'kind', 'reference'],
                condition=models.Q(kind__in=['deposit', 'refund']), name='sc2_supdep_cash_ref'),
        ]
