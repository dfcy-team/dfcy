from django.db import connection
from django.test.utils import CaptureQueriesContext
from apps.supply_chain import services, shipments, logistics
from apps.supply_chain.models import SupplierShipment, DispatchBatch
from apps.supply_chain.read_batches import prepare_shipments, prepare_batches
from tests.test_supply_chain_v2_foundation import world, internal_user, confirmed_order, shipment_payload, freight
from tests.test_supply_chain_v2_logistics import client, write, BASE


def test_prepared_snapshots_match_and_queries_do_not_grow_per_shipment(world):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    for n in range(12):
        services.create_supplier_shipment(buyer, shipment_payload(world,order,str(n),number=f'SHIP-{n}'),idempotency_key=str(n))
    def render(limit, internal=True):
        with CaptureQueriesContext(connection) as queries:
            rows = list(SupplierShipment.objects.filter(tenant=buyer.tenant).select_related('order__supplier').order_by('pk')[:limit])
            prepare_shipments(rows)
            data = [shipments.snapshot(row,internal=internal) for row in rows]
        return data,len(queries)
    small, small_count = render(1)
    full, full_count = render(12)
    assert full_count <= small_count + 1
    assert full_count <= 8
    original = [shipments.snapshot(row,internal=True) for row in SupplierShipment.objects.order_by('pk')]
    assert original == full
    external, _ = render(12,internal=False)
    assert all('unit_price' not in line for row in external for line in row['lines'])


def test_batch_list_matches_detail_payload_with_bounded_queries(world):
    buyer = internal_user(world)
    order = confirmed_order(world,buyer)
    carrier = freight(world)
    for n in range(5):
        shipment=services.create_supplier_shipment(buyer,shipment_payload(world,order,str(n),number=f'SH-{n}'),idempotency_key=str(n))
        services.create_dispatch_batch(buyer,{'shipment_ids':[shipment.pk],'freight_company_id':carrier.pk,'freight_number':str(n)},idempotency_key=f'batch-{n}')
    expected=[logistics.batch_data(row) for row in DispatchBatch.objects.order_by('pk')]
    with CaptureQueriesContext(connection) as queries:
        rows=list(DispatchBatch.objects.select_related('freight_company','planned_warehouse').order_by('pk'))
        prepare_batches(rows)
        actual=[logistics.batch_data(row) for row in rows]
    assert actual == expected
    assert len(queries) <= 11
    response=client(buyer).get(BASE+'dispatch-batches/',{'limit':20})
    assert response.status_code == 200
    assert len(response.data['data']) == 5
