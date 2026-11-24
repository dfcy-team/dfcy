"""SQL projection of confirmed inbound shortage for grouped payable reports."""
from decimal import Decimal

from django.db.models import DecimalField, Exists, ExpressionWrapper, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Cast, Coalesce, Greatest, Least

from .models import DispatchAllocation, InboundLine, ShipmentLine, ReceiptDifferenceDecision

MONEY = DecimalField(max_digits=24, decimal_places=4)
ZERO = Value(Decimal('0'), output_field=MONEY)


def annotate_receipt_shortage(shipments):
    active = DispatchAllocation.objects.filter(
        tenant_id=OuterRef('tenant_id'),
        shipment_line_id=OuterRef('shipment_line_id'),
        membership__batch_id=OuterRef('inbound__batch_id'),
        membership__active_guard=True,
        membership__batch__status='active',
    )
    eligible_receipts = InboundLine.objects.filter(
        tenant_id=OuterRef('tenant_id'), shipment_line_id=OuterRef('pk'),
        inbound__status='confirmed', inbound__batch__status='active',
        received_quantity__isnull=False,
    ).filter(Exists(active)).order_by().values('shipment_line_id')
    expected = eligible_receipts.annotate(total=Sum(Cast(F('expected_quantity'), MONEY))).values('total')
    received = eligible_receipts.annotate(total=Sum(Cast(F('received_quantity'), MONEY))).values('total')
    lines = ShipmentLine.objects.filter(
        tenant_id=OuterRef('tenant_id'), shipment_id=OuterRef('pk'), is_active=True,
        unit_price__isnull=False,
    ).annotate(
        confirmed_expected=Coalesce(Subquery(expected, output_field=MONEY), ZERO, output_field=MONEY),
        confirmed_received=Coalesce(Subquery(received, output_field=MONEY), ZERO, output_field=MONEY),
    )
    capped_expected = Least(Cast(F('quantity'), MONEY), F('confirmed_expected'), output_field=MONEY)
    lines = lines.annotate(shortage=Greatest(capped_expected - F('confirmed_received'), ZERO, output_field=MONEY))
    total = lines.order_by().values('shipment_id').annotate(
        amount=Sum(ExpressionWrapper(F('shortage') * F('unit_price'), output_field=MONEY))
    ).values('amount')
    decisions = ReceiptDifferenceDecision.objects.filter(tenant_id=OuterRef('tenant_id'), shipment_id=OuterRef('pk')).order_by().values('shipment_id').annotate(total=Sum('payable_delta')).values('total')
    return shipments.annotate(inbound_shortage_amount=Coalesce(Subquery(total, output_field=MONEY), ZERO), receipt_decision_delta=Coalesce(Subquery(decisions, output_field=MONEY), ZERO))
