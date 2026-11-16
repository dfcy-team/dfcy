import hashlib
import hmac
import json
from unittest.mock import patch
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone
from apps.integrations.models import (PlatformIntegrationConfig, MarketplaceStoreAuthorization,
    WebhookEvent, authorization_service_write, marketplace_identity_key, marketplace_store_binding_key)
from apps.integrations.marketplace_order_push import parse_event
from apps.sales_management.order_event_scope import milestone_filters
from apps.sales_management.order_presentation import attach_event_milestones
from tests.test_sales_management import create_scope, user_for

pytestmark = pytest.mark.django_db
SECRET = 'TEST-ONLY-PUSH-SECRET'


@pytest.fixture(params=['lazada', 'tiktok'])
def scope(request):
    platform = request.param
    tenant, master, store, _ = create_scope('push-' + platform)
    master.platform_type = platform
    master.save(update_fields=['platform_type'])
    user = user_for(tenant, 'push-' + platform)
    with authorization_service_write():
        config = PlatformIntegrationConfig.objects.create(tenant=tenant, platform=platform, created_by=user,
            account_alias='push', status='active', platform_config={'api_type': 'marketplace',
            'app_key': 'TEST-APP', 'order_push_enabled': True,
            'order_push_callback_url': 'https://example.com/push'})
        identity = marketplace_identity_key(platform, 'PH', '123')
        account = MarketplaceStoreAuthorization.objects.create(tenant=tenant, platform=platform,
            integration_config=config, store=store, region='PH', platform_store_id='123',
            platform_identity_key=identity, active_platform_identity_key=identity,
            active_store_binding_key=marketplace_store_binding_key(tenant.pk, platform, store.pk),
            merchant_subject_id='TEST', credential_id='TEST-REF', token_id='TEST-TOKEN',
            shop_cipher='TEST-CIPHER' if platform == 'tiktok' else '', status='active',
            created_by=user, updated_by=user)
    return config, account


def payload(platform):
    if platform == 'lazada':
        return dict(seller_id='123', message_type=0, site='lazada_ph', timestamp=1700000010000,
            data=dict(trade_order_id='ORDER', trade_order_line_id='LINE',
                      order_status='canceled', status_update_time=1700000000))
    return dict(shop_id='123', type=1, tts_notification_id='TEST-NOTIFICATION', timestamp=1700000010,
        data=dict(order_id='ORDER', order_status='COMPLETED', update_time=1700000000))


def send(config, message=None, signature=None):
    body = json.dumps(message or payload(config.platform)).encode()
    signature = signature if signature is not None else hmac.new(
        SECRET.encode(), b'TEST-APP' + body, hashlib.sha256).hexdigest()
    with patch('apps.integrations.marketplace_order_push.get_custody_backend') as custody:
        custody.return_value.retrieve_secret.return_value = SECRET
        return Client().post(f'/api/platform/{config.platform}/order-status/{config.pk}/', body,
            content_type='application/json', HTTP_AUTHORIZATION=signature)


def test_receive_deduplicate_milestones_and_no_order_mutation(scope):
    config, account = scope
    assert send(config).status_code == 200
    retry = payload(config.platform)
    retry['timestamp'] += 1000
    assert send(config, retry).status_code == 200
    assert WebhookEvent.objects.count() == 1
    event = WebhookEvent.objects.get()
    assert event.raw_envelope.payload['payload']['store_id'] == account.store_id
    row = {'store': {'id': account.store_id}, 'platform': config.platform, 'external_order_id': 'ORDER'}
    attach_event_milestones(config.tenant_id, [row])
    if config.platform == 'lazada':
        assert 'cancelled_at_utc' not in row
        other = payload(config.platform)
        other['data']['trade_order_line_id'] = 'OTHER-LINE'
        assert send(config, other).status_code == 200
        assert WebhookEvent.objects.count() == 2
    else:
        assert row['completed_at_utc'] == event.event_at.isoformat()
        assert WebhookEvent.objects.filter(milestone_filters()['completed_at']).count() == 1


