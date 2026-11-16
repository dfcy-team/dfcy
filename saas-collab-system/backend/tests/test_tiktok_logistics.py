from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.cache import cache
from rest_framework.exceptions import ValidationError

from apps.integrations.tiktok_logistics import collect_order_logistics
from apps.integrations.order_field_mapping import enrich_order_fields, timestamp


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    monkeypatch.setattr('apps.integrations.tiktok_logistics._tracking_cache', lambda: cache)
    cache.clear()
    yield
    cache.clear()


def client(data=None):
    return SimpleNamespace(config=SimpleNamespace(tenant_id=1),
        authorization=SimpleNamespace(pk=2, shop_cipher='test-cipher'),
        now=lambda: datetime(2026, 11, 13, tzinfo=UTC),
        _request=Mock(return_value={'data': data or {'tracking': []}}))


def test_order_tracking_does_not_invent_package_assignment_and_is_cached():
    c = client({'tracking': [{'action_code': 30901,
        'update_time_millis': 1788174000000, 'description': 'Picked up', 'phone': 'HIDDEN'}]})
    facts, traces = collect_order_logistics(c, {'id': '123'})
    assert facts['packages'][0]['package_number'] is None
    event = facts['packages'][0]['events'][0]
    assert event['status'] == '30901'
    assert event['occurred_at_utc'] == timestamp(1788174000000)
    assert 'HIDDEN' not in str((facts, traces))
    assert collect_order_logistics(c, {'id': '123'}) == (facts, [])
    c._request.assert_called_once_with('/fulfillment/202309/orders/123/tracking', query={'shop_cipher': 'test-cipher'})
    observed = enrich_order_fields('tiktok', {'_platform_logistics': facts}, {})['observed_fields']
    assert observed['platform_logistics']['packages'][0]['events'][0] == event


@pytest.mark.parametrize('data', [
    {'order_id': 'other', 'tracking': []},
    {'order_id': '123'},
    {'tracking': [None]},
    {'tracking': {}},
])
def test_invalid_response_fails_without_false_empty_success(data):
    with pytest.raises(ValidationError):
        collect_order_logistics(client(data), {'id': '123'})


@pytest.mark.parametrize('invalid', [{}, {'description': 'Picked up'},
    {'description': None}, {'description': ''}, {'description': '   '},
    {'action_code': True}, {'action_code': '30901'},
    {'update_time_millis': True}, {'update_time_millis': '1788174000000'},
    {'update_time_millis': 0}, {'update_time_millis': -1},
    {'update_time_millis': 10**30}])
def test_invalid_event_blocks_page_and_success_cache(invalid):
    from apps.integrations.readonly_clients import TikTokReadonlyClient
    valid = {'action_code': 30901, 'description': 'Picked up', 'update_time_millis': 1788174000000}
    event = {} if not invalid else {**valid, **invalid}
    if invalid == {'description': 'Picked up'}:
        event = invalid  # Missing required time and code.
    c = object.__new__(TikTokReadonlyClient)
    c.config = SimpleNamespace(tenant_id=1)
    c.authorization = SimpleNamespace(pk=2, shop_cipher='test-cipher')
    c.now = lambda: datetime(2026, 11, 13, tzinfo=UTC)
    c._runtime_path = lambda name, fallback: fallback
    c._request = Mock(side_effect=[
        {'data': {'orders': [{'id': '123'}], 'next_page_token': 'NEXT'}},
        {'data': {'orders': [{'id': '123'}]}},
        {'data': {'tracking': [valid, event]}},
    ])
    with pytest.raises(ValidationError):
        c.fetch_orders('', {'time_from': 1, 'time_to': 2, 'page_size': 1, 'include_logistics': True})
    # No partial success cache, but the eight-hour reservation remains.
    with pytest.raises(ValidationError, match='cooling down'):
        collect_order_logistics(c, {'id': '123'})
    assert c._request.call_count == 3


