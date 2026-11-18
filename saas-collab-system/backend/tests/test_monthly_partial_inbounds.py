from apps.supply_chain.models import InboundShortageTermination, domain_write
from tests.test_partial_inbound_costs import receipt, setup_batch
from tests.test_supply_chain_v2_foundation import world


def test_monthly_drilldown_retains_each_receipt_and_unreceived_balance(world):
    actor, api, batch, line = setup_batch(world)
    first, _ = receipt(world, actor, batch, line, 2, 1, 'monthly-one')
    second, _ = receipt(world, actor, batch, line, 2, 1, 'monthly-two')
    path = '/api/internal/supply-chain/v2/monthly-payables/shipment-drilldown/'
    response = api.get(path, {'shipment_id':line.shipment_id,'month':'2026-10'})
    assert response.status_code == 200, response.data
    data = response.data['data']
    row = next(row for row in data['shipment']['lines'] if row['id'] == line.pk)
    assert row['received_quantity'] == 2 and row['pending_quantity'] == 2
    target = next(row for row in data['batches'] if row['id'] == batch.pk)
    assert {doc['id'] for doc in target['inbounds']} == {first.pk,second.pk}
    assert target['inbound'] is None
    with domain_write():
        InboundShortageTermination.objects.create(tenant=actor.tenant,created_by=actor,
            purchase_order=line.shipment.order, batch=batch, shipment_line=line, quantity=2,
            reason='confirmed final shortage', request_key='monthly-close')
    data = api.get(path, {'shipment_id':line.shipment_id,'month':'2026-10'}).data['data']
    row = next(row for row in data['shipment']['lines'] if row['id'] == line.pk)
    assert row['pending_quantity'] == 0 and row['difference_quantity'] == -2
