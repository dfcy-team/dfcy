from decimal import Decimal
from datetime import UTC, datetime
import pytest
from apps.commerce.models import SalesOrder, RefundReturn, RefundReturnItem, SalesOrderItem
from apps.masterdata.models import StoreMaster
from apps.products.models import ProductSPU, ProductSKU
from apps.sales_management.reporting import business_daily_rows, sku_report
from tests.test_sales_management import create_scope, create_order, create_run, NOW, user_for, grant, client_for

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('timezone, timestamp', [
    ('Asia/Manila', datetime(2026, 9, 3, 16, 30, tzinfo=UTC)),
    ('America/Los_Angeles', datetime(2026, 9, 5, 6, 30, tzinfo=UTC)),
])
def test_report_days_follow_store_local_filter_dates(timezone, timestamp):
    tenant, platform, store, _ = create_scope('local-report')
    store.timezone = timezone
    store.save()
    order = create_order(tenant, store, 'local-day')
    order.created_at_utc = timestamp
    order.business_date = timestamp.date()
    order.save()
    refund = RefundReturn.objects.create(
        tenant=tenant, platform=platform, store=store, sales_order=order,
        source_run=create_run(tenant, 'refund_return', 'local-day'),
        external_return_id='local-day', case_type='return_refund', raw_status='COMPLETED',
        normalized_status='completed', requested_at_utc=timestamp, updated_at_utc=timestamp,
        currency='PHP', refund_amount=20, payload_hash='a'*64)
    RefundReturnItem.objects.create(refund_return=refund, seller_sku=order.items.get().seller_sku,
        external_return_item_id='local-item', quantity=1, currency='PHP', refund_amount=20)
    user = user_for(tenant, 'local-day-viewer')
    grant(user, 'sales_management.view')
    data = client_for(user).get('/api/internal/commerce/overview/', {
        'date_from': '2026-09-04', 'date_to': '2026-09-04'}).json()['data']
    assert [row['date'] for row in data['order_daily']] == ['2026-09-04']
    orders = SalesOrder.objects.filter(tenant=tenant)
    refunds = RefundReturn.objects.filter(tenant=tenant)
    daily = business_daily_rows(orders, refunds)
    assert len(daily) == 1
    assert daily[0]['date'] == '2026-09-04'
    assert daily[0]['units_sold'] == 2
    assert daily[0]['net_sales'] == 80
    trend = sku_report(orders, refunds)[2]
    assert len(trend) == 1 and trend[0]['date'] == '2026-09-04'
    assert Decimal(trend[0]['refund_amount']['PHP']) == 20


def test_reports_count_orders_once_and_do_not_mix_cancelled_or_foreign_facts():
    tenant, platform, store, _ = create_scope('report-new')
    order = create_order(tenant, store, 'report-normal', '100')
    second = create_order(tenant, store, 'report-cancel', '50')
    second.normalized_status = 'cancelled'; second.save()
    item = order.items.get()
    cancelled = second.items.get(); cancelled.seller_sku = item.seller_sku; cancelled.save()
    SalesOrderItem.objects.create(sales_order=order, external_line_id='extra', platform_product_id=item.platform_product_id,
                                 seller_sku=item.seller_sku, quantity=1, line_total_amount=10, currency='PHP')
    run = create_run(tenant, 'refund_return', 'report-refund')
    refund = RefundReturn.objects.create(tenant=tenant, platform=platform, store=store, sales_order=order, source_run=run,
        external_return_id='report-r', case_type='return_refund', raw_status='COMPLETED', normalized_status='completed',
        requested_at_utc=NOW, updated_at_utc=NOW, currency='PHP', refund_amount=20, payload_hash='a'*64)
    RefundReturnItem.objects.create(refund_return=refund, seller_sku=item.seller_sku, external_return_item_id='ri', quantity=1, currency='PHP', refund_amount=20)
    foreign, _, hidden, _ = create_scope('foreign-report-new')
    create_order(foreign, hidden, 'hidden-report-new', '99999')
    user = user_for(tenant, 'new-report-viewer'); grant(user, 'sales_management.skus.view'); grant(user, 'sales_management.view')
    client = client_for(user)
    response = client.get('/api/internal/commerce/sales/skus/', {'report':'true','page_size':1})
    assert response.status_code == 200
    data = response.json()['data']; row = data['results'][0]
    assert data['count'] == 1
    assert row['valid_order_count'] == 1 and row['order_count'] == 2
    assert Decimal(str(row['gross_sales'])) == 110 and Decimal(str(row['total_sales'])) == 160
    assert row['units_sold'] == 3 and row['total_units'] == 5 and row['refund_units'] == 1
    assert Decimal(str(row['refund_amount'])) == 20
    trend = data['trend'][0]
    assert trend['units_sold']['PHP'] == '3'
    assert trend['total_units']['PHP'] == '5'
    assert trend['valid_order_count']['PHP'] == '1'
    assert trend['order_count']['PHP'] == '2'
    assert trend['refund_units']['PHP'] == '1'
    assert Decimal(trend['total_sales']['PHP']) == 160
    assert client.get('/api/internal/commerce/sales/skus/', {'report':'true','sku':'no-match'}).json()['data']['currency_groups'] == []
    assert client.get('/api/internal/commerce/sales/skus/', {'report':'true','grouping':'unsafe'}).status_code == 400
    overview = client.get('/api/internal/commerce/overview/').json()['data']
    assert len(overview['order_daily']) == 1
    daily = overview['order_daily'][0]
    assert daily['order_count'] == 2 and daily['valid_order_count'] == 1
    assert Decimal(str(daily['average_order_value'])) == 75
    business = business_daily_rows(SalesOrder.objects.filter(tenant=tenant), RefundReturn.objects.filter(tenant=tenant))[0]
    assert business['units_sold'] == 5
    assert business['order_count'] == 2
    assert business['cancellation_rate'] == Decimal('0.5')
    assert business['refund_rate'] == Decimal('0.2')


def test_product_grouping_uses_internal_identity_and_retains_unmapped_store_boundaries():
    tenant, platform, store, _ = create_scope('report-group')
    other = StoreMaster.objects.create(tenant=tenant, platform=platform, code='other', name='other', country_code='PH', currency='PHP', timezone='Asia/Manila')
    first = create_order(tenant, store, 'group-first').items.get()
    second = create_order(tenant, other, 'group-second').items.get()
    second.seller_sku = first.seller_sku; second.save()
    orders = SalesOrder.objects.filter(tenant=tenant); refunds = RefundReturn.objects.none()
    assert len(sku_report(orders, refunds, 'product')[0]) == 2
    spu = ProductSPU.objects.create(tenant=tenant, spu_code='report-spu', product_name='report')
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code='report-sku')
    for item in (first,second):
        item.internal_spu=spu; item.internal_sku=sku; item.save()
    assert len(sku_report(orders, refunds, 'store')[0]) == 2
    rows, groups, _ = sku_report(orders, refunds, 'product')
    assert len(rows) == 1 and rows[0]['order_count'] == 2
    assert rows[0]['units_sold'] == 4
