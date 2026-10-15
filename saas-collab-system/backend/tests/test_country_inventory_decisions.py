from datetime import datetime, timedelta, time, timezone as utc_timezone
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.commerce.models import InventorySnapshot
from apps.commerce.country_decisions import decision_rows, sales_windows, permission_signature
from apps.commerce.supply_pipeline import pipeline_for, open_demand
from apps.integrations.models import (HistorySyncBatch, HistorySyncSegment, SyncJob, SyncRun,
    MarketplaceStoreAuthorization, marketplace_identity_key, marketplace_store_binding_key,
    authorization_service_write)
from apps.masterdata.models import CountrySiteMaster, WarehouseMaster
from apps.products.models import ProductSPU, ProductSKU
from apps.permissions.models import DataScope, UserRole, RoleResourcePolicy
from apps.supply_chain.models import domain_write
from apps.sales_management import operating
from apps.sales_management.operating_models import OperatingOrder
from tests.test_sales_management import create_scope, create_order, create_run, grant
from tests.test_supply_chain_v2_foundation import internal_user, world, confirmed_order, shipment_payload
from tests.test_supply_chain_v2_logistics import client, setup, create, arrive, generate, checked, write as supply_write
from tests.test_operating_orders_v2 import write, OPS

BASE = '/api/internal/commerce/inventory/country-decisions/'
NOW = datetime(2026, 10, 15, 8, tzinfo=utc_timezone.utc)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(timezone, 'now', lambda: NOW)


def history_coverage(tenant, store, owner, *, lower=None, upper=None, status='success'):
    from apps.integrations.models import PlatformIntegrationConfig
    config = PlatformIntegrationConfig.objects.create(tenant=tenant, platform='shopee',
        account_alias='coverage', created_by=owner)
    external = f'coverage-store-{store.pk}'
    identity = marketplace_identity_key('shopee', store.country_code, external)
    auth = MarketplaceStoreAuthorization(tenant=tenant, integration_config=config, store=store,
        platform='shopee', region=store.country_code, platform_store_id=external,
        platform_identity_key=identity, active_platform_identity_key=identity,
        active_store_binding_key=marketplace_store_binding_key(tenant.pk, 'shopee', store.pk),
        merchant_subject_id='test', credential_id='test-reference', token_id='test-reference',
        status='active', created_by=owner, updated_by=owner)
    with authorization_service_write():
        auth.save()
    job = SyncJob.objects.create(tenant=tenant, integration_config=config, store_authorization=auth,
                                resource_type='sales_order')
    batch = HistorySyncBatch.objects.create(tenant=tenant, created_by=owner, name='Test coverage',
        idempotency_key='coverage', request_hash='a'*64, start_date=(NOW-timedelta(days=60)).date(),
        end_date=NOW.date()-timedelta(days=1), status='completed')
    segment = HistorySyncSegment.objects.create(batch=batch, sync_job=job, sequence=1, status=status,
        scope={'time_basis':'created','time_from': int((lower or NOW-timedelta(days=60)).timestamp()),
               'time_to': int((upper or NOW).timestamp())-1})
    SyncRun.objects.create(tenant=tenant, sync_job=job, history_segment=segment, run_id='coverage',
                           idempotency_key='coverage', status=status)
    return segment


def stock(tenant, warehouse, sku, *, quantity=40, suffix='stock', provided=True, source=None, hours=1):
    run = create_run(tenant, 'inventory_snapshot', suffix, platform='jifeng_wms')
    run.status = 'success'; run.save()
    return InventorySnapshot.objects.create(tenant=tenant, warehouse=warehouse, source_run=run,
        site_code=warehouse.country_code, source_sku=source or sku.sku_code, internal_sku=sku,
        on_hand_qty=quantity+10, available_qty=quantity, reserved_qty=10, in_transit_qty=8,
        provided_quantity_fields=['available_qty', 'in_transit_qty'] if provided else [],
        snapshot_at_utc=NOW-timedelta(hours=hours), payload_hash='a'*64)


