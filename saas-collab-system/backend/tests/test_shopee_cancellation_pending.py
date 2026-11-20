from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.commerce.models import SalesOrder, RefundReturn
from apps.integrations.adapters import MarketplaceOrderAdapter, _normalized_order_status
from apps.sales_management.services import upsert_normalized_order
from apps.sales_management.reporting import business_daily_rows
from tests.test_sales_management import create_scope, create_run


@pytest.mark.parametrize('raw,expected', [
    ('IN_CANCEL', 'cancellation_pending'), ('CANCELLED', 'cancelled'),
    ('canceled', 'cancelled'), ('READY_TO_SHIP', 'fulfilled'),
    ('CANCELLATION_REQUESTED', 'pending'),
])
def test_cancellation_requires_a_completed_platform_status(raw, expected):
    assert _normalized_order_status(raw) == expected


@pytest.mark.django_db
def test_request_withdrawal_completion_and_replay_update_original_order_day_once():
    tenant, _, store, _ = create_scope('cancel-pending')
    run = create_run(tenant, 'sales_order', 'cancel-pending')
    adapter = object.__new__(MarketplaceOrderAdapter)
    adapter.resource_type = 'sales_order'
    adapter.config = SimpleNamespace(platform='shopee')
    adapter.authorization = SimpleNamespace(store=store, region='PH')
    created = int(datetime(2026, 11, 17, 0, tzinfo=UTC).timestamp())
    record = {'order_sn':'SYNTHETIC-CANCEL', 'create_time':created, 'update_time':created,
        'currency':'PHP', 'total_amount':'938', 'item_list':[
            {'item_id':1,'model_id':1,'model_sku':'SYNTHETIC-A','model_quantity_purchased':1,'model_discounted_price':'469'},
            {'item_id':2,'model_id':2,'model_sku':'SYNTHETIC-B','model_quantity_purchased':1,'model_discounted_price':'469'}]}
    def save(raw, offset):
        payload = adapter.normalize_record({**record, 'order_status':raw, 'update_time':created+offset})
        return upsert_normalized_order(tenant=tenant, source_run=run, payload=payload)
    for raw, offset, cancelled in [('READY_TO_SHIP',1,False),('IN_CANCEL',2,False),
            ('READY_TO_SHIP',3,False),('IN_CANCEL',4,False),('CANCELLED',86400,True),('CANCELLED',86400,True)]:
        order = save(raw, offset)
        assert order.raw_status == raw
        assert SalesOrder.objects.filter(tenant=tenant).count() == 1
        assert order.items.count() == 2
        rows = business_daily_rows(SalesOrder.objects.filter(tenant=tenant), RefundReturn.objects.none())
        assert len(rows) == 1 and rows[0]['date'] == '2026-11-17'
        assert rows[0]['order_count'] == 1
        assert rows[0]['cancelled_order_count'] == int(cancelled)
        assert rows[0]['valid_order_count'] == int(not cancelled)
        assert rows[0]['gross_sales'] == (Decimal('0') if cancelled else Decimal('938'))
        assert rows[0]['units_sold'] == (0 if cancelled else 2)
    order = save('IN_CANCEL', 4)
    assert order.raw_status == 'CANCELLED' and order.normalized_status == 'cancelled'
