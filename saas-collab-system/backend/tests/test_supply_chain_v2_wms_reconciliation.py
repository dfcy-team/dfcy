from datetime import datetime, timezone

import pytest
from rest_framework.test import APIClient

from apps.commerce.models import InboundRecord, InventorySnapshot
from apps.integrations.models import PlatformIntegrationConfig, SyncJob, SyncRun
from apps.masterdata.models import WarehouseMaster
from apps.permissions.models import DataScope, Permission, RoleResourcePolicy, UserRole
from apps.supply_chain.models import BusinessEvent, DispatchBatch, WmsReceiptAllocation
from tests.test_supply_chain_v2_foundation import confirmed_order, internal_user, po_payload, shipment_payload, world
from tests.test_supply_chain_v2_logistics import arrive, checked, client, create, generate, setup, write


BASE = '/api/internal/supply-chain/v2/'
NOW = datetime(2026, 10, 13, 2, tzinfo=timezone.utc)


def grant_sales_view(user, *, warehouse_ids=None):
    permission, _ = Permission.objects.update_or_create(code='sales_management.view', defaults={
        'name': 'sales_management.view', 'module': 'sales_management', 'action': 'view', 'description': 'test'})
    role = UserRole.objects.get(user=user).role
    role.permissions.add(permission)
    if warehouse_ids is not None:
        RoleResourcePolicy.objects.update_or_create(tenant=user.tenant, role=role,
            resource_code='commerce.inventory', permission_code='sales_management.view', defaults={
                'scope_type': 'custom', 'config': {'warehouse_ids': warehouse_ids}})


def wms_line(user, warehouse, sku, *, number='WMS-1', quantity=20, site='US', run_status='success', failed=0):
    config = PlatformIntegrationConfig.objects.create(tenant=user.tenant, platform='jifeng_wms',
        account_alias=f'auth-{number}', created_by=user)
    job = SyncJob.objects.create(tenant=user.tenant, integration_config=config, resource_type='inbound')
    run = SyncRun.objects.create(tenant=user.tenant, sync_job=job, run_id=f'run-{number}',
        idempotency_key=f'key-{number}', status=run_status, failed_count=failed)
    return InboundRecord.objects.create(tenant=user.tenant, site_code=site, warehouse=warehouse,
        internal_sku=sku, source_run=run, external_inbound_id=number, external_line_id='1',
        inbound_type='purchase', source_sku=sku.sku_code, planned_quantity=quantity,
        received_quantity=quantity, status='received', updated_at_utc=NOW)


def confirmed_receipt(world, buyer, rows, carrier, warehouse, *, quantities=None):
    api = client(buyer)
    batch, _ = create(api, rows, carrier, key='wms-batch')
    for index, stage in enumerate(['departed', 'arrived_port', 'arrived_warehouse']):
        response = write(api, f"dispatch-batches/{batch['id']}/stage/", {
            'expected_version': batch['version'], 'stage': stage,
            'occurred_at': f'2026-10-12T0{index+1}:00:00+08:00'}, f'eta-stage-{index}')
        assert response.status_code == 200, response.data
        batch = response.data['data']
    inbound = generate(api, batch, warehouse)
    inbound, _ = checked(api, inbound, quantities=quantities)
    response = write(api, f"inbound-orders/{inbound['id']}/confirm/",
        {'expected_version': inbound['version']}, 'wms-confirm')
    assert response.status_code == 200, response.data
    return api, response.data['data']


