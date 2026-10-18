from datetime import datetime, timezone
from collections import Counter
from django.db import connection
from django.test.utils import CaptureQueriesContext
from apps.supply_chain import services
from apps.supply_chain.fulfillment import prepare_orders, enrich_order, filter_orders
from apps.supply_chain.models import PurchaseOrder
from tests.test_supply_chain_v2_foundation import world, internal_user, confirmed_order, po_payload, shipment_payload, freight
from tests.test_supply_chain_v2_logistics import client, create, arrive, generate, checked, write, BASE
from apps.masterdata.models import WarehouseMaster
from apps.permissions.models import DataScope


def progress(order):
    order=PurchaseOrder.objects.get(pk=order.pk)
    return enrich_order(order, services.purchase_snapshot(order), related=True)


def test_progress_requires_each_purchased_sku_not_just_total_quantity(world):
    buyer=internal_user(world)
    order=confirmed_order(world,buyer,payload=po_payload(world,lines=[{'sku_id':world['sku'].pk,'quantity':1,'unit_price':'2'},{'sku_id':world['sku_b'].pk,'quantity':1,'unit_price':'2'}]))
    services.create_supplier_shipment(buyer,shipment_payload(world,order,'over-one',lines=[{'sku_id':world['sku'].pk,'quantity':2}]),idempotency_key='over-one')
    data=progress(order)
    assert data['fulfillment']['stage']=='partial_shipment'
    assert data['fulfillment']['shipped_quantity']==2 and data['fulfillment']['unshipped_quantity']==1
    assert filter_orders(PurchaseOrder.objects.all(),'partial_shipment').count()==1
    assert filter_orders(PurchaseOrder.objects.all(),'awaiting_dispatch').count()==0
    assert [line['unshipped_quantity'] for line in data['lines']]==[0,1]
    shipment=order.supplier_shipments.get()
    create(client(buyer),[shipment],freight(world))
    after=progress(order)['fulfillment']
    assert after['dispatched_quantity']==2 and after['undispatched_quantity']==1
    assert after['unreceived_quantity']==2


def test_arrival_does_not_count_as_received_and_references_are_own_quantities(world):
    buyer=internal_user(world);api=client(buyer)
    order=confirmed_order(world,buyer,payload=po_payload(world,lines=[{'sku_id':world['sku'].pk,'quantity':4,'unit_price':'2'}]))
    shipment=services.create_supplier_shipment(buyer,shipment_payload(world,order,'s'),idempotency_key='s')
    assert progress(order)['fulfillment']['stage']=='awaiting_dispatch'
    batch,_=create(api,[shipment],freight(world))
    batch=arrive(api,batch)
    assert progress(order)['fulfillment']['stage']=='awaiting_inbound'
    assert filter_orders(PurchaseOrder.objects.all(),'awaiting_inbound').count()==1
    assert progress(order)['fulfillment']['received_quantity']==0
    warehouse=WarehouseMaster.objects.create(tenant=world['tenant'],code='flow-wh',name='Flow warehouse',country_code='US')
    inbound=generate(api,batch,warehouse)
    inbound,_=checked(api,inbound)
    assert progress(order)['fulfillment']['received_quantity']==0
    response=write(api,f"inbound-orders/{inbound['id']}/confirm/",{'expected_version':inbound['version']},'confirm')
    assert response.status_code==200,response.data
    data=progress(order)
    assert data['fulfillment']['stage']=='completed' and data['fulfillment']['received_quantity']==4
    assert filter_orders(PurchaseOrder.objects.all(),'completed').count()==1
    assert len(data['flow_relations']['shipments'])==1
    assert data['flow_relations']['batches'][0]['quantity']==4


def test_extra_sku_does_not_complete_original_purchase_and_list_filter_is_scoped(world):
    buyer=internal_user(world);order=confirmed_order(world,buyer)
    services.create_supplier_shipment(buyer,shipment_payload(world,order,'extra',lines=[{'sku_id':world['sku_b'].pk,'quantity':100,'unit_price':'1'}]),idempotency_key='extra')
    data=progress(order)
    assert data['fulfillment']['stage']=='awaiting_shipment'
    assert data['fulfillment']['extra_shipped_quantity']==100
    response=client(buyer).get(BASE+'purchase-orders/',{'workflow':'awaiting_shipment','country_code':'US'})
    assert response.status_code==200 and response.data['count']==1
    assert client(buyer).get(BASE+'purchase-orders/',{'workflow':'completed'}).data['count']==0
    assert client(buyer).get(BASE+'purchase-orders/',{'workflow':'bogus'}).status_code==400


def test_batch_progress_queries_are_bounded(world):
    buyer=internal_user(world)
    orders=[confirmed_order(world,buyer,key=str(n),payload=po_payload(world,number=f'FLOW-{n}')) for n in range(12)]
    with CaptureQueriesContext(connection) as capture:
        prepare_orders(orders)
    assert len(capture)<=4
    assert all(row._read_fulfillment['stage']=='awaiting_shipment' for row in orders)