def test_signature_shop_site_and_disable_guards(scope):
    config, _ = scope
    assert send(config, signature='bad').status_code == 401
    assert send(config, signature='非ASCII').status_code == 401
    other = payload(config.platform)
    other['seller_id' if config.platform == 'lazada' else 'shop_id'] = 'OTHER-SHOP'
    assert send(config, other).status_code == 403
    if config.platform == 'lazada':
        other = payload(config.platform)
        other['site'] = 'lazada_my'
        assert send(config, other).status_code == 403
    config.platform_config['order_push_enabled'] = False
    config.save(update_fields=['platform_config'])
    assert send(config).status_code == 404
    assert not WebhookEvent.objects.exists()


def test_bad_timestamp_unsupported_topic_and_storage_failure(scope):
    config, _ = scope
    bad = payload(config.platform)
    bad['data']['status_update_time' if config.platform == 'lazada' else 'update_time'] = True
    assert send(config, bad).status_code == 400
    bad = payload(config.platform)
    bad['message_type' if config.platform == 'lazada' else 'type'] = 999
    assert send(config, bad).status_code == 400
    with patch('apps.integrations.marketplace_order_push.archive_webhook_payload', side_effect=RuntimeError('test')):
        with pytest.raises(RuntimeError):
            send(config)
    assert not WebhookEvent.objects.exists()


def test_lazada_reverse_identity_is_distinct():
    normal = payload('lazada')
    reverse = payload('lazada')
    reverse['data'].update(reverse_order_id='RETURN', reverse_order_line_id='RETURN-LINE')
    original = parse_event('lazada', json.dumps(normal).encode())
    result = parse_event('lazada', json.dumps(reverse).encode())
    assert result['kind'] == 'reverse_order_line'
    assert original['event_key'] != result['event_key']


def test_authorization_expiry_and_configuration_isolation(scope):
    config, account = scope
    other = PlatformIntegrationConfig.objects.create(tenant=config.tenant, platform=config.platform,
        created_by=config.created_by, account_alias='other', status='active', platform_config=config.platform_config)
    assert send(other).status_code == 403
    with authorization_service_write():
        account.expires_at = timezone.now() - timedelta(seconds=1)
        account.save(update_fields=['expires_at'])
    assert send(config).status_code == 403
    assert not WebhookEvent.objects.exists()


def test_order_log_api_reads_platform_events(scope):
    from tests.test_sales_management import create_order, create_run, grant, client_for
    config, account = scope
    with patch('tests.test_sales_management.create_run',
               side_effect=lambda tenant, resource, suffix: create_run(tenant, resource, suffix, platform=config.platform)):
        order = create_order(config.tenant, account.store, 'log-' + config.platform)
    order.external_order_id = 'ORDER'
    order.save(update_fields=['external_order_id'])
    grant(config.created_by, 'sales_management.orders.view')
    assert send(config).status_code == 200
    response = client_for(config.created_by).get(f'/api/internal/commerce/orders/{order.pk}/events/')
    assert response.status_code == 200
    data = response.json()['data']
    events = [row for row in data['events'] if row['source'] == '平台状态推送']
    assert len(events) == 1
    assert events[0]['event_type'].startswith(config.platform + '.')
    if config.platform == 'lazada':
        assert events[0]['title'] == '订单商品行状态：canceled'
        assert data['milestones']['cancelled_at'] is None
    else:
        assert events[0]['title'] == '订单完成'
        assert data['milestones']['completed_at'] is not None


def test_tiktok_cancel_is_not_delivered(scope):
    config, account = scope
    if config.platform != 'tiktok':
        return
    message = payload('tiktok')
    message['data']['order_status'] = 'CANCEL'
    assert send(config, message).status_code == 200
    assert WebhookEvent.objects.filter(milestone_filters()['cancelled_at']).count() == 1
    assert not WebhookEvent.objects.filter(milestone_filters()['completed_at']).exists()
