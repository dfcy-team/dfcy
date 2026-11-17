import pytest
from django.utils import timezone

from apps.flash_sales import engine
from apps.flash_sales.models import Batch, Intent, StoreLock, StoreTask, WriteOperation
from apps.flash_sales.notifications import prepare_notifications
from apps.flash_sales.provider import Deferred, SharedCooldown
from apps.flash_sales.services import submit
from tests.test_flash_sales import shop, configured

pytestmark = pytest.mark.django_db


def run_due(task):
    StoreTask.objects.filter(pk=task.pk).update(next_attempt_at=None)
    result = engine.run_step(task.id, adapter=object())
    task.refresh_from_db()
    return result


@pytest.mark.parametrize('prepared', [False, True])
def test_four_prewrite_read_failures_finish_and_release_store_for_next_batch(shop, monkeypatch, prepared):
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id='prewrite-first', store_ids=[store.id]).tasks.get()
    task.snapshot['recipients'] = {'users': [{'user_id': user.id, 'name': 'Synthetic', 'open_id': 'synthetic'}]}
    task.save()
    if prepared:
        intent = Intent.objects.create(tenant=user.tenant, task=task, store=store, slot_id='test', reservation_key='test')
        WriteOperation.objects.create(tenant=user.tenant, intent=intent, key='create', endpoint='create_shop_flash_sale', status='prepared')
    later = Batch.objects.create(tenant=user.tenant, actor=user, source='scheduled', request_id='prewrite-next', payload_hash='test')
    following = StoreTask.objects.create(tenant=user.tenant, batch=later, store=store)
    def limited(*args):
        raise Deferred('HTTP 429 get_shop_flash_sale_list', retry_after=300)
    monkeypatch.setattr(engine, 'step', limited)
    for number in range(1, 4):
        assert run_due(task) == 'waiting'
        assert task.state['prewrite_read_failures'] == number
        assert not task.state.get('retry_paused')
        assert task.next_attempt_at > timezone.now()
        assert engine.run_step(following.id, adapter=object()) == 'not_claimed'
    assert run_due(task) == 'failed'
    assert task.finished_at and task.next_attempt_at is None and task.retry_count == 3
    assert '3 次重试已耗尽' in task.message and '未提交平台写入' in task.message
    assert StoreLock.objects.get(store=store).task_id is None
    assert not task.intents.filter(reservation_key__isnull=False).exists()
    task.batch.refresh_from_db()
    assert task.batch.finished_at
    prepare_notifications(task.batch_id)
    assert task.batch.notifications.count() == 1
    assert run_due(following) == 'waiting'
    assert StoreLock.objects.get(store=store).task_id == following.id


def test_shared_cooldown_does_not_consume_prewrite_retries(shop, monkeypatch):
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id='prewrite-cooldown', store_ids=[store.id]).tasks.get()
    def cooldown(*args):
        raise SharedCooldown('等待冷却', retry_after=300)
    monkeypatch.setattr(engine, 'step', cooldown)
    for _ in range(5):
        assert run_due(task) == 'waiting'
    assert task.retry_count == 0 and not task.state.get('prewrite_read_failures')


def test_submitted_write_is_never_failed_or_unlocked_as_a_read_failure(shop, monkeypatch):
    user, store, _ = shop
    configured(shop)
    task = submit(user, request_id='prewrite-uncertain', store_ids=[store.id]).tasks.get()
    intent = Intent.objects.create(tenant=user.tenant, task=task, store=store, slot_id='uncertain', reservation_key='uncertain')
    WriteOperation.objects.create(tenant=user.tenant, intent=intent, key='create', endpoint='create_shop_flash_sale', status='submitted')
    def limited(*args):
        raise Deferred('读取核对限流', retry_after=300)
    monkeypatch.setattr(engine, 'step', limited)
    for _ in range(3):
        run_due(task)
    assert task.state['retry_paused'] and not task.finished_at
    assert StoreLock.objects.get(store=store).task_id == task.id
    intent.refresh_from_db()
    assert intent.reservation_key == 'uncertain'
