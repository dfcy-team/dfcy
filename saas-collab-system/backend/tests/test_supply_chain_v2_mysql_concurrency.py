"""Real MySQL transaction checks for the replacement supply workflow."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connection

from apps.accounts.models import CustomUser
from apps.masterdata.models import WarehouseMaster
from apps.supply_chain.models import DispatchMembership, InternalStockReceipt, CostVersion
from tests.test_supply_chain_v2_foundation import world, freight
from tests.test_supply_chain_v2_costs import pilot, received_pilot, get, mark
from tests.test_supply_chain_v2_logistics import client, create, arrive, generate, checked, BASE

pytestmark = [pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != 'mysql', reason='Requires real MySQL row locks.')]


def race(user_id, path, payload, keys):
    barrier = Barrier(2)
    def run(key):
        close_old_connections()
        try:
            user = CustomUser.objects.get(pk=user_id)
            api = client(user)
            barrier.wait(timeout=20)
            response = api.post(BASE+path, payload, format='json', HTTP_IDEMPOTENCY_KEY=key)
            return response.status_code, response.data
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, key) for key in keys]
        return [future.result(timeout=60) for future in futures]


def test_mysql_concurrent_dispatch_has_one_active_membership(world):
    buyer, api, shipment = pilot(world)
    carrier = freight(world)
    body = {'freight_company_id': carrier.pk, 'freight_number': 'MYSQL-ONE',
        'shipment_ids': [shipment.pk], 'shipment_versions': [{'id': shipment.pk, 'version': shipment.version}], 'notes': ''}
    responses = race(buyer.pk, 'dispatch-batches/', body, ['dispatch-a', 'dispatch-b'])
    assert sorted(status for status, _ in responses) == [201, 422], responses
    assert DispatchMembership.objects.filter(shipment=shipment, active_guard=True).count() == 1


def test_mysql_concurrent_same_dispatch_key_replays_once(world):
    buyer, api, shipment = pilot(world)
    carrier = freight(world)
    body = {'freight_company_id': carrier.pk, 'freight_number': 'MYSQL-REPLAY',
        'shipment_ids': [shipment.pk], 'shipment_versions': [{'id': shipment.pk, 'version': shipment.version}], 'notes': ''}
    responses = race(buyer.pk, 'dispatch-batches/', body, ['dispatch-same', 'dispatch-same'])
    assert [status for status, _ in responses] == [201, 201], responses
    assert len({body['data']['id'] for _, body in responses}) == 1
    assert DispatchMembership.objects.filter(shipment=shipment, active_guard=True).count() == 1


def test_mysql_duplicate_inbound_confirmation_has_one_receipt(world):
    buyer, api, shipment = pilot(world)
    batch, _ = create(api, [shipment], freight(world))
    batch = arrive(api, batch)
    warehouse = WarehouseMaster.objects.create(tenant=world['tenant'], code='MYSQL-WH', name='MySQL QA', country_code='US')
    inbound = generate(api, batch, warehouse)
    inbound, _ = checked(api, inbound, quantities=[4, 2])
    responses = race(buyer.pk, f"inbound-orders/{inbound['id']}/confirm/",
                     {'expected_version': inbound['version']}, ['inbound-same', 'inbound-same'])
    assert [status for status, _ in responses] == [200, 200], responses
    assert InternalStockReceipt.objects.filter(inbound_id=inbound['id']).count() == 1


def test_mysql_same_cost_key_preserves_one_version(world):
    buyer, api, shipment, batch_id, _ = received_pilot(world)
    context = get(api, 'batch', batch_id)
    body = {'expected_source_version': context['target']['calculation_version'],
            'expected_input_fingerprint': context['input_fingerprint']}
    responses = race(buyer.pk, f'costs/batch/{batch_id}/calculate/', body, ['cost-same', 'cost-same'])
    assert [status for status, _ in responses] == [200, 200], responses
    assert CostVersion.objects.filter(batch_id=batch_id).count() == 1
