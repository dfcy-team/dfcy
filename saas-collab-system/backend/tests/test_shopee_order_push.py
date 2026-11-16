import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import Client
from django.utils import timezone

from apps.integrations.models import (
    MarketplaceStoreAuthorization,
    PlatformIntegrationConfig, WebhookEvent, authorization_service_write,
    marketplace_identity_key, marketplace_store_binding_key,
)
from tests.test_sales_management import create_scope, user_for

pytestmark = pytest.mark.django_db
URL = 'https://example.com/api/platform/shopee/order-status/1/'
KEY = 'TEST-ONLY-SIGNING-KEY'


@pytest.fixture
def scope():
    tenant, _, store, _ = create_scope('push-test')
    user = user_for(tenant, 'push-user')
    with authorization_service_write():
        config = PlatformIntegrationConfig.objects.create(
            tenant=tenant, created_by=user, platform='shopee', account_alias='push',
            status='active', sync_read_enabled=True,
            platform_config={'order_push_enabled': True, 'order_push_callback_url': URL},
        )
        key = marketplace_identity_key('shopee', 'PH', '123')
        account = MarketplaceStoreAuthorization.objects.create(
            tenant=tenant, integration_config=config, store=store, platform='shopee', region='PH',
            platform_store_id='123', platform_identity_key=key, active_platform_identity_key=key,
            active_store_binding_key=marketplace_store_binding_key(tenant.id, 'shopee', store.id),
            merchant_subject_id='TEST-MERCHANT', credential_id='TEST-REFERENCE', token_id='TEST-TOKEN-REF',
            status='active', created_by=user, updated_by=user,
        )
    return config, account, None


def send(config, time=1700000000, sent=1700000010, shop=123, signature=None):
    body = json.dumps({'shop_id': shop, 'code': 3, 'timestamp': sent,
        'data': {'ordersn': 'TEST-ORDER', 'status': 'COMPLETED', 'completed_scenario': 'NORMAL',
                 'update_time': time}}).encode()
    signature = signature if signature is not None else hmac.new(KEY.encode(), URL.encode()+b'|'+body, hashlib.sha256).hexdigest()
    with patch('apps.integrations.shopee_order_push_views.get_custody_backend') as custody:
        custody.return_value.retrieve_secret.return_value = KEY
        return Client().post(f'/api/platform/shopee/order-status/{config.pk}/', body,
                             content_type='application/json', HTTP_AUTHORIZATION=signature)


def test_receive_dedup_and_read(scope):
    config, _, app = scope
    assert send(config).status_code == 204
    assert send(config, sent=1700000999).status_code == 204
    assert WebhookEvent.objects.count() == 1
    row = WebhookEvent.objects.get()
    assert row.processing_status == 'processed'
    assert row.raw_envelope.payload['payload']['event_at']


def test_invalid_signature_unknown_shop_and_disabled(scope):
    config, _, _ = scope
    assert send(config, signature='invalid').status_code == 401
    assert send(config, shop=456).status_code == 403
    config.platform_config['order_push_enabled'] = False
    config.save(update_fields=['platform_config'])
    assert send(config).status_code == 404
    assert not WebhookEvent.objects.exists()


def test_storage_failure_is_not_acknowledged(scope):
    config, _, _ = scope
    with patch('apps.integrations.shopee_order_push_views.archive_webhook_payload', side_effect=RuntimeError('test')):
        with pytest.raises(RuntimeError):
            send(config)
    assert not WebhookEvent.objects.exists()


def test_local_order_log_is_scoped_and_read_only(scope):
    from tests.test_sales_management import create_order, grant, client_for
    config, account, _ = scope
    order = create_order(config.tenant, account.store, 'push-log')
    order.external_order_id = 'TEST-ORDER'
    order.save(update_fields=['external_order_id'])
    grant(config.created_by, 'sales_management.orders.view')
    assert send(config).status_code == 204
    client = client_for(config.created_by)
    response = client.get(f'/api/internal/commerce/orders/{order.pk}/events/')
    assert response.status_code == 200
    data = response.json()['data']
    assert len(data['events']) == 2
    assert any(event.get('title') == '订单创建' for event in data['events'])
    assert data['milestones']['completed_at'] is not None
    assert data['milestones']['cancelled_at'] is None
    order.refresh_from_db()
    assert order.completed_at_utc is None
    assert client.post(f'/api/internal/commerce/orders/{order.pk}/events/', {}).status_code in (403, 405)