@pytest.mark.django_db
def test_expected_warehouse_date_is_audited_and_closed_at_arrival(world):
    buyer, first, second, carrier, warehouse = setup(world)
    api = client(buyer)
    body = {'shipment_ids': [first.pk], 'shipment_versions': [{'id': first.pk, 'version': first.version}],
        'freight_company_id': carrier.pk, 'freight_number': 'FREIGHT-ETA', 'notes': 'ETA test',
        'expected_warehouse_date': '2026-11-01'}
    response = write(api, 'dispatch-batches/', body, 'eta-create')
    assert response.status_code == 201, response.data
    batch = response.data['data']
    assert str(batch['expected_warehouse_date']) == '2026-11-01'
    response = api.patch(BASE + f"dispatch-batches/{batch['id']}/", {
        'expected_version': batch['version'], 'expected_warehouse_date': '2026-11-04',
        'freight_company_id': carrier.pk, 'freight_number': 'FREIGHT-001', 'notes': '整批发运'},
        format='json', HTTP_IDEMPOTENCY_KEY='eta-edit')
    assert response.status_code == 200, response.data
    batch = response.data['data']
    for index, stage in enumerate(['departed', 'arrived_port']):
        response = write(api, f"dispatch-batches/{batch['id']}/stage/", {
            'expected_version': batch['version'], 'stage': stage,
            'occurred_at': f'2026-10-12T0{index+1}:00:00+08:00'}, f'eta-stage-{index}')
        assert response.status_code == 200, response.data
        batch = response.data['data']
    updated = {'expected_version': batch['version'], 'expected_warehouse_date': '2026-11-08', 'reason': '船期调整'}
    response = write(api, f"dispatch-batches/{batch['id']}/expected-warehouse-date/", updated, 'eta-post-departure')
    assert response.status_code == 200, response.data
    assert str(response.data['data']['expected_warehouse_date']) == '2026-11-08'
    replay = write(api, f"dispatch-batches/{batch['id']}/expected-warehouse-date/", updated, 'eta-post-departure')
    assert replay.status_code == 200
    changed = {**updated, 'expected_warehouse_date': '2026-11-10'}
    assert write(api, f"dispatch-batches/{batch['id']}/expected-warehouse-date/", changed,
        'eta-post-departure').status_code == 422
    current = replay.data['data']
    final_stage = write(api, f"dispatch-batches/{current['id']}/stage/", {
        'expected_version': current['version'], 'stage': 'arrived_warehouse',
        'occurred_at': '2026-10-12T03:00:00+08:00'}, 'eta-arrival')
    current = final_stage.data['data']
    rejected = write(api, f"dispatch-batches/{current['id']}/expected-warehouse-date/",
        {'expected_version': current['version'], 'expected_warehouse_date': '2026-11-12', 'reason': 'late'}, 'eta-after-arrival')
    assert rejected.status_code == 422
    assert DispatchBatch.objects.get(pk=current['id']).stage == 'arrived_warehouse'
    assert BusinessEvent.objects.filter(aggregate_type='dispatchbatch', aggregate_id=current['id'],
        action='expected_warehouse_date_updated').count() == 1


