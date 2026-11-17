from django.db import connection
from django.test.utils import CaptureQueriesContext
import pytest

from apps.flash_sales.domain import normalize_items
from apps.flash_sales.engine import run_step
from apps.flash_sales.services import submit
from tests.test_flash_sales import shop, configured, FakeShopee
from tests.test_flash_activity_pagination import reader, activity


def test_models_are_indexed_once_preserving_product_and_variant_order():
    class CountedModels(list):
        traversals = 0
        def __iter__(self):
            self.traversals += 1
            return super().__iter__()
    models = CountedModels([{'item_id': str(i), 'model_id': i * 2 + j, 'input_promotion_price': '1.25'}
                            for i in range(1, 101) for j in (0, 1)])
    result = normalize_items([{'item_id': i} for i in range(1, 102)], models)
    assert len(result) == 201
    assert [(r['item_id'], r['model_id']) for r in result[:2]] == [('1', '2'), ('1', '3')]
    assert result[-1]['item_id'] == '101' and result[-1]['model_id'] == '0'
    assert models.traversals == 1


def test_fresh_target_check_reads_only_target_window():
    rows = [activity(i) for i in range(2558)]
    target = activity(3000, kind=1)
    adapter, calls = reader(rows + [target])
    actual = adapter.activities(window=(target['start_time'] - 1, target['start_time'] + 1))
    assert actual == [target]
    assert len(calls) == 3
    assert all('start_time' in call for call in calls)


@pytest.mark.django_db
def test_target_created_after_initial_read_is_still_rejected(shop):
    configured(shop)
    user, store, _ = shop
    class ConcurrentCreation(FakeShopee):
        def slots(self):
            self.created['external'] = {**self.target, 'flash_sale_id': 30, 'status': 1}
            return super().slots()
    adapter = ConcurrentCreation()
    task = submit(user, request_id='fresh-target-guard', store_ids=[store.pk]).tasks.get()
    assert run_step(task.pk, adapter=adapter) == 'failed'
    assert adapter.calls == []
    assert not task.intents.exclude(platform_id="").exists()
    assert not task.intents.filter(reservation_key__isnull=False).exists()


@pytest.mark.django_db
def test_completed_write_receipts_are_loaded_once(shop):
    configured(shop)
    user, store, _ = shop
    task = submit(user, request_id='many-receipts', store_ids=[store.pk]).tasks.get()
    adapter = FakeShopee()
    assert run_step(task.pk, adapter=adapter) == 'queued'
    intent = task.intents.get()
    intent.items = [{'item_id': str(i), 'model_id': '0', 'price': '1.25', 'stock': 7, 'purchase_limit': 0} for i in range(1, 151)]
    intent.save(update_fields=['items'])
    adapter.products[intent.platform_id] = [{**row, 'status': 1} for row in intent.items]
    for offset in range(0, 150, 5):
        intent.writes.create(tenant_id=task.tenant_id, key=f'add:{offset}', endpoint='add_shop_flash_sale_items', payload={}, response={}, status='returned')
    with CaptureQueriesContext(connection) as queries:
        run_step(task.pk, adapter=adapter)
    reads = [q for q in queries if q['sql'].lstrip().upper().startswith('SELECT') and 'flash_sales_writeoperation' in q['sql'].lower()]
    intent.refresh_from_db()
    assert intent.status == 'succeeded'
    assert len(reads) <= 6
    assert len(adapter.calls) == 1  # Only the original create; receipts must not be replayed.
