from types import SimpleNamespace
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from apps.finance.summary_shipped_items import shipped_items


def package(key='WH-1', **changes):
    return {'warehouse_order_no': key, 'status': '7', 'shipped_at_utc': '2026-08-31T20:00:00+00:00',
            'items': [{'sku': 'B', 'quantity': 2}], **changes}


def lookup(packages):
    return SimpleNamespace(status='matched', warehouse_id=1, snapshot={'packages': packages})


@pytest.mark.parametrize('state,label', [(2, '待生成'), (3, '待拣货'), (7, '已发货'), (9, '已取消')])
def test_jifeng_document_status_mapping(state, label):
    from apps.sales_management.warehouse_orders import jifeng_package
    assert jifeng_package({'status': state})['status_label'] == label


def test_cancelled_package_is_excluded_but_picking_is_pending():
    rows, reasons = shipped_items(lookup([package(), package('cancelled', status='9')]), 'Asia/Manila')
    assert len(rows) == 1 and not reasons
    rows, reasons = shipped_items(lookup([package(), package('picking', status='3')]), 'Asia/Manila')
    assert len(rows) == 1 and reasons


def test_shipped_items_deduplicate_and_keep_split_shipments():
    rows, reasons = shipped_items(lookup([package(), package(), package('WH-2')]), 'Asia/Manila')
    assert not reasons and len(rows) == 2
    assert sum(row['quantity'] for row in rows) == 4
    assert rows[0]['shipped_date'] == '2026-09-01'


@pytest.mark.parametrize('changes', [{'status': state} for state in ('1', '2', '3', '4', '5', '6', '8', '9', '10', '11', '99')] + [{'shipped_at_utc': None}, {'items': []}, {'items': [{'sku': 'B', 'quantity': 1.5}]}])
def test_pending_or_invalid_evidence_does_not_supply_cost(changes):
    rows, reasons = shipped_items(lookup([package(**changes)]), 'Asia/Manila')
    assert not rows and reasons


@pytest.mark.django_db
def test_cost_uses_shipped_B_not_platform_A_and_missing_evidence_is_unknown(settings):
    from tests.test_sales_management import create_scope, create_order, user_for
    from tests.test_finance_database_summary import posted_settlement
    from apps.products.models import ProductSPU, ProductSKU, ProductCostVersion
    from apps.sales_management.warehouse_order_models import OrderWarehouseLookup
    from apps.sales_management.registration_models import PendingOrderDetail
    from apps.finance.summary_database import collect
    settings.SALES_ORDER_WAREHOUSE_SYNC_ENABLED = False
    tenant, platform, store, warehouse = create_scope('shipped-cost', currency='CNY')
    actor = user_for(tenant, 'shipped-cost-user')
    order = create_order(tenant, store, 'platform-A')
    platform.platform_type = 'lazada'; platform.save()
    config = order.source_run.sync_job.integration_config
    config.platform = 'lazada'; config.save()
    posted_settlement(actor, store, order.source_run, order, Decimal('100'))
    spu = ProductSPU.objects.create(tenant=tenant, spu_code='B', product_name='B')
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code='B')
    PendingOrderDetail.objects.create(order=order, adjusted=True, source_hash='test',
        lines=[{'sku_id': sku.pk, 'quantity': 999}])
    ProductCostVersion.objects.create(tenant=tenant, sku=sku, warehouse=warehouse, version_no=1,
        status='confirmed', confirmed_cost=Decimal('12'), effective_from=datetime(2026,8,1,tzinfo=timezone.utc),
        effective_to=datetime(2026,9,3,tzinfo=timezone.utc), created_by=actor)
    ProductCostVersion.objects.create(tenant=tenant, sku=sku, warehouse=warehouse, version_no=2,
        status='confirmed', confirmed_cost=Decimal('99'), effective_from=datetime(2026,9,3,tzinfo=timezone.utc), created_by=actor)
    row = OrderWarehouseLookup.objects.create(order=order, warehouse=warehouse, status='matched', snapshot={'packages':[package()]})
    scope = {'stores':[store.pk], 'from':'2026-09-01', 'to':'2026-09-30'}
    cost = next(f for f in collect(actor, scope)['facts'] if f['kind']=='product_cost')
    assert cost['amount']=='-24.000000'
    assert cost['cost_calculation']['components'][0]['sku_id']==sku.pk
    flows = collect(actor, scope)['cost_flows']
    assert len(flows) == 1 and flows[0]['amount'] == '-24.000000'
    assert flows[0]['date'] == '2026-09-01' and flows[0]['currency'] == 'CNY'
    assert collect(actor, scope)['cost_flows'] == flows
    from apps.sales_management.aftersales_models import AftersalesCase, WarehouseReturnReceipt, WarehouseReturnLine, ReturnAllocation
    case=AftersalesCase.objects.create(tenant=tenant,store=store,order=order,source_key='cost-return')
    receipt=WarehouseReturnReceipt.objects.create(tenant=tenant,warehouse=warehouse,return_no='RETURN-1',received_at=datetime(2026,9,12,tzinfo=timezone.utc))
    received=WarehouseReturnLine.objects.create(receipt=receipt,sku='B',received_quantity=1)
    allocation=ReturnAllocation.objects.create(line=received,case=case,case_sku='B',quantity=1)
    source=collect(actor,scope)
    credit=next(f for f in source['facts'] if f.get('cost_event')=='return')
    assert Decimal(credit['amount'])==12 and credit['date']=='2026-09-12'
    assert credit['cost_conversion']['local_amount']=='12.000000'
    assert len([f for f in source['raw_flows'] if f.get('cost_event')=='return'])==1
    allocation.delete()
    row.snapshot = {'packages': [package(shipped_at_utc='2026-08-30T20:00:00+00:00')]}
    row.save()
    assert collect(actor, scope)['cost_flows'] == []
    august = collect(actor, {**scope, 'from':'2026-08-01', 'to':'2026-08-31'})
    assert len(august['cost_flows']) == 1 and august['cost_flows'][0]['date'] == '2026-08-31'
    assert august['cost_flows'][0]['amount'] == '-24.000000'
    assert not any(f['kind'] == 'product_cost' for f in august['facts'])
    row.snapshot = {'packages': [package(items=[{'sku':'missing', 'quantity':1}])]}
    row.save()
    missing_flow = collect(actor, scope)['cost_flows'][0]
    assert missing_flow['amount'] is None and missing_flow['status'] == 'pending'
    row.status='not_found';row.save()
    cost = next(f for f in collect(actor, scope)['facts'] if f['kind']=='product_cost')
    assert cost['amount'] is None and cost['status']=='pending'
