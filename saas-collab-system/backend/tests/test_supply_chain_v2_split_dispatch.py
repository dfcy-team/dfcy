from decimal import Decimal

from apps.supply_chain import services, shipments, dispatch_allocations
from apps.supply_chain.models import DispatchBatch, DispatchAllocation
from tests.test_supply_chain_v2_foundation import world, internal_user, confirmed_order, shipment_payload, freight
from tests.test_supply_chain_v2_logistics import client, write, arrive, generate, BASE
from tests.test_supply_chain_v2_costs import mark, fee, calculate, get
from apps.masterdata.models import WarehouseMaster


def setup(world):
    buyer = internal_user(world)
    shipment = services.create_supplier_shipment(buyer, shipment_payload(world, confirmed_order(world, buyer), 'split',
        lines=[{'sku_id': world['sku'].pk, 'quantity': 100}]), idempotency_key='split')
    return buyer, client(buyer), shipment, freight(world)


def create_part(api, shipment, carrier, qty, key):
    shipment.refresh_from_db()
    return write(api, 'dispatch-batches/', {
        'shipment_ids': [shipment.pk], 'shipment_versions': [{'id': shipment.pk, 'version': shipment.version}],
        'allocations': [{'shipment_line_id': shipment.lines.get().pk, 'quantity': qty}],
        'freight_company_id': carrier.pk, 'freight_number': key}, key)


def test_split_capacity_edit_release_and_cancel(world):
    buyer, api, shipment, carrier = setup(world)
    first = create_part(api, shipment, carrier, 60, 'first')
    assert first.status_code == 201, first.data
    a = first.data['data']
    assert a['shipments'][0]['lines'][0]['quantity'] == 60
    assert a['shipments'][0]['lines'][0]['source_quantity'] == 100
    assert a['shipments'][0]['allocation_lines'][0]['quantity'] == 100
    assert a['shipments'][0]['allocation_lines'][0]['current_batch_quantity'] == 60
    assert api.get(BASE + 'dispatch-candidates/').data['count'] == 1
    assert create_part(api, shipment, carrier, 41, 'excess').status_code == 422
    b = create_part(api, shipment, carrier, 40, 'second').data['data']
    assert api.get(BASE + 'dispatch-candidates/').data['count'] == 0
    projection = shipments.snapshot(shipment)
    assert projection['logistics_stage'] == 'split'
    assert sorted(g['quantity'] for g in projection['dispatch_allocations']) == [40, 60]
    shipment.refresh_from_db()
    response = write(api, f"dispatch-batches/{a['id']}/members/", {'expected_version': a['version'],
        'reason': '分两批后调整装载', 'shipment_ids': [shipment.pk],
        'shipment_versions': [{'id': shipment.pk, 'version': shipment.version}],
        'allocations': [{'shipment_line_id': shipment.lines.get().pk, 'quantity': 50}]}, 'reduce')
    assert response.status_code == 200, response.data
    assert shipments.snapshot(shipment)['remaining_quantity'] == 10
    assert write(api, f"dispatch-batches/{b['id']}/cancel/", {'expected_version': b['version'], 'reason': '取消第二批'}, 'cancel').status_code == 200
    assert shipments.snapshot(shipment)['remaining_quantity'] == 50
    assert DispatchAllocation.objects.count() == 3  # historical reservation remains


