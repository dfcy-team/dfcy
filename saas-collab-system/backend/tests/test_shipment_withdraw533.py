from apps.supply_chain.models import BusinessEvent
from tests.test_supply_chain_v2_foundation import world, internal_user, confirmed_order
from tests.test_supply_chain_v2_shipments import INTERNAL, buyer_client, draft, upload, write


def test_withdraw_reopen_resubmit_keeps_quantity_and_audit(world):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    api = buyer_client(buyer)
    root = INTERNAL + 'supplier-shipments/'
    shipment = upload(api, root, draft(api, INTERNAL, world, order, quantity=8))
    submitted = write(api, root + f"{shipment['id']}/submit/",
                      {'expected_version': shipment['version']}, 'withdraw-initial-submit')
    assert submitted.status_code == 200, submitted.data
    shipment = submitted.data['data']
    body = {'expected_version': shipment['version'], 'reason': 'correct packing details'}
    path = root + f"{shipment['id']}/withdraw/"
    withdrawn = write(api, path, body, 'withdraw-once')
    assert withdrawn.status_code == 200, withdrawn.data
    assert withdrawn.data['data']['status'] == 'draft'
    version = withdrawn.data['data']['version']
    assert version > shipment['version']
    assert write(api, path, body, 'withdraw-once').status_code == 200
    assert write(api, path, body, 'withdraw-stale').status_code == 422
    reopened = api.get(root + f"{shipment['id']}/")
    assert reopened.status_code == 200, reopened.data
    assert reopened.data['data']['lines'][0]['quantity'] == 8
    resubmitted = write(api, root + f"{shipment['id']}/submit/",
                        {'expected_version': version}, 'withdraw-resubmit')
    assert resubmitted.status_code == 200, resubmitted.data
    assert resubmitted.data['data']['lines'][0]['excess_quantity'] == 0
    event = BusinessEvent.objects.get(tenant=buyer.tenant, aggregate_id=shipment['id'],
                                     action='shipment_withdrawn')
    assert event.payload['reason'] == body['reason']
