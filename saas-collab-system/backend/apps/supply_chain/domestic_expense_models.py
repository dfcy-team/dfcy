"""Shipment-owned domestic expenses with independent payees and currencies."""
from django.db import models
from .models import Record


class DomesticExpenseGroup(Record):
    shipment = models.ForeignKey('supply_chain.SupplierShipment', on_delete=models.PROTECT,
                                 related_name='domestic_expense_groups')
    supplier = models.ForeignKey('masterdata.SupplierMaster', on_delete=models.PROTECT, null=True, blank=True)
    carrier = models.ForeignKey('supply_chain.FreightCompany', on_delete=models.PROTECT, null=True, blank=True)
    currency = models.CharField(max_length=3)
    lines = models.JSONField(default=list)
    amount = models.DecimalField(max_digits=24, decimal_places=4, default=0)
    is_active = models.BooleanField(default=True)

    @property
    def number(self):
        return f'{self.shipment.number}-国内费用{self.pk}'

    @property
    def status(self):
        return self.shipment.status

    class Meta:
        constraints = [
            models.CheckConstraint(condition=(
                models.Q(supplier__isnull=False, carrier__isnull=True)
                | models.Q(supplier__isnull=True, carrier__isnull=False)),
                name='sc2_domestic_expense_one_payee'),
            models.CheckConstraint(condition=models.Q(amount__gte=0), name='sc2_domestic_expense_positive'),
        ]
