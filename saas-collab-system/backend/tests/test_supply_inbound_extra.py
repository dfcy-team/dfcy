from datetime import timedelta
from io import BytesIO
from decimal import Decimal

import pytest

from openpyxl import load_workbook

from apps.supply_chain.bigseller import export_inbound
from apps.supply_chain.dates import business_date
from apps.supply_chain.models import InboundOrder, InternalStockReceiptLine, SupplierProductPrice, domain_write
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_v2_logistics import BASE, arrive, checked, client, create, generate, setup, write


@pytest.mark.parametrize("price", [None, "2.1234", "0.0000"])
def test_extra_sku_is_received_without_mutating_source(world, price):
    buyer, shipment, _, carrier, warehouse = setup(world)
    api = client(buyer)
    batch, _ = create(api, [shipment], carrier)
    inbound = generate(api, arrive(api, batch), warehouse)
    inbound, _ = checked(api, inbound)
    extra = {'sku_id': world['sku_b'].pk, 'received_quantity': 3, 'difference_note': '到仓清点发现额外商品', 'unit_price': price}
    path = f"inbound-orders/{inbound['id']}/"
    sku = world['sku_b']
    sku.purchase_price = Decimal('8.0000')
    sku.save(update_fields=['purchase_price'])
    with domain_write():
        SupplierProductPrice.objects.create(
            tenant=world['tenant'], supplier=world['supplier_b'], sku=sku, created_by=buyer,
            unit_price=Decimal('90.0000'), effective_date=business_date() + timedelta(days=1),
            source_kind='manual',
        )
    fallback = api.get(BASE+path+'extra-skus/', {'search': 'SC2-SKU'})
    assert Decimal(fallback.data['data'][0]['reference_unit_price']) == Decimal('8.0000')
    with domain_write():
        SupplierProductPrice.objects.create(
            tenant=world['tenant'], supplier=world['supplier'], sku=sku, created_by=buyer,
            unit_price=Decimal('5.2500'), effective_date=business_date(),
            source_kind='manual',
        )
    options = api.get(BASE+path+'extra-skus/', {'search': 'SC2-SKU'})
    assert options.status_code == 200 and [row['id'] for row in options.data['data']] == [extra['sku_id']]
    assert Decimal(options.data['data'][0]['reference_unit_price']) == Decimal('5.2500')
    body = {'expected_version': inbound['version'], 'extra_lines': [extra]}
    invalid = write(api, path, {**body, 'extra_lines': [{**extra, 'sku_id': world['sku'].pk}]}, 'duplicate-source', 'patch')
    assert invalid.status_code in (400, 422)
    saved = write(api, path, body, 'save-extra', 'patch')
    assert saved.status_code == 200, saved.data
    data = saved.data['data']
    assert len(data['lines']) == len(inbound['lines'])
    assert data['extra_lines'][0]['received_quantity'] == 3
    assert not InternalStockReceiptLine.objects.exists()
    confirm = {'expected_version': data['version']}
    result = write(api, path+'confirm/', confirm, 'confirm-extra')
    assert result.status_code == 200, result.data
    entry = InternalStockReceiptLine.objects.get(sku=world['sku_b'])
    assert entry.inbound_line_id is None and entry.received_quantity == 3
    assert write(api, path+'confirm/', confirm, 'confirm-extra').status_code == 200
    assert InternalStockReceiptLine.objects.filter(sku=world['sku_b']).count() == 1
    listed = api.get(BASE+'inbound-orders/', {'search': world['sku_b'].sku_code}).data['data']
    assert len(listed) == 1 and listed[0]['received_quantity'] == inbound['received_quantity'] + 3
    assert listed[0]['received_amount_complete'] is (price is not None)
    expected_extra = Decimal(price) * 3 if price is not None else Decimal(0)
    assert Decimal(listed[0]['received_amount']) == Decimal(inbound['received_amount']) + expected_extra
    assert listed[0]['received_amount'] == result.data['data']['received_amount']
    obj = InboundOrder.objects.get(pk=inbound['id'])
    book = load_workbook(BytesIO(export_inbound(obj, sku_mode='current')), read_only=True)
    try:
        rows = list(book['SKU'].values)[1:]
        row = next(row for row in rows if row[1] == world['sku_b'].sku_code)
        assert row[2] == 3
        assert row[7] == (float(price) if price is not None else None)
    finally:
        book.close()
