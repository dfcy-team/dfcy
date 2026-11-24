"""Partial receipts release costs against the complete dispatch plan."""
from decimal import Decimal
import pytest
from unittest.mock import patch

from django.test.utils import CaptureQueriesContext
from django.db import connection

from apps.masterdata.models import WarehouseMaster
from apps.supply_chain import costs, cost_ledger, inbound_costs
from apps.supply_chain.models import (CostAdjustment, InboundOrder, InboundLine,
    InternalStockReceipt, InternalStockReceiptLine, InboundShortageTermination, domain_write)
from tests.test_supply_chain_v2_foundation import world, freight
from tests.test_supply_chain_v2_costs import pilot, mark, fee, calculate
from tests.test_supply_chain_v2_logistics import create, arrive


def setup_batch(world):
    actor, api, shipment = pilot(world)
    shipment = mark(actor, shipment)
    fee(api, 'shipment', shipment, '6')
    shipment.refresh_from_db()
    data, _ = create(api, [shipment], freight(world))
    data = arrive(api, data)
    from apps.supply_chain.models import DispatchBatch
    batch = DispatchBatch.objects.get(pk=data['id'])
    fee(api, 'batch', batch.pk, '30', billed_cbm='1.500000')
    line = shipment.lines.get(sku=world['sku'])
    return actor, api, batch, line


def receipt(world, actor, batch, line, expected, actual, suffix):
    warehouse = WarehouseMaster.objects.create(tenant=world['tenant'], code='W'+suffix, name='Warehouse '+suffix, country_code='US')
    with domain_write():
        inbound = InboundOrder.objects.create(tenant=world['tenant'], created_by=actor, batch=batch,
            number='IN'+suffix, warehouse=warehouse, status='confirmed', receipt_mode='manual_partial', stock_receipt_ref='R'+suffix)
        source = InboundLine.objects.create(tenant=world['tenant'], created_by=actor, inbound=inbound,
            shipment_line=line, expected_quantity=expected, received_quantity=actual)
        stock = InternalStockReceipt.objects.create(tenant=world['tenant'], created_by=actor,
            inbound=inbound, warehouse=warehouse, receipt_ref='R'+suffix)
        entry = InternalStockReceiptLine.objects.create(tenant=world['tenant'], created_by=actor,
            receipt=stock, inbound_line=source, sku=line.sku, sku_code_snapshot=line.sku_code_snapshot, received_quantity=actual)
    return inbound, entry


def test_two_warehouses_overage_cannot_consume_later_plan(world):
    actor, api, batch, line = setup_batch(world)
    first, stock1 = receipt(world, actor, batch, line, 1, 2, '1')
    fee(api, 'inbound', first.pk, '2')
    one, _ = calculate(api, 'batch', batch.pk, key='one')
    second, stock2 = receipt(world, actor, batch, line, 3, 3, '2')
    fee(api, 'inbound', second.pk, '3')
    data, _ = calculate(api, 'batch', batch.pk, key='two')
    allocations = data['summary']['receipt_cost_allocations']
    assert [row['consumed_quantity'] for row in allocations] == [1, 3]
    assert [row['actual_quantity'] for row in allocations] == [2, 3]
    assert sum(Decimal(row['received_goods_amount']) for row in allocations) == Decimal('10')
    assert len({row['warehouse_id'] for row in allocations}) == 2
    assert not CostAdjustment.objects.filter(current_version_id=data['id']).exists()
    version = costs.CostVersion.objects.get(pk=data['id'])
    entries = list(cost_ledger.entries_for(actor))
    assert cost_ledger.fingerprints_for_entries(entries)[('batch', batch.pk)] == costs.inputs('batch', batch)[1]
    rows = cost_ledger.serialize_many(cost_ledger.filter_entries(cost_ledger.entries_for(actor), {'warehouse_id': first.warehouse_id}), {})
    assert len(rows) == 1 and rows[0]['received_quantity'] == 2
    assert rows[0]['received_goods_amount'] == '2.5000'
    assert rows[0]['received_unit_cost'] != data['entries'][0]['received_unit_cost']
    assert version.entries.get(shipment_line=line).receipt_line_id is None


def test_repeated_short_refill_and_explicit_loss(world):
    actor, api, batch, line = setup_batch(world)
    first, _ = receipt(world, actor, batch, line, 4, 1, 'short')
    fee(api, 'inbound', first.pk, '0')
    second, _ = receipt(world, actor, batch, line, 3, 1, 'refill')
    fee(api, 'inbound', second.pk, '0')
    before, _ = calculate(api, 'batch', batch.pk, key='before')
    assert before['summary']['consumed_quantity'] == 2
    with domain_write():
        InboundShortageTermination.objects.create(tenant=world['tenant'], created_by=actor,
            purchase_order=line.shipment.order, batch=batch, shipment_line=line, quantity=2,
            reason='Final shortage', request_key='close', origin='final_shortage')
    after, _ = calculate(api, 'batch', batch.pk, key='after')
    entry = next(row for row in after['entries'] if row['shipment_line_id'] == line.pk)
    assert entry['pending_total'] == '0.0000'
    assert Decimal(after['summary']['shortage_loss']) > 0
    assert Decimal(after['summary']['shipped_total']) + Decimal(after['summary']['clearance_fee']) == (
        Decimal(after['summary']['received_total']) + Decimal(after['summary']['pending_total']) + Decimal(after['summary']['shortage_loss']))


