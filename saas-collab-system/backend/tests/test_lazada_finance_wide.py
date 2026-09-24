from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from apps.finance.wide_service import build_lazada_finance_wide_rows


def _row(source_key, item_id, fee_name, amount):
    item = SimpleNamespace(
        external_line_id=item_id,
        seller_sku=f"SKU-{item_id}" if item_id else "",
        platform_variant_id=f"LZ-{item_id}" if item_id else "",
        raw_line_status="delivered",
        item_name_snapshot=f"Item {item_id}" if item_id else "",
    ) if item_id else None
    return SimpleNamespace(
        tenant_id=1,
        store_id=2,
        authorization_id=3,
        source_run_id=4,
        source_key=source_key,
        business_date=date(2026, 9, 1),
        currency="PHP",
        external_order_id="ORDER-1",
        external_order_item_id=item_id,
        seller_sku=item.seller_sku if item else "",
        platform_variant_id=item.platform_variant_id if item else "",
        raw_fee_name=fee_name,
        signed_amount=Decimal(amount),
        sales_order_item_id=1 if item else None,
        sales_order_item=item,
        store=SimpleNamespace(country_code="PH"),
    )


def test_order_level_fee_is_allocated_by_item_sales_and_reconciles():
    rows = [
        _row("sale-a", "ITEM-A", "Item Price Credit", "60"),
        _row("sale-b", "ITEM-B", "Item Price Credit", "40"),
        _row("commission", "", "Commission", "-10"),
        _row("unknown", "ITEM-A", "A New Lazada Fee", "-1"),
    ]

    result = sorted(build_lazada_finance_wide_rows(rows), key=lambda row: row["external_order_item_id"])

    assert len(result) == 2
    assert result[0]["commission"] == Decimal("-6.0000")
    assert result[1]["commission"] == Decimal("-4.0000")
    assert result[0]["other_fee"] == Decimal("-1.0000")
    assert result[0]["unknown_fee_names"] == ["A New Lazada Fee"]
    assert sum((row["net_income"] for row in result), Decimal("0")) == Decimal("89.0000")
