from datetime import date, datetime, timezone
from decimal import Decimal
import pytest
from apps.finance.summary_database import collect
from apps.finance.summary_return_costs import return_costs
from tests.test_sales_management import create_scope, create_order, user_for


def test_original_order_price_is_reference_and_seller_refund_is_not_a_fee():
    from types import SimpleNamespace
    from apps.finance.summary_raw_flows import source_flows
    store = SimpleNamespace(pk=1, code='SP6TH', country_code='TH', currency='THB',
                            platform=SimpleNamespace(platform_type='shopee'))
    records = [SimpleNamespace(pk=i, store_id=1, raw_fee_name=name, fee_category='other',
        signed_amount=Decimal(value), business_date=date(2026,9,1), external_order_id='ORDER',
        currency='THB', match_status='matched') for i, (name,value) in enumerate([
            ('order_original_price','100'), ('seller_return_refund','-10'), ('escrow_amount','80')])]
    rows = source_flows({1:store}, records, [], [], [], [], date(2026,9,1), date(2026,9,30))
    assert [(r['kind'],r['status']) for r in rows] == [('sales','reference'),('refund','confirmed'),('settlement','reference')]
    assert [r['amount'] for r in rows] == ['100','-10','80']


@pytest.mark.django_db
def test_unsettled_registered_fee_is_raw_evidence_and_unregister_removes_it():
    from apps.finance.warehouse_fee_models import WarehouseFee
    tenant, _, store, warehouse = create_scope('raw-fees')
    actor=user_for(tenant,'raw-fees')
    order=create_order(tenant,store,'unsettled')
    fee=WarehouseFee.objects.create(tenant=tenant,store=store,warehouse=warehouse,order=order,
        external_order_id=order.external_order_id,country='PH',kind='order',bill_month='2026-09',
        bill_number='test',fee_item='handling',reference='test',amount=Decimal('3.1'),currency='CNY',
        business_key='f'*64,content_hash='a'*64,created_by=actor,status='registered')
    scope={'stores':[store.pk],'from':'2026-09-01','to':'2026-09-30'}
    source=collect(actor,scope)
    row=next(f for f in source['raw_flows'] if f['source_id']==f'warehouse:{fee.pk}')
    assert Decimal(row['amount'])==Decimal('-3.1') and row['period_date'] is None
    assert row['date']=='2026-09' and not any(f['kind']=='warehouse_order' for f in source['facts'])
    fee.status='draft';fee.save()
    assert not any(f['source_id']==f'warehouse:{fee.pk}' for f in collect(actor,scope)['raw_flows'])


@pytest.mark.django_db
def test_return_uses_outbound_price_and_receipt_date_and_rejects_over_return():
    from apps.sales_management.aftersales_models import AftersalesCase, WarehouseReturnReceipt, WarehouseReturnLine, ReturnAllocation
    tenant, _, store, warehouse=create_scope('return-cost',currency='CNY')
    actor=user_for(tenant,'return-cost');order=create_order(tenant,store,'returned')
    case=AftersalesCase.objects.create(tenant=tenant,store=store,order=order,source_key='test')
    receipt=WarehouseReturnReceipt.objects.create(tenant=tenant,warehouse=warehouse,return_no='R1',received_at=datetime(2026,9,12,tzinfo=timezone.utc))
    line=WarehouseReturnLine.objects.create(receipt=receipt,sku='B',received_quantity=3)
    allocation=ReturnAllocation.objects.create(line=line,case=case,case_sku='B',quantity=1)
    outbound={order.pk:[{'warehouse_id':warehouse.pk,'source_sku':'B','sku_id':1,'shipped_date':'2026-08-10',
        'quantity':2,'unit_cost':'12.000000','reasons':[],'source_flow_id':'out:1'}]}
    args=(actor,{store.pk:store},outbound,{'b':{1}},date(2026,9,1),date(2026,9,30))
    row=return_costs(*args)[0]
    assert Decimal(row['amount'])==12 and row['date']=='2026-09-12' and row['return_event']['verified']
    assert row['source_proof']['outbound_flow_ids']==['out:1']
    assert return_costs(*args)==[row]
    allocation.quantity=3;allocation.save()
    row=return_costs(*args)[0]
    assert row['amount'] is None and row['status']=='pending'
    allocation.delete()
    assert return_costs(*args)==[]