def sale(tenant, store, sku, suffix, days, quantity, *, currency=None, paid=True, status='completed'):
    order = create_order(tenant, store, suffix)
    order.created_at_utc = NOW-timedelta(days=days)
    order.updated_at_utc = order.created_at_utc
    order.paid_at_utc = order.created_at_utc if paid else None
    order.normalized_status = status
    order.currency = currency or store.currency
    order.save()
    order.source_run.status = 'success'; order.source_run.save()
    line = order.items.first()
    line.internal_sku = sku; line.quantity = quantity
    line.currency = order.currency; line.line_total_amount = quantity*2
    line.save()
    return order


@pytest.fixture
def facts(db):
    tenant, platform, store, warehouse = create_scope('p2-decisions')
    country = CountrySiteMaster.objects.create(tenant=tenant, code='ph', name='菲律宾', country_code='PH')
    spu = ProductSPU.objects.create(tenant=tenant, spu_code='P2', product_name='Test product')
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code='P2-NEW', legacy_sku_code='P2-OLD', product_name='Test product')
    actor = internal_user({'tenant':tenant}, 'p2-operator', codes=(operating.VIEW, operating.MANAGE,
        'sales_management.view', 'sales_management.skus.view', 'sales_management.supply_summary.view'))
    snapshot = stock(tenant, warehouse, sku)
    sale(tenant, store, sku, 'seven', 2, 10)
    sale(tenant, store, sku, 'fifteen', 10, 20)
    sale(tenant, store, sku, 'thirty', 25, 30)
    sale(tenant, store, sku, 'usd', 2, 1, currency='USD')
    sale(tenant, store, sku, 'cancelled', 2, 100, status='cancelled')
    sale(tenant, store, sku, 'unpaid', 2, 100, paid=False)
    segment = history_coverage(tenant, store, actor)
    return locals()


def test_latest_stock_windows_currencies_and_same_formula(facts):
    f = facts; api = client(f['actor'])
    data = api.get(BASE, {'country_id': f['country'].pk, 'search': 'P2-OLD'}).data['data']
    row = data['results'][0]
    assert row['available_stock'] == '40'  # available already excludes reserved; no second subtraction.
    assert row['wms_in_transit_stock'] == '8'
    assert row['pipeline']['effective_incoming'] == 0
    assert [w['units'] for w in row['sales_windows']] == [11,31,61]
    assert row['sales_windows'][0]['amount_by_currency'] == {'PHP':'20.0000', 'USD':'2.0000'}
    assert all(w['coverage_complete'] for w in row['sales_windows'])
    assert row['suggested_quantity'] == 82
    preview = write(api, OPS+'preview/', {'country_id': f['country'].pk, 'sku_ids':[f['sku'].pk],
        'sales_start':'2026-09-15', 'sales_end':'2026-10-14', 'sales_window_days':30, 'target_days':60,
        'target_stock_sales_ratio':'2', 'include_in_transit':True}, 'p2-preview').data['data']
    assert preview['lines'][0]['suggested_quantity'] == row['suggested_quantity']
    assert row['stock_age']['status'] == 'unavailable'
    assert not row['cost_ledger_url']  # Quantity summary does not grant supplier prices.


def test_missing_quantity_zero_stale_failed_and_alias_ambiguity(facts):
    f = facts
    def current():
        return decision_rows(f['actor'],f['country'],[f['sku']])[0]
    f['snapshot'].provided_quantity_fields=[]; f['snapshot'].save()
    assert current()['available_stock'] is None
    f['snapshot'].provided_quantity_fields=['available_qty','in_transit_qty']
    f['snapshot'].available_qty=0; f['snapshot'].save()
    assert current()['available_stock'] == '0'
    newer=stock(f['tenant'],f['warehouse'],f['sku'],quantity=20,suffix='failed-latest',hours=0)
    newer.source_run.status='failed'; newer.source_run.save()
    assert current()['available_stock'] is None  # Never fall back to the older success.
    newer.source_run.status='success'; newer.source_run.save()
    other=stock(f['tenant'],f['warehouse'],f['sku'],quantity=30,suffix='old-code',source='P2-OLD',hours=0.5)
    assert 'ambiguous_inventory_aliases' in current()['issues']
    assert current()['available_stock'] is None  # Cross-run aliases are not silently discarded.
    other.internal_sku=None; other.save()
    assert 'unmapped_inventory' in current()['issues']


