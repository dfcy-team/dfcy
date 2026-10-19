from rest_framework.test import APIClient

from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_v2_logistics import BASE, setup


def test_candidates_and_split_batch_return_shipment_and_allocation_quantities(world):
    buyer, shipment, _, carrier, _ = setup(world)
    api = APIClient()
    api.force_authenticate(user=buyer)

    candidate = next(row for row in api.get(BASE + 'dispatch-candidates/').data['data'] if row['id'] == shipment.pk)
    source = candidate['lines'][0]
    shipment_quantity = shipment.lines.get(is_active=True).quantity
    assert source['quantity'] == shipment_quantity
    assert source['allocated_quantity'] == 0
    assert source['remaining_quantity'] == shipment_quantity

    line = shipment.lines.get(is_active=True)
    batch_quantity = min(3, line.quantity)
    response = api.post(BASE + 'dispatch-batches/', {
        'shipment_ids': [shipment.pk], 'shipment_versions': [{'id': shipment.pk, 'version': shipment.version}],
        'allocations': [{'shipment_line_id': line.pk, 'quantity': batch_quantity}],
        'freight_company_id': carrier.pk, 'freight_number': 'QTY-1',
    }, format='json', HTTP_IDEMPOTENCY_KEY='quantity-details')
    assert response.status_code == 201, response.data
    batch = response.data['data']

    detail = api.get(BASE + f"dispatch-batches/{batch['id']}/").data['data']
    line = detail['shipments'][0]['lines'][0]
    assert line['source_quantity'] == shipment_quantity
    assert line['allocated_quantity'] == batch_quantity
    assert line['remaining_quantity'] == shipment_quantity - batch_quantity
    assert line['current_batch_quantity'] == batch_quantity
