"""Supplier/carrier projections stay page-local and do not hydrate products."""
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.supply_chain import costs
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_v2_logistics import setup, client, create, arrive, generate, BASE


def test_supplier_columns_and_cost_parties_for_all_document_types(world):
    buyer, one, two, carrier, warehouse = setup(world, mixed_suppliers=True)
    api = client(buyer)
    batch, _ = create(api, [one, two], carrier)
    expected = 'Supplier A, Supplier B'
    assert batch['supplier_names'] == expected
    batch = arrive(api, batch)
    inbound = generate(api, batch, warehouse)
    assert inbound['supplier_names'] == expected
    for kind, number in [('batch', batch['number']), ('inbound', inbound['number'])]:
        response = api.get(BASE + 'cost-targets/', {'kind': kind})
        assert response.status_code == 200
        row = next(r for r in response.data['data'] if r['number'] == number)
        assert row['supplier_names'] == expected
        assert row['freight_company_names'] == carrier.name
    shipment_rows = api.get(BASE + 'cost-targets/', {'kind': 'shipment'}).data['data']
    assert {r['supplier_names'] for r in shipment_rows} == {'Supplier A', 'Supplier B'}
    assert all(r['freight_company_names'] == carrier.name for r in shipment_rows)
    assert api.get(BASE + 'dispatch-batches/').data['data'][0]['supplier_names'] == expected
    assert api.get(BASE + 'inbound-orders/').data['data'][0]['supplier_names'] == expected


def test_cost_party_projection_uses_one_query_for_entire_authorized_page(world):
    buyer, one, two, carrier, _ = setup(world, mixed_suppliers=True)
    create(client(buyer), [one, two], carrier)
    rows = list(costs.targets(buyer, 'shipment').order_by('pk'))
    with CaptureQueriesContext(connection) as queries:
        costs.prepare_target_parties('shipment', rows)
        data = [costs.target_data('shipment', row) for row in rows]
    assert len(queries) == 1
    assert len(data) == 2
    assert data[0]['supplier_names'] == 'Supplier A'
    assert data[1]['supplier_names'] == 'Supplier B'
    # No shipment line/product reads should be needed just to label the parties.
    assert 'supply_chain_shipmentline' not in queries[0]['sql'].lower()
