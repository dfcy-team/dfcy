from unittest.mock import Mock

import pytest
from django.utils import timezone
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import CustomUser
from apps.flash_sales.models import Batch, Intent, Notification, StoreTask
from apps.flash_sales.notifications import deliver, prepare_notifications
from apps.integrations.models import FeishuConnection, FeishuIdentity
from apps.masterdata.models import StoreMaster
from tests.test_flash_sales import shop

pytestmark = pytest.mark.django_db


def test_batch_waits_then_sends_one_clear_summary_per_recipient(shop):
    user, store, _ = shop
    other = CustomUser.objects.create_user(username='summary-other', tenant=user.tenant, user_type='internal')
    for person in [user, other]:
        FeishuIdentity.objects.create(tenant=user.tenant, user=person, open_id=f'synthetic-{person.id}')
    FeishuConnection.objects.create(tenant=user.tenant, app_id='synthetic-app', app_secret_ref='synthetic-ref',
        enabled=True, created_by=user, updated_by=user)
    batch = Batch.objects.create(tenant=user.tenant, actor=user, source='manual', request_id='summary', payload_hash='test')
    tasks = []
    for index, recipient in enumerate([user, user, other, user]):
        target_store = StoreMaster.objects.create(tenant=user.tenant, platform=store.platform,
            code=f'SUM{index}', name=f'Summary shop {index}')
        tasks.append(StoreTask.objects.create(tenant=user.tenant, batch=batch, store=target_store,
            status='waiting' if index == 1 else 'succeeded', completed=0 if index == 1 else 1,
            message='平台处理未完成' if index == 1 else '已完成 1/1 个时段',
            snapshot={'recipients': {'mode': 'disabled' if index == 3 else 'custom', 'users': [
                {'user_id': recipient.id, 'name': recipient.username, 'open_id': f'synthetic-{recipient.id}'}]}}))
    prepare_notifications(batch.id)
    assert not Notification.objects.exists()
    tasks[1].status = 'failed'
    tasks[1].message = '三次重试后仍失败，目标活动已清理'
    tasks[1].save()
    batch.finished_at = timezone.now()
    batch.save()
    Intent.objects.create(tenant=user.tenant, task=tasks[0], store=tasks[0].store, slot_id='1',
        platform_id='old', status='failed', absence_evidence={'absent': True})
    Intent.objects.create(tenant=user.tenant, task=tasks[0], store=tasks[0].store, slot_id='1',
        platform_id='new', status='succeeded', target={'start_time': 1794888000, 'end_time': 1794895200},
        result={'execution_attempt': 1, 'specifications': [{'state': 'enabled'}, {'state': 'rejected'}]})
    Intent.objects.create(tenant=user.tenant, task=tasks[1], store=tasks[1].store, slot_id='2',
        platform_id='failed', status='failed', absence_evidence={'absent': True},
        result={'execution_attempt': 3, 'specifications': [{'state': 'rejected', 'reason': '活动价高于近七天最低价'}]})
    with CaptureQueriesContext(connection) as queries:
        prepare_notifications(batch.id)
    # Sorting the large result JSON in MySQL exhausts the server sort buffer.
    intent_queries = [q['sql'] for q in queries if 'FROM "flash_sales_intent"' in q['sql'] or 'FROM `flash_sales_intent`' in q['sql']]
    assert intent_queries and all('ORDER BY' not in sql for sql in intent_queries)
    prepare_notifications(batch.id)
    assert Notification.objects.count() == 2
    sender = Mock()
    sender.send.return_value = 'synthetic-message'
    for notification in Notification.objects.all():
        assert deliver(notification.pk, sender) == 'accepted'
        assert deliver(notification.pk, sender) == 'accepted'
    assert sender.send.call_count == 2
    messages = {call.args[1]: call.args[3]['text'] for call in sender.send.call_args_list}
    text = messages[f'synthetic-{user.id}']
    assert '本通知店铺：2 家｜成功 1 家｜失败 1 家' in text
    assert '成功｜Summary shop 0' in text and '失败｜Summary shop 1' in text
    assert 'Summary shop 2' not in text and 'Summary shop 3' not in text
    assert '第 1 次重试成功' in text and '重建重试：3 次' in text
    assert '失败活动已全部清理' in text and '活动价高于近七天最低价' in text
    assert '活动时段：' in text and '规格结果：已参加 1，平台拒绝 1' in text
    assert f'&batch={batch.id}' in text
    assert 'Summary shop 2' in messages[f'synthetic-{other.id}']
    assert 'Summary shop 0' not in messages[f'synthetic-{other.id}']


def test_existing_notification_cannot_send_before_whole_batch_finishes(shop):
    user, store, _ = shop
    batch = Batch.objects.create(tenant=user.tenant, actor=user, source='manual', request_id='unfinished', payload_hash='test')
    StoreTask.objects.create(tenant=user.tenant, batch=batch, store=store, status='confirming')
    notification = Notification.objects.create(tenant=user.tenant, batch=batch, recipient=user, snapshot={})
    sender = Mock()
    assert deliver(notification.pk, sender) == 'pending'
    sender.send.assert_not_called()

@pytest.mark.parametrize('source,scope', [('manual','active'),('manual','history'),('post_sync','affected')])
def test_sync_never_creates_notification_and_old_pending_delivery_is_skipped(shop, source, scope):
    user, store, _ = shop
    batch = Batch.objects.create(tenant=user.tenant, actor=user, source=source, operation='sync',
        request_id=f'silent-{source}-{scope}', payload_hash='test', finished_at=timezone.now())
    StoreTask.objects.create(tenant=user.tenant, batch=batch, store=store, status='succeeded',
        snapshot={'sync_scope':scope, 'recipients':{'users':[{'user_id':user.id,'open_id':'synthetic','name':'Synthetic'}]}})
    prepare_notifications(batch.id)
    assert not batch.notifications.exists()
    row = Notification.objects.create(tenant=user.tenant, batch=batch, recipient=user, snapshot={})
    sender = Mock()
    assert deliver(row.pk, sender) == 'skipped'
    sender.send.assert_not_called()
    row.refresh_from_db()
    assert row.message == '同步任务不推送飞书'