def test_extra_sku_departure_stage_agrees_with_filter(world):
    buyer=internal_user(world);api=client(buyer);order=confirmed_order(world,buyer)
    services.create_supplier_shipment(buyer,shipment_payload(world,order,'ordered',lines=[{'sku_id':world['sku'].pk,'quantity':10}]),idempotency_key='ordered')
    extra=services.create_supplier_shipment(buyer,shipment_payload(world,order,'extra-only',number='EXTRA-ONLY',lines=[{'sku_id':world['sku_b'].pk,'quantity':1,'unit_price':'1'}]),idempotency_key='extra-only')
    batch,_=create(api,[extra],freight(world))
    result=write(api,f"dispatch-batches/{batch['id']}/stage/",{'expected_version':batch['version'],'stage':'departed','occurred_at':'2026-10-12T01:00:00+08:00'},'depart-extra')
    assert result.status_code==200,result.data
    assert progress(order)['fulfillment']['stage']=='in_transit'
    assert filter_orders(PurchaseOrder.objects.all(),'in_transit').count()==1
    assert filter_orders(PurchaseOrder.objects.all(),'awaiting_dispatch').count()==0


def test_shipment_sku_options_are_paged_and_search_old_code(world):
    buyer=internal_user(world);api=client(buyer)
    sku=world['sku'];sku.legacy_sku_code='OLD-SEARCH';sku.save()
    response=api.get(BASE+'shipment-options/',{'search':'OLD-SEARCH','limit':1})
    assert response.status_code==200,response.data
    assert response.data['data']['count']==1
    assert [r['id'] for r in response.data['data']['skus']]==[sku.pk]
    assert api.get(BASE+'shipment-options/',{'limit':101}).status_code==422
    assert api.get(BASE+'shipment-options/',{'offset':-1}).status_code==422
    assert api.get(BASE+'shipment-options/',{'limit':1,'offset':1}).data['data']['offset']==1


def test_purchase_list_supplier_date_filters_and_stage_counts(world):
    buyer=internal_user(world); api=client(buyer)
    draft=services.create_purchase_order(buyer,po_payload(world,number='FILTER-DRAFT',order_date='2026-10-10'),idempotency_key='filter-draft')
    confirmed=confirmed_order(world,buyer,key='filter-confirmed',payload=po_payload(world,number='FILTER-CONFIRMED',order_date='2026-10-12'))
    confirmed_order(world,buyer,key='filter-other-supplier',payload=po_payload(world,number='FILTER-OTHER',supplier=world['supplier_b'],order_date='2026-10-12'))
    params={'supplier_id':world['supplier'].pk,'order_date_from':'2026-10-10','order_date_to':'2026-10-12','include_workflow_counts':'1'}
    response=api.get(BASE+'purchase-orders/',params)
    assert response.status_code==200,response.data
    counts=response.data['workflow_counts']
    assert response.data['count']==2 and counts['all']==2 and counts['pending']==2
    assert counts['draft']==1 and counts['awaiting_shipment']==1
    assert api.get(BASE+'purchase-orders/',{**params,'workflow':'pending'}).data['count']==2
    assert api.get(BASE+'purchase-orders/',{**params,'workflow':'awaiting_shipment'}).data['count']==1
    assert api.get(BASE+'purchase-orders/',{**params,'order_date_from':'2026-10-11'}).data['workflow_counts']['draft']==0
    assert api.get(BASE+'purchase-orders/',{'supplier_id':'invalid'}).status_code==400
    assert api.get(BASE+'purchase-orders/',{'order_date_from':'2026-10-13','order_date_to':'2026-10-12'}).status_code==400
    expected_orders=list(PurchaseOrder.objects.filter(pk__in=[draft.pk,confirmed.pk]))
    prepare_orders(expected_orders)
    expected=Counter(order._read_fulfillment['stage'] for order in expected_orders)
    assert {stage:counts[stage] for stage in expected}==dict(expected)


def test_purchase_filter_counts_respect_internal_supplier_scope(world):
    buyer=internal_user(world,scope=DataScope.ScopeType.CUSTOM,config={'supplier_ids':[world['supplier'].pk]})
    confirmed_order(world,buyer,key='scope-visible',payload=po_payload(world,number='SCOPE-VISIBLE'))
    other=internal_user(world,'other-scope-owner')
    confirmed_order(world,other,key='scope-hidden',payload=po_payload(world,number='SCOPE-HIDDEN',supplier=world['supplier_b']))
    response=client(buyer).get(BASE+'purchase-orders/',{'supplier_id':world['supplier_b'].pk,'include_workflow_counts':'1'})
    assert response.status_code==200,response.data
    assert response.data['count']==0 and response.data['workflow_counts']['all']==0
