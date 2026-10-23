import pytest

from apps.sales_management.operating_models import OperatingOrder
from tests.test_replenishment_strategy_flow import configured, order_body, preview, client
from tests.test_supply_chain_v2_foundation import world


def test_manual_quantity_adjustment_requires_and_snapshots_reason(world, configured):
    actor, strategy, _ = configured
    api = client(actor)
    result = preview(api, world, strategy).data['data']
    suggested = result['lines'][0]['suggested_quantity']
    body = order_body(world, result['preview_token'], quantity=suggested + 1)
    body['notes'] = ''
    rejected = api.post('/api/internal/commerce/operating-orders/', body, format='json',
        HTTP_IDEMPOTENCY_KEY='adjustment-without-reason')
    assert rejected.status_code == 422
    assert OperatingOrder.objects.count() == 0

    body['notes'] = '根据促销备货计划手工增加 1 件'
    saved = api.post('/api/internal/commerce/operating-orders/', body, format='json',
        HTTP_IDEMPOTENCY_KEY='adjustment-with-reason')
    assert saved.status_code == 201, saved.data
    assert saved.data['data']['calculation_snapshot']['operator_adjustment_reason'] == body['notes']
