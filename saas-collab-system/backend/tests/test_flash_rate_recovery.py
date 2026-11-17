import pytest
from apps.flash_sales import engine
from apps.flash_sales.models import StoreTask, StoreLock
from apps.flash_sales.provider import RateLimited, UnknownWrite
from apps.flash_sales.services import submit
from apps.flash_sales.notifications import prepare_notifications, notification_text
from tests.test_flash_sales import shop, configured, FakeShopee

pytestmark = pytest.mark.django_db

def due(task, adapter):
    StoreTask.objects.filter(pk=task.pk).update(next_attempt_at=None)
    result = engine.run_step(task.pk, adapter=adapter)
    task.refresh_from_db()
    return result

@pytest.mark.parametrize('written', [False, True])
def test_rate_limit_does_not_exhaust_execution_retries(shop, monkeypatch, written):
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id='rate-limit', store_ids=[store.id]).tasks.get()
    adapter = FakeShopee()
    if written:
        due(task, adapter)
    def limited(*args):
        raise RateLimited('synthetic rate limit', retry_after=300)
    monkeypatch.setattr(engine, 'step', limited)
    for _ in range(6):
        assert due(task, adapter) == 'waiting'
    assert task.next_attempt_at and not task.finished_at
    assert not task.state.get('retry_paused') and not task.state.get('prewrite_read_failures')
    assert task.retry_count == 0
    assert StoreLock.objects.get(store=store).task_id == task.id

def test_unknown_owned_write_is_not_automatically_deleted(shop, monkeypatch):
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id='unknown-owned', store_ids=[store.id]).tasks.get()
    adapter = FakeShopee()
    due(task, adapter)
    intent = task.intents.get()
    def uncertain(*args):
        raise UnknownWrite('readback pending')
    monkeypatch.setattr(engine, 'step', uncertain)
    assert due(task, adapter) == 'confirming'
    intent.refresh_from_db()
    assert intent.status == 'adding'
    assert not any(endpoint == 'delete_shop_flash_sale' for endpoint, _ in adapter.calls)

def test_attention_and_final_summary_are_distinct_and_idempotent(shop):
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id='attention-summary', store_ids=[store.id]).tasks.get()
    task.snapshot['recipients'] = {'users': [{'user_id': user.id, 'name': 'Synthetic', 'open_id': 'synthetic'}]}
    task.state, task.status = {'retry_paused': True}, 'confirming'
    task.save()
    prepare_notifications(task.batch_id)
    row = task.batch.notifications.get()
    assert row.snapshot['phase'] == 'attention'
    assert '批次尚未结束' in notification_text(task.batch, row.snapshot)
    row.status, row.message_id = 'accepted', 'synthetic-receipt'
    row.save()
    prepare_notifications(task.batch_id)
    row.refresh_from_db()
    assert row.status == 'accepted'
    task.status = 'failed'
    task.save()
    prepare_notifications(task.batch_id)
    row.refresh_from_db()
    assert row.status == 'pending' and row.snapshot['phase'] == 'final'
    assert row.snapshot['attention_receipt']['message_id'] == 'synthetic-receipt'
    assert task.batch.notifications.count() == 1

@pytest.mark.parametrize('limited', [False, True])
def test_stock_adjustments_are_grouped_and_prepared_payload_survives_cooldown(shop, limited):
    user, store, _ = shop
    configured(shop)
    class MultiStock(FakeShopee):
        def __init__(self):
            super().__init__()
            self.source = [{**self.source[0], 'item_id': str(100+n)} for n in range(5)]
            self.adds = 0
            self.target_reads = 0
        def items(self, activity_id):
            if str(activity_id) != '10':
                self.target_reads += 1
            return super().items(activity_id)
        def call(self, endpoint, *, body):
            if endpoint != 'add_shop_flash_sale_items':
                return super().call(endpoint, body=body)
            self.adds += 1
            if self.adds == 1:
                self.calls.append((endpoint, body))
                return {'failed_items': [{'item_id': r['item_id'], 'model_id': r['model_id'], 'err_msg': 'insufficient stock'} for r in self.source]}
            if limited and self.adds == 2:
                raise RateLimited('synthetic cooldown', retry_after=300)
            self.calls.append((endpoint, body))
            self.products['20'] = [{**r, 'stock': 2, 'status': 1} for r in self.source]
            return {}
    adapter = MultiStock()
    task = submit(user, request_id='grouped-stock', store_ids=[store.id]).tasks.get()
    for _ in range(10):
        due(task, adapter)
        if task.status == 'succeeded':
            break
    assert task.status == 'succeeded'
    adjusted = task.intents.get().writes.get(key='adjust:0')
    assert len(adjusted.payload['items']) == 5
    assert len(task.intents.get().result['adjustments']) == 5
    assert adapter.target_reads == 2
    assert sum(e == 'add_shop_flash_sale_items' for e, _ in adapter.calls) == 2

def test_attention_delivery_does_not_suppress_final_delivery(shop):
    from unittest.mock import Mock
    from apps.flash_sales.notifications import deliver
    from apps.integrations.models import FeishuIdentity, FeishuConnection
    user, store, _ = shop
    configured(shop)
    FeishuIdentity.objects.create(tenant=user.tenant, user=user, open_id='synthetic')
    FeishuConnection.objects.create(tenant=user.tenant, app_id='synthetic', app_secret_ref='synthetic', enabled=True, created_by=user, updated_by=user)
    task = submit(user, request_id='attention-delivery', store_ids=[store.id]).tasks.get()
    task.snapshot['recipients'] = {'users': [{'user_id': user.id, 'name': 'Synthetic', 'open_id': 'synthetic'}]}
    task.state, task.status = {'retry_paused': True}, 'confirming'
    task.save()
    prepare_notifications(task.batch_id)
    row = task.batch.notifications.get()
    sender = Mock()
    sender.send.return_value = 'synthetic-message'
    assert deliver(row.pk, sender) == 'accepted'
    assert deliver(row.pk, sender) == 'accepted'
    task.status = 'succeeded'
    task.save()
    prepare_notifications(task.batch_id)
    assert deliver(row.pk, sender) == 'accepted'
    assert deliver(row.pk, sender) == 'accepted'
    assert sender.send.call_count == 2
    keys = [call.args[4] for call in sender.send.call_args_list]
    assert keys[0].endswith(':attention') and keys[1] == keys[0][:-10]