def test_incomplete_sales_blocks_suggestion_and_real_alerts(facts):
    f=facts; f['segment'].status='failed'; f['segment'].save()
    row=decision_rows(f['actor'],f['country'],[f['sku']])[0]
    assert row['sales_windows'][-1]['units'] == 61
    assert 'collection_coverage_unproven' in row['issues'] and row['suggested_quantity'] is None
    grant(f['actor'],'alerts.evaluate')
    response=client(type(f['actor']).objects.get(pk=f['actor'].pk)).post(BASE+'evaluate-alerts/',
        {'country_id':f['country'].pk,'sku_ids':[f['sku'].pk]},format='json')
    assert response.status_code == 200, response.data
    assert response.data['data']['created']==0 and len(response.data['data']['skipped'])==1


def test_completed_refunds_are_separate_from_sales_and_pending_refunds(facts):
    from apps.commerce.models import RefundReturn, RefundReturnItem
    f=facts
    run=create_run(f['tenant'],'refund_return','p2-refund');run.status='success';run.save()
    for index,status in enumerate(['completed','pending']):
        refund=RefundReturn.objects.create(tenant=f['tenant'],platform=f['platform'],store=f['store'],source_run=run,
            external_return_id=f'P2-REFUND-{index}',case_type='refund',raw_status=status,normalized_status=status,
            requested_at_utc=NOW-timedelta(days=2),updated_at_utc=NOW-timedelta(days=1),
            currency='PHP',refund_amount='4',payload_hash='b'*64)
        RefundReturnItem.objects.create(refund_return=refund,internal_sku=f['sku'],external_return_item_id='1',
            platform_product_id='P2',quantity=2,currency='PHP',refund_amount='4')
    row=decision_rows(f['actor'],f['country'],[f['sku']])[0]
    window=row['sales_windows'][0]
    assert window['units']==11 and window['refund_units']==2
    assert window['refund_amount_by_currency']=={'PHP':'4.0000'}
    assert row['suggested_quantity']==82


def test_warehouse_product_permissions_and_replay_after_revocation(facts):
    f=facts; actor=f['actor']; role=UserRole.objects.get(user=actor).role
    api=client(actor)
    payload={'country_id':f['country'].pk,'sku_ids':[f['sku'].pk], 'sales_start':'2026-09-15',
             'sales_end':'2026-10-14','target_stock_sales_ratio':'2'}
    response=write(api,OPS+'preview/',payload,'scoped-preview')
    assert response.status_code==200,response.data
    role.permissions.remove(role.permissions.get(code='sales_management.supply_summary.view'))
    actor=type(actor).objects.get(pk=actor.pk); api=client(actor)
    assert write(api,OPS+'preview/',payload,'scoped-preview').status_code==403
    row=api.get(BASE,{'country_id':f['country'].pk}).data['data']['results'][0]
    assert row['pipeline']['authorized'] is False and row['pipeline']['transporting'] is None
    other=ProductSKU.objects.create(tenant=f['tenant'],spu=f['spu'],sku_code='PRIVATE')
    RoleResourcePolicy.objects.create(tenant=f['tenant'],role=role,resource_code='commerce.inventory',
        permission_code='sales_management.view',scope_type='custom',config={'sku_ids':[other.pk]})
    actor=type(actor).objects.get(pk=actor.pk)
    data=client(actor).get(BASE,{'country_id':f['country'].pk}).data['data']
    assert [r['sku'] for r in data['results']]==['PRIVATE']
    assert client(actor).get(BASE+f"{f['country'].pk}/skus/{f['sku'].pk}/image/").status_code==404


