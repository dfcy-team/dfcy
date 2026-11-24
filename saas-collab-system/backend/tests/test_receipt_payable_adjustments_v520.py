from decimal import Decimal
from types import SimpleNamespace

from apps.supply_chain.costs import shipment_receipt_adjustment


def test_confirmed_receipt_shortage_is_capped_by_shipment_quantity_and_priced():
    shipment = SimpleNamespace(
        _receipt_adjustment=None,
        _receipt_lines=[
            SimpleNamespace(pk=11, quantity=Decimal('10'), unit_price=Decimal('2.50'),
                            sku_code_snapshot='SKU-A'),
            SimpleNamespace(pk=12, quantity=Decimal('4'), unit_price=Decimal('3.00'),
                            sku_code_snapshot='SKU-B'),
        ],
        _receipt_rows=[
            SimpleNamespace(shipment_line_id=11, expected_quantity=Decimal('12'),
                            received_quantity=Decimal('7')),
            SimpleNamespace(shipment_line_id=12, expected_quantity=Decimal('4'),
                            received_quantity=Decimal('1')),
        ],
    )

    amount, details = shipment_receipt_adjustment(shipment)

    # Only ten units were billed for SKU-A; seven received leaves three,
    # even when cumulative partial-receipt expectations add up to twelve.
    assert amount == Decimal('16.5000')
    assert [(row['shipment_line_id'], row['shortage_quantity'], row['amount']) for row in details] == [
        (11, Decimal('3'), '7.5000'), (12, Decimal('3'), '9.0000')
    ]


def test_no_confirmed_shortage_rows_means_no_deduction():
    shipment = SimpleNamespace(
        _receipt_adjustment=None,
        _receipt_lines=[SimpleNamespace(pk=11, quantity=Decimal('10'),
                                        unit_price=Decimal('2.50'), sku_code_snapshot='SKU-A')],
        _receipt_rows=[],
    )

    assert shipment_receipt_adjustment(shipment) == (Decimal('0'), [])
