import pytest
from apps.flash_sales.models import Batch, StoreTask, Intent
from tests.test_flash_sales import shop

pytestmark = pytest.mark.django_db

def test_workspace_excludes_specifications_but_detail_keeps_them(shop):
    user, store, client = shop
    batch = Batch.objects.create(tenant=user.tenant, actor=user, source='manual', operation='run', request_id='payload', payload_hash='test')
    task = StoreTask.objects.create(tenant=user.tenant, store=store, batch=batch, status='waiting', state={'retry_paused':True})
    rows = [{'item_id':str(i), 'model_id':'0', 'state':'enabled', 'reason':'sentinel-details'} for i in range(500)]
    Intent.objects.create(tenant=user.tenant, store=store, task=task, slot_id='1', target={}, items=rows, result={'specifications':rows})
    overview = client.get('/api/internal/marketing/flash-sales/workspace/')
    summary = overview.data['data']['batches'][0]['tasks'][0]
    assert summary['retry_paused'] is True
    assert summary['intents'] == []
    assert b'sentinel-details' not in overview.content
    detail = client.get(f'/api/internal/marketing/flash-sales/batches/{batch.pk}/').data['data']
    assert detail['tasks'][0]['intents'][0]['result']['specifications'] == rows

def test_manual_reconcile_is_scoped_and_cannot_bypass_wait(shop):
    from datetime import timedelta
    from django.utils import timezone
    user, store, client = shop
    batch = Batch.objects.create(tenant=user.tenant, actor=user, source='manual', operation='run', request_id='manual-reconcile', payload_hash='test')
    until=timezone.now()+timedelta(minutes=5)
    task=StoreTask.objects.create(tenant=user.tenant,store=store,batch=batch,status='waiting',next_attempt_at=until)
    url=f'/api/internal/marketing/flash-sales/batches/{batch.pk}/'
    assert client.post(url,{'action':'reconcile','task_id':task.pk},format='json').status_code==400
    task.refresh_from_db();assert task.next_attempt_at==until
    assert client.post(url,{'action':'reconcile','task_id':task.pk+100},format='json').status_code==404
    task.next_attempt_at=timezone.now()-timedelta(seconds=1);task.save()
    assert client.post(url,{'action':'reconcile','task_id':task.pk},format='json').status_code==200
    task.refresh_from_db();assert task.next_attempt_at is None
