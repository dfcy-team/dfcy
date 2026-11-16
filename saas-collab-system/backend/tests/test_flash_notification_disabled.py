from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.flash_sales.models import Batch, Notification, StoreConfig, StoreTask, TenantControl
from apps.flash_sales.notifications import deliver, prepare_notifications, recipient_snapshot
from tests.test_flash_sales import shop, configured

pytestmark = pytest.mark.django_db


def test_disabled_mode_saved_and_never_uses_fallback(shop):
    user, store, client = shop
    configured(shop)
    config = StoreConfig.objects.get(store=store)
    response = client.put('/api/internal/marketing/flash-sales/notifications/', {'stores': [{
        'store_id': store.pk, 'version': config.version, 'notification_mode': 'disabled', 'recipient_ids': [],
    }]}, format='json')
    assert response.status_code == 200
    config.refresh_from_db()
    assert recipient_snapshot(store, config) == {'mode': 'disabled', 'reason': '已关闭推送', 'error': '', 'users': []}
    assert not config.recipients.exists()
    assert client.get('/api/internal/marketing/flash-sales/workspace/').data['data']['stores'][0]['notification_mode'] == 'disabled'


def test_history_cutoff_blocks_preparation_and_delivery(shop):
    user, store, _ = shop
    batch = Batch.objects.create(tenant=user.tenant, actor=user, source='manual', request_id='old-notify', payload_hash='test')
    StoreTask.objects.create(tenant=user.tenant, store=store, batch=batch, status='succeeded', snapshot={
        'recipients': {'users': [{'user_id': user.pk, 'name': 'test', 'open_id': 'synthetic'}]},
    })
    TenantControl.objects.create(tenant=user.tenant, notifications_not_before=timezone.now()+timedelta(seconds=1))
    prepare_notifications(batch.pk)
    assert not Notification.objects.exists()
    row = Notification.objects.create(tenant=user.tenant, batch=batch, recipient=user, snapshot={'open_id': 'synthetic'})
    sender = Mock()
    assert deliver(row.pk, sender) == 'skipped'
    sender.send.assert_not_called()


def test_disabled_config_requires_store_permission(shop):
    user, store, client = shop
    configured(shop)
    config = StoreConfig.objects.get(store=store)
    user.is_superuser = False
    user.save()
    assert client.put('/api/internal/marketing/flash-sales/notifications/', {'stores': [{
        'store_id': store.pk, 'version': config.version, 'notification_mode': 'disabled', 'recipient_ids': [],
    }]}, format='json').status_code == 403
    config.refresh_from_db()
    assert config.notification_mode == 'owner'


def test_new_batch_still_prepares_after_cutoff_and_disabled_store_stays_out(shop):
    user, store, _ = shop
    TenantControl.objects.create(tenant=user.tenant, notifications_not_before=timezone.now()-timedelta(seconds=1))
    batch = Batch.objects.create(tenant=user.tenant, actor=user, source='manual', request_id='new-notify', payload_hash='test')
    task = StoreTask.objects.create(tenant=user.tenant, store=store, batch=batch, status='succeeded', snapshot={
        'recipients': {'mode': 'disabled', 'users': []},
    })
    prepare_notifications(batch.pk)
    assert not Notification.objects.exists()
    task.snapshot = {'recipients': {'mode': 'owner', 'users': [{'user_id': user.pk, 'name': 'test', 'open_id': 'synthetic'}]}}
    task.save()
    prepare_notifications(batch.pk)
    assert Notification.objects.get().snapshot['stores'][0]['store_id'] == store.pk
