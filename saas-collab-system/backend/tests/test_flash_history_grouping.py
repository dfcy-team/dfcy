import pytest
from django.utils import timezone

from apps.flash_sales.models import Batch, StoreTask
from apps.flash_sales.tasks import prepare_post_sync
from tests.test_flash_sales import shop

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("sync_status", ["queued", "succeeded", "failed"])
def test_post_sync_stays_in_parent_history_and_manual_sync_remains_separate(shop, sync_status):
    user, store, client = shop
    parent = Batch.objects.create(tenant=user.tenant, actor=user, source="manual", operation="run",
                                  request_id="parent", payload_hash="test", finished_at=timezone.now())
    task = StoreTask.objects.create(tenant=user.tenant, store=store, batch=parent,
                                    status="succeeded", completed=1, finished_at=timezone.now())
    prepare_post_sync(parent.pk)
    child = Batch.objects.get(source="post_sync")
    child.tasks.update(status=sync_status, message="sync result")
    manual = Batch.objects.create(tenant=user.tenant, actor=user, source="manual", operation="sync",
                                  request_id="manual-sync", payload_hash="test")
    StoreTask.objects.create(tenant=user.tenant, store=store, batch=manual)
    data = client.get('/api/internal/marketing/flash-sales/workspace/').data['data']
    assert data['batch_total'] == 2
    assert {row['id'] for row in data['batches']} == {str(parent.pk), str(manual.pk)}
    main = next(row for row in data['batches'] if row['id'] == str(parent.pk))
    assert main['tasks'][0]['status'] == 'succeeded'
    assert main['tasks'][0]['sync'] == {'status':sync_status, 'message':'sync result'}
    assert Batch.objects.filter(pk=child.pk).exists()