def test_preview_consumption_reservation_and_plan_metadata(facts):
    f=facts; api=client(f['actor'])
    payload={'country_id':f['country'].pk,'sku_ids':[f['sku'].pk], 'sales_start':'2026-09-15',
             'sales_end':'2026-10-14','target_stock_sales_ratio':'2'}
    original=write(api,OPS,{'country_id':f['country'].pk,'source_kind':'new_goods',
        'lines':[{'sku_id':f['sku'].pk,'quantity':5}]},'manual').data['data']
    preview=write(api,OPS+'preview/',payload,'first-preview').data['data']
    assert preview['lines'][0]['suggested_quantity']==77
    body={'country_id':f['country'].pk,'source_kind':'season','preview_token':preview['preview_token'],
        'campaign':'圣诞','plan_revision':'V2','demand_start':'2026-11-01','demand_end':'2026-12-25',
        'notes':'已复核','lines':[{'sku_id':f['sku'].pk,'quantity':77}]}
    order=write(api,OPS,body,'draft')
    assert order.status_code==201,order.data
    assert order.data['data']['campaign']=='圣诞'
    assert write(api,OPS,body,'draft').data['data']['id']==order.data['data']['id']
    assert write(api,OPS,body,'duplicate').status_code==422
    assert write(api,OPS+f"{original['id']}/",{**body,'expected_version':original['version']},'rebind','patch').status_code==422
    assert open_demand(f['actor'],f['country'],[f['sku'].pk])[0][f['sku'].pk]==82
    after=write(api,OPS+'preview/',payload,'after-reservation').data['data']
    assert after['lines'][0]['suggested_quantity']==0
    assert write(api,OPS,{**body,'preview_token':after['preview_token'],'demand_end':'2026-10-01'},'invalid-period').status_code==400


def test_edit_preview_excludes_own_reservation_and_cannot_create_another_order(facts):
    f=facts;api=client(f['actor'])
    original=write(api,OPS,{'country_id':f['country'].pk,'source_kind':'new_goods',
        'lines':[{'sku_id':f['sku'].pk,'quantity':82}]},'editable-source').data['data']
    query={'country_id':f['country'].pk,'sku_ids':[f['sku'].pk], 'sales_start':'2026-09-15',
           'sales_end':'2026-10-14','target_stock_sales_ratio':'2','exclude_operating_order_id':original['id']}
    response=write(api,OPS+'preview/',query,'edit-preview')
    assert response.status_code==200,response.data
    preview=response.data['data']
    assert preview['lines'][0]['suggested_quantity']==82
    body={'country_id':f['country'].pk,'source_kind':'cycle','preview_token':preview['preview_token'],
        'lines':[{'sku_id':f['sku'].pk,'quantity':82}]}
    assert write(api,OPS,body,'cannot-create-from-edit').status_code==422
    updated=write(api,OPS+f"{original['id']}/",{**body,'expected_version':original['version']},'apply-edit-preview','patch')
    assert updated.status_code==200,updated.data
    assert OperatingOrder.objects.count()==1
    assert open_demand(f['actor'],f['country'],[f['sku'].pk])[0][f['sku'].pk]==82


def test_real_alerts_use_shared_facts_and_preserve_follow_up(facts):
    from apps.alerts.models import InventoryAlert, InventoryAlertRule
    f=facts; grant(f['actor'],'alerts.evaluate'); grant(f['actor'],'alerts.view'); grant(f['actor'],'alerts.manage')
    api=client(type(f['actor']).objects.get(pk=f['actor'].pk))
    InventoryAlertRule.objects.create(tenant=f['tenant'],rule_code='P2-LOW',alert_type='low_coverage',
        threshold_config={'coverage_days':30},severity='high',effective_at=NOW-timedelta(days=1))
    payload={'country_id':f['country'].pk,'sku_ids':[f['sku'].pk]}
    response=api.post(BASE+'evaluate-alerts/',payload,format='json')
    assert response.status_code==200,response.data
    assert response.data['data']['created']==1 and response.data['data']['notification_sent'] is False
    alert=InventoryAlert.objects.get(tenant=f['tenant'])
    assert alert.source_summary['mode']=='real_observation' and alert.available_stock==40
    follow=api.patch(f'/api/internal/alerts/inventory/{alert.pk}/follow-up/',
        {'expected_version':alert.version,'action_plan':'核查补货','due_date':'2026-10-20','status':'in_progress'},format='json')
    assert follow.status_code==200,follow.data
    api.post(BASE+'evaluate-alerts/',payload,format='json')
    alert.refresh_from_db()
    assert alert.action_plan=='核查补货' and alert.status=='in_progress' and alert.version==3