def test_split_inbound_and_cost_quantity_and_fee_conservation(world):
    buyer, api, shipment, carrier = setup(world)
    sku = world['sku']; sku.package_volume = Decimal('.1'); sku.save()
    shipment = mark(buyer, shipment)
    fee(api, 'shipment', shipment, '0.0001')
    a = create_part(api, shipment, carrier, 60, 'a').data['data']
    b = create_part(api, shipment, carrier, 40, 'b').data['data']
    assert not get(api, 'shipment', shipment)['target']['calculation_allowed']
    warehouse = WarehouseMaster.objects.create(tenant=world['tenant'], code='split-wh', name='Split', country_code='US')
    totals = []
    for batch, qty in [(a, 60), (b, 40)]:
        batch = arrive(api, batch)
        inbound = generate(api, batch, warehouse)
        assert inbound['lines'][0]['expected_quantity'] == qty
        fee(api, 'batch', batch['id'], '0')
        result, _ = calculate(api, 'batch', batch['id'])
        entry = result['entries'][0]
        assert entry['quantity'] == qty
        assert Decimal(entry['goods_amount']) == Decimal('2.5') * qty
        totals.append(Decimal(entry['collection_fee']))
    assert sum(totals) == Decimal('0.0001')
    from apps.supply_chain.cost_ledger import entries_for
    entries = list(entries_for(buyer))
    assert len(entries) == 2 and sum(row.quantity for row in entries) == 100
    assert sum(row.goods_amount for row in entries) == Decimal('250')
    fee(api, 'shipment', shipment, '0.0003')
    revised = []
    for batch in (a, b):
        assert get(api, 'batch', batch['id'])['latest_cost']['status'] == 'recalculation_required'
        version, _ = calculate(api, 'batch', batch['id'])
        revised.append(Decimal(version['entries'][0]['collection_fee']))
    assert sum(revised) == Decimal('0.0003')
    assert sum(dispatch_allocations.batch_quantities(batch).get(shipment.lines.get().pk, 0) for batch in DispatchBatch.objects.all()) == 100


def test_migration_backfills_existing_full_shipments(world):
    from importlib import import_module
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    buyer, api, shipment, carrier = setup(world)
    # Historical model managers bypass runtime service guards as migration models do.
    from django.test import override_settings
    with override_settings(MIGRATION_MODULES={}):
        state = MigrationExecutor(connection).loader.project_state([('supply_chain', '0026_dispatch_line_allocations')]).apps
    Batch = state.get_model('supply_chain', 'DispatchBatch')
    Member = state.get_model('supply_chain', 'DispatchMembership')
    batch = Batch.objects.create(tenant_id=buyer.tenant_id, created_by_id=buyer.pk, number='legacy-batch',
        country_id=shipment.order.country_id, country_code_snapshot='US', freight_company_id=carrier.pk,
        freight_number='legacy', creation_key='legacy', request_hash='a'*64)
    member = Member.objects.create(tenant_id=buyer.tenant_id, created_by_id=buyer.pk, batch_id=batch.pk, shipment_id=shipment.pk)
    module = import_module('apps.supply_chain.migrations.0026_dispatch_line_allocations')
    module.backfill(state, type('Editor', (), {'connection': connection})())
    row = DispatchAllocation.objects.get(membership_id=member.pk)
    assert row.quantity == 100 and row.shipment_line_id == shipment.lines.get().pk


def test_rejected_duplicate_or_foreign_allocation_has_no_partial_write(world):
    buyer, api, shipment, carrier = setup(world)
    line = shipment.lines.get()
    body = {'shipment_ids': [shipment.pk], 'shipment_versions': [{'id': shipment.pk, 'version': shipment.version}],
        'freight_company_id': carrier.pk, 'freight_number': 'bad',
        'allocations': [{'shipment_line_id': line.pk, 'quantity': 50}, {'shipment_line_id': line.pk, 'quantity': 50}]}
    assert write(api, 'dispatch-batches/', body, 'duplicate-line').status_code == 422
    body['allocations'] = [{'shipment_line_id': line.pk + 999, 'quantity': 1}]
    assert write(api, 'dispatch-batches/', body, 'foreign-line').status_code == 422
    assert not DispatchBatch.objects.exists() and not DispatchAllocation.objects.exists()


def test_supplier_tracking_discloses_only_own_allocated_lines(world):
    from tests.test_supply_chain_v2_logistics import setup as mixed_setup, create
    buyer, one, two, carrier, warehouse = mixed_setup(world, mixed_suppliers=True)
    api = client(buyer)
    batch, _ = create(api, [one, two], carrier)
    data = shipments.snapshot(one)
    assert data['dispatch_allocations'][0]['quantity'] == one.lines.get().quantity
    assert data['dispatch_allocations'][0]['lines'] == [{'shipment_line_id': one.lines.get().pk, 'quantity': one.lines.get().quantity}]
    assert all('unit_price' not in row for row in data['lines'])


def test_contract_reports_quantity_based_dispatch():
    from apps.supply_chain.contracts import CONTRACT
    assert CONTRACT['invariants']['active_batches_per_shipment'] is None
    assert CONTRACT['invariants']['allocated_quantity_lte_shipped'] is True
    assert CONTRACT['capabilities']['predeparture_dispatch_quantity_adjustment'] is True
