import pytest
from rest_framework.test import APIClient

from apps.permissions.models import DataScope
from apps.supply_chain.cost_models import PaymentRecord
from apps.supply_chain.models import BusinessEvent
from apps.supply_chain import services
from apps.tenants.models import Tenant
from apps.supply_chain.payment_item_models import PaymentItem
from tests.test_supply_chain_v2_costs import pilot
from tests.test_supply_chain_v2_foundation import internal_user, world
from tests.test_supply_chain_v2_logistics import BASE

pytestmark = pytest.mark.django_db


def test_choice_is_selection_only_scoped_and_uses_seed_version(world):
    buyer, api, shipment = pilot(world)
    with services.domain_write():
        seed = services._event(buyer, shipment, 'count_difference_case_seeded', 'choice-seed',
            {'source_purchase_id': shipment.order_id, 'source_shipment_id': shipment.pk,
             'source_purchase': 'PO source', 'source_shipment': shipment.number})
    path = BASE + 'count-difference-choices/'
    assert api.get(path).status_code == 200
    readonly = internal_user(world, 'choice-viewer', codes=('supply.v2.view',))
    readonly_api = APIClient(); readonly_api.force_authenticate(user=readonly)
    listed = readonly_api.get(path)
    assert listed.status_code == 200, listed.data
    row = listed.data['data'][0]
    assert row['event_id'] == seed.pk and row['option'] == 'pending_review'

    payload = {'source_purchase_id': shipment.order_id, 'source_shipment_id': shipment.pk,
               'option': 'supplier_waived', 'notes': '双方确认免补', 'expected_event_id': seed.pk}
    denied = readonly_api.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='choice-readonly')
    assert denied.status_code in (403, 404)
    foreign_world = {**world, 'tenant': Tenant.objects.create(code='choice-foreign', name='Other tenant')}
    foreign = internal_user(foreign_world, 'choice-foreign-user')
    foreign_api = APIClient(); foreign_api.force_authenticate(user=foreign)
    assert foreign_api.get(path).data['data'] == []
    assert foreign_api.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='choice-foreign').status_code == 404
    saved = api.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='choice-save')
    assert saved.status_code == 201, saved.data
    assert saved.data['data']['selection_only'] is True
    assert PaymentRecord.objects.count() == 0 and PaymentItem.objects.count() == 0

    stale = {**payload, 'option': 'return_goods', 'expected_event_id': seed.pk}
    assert api.post(path, stale, format='json', HTTP_IDEMPOTENCY_KEY='choice-stale').status_code == 400
    changed_replay = {**payload, 'option': 'return_goods', 'expected_event_id': saved.data['data']['event_id']}
    assert api.post(path, changed_replay, format='json', HTTP_IDEMPOTENCY_KEY='choice-save').status_code == 422
    replay = api.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='choice-save')
    assert replay.status_code == 200 and replay.data['data']['event_id'] == saved.data['data']['event_id']
    current = api.get(path).data['data'][0]
    assert current['option'] == 'supplier_waived'