@pytest.mark.django_db
@pytest.mark.parametrize('country_code,zone,currency',[('PH','Asia/Manila','PHP'),('TH','Asia/Bangkok','THB'),('MY','Asia/Kuala_Lumpur','MYR')])
def test_country_reuse_and_zero_with_complete_coverage(country_code,zone,currency):
    tenant,_,store,warehouse=create_scope(f'p2-{country_code}',country=country_code,currency=currency)
    store.timezone=zone;store.save()
    country=CountrySiteMaster.objects.create(tenant=tenant,code=country_code.lower(),country_code=country_code,name=country_code)
    spu=ProductSPU.objects.create(tenant=tenant,spu_code='ZERO',product_name='Zero')
    sku=ProductSKU.objects.create(tenant=tenant,spu=spu,sku_code='ZERO')
    actor=internal_user({'tenant':tenant},'zero-operator',codes=('sales_management.view','sales_management.skus.view',
        'sales_management.supply_summary.view'))
    stock(tenant,warehouse,sku,quantity=0)
    history_coverage(tenant,store,actor)
    row=client(actor).get(BASE,{'country_id':country.pk}).data['data']['results'][0]
    assert row['inventory_complete'] and row['available_stock']=='0' and row['suggested_quantity']==0
    assert [w['units'] for w in row['sales_windows']]==[0,0,0]


def test_store_local_completed_day_is_used(facts):
    f=facts; f['store'].timezone='America/Los_Angeles'; f['store'].save()
    # At 00:30 Shanghai, LA has not completed Oct 14. The endpoint must use Oct 13.
    from unittest.mock import patch
    with patch('django.utils.timezone.now',return_value=datetime(2026,10,14,16,30,tzinfo=utc_timezone.utc)):
        row=client(f['actor']).get(BASE,{'country_id':f['country'].pk}).data['data']['results'][0]
    assert row['sales_windows'][0]['end_date']=='2026-10-13'


def test_pipeline_mutually_exclusive_and_eta(world):
    from apps.supply_chain import services
    from apps.supply_chain.models import DispatchBatch, InternalStockReceiptLine
    buyer,one,two,carrier,warehouse=setup(world)
    grant(buyer,'sales_management.supply_summary.view')
    buyer=type(buyer).objects.get(pk=buyer.pk)
    def project():
        return pipeline_for(buyer,world['country'],[world['sku'].pk],today=NOW.date(),target_days=60)[world['sku'].pk]
    first=project()
    assert (first['production_unshipped'],first['awaiting_dispatch'])==(2,8)
    api=client(buyer); batch,_=create(api,[one,two],carrier)
    with domain_write():
        obj=DispatchBatch.objects.get(pk=batch['id']);obj.expected_warehouse_date=NOW.date()+timedelta(days=10);obj.save()
    assert project()['effective_incoming']==8
    batch=arrive(api,batch)
    assert (project()['awaiting_dispatch'],project()['transporting'],project()['arrived_unchecked'],project()['effective_incoming'])==(0,0,8,0)
    inbound=generate(api,batch,warehouse);inbound,_=checked(api,inbound)
    confirmed=supply_write(api,f"inbound-orders/{inbound['id']}/confirm/",{'expected_version':inbound['version']},'confirm-inbound')
    assert confirmed.status_code==200,confirmed.data
    row=project()
    assert (row['arrived_unchecked'],row['received_awaiting_wms'],row['wms_received'])==(0,8,0)
    assert InventorySnapshot.objects.count()==0  # Internal receipts never create WMS stock.