def test_failure_reserves_interval_and_does_not_repeat_network_request():
    c = client()
    c._request.side_effect = ValidationError('provider failure')
    with pytest.raises(ValidationError):
        collect_order_logistics(c, {'id': '123'})
    with pytest.raises(ValidationError, match='cooling down'):
        collect_order_logistics(c, {'id': '123'})
    assert c._request.call_count == 1


def test_legacy_success_cache_is_not_reused_and_reservation_survives():
    import hashlib
    key = 'tk-order-tracking:' + hashlib.sha256(b'1:2:123').hexdigest()
    cache.set(key, {'status': 'ok', 'packages': [{'events': [{}]}]})
    cache.set(key + ':requested', True)
    c = client()
    with pytest.raises(ValidationError, match='cooling down'):
        collect_order_logistics(c, {'id': '123'})
    c._request.assert_not_called()


def test_empty_tracking_is_valid_and_unknown_integer_code_is_preserved():
    facts, _ = collect_order_logistics(client(), {'id': '123'})
    assert facts['status'] == 'ok' and facts['packages'][0]['events'] == []
    c = client({'tracking': [{'action_code': 987654, 'description': 'New event', 'update_time_millis': 1}]})
    facts, _ = collect_order_logistics(c, {'id': '456'})
    assert facts['packages'][0]['events'][0]['status'] == '987654'
    assert facts['packages'][0]['events'][0]['occurred_at_utc'] == '1970-01-01T00:00:00.001000+00:00'


def test_shared_cache_failure_does_not_bypass_request_protection(monkeypatch):
    monkeypatch.setattr('apps.integrations.tiktok_logistics._tracking_cache',
        Mock(side_effect=ConnectionError('cache unavailable')))
    c = client()
    with pytest.raises(ConnectionError):
        collect_order_logistics(c, {'id': '123'})
    c._request.assert_not_called()


def test_cache_is_scoped_to_authorization_and_tenant():
    first, second = client(), client()
    collect_order_logistics(first, {'id': '123'})
    second.config.tenant_id = 3
    collect_order_logistics(second, {'id': '123'})
    assert second._request.call_count == 1


def test_invalid_identity_cannot_become_request_path():
    c = client()
    with pytest.raises(ValidationError):
        collect_order_logistics(c, {'id': '../other'})
    c._request.assert_not_called()


def test_tiktok_scope_is_opt_in_and_bounded():
    from apps.integrations.readonly_clients import default_sync_scope
    config = SimpleNamespace(platform='tiktok', platform_config={})
    scope = default_sync_scope(config, {'include_logistics': True}, 'sales_order')
    assert scope['include_logistics'] is True and scope['page_size'] == 4
    with pytest.raises(ValidationError):
        default_sync_scope(config, {'include_logistics': True}, 'refund_return')


def test_order_page_attaches_tracking_before_advancing_cursor(monkeypatch):
    from apps.integrations.readonly_clients import TikTokReadonlyClient
    from apps.integrations import tiktok_logistics
    c = object.__new__(TikTokReadonlyClient)
    c.authorization = SimpleNamespace(shop_cipher='test-cipher')
    c._runtime_path = lambda name, fallback: fallback
    c._request = Mock(side_effect=[{'data': {'orders': [{'id': '123'}], 'next_page_token': 'NEXT'}},
                                  {'data': {'orders': [{'id': '123'}]}}])
    collector = Mock(return_value=({'status': 'ok', 'packages': []}, []))
    monkeypatch.setattr(tiktok_logistics, 'collect_order_logistics', collector)
    scope = {'time_from': 1, 'time_to': 2, 'page_size': 1, 'include_logistics': True}
    result = c.fetch_orders('', scope)
    assert result['records'][0]['_platform_logistics']['status'] == 'ok'
    assert result['next_cursor'] == 'NEXT'
    c._request.side_effect = [{'data': {'orders': [{'id': '123'}], 'next_page_token': 'NEXT'}},
                             {'data': {'orders': [{'id': '123'}]}}]
    collector.side_effect = ValidationError('tracking failed')
    with pytest.raises(ValidationError, match='tracking failed'):
        c.fetch_orders('', scope)
