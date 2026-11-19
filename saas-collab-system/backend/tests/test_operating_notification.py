from unittest.mock import patch
import pytest
from apps.sales_management import operating
from apps.sales_management.operating_models import OperatingOrder
from apps.supply_chain.operating_notifications import enqueue_confirmed, CODE
from tests.test_supply_chain_v2_foundation import world
from tests.test_operating_orders_v2 import operator, client, write, OPS


@pytest.mark.django_db
def test_confirm_enqueues_once_and_replay_does_not_enqueue_again(world):
    user = operator(world)
    response = write(client(user), OPS, {
        'country_id': world['country'].pk, 'source_kind': 'new_goods',
        'lines': [{'sku_id': world['sku'].pk, 'quantity': 10}], 'notes': '',
    }, 'notification-order')
    assert response.status_code == 201, response.data
    data = response.data['data']
    with patch('apps.supply_chain.operating_notifications.enqueue_confirmed') as enqueue:
        payload = {'expected_version': data['version']}
        first = write(client(user), OPS + f"{data['id']}/submit/", payload, 'notification-confirm')
        second = write(client(user), OPS + f"{data['id']}/submit/", payload, 'notification-confirm')
    assert first.status_code == second.status_code == 200
    assert enqueue.call_count == 1
    assert OperatingOrder.objects.get(pk=data['id']).status == 'submitted'


def test_enqueue_uses_order_key_and_personal_delivery():
    from types import SimpleNamespace
    order = SimpleNamespace(pk=55, tenant_id=3)
    rule = SimpleNamespace(pk=7)
    with patch('apps.supply_chain.operating_notifications.FeishuConfigRule.objects.filter') as query, patch('apps.supply_chain.operating_notifications.enqueue_rule') as enqueue:
        query.return_value.first.return_value = rule
        enqueue_confirmed(order)
        assert query.call_args.kwargs == {'tenant_id': 3, 'kind': 'notification', 'code': CODE, 'enabled': True}
        assert enqueue.call_args.kwargs['key'] == 'operating-order:55:submitted'
        assert enqueue.call_args.kwargs['payload'] == {'operating_order_id': 55}
