from decimal import Decimal
import pytest
from apps.supply_chain import services
from apps.permissions.models import DataScope
from tests.test_supply_chain_v2_foundation import world, internal_user, supplier_user, confirmed_order, po_payload, shipment_payload
from tests.test_supply_chain_v2_logistics import client, BASE, write
from tests.test_supply_chain_v2_costs import received_pilot, get


def test_dashboard_quantities_scope_and_country_filter(world):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    for key, qty in [('s1', 3), ('s2', 2)]:
        services.create_supplier_shipment(buyer, shipment_payload(world, order, key, number=key, lines=[{'sku_id': world['sku'].pk, 'quantity': qty}]), idempotency_key=key)
    api = client(buyer)
    response = api.get(BASE+'dashboard/')
    assert response.status_code == 200, response.data
    data = response.data['data']
    assert data['totals']['purchase_quantity'] == 10
    assert data['totals']['unshipped_quantity'] == 5
    assert data['totals']['unallocated_quantity'] == 5
    assert data['inventory']['quantity'] is None
    assert api.get(BASE+'dashboard/queue/?queue=purchases').data['count'] == 1
    assert api.get(BASE+'dashboard/?country_id='+str(world['country_ca'].pk)).status_code == 404
    outsider = internal_user(world, 'restricted', scope=DataScope.ScopeType.CUSTOM, config={'supplier_ids':[world['supplier_b'].pk]})
    assert client(outsider).get(BASE+'dashboard/').data['data']['totals']['purchase_orders'] == 0
    assert client(supplier_user(world,world['supplier'],'outside')).get(BASE+'dashboard/').status_code == 403


def test_dashboard_allocation_stages_and_current_settlement_only(world):
    buyer, api, shipment, batch, inbound = received_pilot(world)
    data = api.get(BASE+'dashboard/').data['data']
    assert data['totals']['unallocated_quantity'] == 0
    assert data['totals']['in_transit_quantity'] == 0
    assert data['totals']['at_warehouse_quantity'] == 0
    for amount, version in [('3',0),('7',1)]:
        ctx=get(api,'shipment',shipment)
        response=write(api,f'costs/shipment/{shipment.pk}/settlement/',{'expected_source_version':ctx['target']['version'],'expected_version':version,'recorded_amount':amount,'reference_number':'PAY','date':'2026-10-14','reason':'test'},f'settle-{version}')
        assert response.status_code == 200, response.data
    response=api.get(BASE+'dashboard/?section=costs')
    assert response.status_code == 200, response.data
    groups=response.data['data']['groups']
    assert Decimal(groups['supplier']['recorded']) == 7
    assert Decimal(groups['supplier']['amount']) == 20
    assert Decimal(groups['supplier']['unsettled']) == 13
    assert Decimal(groups['carrier']['amount']) == 30
    queue=api.get(BASE+'dashboard/queue/?queue=supplier&limit=1')
    assert queue.status_code==200,queue.data
    assert queue.data['count']==1 and 'kind=shipment' in queue.data['data'][0]['href']


def test_dashboard_unknown_price_is_not_zero_due(world):
    buyer=internal_user(world)
    order=confirmed_order(world,buyer)
    services.create_supplier_shipment(buyer,shipment_payload(world,order,'s',lines=[{'sku_id':world['sku'].pk,'quantity':1},{'sku_id':world['sku_b'].pk,'quantity':1}]),idempotency_key='s')
    response=client(buyer).get(BASE+'dashboard/?section=costs')
    assert response.status_code==200,response.data
    assert response.data['data']['groups']['supplier']['unknown_documents']==1


def test_dashboard_single_country_total_and_query_count_do_not_scale_per_order(world, django_assert_num_queries):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    buyer=internal_user(world)
    confirmed_order(world,buyer)
    confirmed_order(world,buyer,key='ca',payload=po_payload(world,number='CA',country=world['country_ca']))
    api=client(buyer)
    result=api.get(BASE+'dashboard/?country_id='+str(world['country_ca'].pk))
    assert result.status_code==200,result.data
    assert result.data['data']['totals']['purchase_quantity']==10
    assert len(result.data['data']['countries'])==1
    with CaptureQueriesContext(connection) as first: api.get(BASE+'dashboard/')
    for i in range(3): confirmed_order(world,buyer,key=f'more-{i}',payload=po_payload(world,number=f'MORE-{i}'))
    with CaptureQueriesContext(connection) as second: api.get(BASE+'dashboard/')
    assert len(second)<=len(first)+1