def test_quantity_provenance_survives_normalizing_and_ingestion(facts):
    from apps.integrations.inventory_snapshot_contract import normalize_inventory_snapshot_record
    from apps.commerce.services import upsert_inventory_snapshot, bulk_upsert_inventory_snapshots
    f=facts
    base={'contract_version':'inventory_snapshot.v1','site_code':'PH','warehouse_id':f['warehouse'].pk,
          'source_sku':f['sku'].sku_code,'snapshot_at_utc':NOW.isoformat(),'available_qty':0}
    normalized=normalize_inventory_snapshot_record(base)
    assert normalized['provided_quantity_fields']==['available_qty']
    assert normalized['in_transit_qty']==0
    run=create_run(f['tenant'],'inventory_snapshot','ingest-zero',platform='jifeng_wms')
    row=upsert_inventory_snapshot(tenant=f['tenant'],payload=normalized,source_run=run)
    assert row.provided_quantity_fields==['available_qty'] and row.available_qty==0
    normalized['snapshot_at_utc']=(NOW+timedelta(minutes=1)).isoformat()
    bulk_upsert_inventory_snapshots(tenant=f['tenant'],payloads=[normalized],source_run=run)
    assert InventorySnapshot.objects.order_by('-pk').first().provided_quantity_fields==['available_qty']


@pytest.mark.parametrize('units,target,days,expected',[(7,8,7,8),(7,9,7,9),(7,72,7,72),(30,365,30,365),(1,8,7,2)])
def test_exact_days_never_add_one_due_to_decimal_ratio(units,target,days,expected):
    from apps.commerce.country_decisions import suggestion_quantity
    assert suggestion_quantity(units,None,0,target_days=target,window_days=days)==expected


def test_revoked_metric_access_is_redacted_in_both_order_and_history(facts):
    import json
    f=facts;api=client(f['actor'])
    preview=write(api,OPS+'preview/',{'country_id':f['country'].pk,'sku_ids':[f['sku'].pk],
        'sales_start':'2026-09-15','sales_end':'2026-10-14','target_stock_sales_ratio':'2'},'history-preview').data['data']
    created=write(api,OPS,{'country_id':f['country'].pk,'source_kind':'cycle','preview_token':preview['preview_token'],
        'lines':[{'sku_id':f['sku'].pk,'quantity':82}]},'history-order').data['data']
    role=UserRole.objects.get(user=f['actor']).role
    role.permissions.remove(role.permissions.get(code='sales_management.supply_summary.view'))
    actor=type(f['actor']).objects.get(pk=f['actor'].pk)
    data=client(actor).get(OPS+f"{created['id']}/").data['data']
    assert data['calculation_snapshot']['restricted'] is True
    assert 'available_stock' not in json.dumps(data['history'],default=str)


def test_wms_receipt_ahead_of_manual_transport_stage_blocks_double_count(world):
    from apps.supply_chain.models import DispatchBatch
    from tests.test_supply_chain_v2_wms_reconciliation import wms_line
    buyer,one,two,carrier,warehouse=setup(world)
    grant(buyer,'sales_management.supply_summary.view');buyer=type(buyer).objects.get(pk=buyer.pk)
    api=client(buyer);batch,_=create(api,[one,two],carrier)
    with domain_write():
        obj=DispatchBatch.objects.get(pk=batch['id']);obj.planned_warehouse=warehouse
        obj.expected_warehouse_date=NOW.date()+timedelta(days=3);obj.save()
    response=supply_write(api,f"dispatch-batches/{batch['id']}/stage/",{'expected_version':obj.version,
        'stage':'departed','occurred_at':'2026-10-12T01:00:00+08:00'},'depart-only')
    assert response.status_code==200,response.data
    wms_line(buyer,warehouse,world['sku'])
    row=pipeline_for(buyer,world['country'],[world['sku'].pk],today=NOW.date(),target_days=60)[world['sku'].pk]
    assert row['transporting']==8 and row['effective_incoming'] is None
    assert 'wms_receipt_overlap_unresolved' in row['issues']
