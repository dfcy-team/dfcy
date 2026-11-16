from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.adapters import MarketplaceRefundAdapter
from apps.integrations.return_logistics import lazada_return_logistics, tiktok_return_logistics
from apps.sales_management.aftersales import return_tracking_number
from apps.sales_management.aftersales_models import AftersalesCase, ReturnAllocation
from apps.sales_management.services import upsert_normalized_refund
from tests.test_sales_management import NOW, create_scope, create_order, create_run


@pytest.mark.parametrize('fields', [{}, {'quantity': None}, {'quantity': 0},
    {'quantity': -1}, {'quantity': '1.5'}, {'quantity': True}])
def test_tiktok_return_quantity_must_be_explicit_positive_integer(fields):
    item = {**fields, 'refund_amount': {'currency': 'PHP', 'refund_total': '2'}}
    with pytest.raises(ValidationError, match='TK_RETURN_QUANTITY_UNCONFIRMED'):
        MarketplaceRefundAdapter._tiktok_refund_item(item, 'RETURN', 0, 'PHP')


@pytest.mark.parametrize('fields', [{'quantity': 2}, {'return_quantity': '2'}])
def test_tiktok_return_preserves_explicit_quantity(fields):
    item = {**fields, 'refund_amount': {'currency': 'PHP', 'refund_total': '2'}}
    assert MarketplaceRefundAdapter._tiktok_refund_item(item, 'RETURN', 0, 'PHP')['quantity'] == 2


@pytest.mark.django_db
@pytest.mark.parametrize('platform', ['lazada', 'tiktok'])
def test_return_snapshot_flows_from_official_adapter_to_case(platform):
    tenant, _, store, _ = create_scope('return-' + platform)
    order = create_order(tenant, store, 'return-' + platform)
    store.platform.platform_type = platform
    store.platform.save()
    config = order.source_run.sync_job.integration_config
    config.platform = platform
    config.save()
    adapter = MarketplaceRefundAdapter(SimpleNamespace(platform=platform, platform_config={}))
    adapter.authorization = SimpleNamespace(store=store, region='PH')
    if platform == 'tiktok':
        raw = {'return_id': 'RETURN', 'order_id': order.external_order_id, 'return_type': 'RETURN_AND_REFUND',
               'return_status': 'BUYER_SHIPPED_ITEM', 'return_tracking_number': 'REVERSE',
               'return_provider_name': 'Carrier', 'create_time': int(NOW.timestamp()),
               'update_time': int(NOW.timestamp()), 'refund_amount': {'currency': 'PHP', 'refund_total': '1',
                   'refund_subtotal': '1', 'refund_shipping_fee': '0', 'refund_tax': '0'},
               'return_line_items': []}
        facts = tiktok_return_logistics(raw, NOW.isoformat())
    else:
        raw = {'reverse_order_id': 'RETURN', 'trade_order_id': order.external_order_id,
               'request_type': 'RETURN', 'reverse_order_lines': [{'reverse_order_line_id': 'LINE',
               'return_order_line_gmt_create': int(NOW.timestamp()),
               'return_order_line_gmt_modified': int(NOW.timestamp()), 'refund_amount': 1}]}
        client = SimpleNamespace(now=lambda: NOW, _request=Mock(return_value={'code': '0', 'data': {
            'reverse_order_id': 'RETURN', 'trade_order_id': order.external_order_id, 'is_rtm': 'true',
            'reverseOrderLineDTOList': [{'reverse_order_line_id': 'LINE', 'tracking_number': 'REVERSE'}]}}))
        facts, _ = lazada_return_logistics(client, raw)
    raw['_platform_logistics'] = facts
    payload = adapter.normalize_record(raw)
    refund = upsert_normalized_refund(tenant=tenant, source_run=create_run(tenant, 'refund_return', platform, platform=platform), payload=payload)
    case = AftersalesCase.objects.get(refund=refund)
    assert case.tracking_no == 'REVERSE'
    assert case.return_status != 'received'
    assert not ReturnAllocation.objects.exists()
    refund.sales_order.refresh_from_db()
    assert return_tracking_number(refund) == 'REVERSE'
    snapshot = refund.sales_order.source_details['platform_return_logistics']['RETURN']
    snapshot['return_destination'] = 'platform'
    assert return_tracking_number(refund) == ''


def test_lazada_refuses_wrong_order_or_return_identity():
    client = SimpleNamespace(now=lambda: NOW, _request=Mock(return_value={'code': '0', 'data': {
        'reverse_order_id': 'WRONG', 'trade_order_id': 'ORDER', 'reverseOrderLineDTOList': []}}))
    with pytest.raises(ValidationError, match='identity'):
        lazada_return_logistics(client, {'reverse_order_id': 'RETURN', 'trade_order_id': 'ORDER'})
    client._request.assert_called_once_with('/rest/order/reverse/return/detail/list', {'reverse_order_id': 'RETURN'})


def test_return_contract_rejects_cross_platform_snapshot():
    from apps.integrations.refund_return_contract import normalize_refund_return_record
    from django.core.exceptions import ValidationError as ContractError
    with pytest.raises(ContractError, match='platform identity'):
        normalize_refund_return_record('tiktok', {'store_id': '1', 'external_return_id': 'RETURN',
            'contract_version': 'refund_return.v1', 'case_type': 'RETURN_AND_REFUND',
            'raw_status': 'BUYER_SHIPPED_ITEM', 'normalized_status': 'pending',
            'requested_at_utc': NOW.isoformat(), 'updated_at_utc': NOW.isoformat(),
            'external_order_id': 'ORDER', 'currency': 'PHP', 'items': [],
            'platform_logistics': {'platform': 'lazada', 'return_sn': 'RETURN', 'order_sn': 'ORDER'}})