def test_zero_receipt_clearance_and_nonblocking_automatic_fallback(world):
    actor, api, batch, line = setup_batch(world)
    inbound, stock = receipt(world, actor, batch, line, 4, 0, 'zero')
    # Zero-quantity receipts retain their known clearance cost without releasing goods.
    fee(api, 'inbound', inbound.pk, '0', billed_cbm='1.000000')
    with patch.object(costs, 'fee_amounts', return_value={line.pk: Decimal('7')}):
        version = inbound_costs.estimate_for_inbound(actor, inbound)
    assert version.state == 'estimated'
    part = version.summary['receipt_cost_allocations'][0]
    assert part['received_goods_amount'] == '0.0000'
    assert part['clearance_fee'] == '7.0000'
    assert part['received_total'] == '7.0000'
    assert inbound_costs.estimate_for_inbound(actor, inbound).pk == version.pk
    other, _ = receipt(world, actor, batch, line, 4, 1, 'retry')
    with patch.object(costs, 'fee_amounts', side_effect=ValueError('stale remeasurement')):
        fallback = inbound_costs.estimate_for_inbound(actor, other)
    assert fallback.state == 'estimated'
    assert any('stale remeasurement' in issue for issue in fallback.issues)
    assert fallback.entries.get(shipment_line=line).goods_amount == Decimal('10')
    assert fallback.entries.get(shipment_line=line).received_total is None
    assert InternalStockReceiptLine.objects.filter(pk=stock.pk).exists()


def test_legacy_origin_does_not_generate_new_loss(world):
    actor, api, batch, line = setup_batch(world)
    inbound, _ = receipt(world, actor, batch, line, 4, 1, 'old')
    fee(api, 'inbound', inbound.pk, '0')
    with domain_write():
        InboundShortageTermination.objects.create(tenant=world['tenant'], created_by=actor,
            purchase_order=line.shipment.order, batch=batch, shipment_line=line, quantity=3,
            reason='Historical closed', request_key='old', origin='legacy_closed')
    data, _ = calculate(api, 'batch', batch.pk)
    assert data['summary']['shortage_loss'] == '0.0000'
    assert Decimal(next(row for row in data['entries'] if row['shipment_line_id'] == line.pk)['pending_total']) > 0


def test_rounding_and_per_receipt_overage_rules():
    assert inbound_costs.released(Decimal('1'), 0, 1, 3) == Decimal('.3333')
    assert inbound_costs.released(Decimal('1'), 1, 1, 3) == Decimal('.3334')
    assert inbound_costs.released(Decimal('1'), 2, 1, 3) == Decimal('.3333')
    assert inbound_costs.released(Decimal('100'), 0, min(12, 10), 100) == Decimal('10')
    assert inbound_costs.released(Decimal('100'), 10, min(90, 90), 100) == Decimal('90')

def test_manual_receipts_publish_each_warehouse_and_adjust_existing_receipt_only(world):
    from apps.products.models import ProductCostVersion
    actor, api, batch, line = setup_batch(world)
    first, stock1 = receipt(world, actor, batch, line, 1, 1, 'publish1')
    fee(api, 'inbound', first.pk, '1', billed_cbm='1.000000')
    first_version, _ = calculate(api, 'batch', batch.pk, key='first-confirmed')
    second, stock2 = receipt(world, actor, batch, line, 3, 3, 'publish2')
    fee(api, 'inbound', second.pk, '3', billed_cbm='1.000000')
    second_version, _ = calculate(api, 'batch', batch.pk, key='second-confirmed')
    assert second_version['calculated_status'] == 'confirmed'
    published = ProductCostVersion.objects.filter(sku=line.sku)
    assert set(published.values_list('warehouse_id', flat=True)) == {first.warehouse_id, second.warehouse_id}
    assert not CostAdjustment.objects.filter(current_version_id=second_version['id']).exists()
    fee(api, 'inbound', first.pk, '2', billed_cbm='1.000000', key='changed-clearance')
    changed, _ = calculate(api, 'batch', batch.pk, key='remeasure')
    adjustment = CostAdjustment.objects.get(current_version_id=changed['id'])
    assert adjustment.receipt_line_id == stock1.pk and adjustment.delta == Decimal('1')
    with CaptureQueriesContext(connection) as queries:
        fingerprints = cost_ledger.fingerprints_for_entries(cost_ledger.entries_for(actor))
    assert fingerprints[('batch', batch.pk)] == costs.inputs('batch', batch)[1]
    assert len(queries) <= 45


