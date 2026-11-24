from decimal import Decimal

import pytest

from apps.supply_chain.costs import shipment_receipt_adjustment
from apps.supply_chain.models import InboundLine, InboundOrder, ShipmentLine, SupplierShipment, domain_write
from apps.supply_chain.receipt_payable_adjustments import annotate_receipt_shortage
from tests.test_supply_chain_v2_costs import received_pilot
from tests.test_supply_chain_v2_foundation import world


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('first_received,second_expected,second_received', [
    (1, 3, 3),  # expected 2/1 then 3/3: cumulative source receipt is complete
    (3, 2, 1),  # expected 2/3 then 2/1: overreceipt offsets the later shortage
])
def test_partial_receipts_cap_cumulative_expected_before_subtracting_received(
        world, first_received, second_expected, second_received):
    buyer, _, shipment, _, inbound_id = received_pilot(world)
    line = shipment.lines.filter(is_active=True, unit_price__isnull=False).first()
    with domain_write():
        line.quantity = 4
        line.save()
        first = InboundLine.objects.get(inbound_id=inbound_id, shipment_line=line)
        first.expected_quantity = 2
        first.received_quantity = first_received
        first.save()
        inbound = first.inbound
        second = InboundOrder.objects.create(
            tenant=buyer.tenant, created_by=buyer, number=f'{inbound.number}-partial-2',
            batch=inbound.batch, receipt_mode='manual_partial', warehouse=inbound.warehouse,
            status='confirmed', stock_receipt_ref=f'{inbound.stock_receipt_ref}-2',
            confirmed_at=inbound.confirmed_at, confirmed_by=buyer,
        )
        InboundLine.objects.create(tenant=buyer.tenant, created_by=buyer, inbound=second,
            shipment_line=line, expected_quantity=second_expected,
            received_quantity=second_received)

    # The source cap is applied to cumulative expected quantities before receipts
    # are deducted: max(min(4, expected sum) - received sum, 0).
    expected_shortage = max(min(4, 2 + second_expected) - (first_received + second_received), 0)
    amount, details = shipment_receipt_adjustment(shipment)
    assert amount == Decimal(expected_shortage) * line.unit_price
    assert (details[0]['shortage_quantity'] if details else 0) == expected_shortage

    projected = annotate_receipt_shortage(SupplierShipment.objects.filter(pk=shipment.pk)).get()
    assert projected.inbound_shortage_amount == amount
