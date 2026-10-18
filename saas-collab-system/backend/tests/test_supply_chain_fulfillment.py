from datetime import datetime, timezone
from django.db import connection
from django.test.utils import CaptureQueriesContext
from apps.supply_chain import services
from apps.supply_chain.fulfillment import prepare_orders, enrich_order, filter_orders
from apps.supply_chain.models import PurchaseOrder
from tests.test_supply_chain_v2_foundation import world, internal_user, confirmed_order, po_payload, shipment_payload, freight
from tests.test_supply_chain_v2_logistics import client, create, arrive, generate, checked, write, BASE
from apps.masterdata.models import WarehouseMaster


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
