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
        assert row['document_time']
    shipment_rows = api.get(BASE + 'cost-targets/', {'kind': 'shipment'}).data['data']
    assert {r['supplier_names'] for r in shipment_rows} == {'Supplier A', 'Supplier B'}
    assert all(r['freight_company_names'] == carrier.name for r in shipment_rows)
    assert all(r['document_time'] for r in shipment_rows)
    assert api.get(BASE + 'dispatch-batches/').data['data'][0]['supplier_names'] == expected
    assert api.get(BASE + 'inbound-orders/').data['data'][0]['supplier_names'] == expected


def test_cost_party_and_source_projection_uses_two_queries_for_entire_authorized_page(world):
    buyer, one, two, carrier, _ = setup(world, mixed_suppliers=True)
    create(client(buyer), [one, two], carrier)
    rows = list(costs.targets(buyer, 'shipment').order_by('pk'))
    with CaptureQueriesContext(connection) as queries:
        costs.prepare_target_parties('shipment', rows)
        data = [costs.target_data('shipment', row) for row in rows]
    # Multi-PO source links require one page-wide source query in addition to
    # the existing carrier projection; neither query is repeated per shipment.
    assert len(queries) == 2
    assert len(data) == 2
    assert data[0]['supplier_names'] == 'Supplier A'
    assert data[1]['supplier_names'] == 'Supplier B'
    for obj, projected in zip(rows, data):
        assert any(link['href'] == f'/supply-chain/purchase-orders?order_id={obj.order_id}'
                   for link in projected['source_links'])
    source_queries = [q['sql'].lower() for q in queries if 'supply_chain_shipmentline' in q['sql'].lower()]
    assert len(source_queries) == 1
    assert all('products_productsku' not in q['sql'].lower() for q in queries)
    assert all('products_productspu' not in q['sql'].lower() for q in queries)