def test_large_event_history_keeps_milestones_and_pages_without_raw_json_lookup(scope):
    from tests.test_sales_management import create_order, grant, client_for
    config, account, _ = scope
    order = create_order(config.tenant, account.store, 'many-events')
    order.external_order_id = 'TEST-ORDER'
    order.save(update_fields=['external_order_id'])
    grant(config.created_by, 'sales_management.orders.view')
    assert send(config).status_code == 204
    original = WebhookEvent.objects.get()
    WebhookEvent.objects.bulk_create([WebhookEvent(tenant=config.tenant, platform='shopee',
        event_id=f'test-event-{i}', event_type='shopee.order_status:123', signature_status='valid',
        payload_hash='0'*64, external_shop_id='123', external_order_id='TEST-ORDER',
        order_status='SHIPPED', event_at=original.event_at+timedelta(seconds=i+1)) for i in range(510)])
    client = client_for(config.created_by)
    url = f'/api/internal/commerce/orders/{order.pk}/events/'
    first = client.get(url).json()['data']
    last = client.get(url, {'page': 6}).json()['data']
    assert first['count'] == 512 and len(first['events']) == 100 and first['has_more']
    assert len(last['events']) == 12 and not last['has_more']
    assert first['milestones']['completed_at'] == last['milestones']['completed_at']
    assert first['milestones']['completed_at'] is not None
    assert not {event['id'] for event in first['events']} & {event['id'] for event in last['events']}
    detail = client.get(f'/api/internal/commerce/orders/{order.pk}/').json()['data']
    assert detail['time_sources']['completed_at_utc'] == 'verified_platform_push'
    order.refresh_from_db()
    assert order.completed_at_utc is None


def test_workspace_list_has_items_without_exposing_warehouse_to_order_only_role(scope):
    from tests.test_sales_management import create_order, grant, client_for
    config, account, _ = scope
    create_order(config.tenant, account.store, 'workspace')
    grant(config.created_by, 'sales_management.orders.view')
    result = client_for(config.created_by).get('/api/internal/commerce/orders/',
        {'presentation': 'workspace', 'include_summary': 'false'}).json()['data']['results'][0]
    assert len(result['items']) == 1
    assert result['warehouse_summary']['status'] == 'forbidden'
    assert 'snapshot' not in result['warehouse_summary']


@pytest.mark.django_db(transaction=True)
def test_mysql_concurrent_push_retry_is_idempotent(scope):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import connection, close_old_connections
    if connection.vendor != 'mysql':
        pytest.skip('MySQL transaction and locking acceptance')
    config, _, _ = scope
    # Patch custody once; independent thread-local DB connections and requests.
    body = json.dumps({'shop_id': 123, 'code': 3, 'timestamp': 1700000010,
        'data': {'ordersn': 'CONCURRENT', 'status': 'IN_CANCEL', 'update_time': 1700000000}}).encode()
    signature = hmac.new(KEY.encode(), URL.encode()+b'|'+body, hashlib.sha256).hexdigest()
    def deliver(_):
        close_old_connections()
        try:
            return Client().post(f'/api/platform/shopee/order-status/{config.pk}/', body,
                content_type='application/json', HTTP_AUTHORIZATION=signature).status_code
        finally:
            close_old_connections()
    with patch('apps.integrations.shopee_order_push_views.get_custody_backend') as custody:
        custody.return_value.retrieve_secret.return_value = KEY
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(deliver, range(2))) == [204, 204]
    assert WebhookEvent.objects.filter(external_order_id='CONCURRENT').count() == 1