@pytest.mark.django_db
def test_wms_allocations_enforce_both_quantity_caps_scope_and_append_only_unlink(world):
    buyer = internal_user(world, username='wms-buyer', codes=('supply.v2.view', 'supply.v2.manage', 'sales_management.view'))
    grant_sales_view(buyer)
    first_order = confirmed_order(world, buyer)
    from tests.test_supply_chain_v2_logistics import freight
    from apps.supply_chain.services import create_supplier_shipment
    first = create_supplier_shipment(
        buyer, shipment_payload(world, first_order, 'wms-shipment-1'), idempotency_key='wms-shipment-1')
    second_order = confirmed_order(world, buyer, key='wms-po-2', payload=po_payload(world, number='PO-WMS-2'))
    second = create_supplier_shipment(
        buyer, shipment_payload(world, second_order, 'wms-shipment-2', number='SH-WMS-2'), idempotency_key='wms-shipment-2')
    carrier = freight(world)
    warehouse = WarehouseMaster.objects.create(tenant=world['tenant'], code='wms-us', name='WMS US', country_code='US')
    api, inbound = confirmed_receipt(world, buyer, [first, second], carrier, warehouse, quantities=[3, 3])
    wms = wms_line(buyer, warehouse, world['sku'], quantity=5)
    before_snapshots = InventorySnapshot.objects.count()
    line_a, line_b = inbound['lines']
    payload = {'inbound_line_id': line_a['id'], 'wms_line_id': wms.pk, 'quantity': 3, 'notes': '箱数核对'}
    response = write(api, f"inbound-orders/{inbound['id']}/wms-allocations/", payload, 'wms-link-a')
    assert response.status_code == 201, response.data
    allocation_id = response.data['data']['id']
    replay = write(api, f"inbound-orders/{inbound['id']}/wms-allocations/", payload, 'wms-link-a')
    assert replay.status_code == 201 and replay.data['data']['id'] == allocation_id
    assert write(api, f"inbound-orders/{inbound['id']}/wms-allocations/", {**payload, 'quantity': 2}, 'wms-link-a').status_code == 422
    local_over = {**payload, 'wms_line_id': wms.pk, 'quantity': 1}
    assert write(api, f"inbound-orders/{inbound['id']}/wms-allocations/", local_over, 'wms-link-local-over').status_code == 422
    wms_over = {**payload, 'inbound_line_id': line_b['id'], 'quantity': 3}
    assert write(api, f"inbound-orders/{inbound['id']}/wms-allocations/", wms_over, 'wms-link-wms-over').status_code == 422
    state = api.get(BASE + f"inbound-orders/{inbound['id']}/wms-reconciliation/")
    assert state.status_code == 200 and state.data['data'][0]['allocated_quantity'] == 3
    assert InboundRecord.objects.get(pk=wms.pk).received_quantity == 5
    assert InventorySnapshot.objects.count() == before_snapshots
    allocation = WmsReceiptAllocation.objects.get(pk=allocation_id)
    bad_remove = {'expected_version': allocation.version, 'reason': ''}
    assert write(api, f"inbound-orders/{inbound['id']}/wms-allocations/{allocation_id}/deactivate/", bad_remove, 'wms-remove-bad').status_code == 400
    remove = {'expected_version': allocation.version, 'reason': 'WMS 行复核后不匹配'}
    response = write(api, f"inbound-orders/{inbound['id']}/wms-allocations/{allocation_id}/deactivate/", remove, 'wms-remove')
    assert response.status_code == 200 and response.data['data']['is_active'] is False
    replay = write(api, f"inbound-orders/{inbound['id']}/wms-allocations/{allocation_id}/deactivate/", remove, 'wms-remove')
    assert replay.status_code == 200
    allocation.refresh_from_db()
    assert not allocation.is_active and allocation.version == 2
    assert BusinessEvent.objects.filter(aggregate_type='wmsreceiptallocation', aggregate_id=allocation_id,
        action='deactivated').count() == 1


@pytest.mark.django_db
def test_wms_candidate_scope_and_source_run_health_are_enforced(world):
    buyer, shipment, _, carrier, warehouse = setup(world)
    grant_sales_view(buyer)
    api, inbound = confirmed_receipt(world, buyer, [shipment], carrier, warehouse, quantities=[2])
    good = wms_line(buyer, warehouse, world['sku'], number='WMS-GOOD', quantity=2)
    failed = wms_line(buyer, warehouse, world['sku'], number='WMS-FAILED', quantity=2, run_status='failed')
    from apps.supply_chain import logistics, wms_reconciliation
    assert [row['id'] for row in wms_reconciliation.candidates(buyer,
        logistics.inbound_for(buyer, inbound['id']), inbound['lines'][0]['id'])] == [good.pk]
    other_warehouse = WarehouseMaster.objects.create(tenant=world['tenant'], code='wms-other', name='Other', country_code='US')
    hidden = wms_line(buyer, other_warehouse, world['sku'], number='WMS-HIDDEN', quantity=2)
    restricted = internal_user(world, username='wms-limited', codes=('supply.v2.view', 'supply.v2.manage', 'sales_management.view'))
    grant_sales_view(restricted, warehouse_ids=[other_warehouse.pk])
    limited_api = client(restricted)
    response = limited_api.get(BASE + f"inbound-orders/{inbound['id']}/wms-candidates/", {'inbound_line_id': inbound['lines'][0]['id']})
    assert response.status_code == 200 and response.data['data'] == []
    assert failed.pk != good.pk and hidden.pk != good.pk