def test_legacy_snapshot_fallback_and_fingerprint_preserved(world):
    actor, api, batch, line = setup_batch(world)
    inbound, stock = receipt(world, actor, batch, line, 4, 3, 'legacy')
    with domain_write():
        inbound.receipt_mode = 'legacy_full'
        inbound.save(update_fields=['receipt_mode'])
    other = line.shipment.lines.exclude(pk=line.pk).get()
    with domain_write():
        source = InboundLine.objects.create(tenant=world['tenant'], created_by=actor, inbound=inbound, shipment_line=other, expected_quantity=other.quantity, received_quantity=0)
        InternalStockReceiptLine.objects.create(tenant=world['tenant'], created_by=actor, receipt=stock.receipt, inbound_line=source, sku=other.sku, sku_code_snapshot=other.sku_code_snapshot, received_quantity=0)
    fee(api, 'inbound', inbound.pk, '1', billed_cbm='1.000000')
    before = costs.inputs('batch', batch)
    assert 'inbound' in before[0] and 'inbounds' not in before[0]
    data, _ = calculate(api, 'batch', batch.pk, key='legacy-cost')
    assert set(data['summary']) == {'shipped_quantity', 'received_quantity', 'shipped_total', 'received_total', 'pending_total'}
    version = costs.CostVersion.objects.get(pk=data['id'])
    parts = inbound_costs.receipt_allocations(version)
    assert len(parts) == 2 and parts[0]['receipt_line_id'] == stock.pk
    with domain_write():
        InboundShortageTermination.objects.create(tenant=world['tenant'], created_by=actor,
            purchase_order=line.shipment.order, batch=batch, shipment_line=line, quantity=1,
            reason='Historical closed', request_key='legacy-closed', origin='legacy_closed')
    assert costs.inputs('batch', batch)[1] == before[1]
    assert cost_ledger.fingerprints_for_entries(cost_ledger.entries_for(actor))[('batch', batch.pk)] == before[1]

@pytest.mark.parametrize("with_domestic_expense", [False, True])
def test_twenty_owner_fingerprints_use_bounded_queries_and_shared_serializer(world, with_domestic_expense):
    from apps.supply_chain.models import DispatchBatch, DispatchMembership, DispatchAllocation, CostEntry, CostVersion
    actor, api, batch, line = setup_batch(world)
    with domain_write():
        line.quantity = 100
        line.save()
        for index in range(20):
            owner = DispatchBatch.objects.create(tenant=world['tenant'], created_by=actor,
                number=f'PAGE-{index}', country=batch.country, country_code_snapshot=batch.country_code_snapshot,
                freight_company=batch.freight_company, freight_number=f'PAGE-{index}', creation_key=f'page-{index}', request_hash='a'*64)
            membership = DispatchMembership.objects.create(tenant=world['tenant'], created_by=actor, batch=owner, shipment=line.shipment)
            DispatchAllocation.objects.create(tenant=world['tenant'], created_by=actor, membership=membership, shipment_line=line, quantity=4)
            version = CostVersion.objects.create(tenant=world['tenant'], created_by=actor, batch=owner,
                sequence=1, state='estimated', stage='shipped', input_fingerprint='a'*64, source_snapshot={'kind': 'batch'}, summary={'shipped_quantity': 4},
                creation_key=f'page-cost-{index}', request_hash='a'*64)
            CostEntry.objects.create(tenant=world['tenant'], created_by=actor, cost_version=version, shipment_line=line, quantity=4)
    if with_domestic_expense:
        from apps.supply_chain import domestic_expenses
        line.shipment.refresh_from_db()
        domestic_expenses.save(actor, line.shipment_id, {'expected_version': line.shipment.version, 'lines': [
            {'name': 'query-bound expense', 'amount': '1', 'currency': 'CNY', 'payee_type': 'supplier',
             'payee_id': world['supplier_b'].pk, 'include_in_cost': True, 'method': 'quantity'}]}, 'query-bound-expense')
    entries = list(CostEntry.objects.filter(cost_version__creation_key__startswith='page-cost-').select_related('cost_version__batch'))
    assert len({entry.cost_version.batch_id for entry in entries}) == 20
    with CaptureQueriesContext(connection) as queries:
        fingerprints = cost_ledger.fingerprints_for_entries(entries)
    assert len(queries) <= 12
    assert len(fingerprints) == 20
    for entry in entries:
        owner = entry.cost_version.batch
        assert fingerprints[('batch', owner.pk)] == costs.inputs('batch', owner)[1]
