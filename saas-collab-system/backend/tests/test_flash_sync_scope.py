from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from rest_framework.exceptions import ValidationError

from apps.flash_sales import engine
from apps.flash_sales.models import Intent, WriteOperation
from apps.flash_sales.services import submit
from tests.test_flash_activity_pagination import reader, activity
from tests.test_flash_sales import shop, configured, FakeShopee

pytestmark = pytest.mark.django_db


def test_store_sync_reads_only_current_and_future(shop):
    user, store, _ = shop
    task = submit(user, request_id='active-sync', store_ids=[store.pk], operation='sync').tasks.get()
    class Adapter:
        def activities(self, *, window, kinds):
            assert kinds == (1, 2) and window is None
            return []
    assert engine.run_step(task.pk, adapter=Adapter()) == 'succeeded'


def test_history_sync_uses_store_local_inclusive_date_boundaries(shop):
    user, store, client = shop
    response = client.post('/api/internal/marketing/flash-sales/batches/', {
        'request_id':'history-sync', 'store_ids':[store.pk], 'operation':'sync', 'sync_scope':'history',
        'date_from':'2026-11-01', 'date_to':'2026-11-02'}, format='json')
    assert response.status_code == 202
    from apps.flash_sales.models import Batch
    task = Batch.objects.get(pk=response.data['data']['id']).tasks.get()
    start = int(datetime(2026, 11, 1, tzinfo=ZoneInfo('Asia/Manila')).timestamp())
    end = int(datetime(2026, 11, 3, tzinfo=ZoneInfo('Asia/Manila')).timestamp()) - 1
    assert task.snapshot['sync_window'] == [start, end]
    class Adapter:
        def activities(self, *, window, kinds):
            assert kinds == (3,) and window == [start, end]
            return []
    assert engine.run_step(task.pk, adapter=Adapter()) == 'succeeded'


@pytest.mark.parametrize('start,end', [(None,None),('2026-11-03','2026-11-01'),('bad','2026-11-01')])
def test_history_sync_rejects_missing_or_invalid_dates(shop, start, end):
    user, store, _ = shop
    with pytest.raises(ValidationError):
        submit(user, request_id='invalid-history', store_ids=[store.pk], operation='sync',
               sync_scope='history', date_from=start, date_to=end)


def test_active_source_falls_back_to_recent_history_and_stops_on_first_match():
    rows = [dict(activity(1,kind=1),item_count=0),dict(activity(2,kind=2),item_count=0),
            dict(activity(10),item_count=1),dict(activity(20),item_count=1)]
    adapter, calls = reader(rows)
    assert next(adapter.candidate_activities({},lambda:None))['flash_sale_id'] == 20
    assert len(calls) == 3


def test_history_range_excludes_both_adjacent_days():
    rows = [activity(i,start=start) for i,start in enumerate([99,100,199,200])]
    adapter, calls = reader(rows)
    assert [r['start_time'] for r in adapter.activities(window=(100,199),kinds=(3,))] == [100,199]
    assert len(calls) == 1


def test_stock_checks_reuse_source_read_only_within_one_step(shop):
    user, store, _ = shop
    configured(shop)
    task = engine.claim(submit(user, request_id='stock-source-read', store_ids=[store.pk]).tasks.get().pk)
    adapter = FakeShopee()
    rows = [{**adapter.source[0], 'item_id':str(i), 'model_id':'0', 'available_stock':3} for i in [100,101,102]]
    adapter.source = rows
    adapter.products['20'] = [{**rows[2], 'stock':7, 'status':1}]
    adapter.created['20'] = {**adapter.target,'flash_sale_id':20,'status':1}
    intent = Intent.objects.create(tenant=user.tenant,store=store,task=task,source_id='10',platform_id='20',
        slot_id='999',target=adapter.target,owns_activity=True,status='adding',items=[{**r,'stock':7} for r in rows])
    WriteOperation.objects.create(tenant=user.tenant,intent=intent,key='add:0',endpoint='add_shop_flash_sale_items',
        status='returned',payload={},response={'rejections':[{'item_id':str(i),'model_id':'0','reason':'stock','stock_rejected':True} for i in [100,101]]})
    reads = []
    original = adapter.items
    def items(pk):
        reads.append(pk)
        return original(pk)
    adapter.items = items
    engine.advance_create(task,intent,adapter)
    assert reads == ['20','10']
    assert intent.status == 'succeeded'
