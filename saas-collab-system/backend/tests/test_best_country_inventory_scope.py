from datetime import timedelta

import pytest
from rest_framework.exceptions import PermissionDenied

from apps.alerts.inventory_views import build_pending_views
from apps.commerce import country_decisions as decisions
from apps.commerce.models import InventorySnapshot
from apps.integrations.models import WarehouseAuthorization
from apps.masterdata.models import CountrySiteMaster, WarehouseMaster
from apps.permissions.models import DataScope, Permission, Role, RoleResourcePolicy, UserRole
from apps.products.models import ProductSKU
from apps.supply_chain.models import DispatchBatch, domain_write
from tests.test_country_inventory_decisions import BASE, NOW, clock, facts
from tests.test_sales_management import client_for, create_run, grant, user_for
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_v2_split_dispatch import create_part, setup as split_setup


def scoped_actor(facts, label, *branches):
    tenant = facts['tenant']
    actor = user_for(tenant, label)
    grant(actor, decisions.SALES)
    grant(actor, 'sales_management.supply_summary.view')
    permission, _ = Permission.objects.get_or_create(code=decisions.INVENTORY,
        defaults={'name': decisions.INVENTORY, 'module': 'sales_management', 'action': 'view'})
    for index, config in enumerate(branches):
        role = Role.objects.create(tenant=tenant, code=f'{label}-{index}', name=f'{label}-{index}')
        role.permissions.add(permission)
        UserRole.objects.create(tenant=tenant, user=actor, role=role)
        if set(config) <= {'warehouse_ids', 'sku_ids', 'spu_ids'}:
            RoleResourcePolicy.objects.create(tenant=tenant, role=role, resource_code='commerce.inventory',
                permission_code=decisions.INVENTORY, scope_type='custom', config=config)
        else:
            DataScope.objects.create(tenant=tenant, role=role, scope_type='custom', config=config)
    return actor


def warehouse(facts, code, country='PH'):
    return WarehouseMaster.objects.create(tenant=facts['tenant'], code=code, name=code, country_code=country)


def snapshot(facts, warehouse, sku, label, *, provider=decisions.BEST, source_sku=None,
             quantity=19, minutes=20, status='success', bind=False, published=False):
    tenant = facts['tenant']
    run = create_run(tenant, 'inventory_snapshot', label, platform=provider)
    if bind:
        job = run.sync_job
        job.warehouse_authorization = WarehouseAuthorization.objects.create(tenant=tenant,
            integration_config=job.integration_config, warehouse=warehouse, provider=provider,
            external_warehouse_code=label, external_warehouse_region=warehouse.country_code,
            status='active', created_by=facts['actor'], updated_by=facts['actor'])
        job.save(update_fields=['warehouse_authorization'])
    run.status = status
    run.finished_at = NOW - timedelta(minutes=minutes - 1)
    if published:
        run.masked_log = {'decision_source': {'started_from_initial_cursor': True,
            'ended_without_cursor': True, 'all_records_valid': True}}
    run.save(update_fields=['status', 'finished_at', 'masked_log'])
    return InventorySnapshot.objects.create(tenant=tenant, warehouse=warehouse, source_run=run,
        site_code=warehouse.country_code, source_sku=source_sku or sku.sku_code, internal_sku=sku,
        on_hand_qty=quantity, available_qty=quantity, provided_quantity_fields=['available_qty', 'on_hand_qty'],
        snapshot_at_utc=NOW - timedelta(minutes=minutes), payload_hash='a' * 64)


def api_data(actor, facts, **params):
    response = client_for(actor).get(BASE, {'country_id': facts['country'].pk, **params})
    assert response.status_code == 200, response.data
    return response.data['data']


def test_provider_metadata_and_country_options_follow_inventory_grants(facts):
    best = warehouse(facts, 'Private BEST')
    other_country = CountrySiteMaster.objects.create(tenant=facts['tenant'], code='th', name='Thailand',
        country_code='TH')
    snapshot(facts, best, facts['sku'], 'best-stock')
    snapshot(facts, best, None, 'best-unmapped', source_sku='BEST-UNMAPPED')
    thailand = warehouse(facts, 'Thailand BEST', country='TH')
    snapshot(facts, thailand, facts['sku'], 'th-best')
    snapshot(facts, thailand, None, 'th-best-unmapped', source_sku=facts['sku'].sku_code, minutes=10)

    jifeng_actor = scoped_actor(facts, 'jifeng-only', {'platforms': [decisions.JIFENG]})
    data = api_data(jifeng_actor, facts)
    assert {option['id'] for option in data['countries']} == {facts['country'].pk}
    row = data['results'][0]
    assert [(item['id'], item['name']) for item in row['warehouses']] == [
        (facts['warehouse'].pk, facts['warehouse'].name)]
    assert row['available_stock'] == '40'
    assert 'unmapped_inventory' not in row['issues']

    best_actor = scoped_actor(facts, 'best-only', {'platforms': [decisions.BEST]})
    data = api_data(best_actor, facts, mapped_only='true')
    assert {option['id'] for option in data['countries']} == {facts['country'].pk, other_country.pk}
    assert data['count'] == 1
    assert data['summary']['stocked'] == 1
    row = data['results'][0]
    assert row['available_stock'] == '19'
    assert row['unmapped_inventory_excluded']
    assert [(item['id'], item['name']) for item in row['warehouses']] == [(best.pk, best.name)]

    product_actor = scoped_actor(facts, 'best-product-only',
        {'platforms': [decisions.BEST], 'sku_ids': [facts['sku'].pk]})
    assert {option['id'] for option in api_data(product_actor, facts)['countries']} == {facts['country'].pk}


def test_role_branches_do_not_mix_provider_warehouse_product_and_site(facts):
    best = warehouse(facts, 'BEST Branch')
    unknown = warehouse(facts, 'BEST Unmapped Only')
    sku_a = facts['sku']
    sku_b = ProductSKU.objects.create(tenant=facts['tenant'], spu=facts['spu'], sku_code='SKU-B')
    sku_c = ProductSKU.objects.create(tenant=facts['tenant'], spu=facts['spu'], sku_code='SKU-C')
    snapshot(facts, best, sku_b, 'best-b')
    snapshot(facts, best, sku_a, 'best-a', quantity=99)
    snapshot(facts, best, None, 'best-unknown', source_sku='BEST-UNKNOWN')
    snapshot(facts, unknown, None, 'best-unmapped-only', source_sku='UNKNOWN-ONLY')
    snapshot(facts, facts['warehouse'], sku_b, 'jifeng-b', provider=decisions.JIFENG, quantity=99)

    actor = scoped_actor(facts, 'mixed-branches',
        {'platforms': [decisions.JIFENG], 'warehouse_ids': [facts['warehouse'].pk],
         'store_ids': [facts['store'].pk], 'sku_ids': [sku_a.pk]},
        {'platforms': [decisions.BEST], 'warehouse_ids': [best.pk], 'regions': ['PH'], 'sku_ids': [sku_b.pk]},
        {'platforms': [decisions.BEST], 'warehouse_ids': [best.pk], 'regions': ['TH']},
        {'warehouse_ids': [unknown.pk], 'spu_ids': [sku_c.spu_id], 'sku_ids': [sku_c.pk]})
    rows = {row['sku_id']: row for row in api_data(actor, facts)['results']}
    assert [(item['id'], item['available_qty']) for item in rows[sku_a.pk]['warehouses']] == [
        (facts['warehouse'].pk, '40')]
    assert [(item['id'], item['available_qty']) for item in rows[sku_b.pk]['warehouses']] == [(best.pk, '19')]
    assert rows[sku_c.pk]['warehouses'] == []
    assert all('unmapped_inventory' not in row['issues'] for row in rows.values())

    context = decisions.inventory_context_for(actor, facts['country'], include_best=True)
    cached = decisions.decision_rows(actor, facts['country'], [sku_a, sku_b], inventory_context=context,
                                     include_best=True)
    for row in cached:
        assert row['warehouses'] == rows[row['sku_id']]['warehouses']
        assert row['available_stock'] == rows[row['sku_id']]['available_stock']
    with pytest.raises(PermissionDenied):
        decisions.decision_rows(facts['actor'], facts['country'], [sku_a], inventory_context=context,
                                include_best=True)


def test_best_terminal_run_is_a_sku_observation_not_a_warehouse_publication(facts, settings):
    settings.INVENTORY_COMPLETE_BATCH_READS_ENABLED = True
    best = warehouse(facts, 'BEST bounded batch')
    sku_a = facts['sku']
    sku_b = ProductSKU.objects.create(tenant=facts['tenant'], spu=facts['spu'], sku_code='NOT-QUERIED')
    snapshot(facts, best, sku_a, 'best-terminal', bind=True, quantity=0)
    snapshot(facts, facts['warehouse'], sku_a, 'jifeng-good', provider=decisions.JIFENG,
             bind=True, published=True, quantity=4, minutes=30)
    snapshot(facts, facts['warehouse'], sku_a, 'jifeng-partial', provider=decisions.JIFENG,
             bind=True, quantity=90)

    rows = {row['sku_id']: row for row in api_data(facts['actor'], facts)['results']}
    assert rows[sku_a.pk]['available_stock'] == '4'
    assert {item['id']: item['available_qty'] for item in rows[sku_a.pk]['warehouses']} == {
        facts['warehouse'].pk: '4', best.pk: '0'}
    assert rows[sku_b.pk]['available_stock'] is None
    assert rows[sku_b.pk]['inventory_complete'] is False
    assert 'missing_inventory_snapshot' in rows[sku_b.pk]['blocking_issues']


def test_latest_best_rows_never_resurrect_an_older_mapping_or_count_warehouse_twice(facts):
    wh, sku = facts['warehouse'], facts['sku']
    older = snapshot(facts, wh, sku, 'best-on-shared-warehouse', source_sku='BEST-CODE', quantity=7)
    all_row = api_data(facts['actor'], facts)['results'][0]
    assert all_row['available_stock'] == '7'
    assert all_row['source_snapshot_ids'] == [older.pk]
    actor = scoped_actor(facts, 'best-on-shared', {'platforms': [decisions.BEST], 'regions': ['PH']})

    snapshot(facts, wh, sku, 'best-latest-failed', source_sku='BEST-CODE', minutes=10, status='failed')
    row = api_data(actor, facts)['results'][0]
    assert row['available_stock'] is None
    assert 'inventory_source_incomplete' in row['blocking_issues']

    snapshot(facts, wh, None, 'best-latest-unmapped', source_sku='BEST-CODE', minutes=5, bind=True)
    assert api_data(actor, facts, mapped_only='true')['count'] == 0
    row = api_data(actor, facts)['results'][0]
    assert row['available_stock'] is None
    assert 'unmapped_inventory' in row['blocking_issues']


def test_background_decision_view_uses_the_same_best_scope_as_direct(facts):
    best = warehouse(facts, 'BEST from menu')
    snapshot(facts, best, facts['sku'], 'best-menu-observation')
    actor = scoped_actor(facts, 'best-menu-reader', {'platforms': [decisions.BEST]})
    assert api_data(actor, facts, decision_state='all')['query_state'] == 'building'
    assert build_pending_views()['completed'] == 1
    menu = api_data(actor, facts, decision_state='all')
    direct = api_data(actor, facts)
    assert menu['query_state'] == 'ready'
    assert menu['results'][0]['warehouses'] == direct['results'][0]['warehouses']
    assert menu['results'][0]['available_stock'] == direct['results'][0]['available_stock'] == '19'


def test_provider_scopes_keep_authorized_in_transit_at_unobserved_warehouses(world):
    buyer, api, shipment, carrier = split_setup(world)
    facts = {**world, 'actor': buyer}
    country = world['country']
    sku = world['sku']
    observed = warehouse(facts, 'Observed warehouse', country='US')
    snapshot(facts, observed, sku, 'jifeng-observed', provider=decisions.JIFENG)
    authorized = warehouse(facts, 'Authorized manual warehouse', country='US')
    other = warehouse(facts, 'Other manual warehouse', country='US')
    assigned_batches = {}
    for destination, quantity in ((authorized, 35), (other, 65)):
        response = create_part(api, shipment, carrier, quantity, f'manual-{destination.pk}')
        assert response.status_code == 201, response.data
        with domain_write():
            batch = DispatchBatch.objects.get(pk=response.data['data']['id'])
            batch.planned_warehouse = destination
            batch.expected_warehouse_date = NOW.date() + timedelta(days=10)
            batch.stage = 'departed'
            batch.departed_at = NOW
            batch.save()
        assigned_batches[destination.pk] = batch.pk

    for provider, include_best in ((decisions.JIFENG, False), (decisions.JIFENG, True), (decisions.BEST, True)):
        for restricted in (False, True):
            config = {'platforms': [provider], 'regions': ['US']}
            if restricted:
                config['warehouse_ids'] = [authorized.pk]
            actor = scoped_actor(facts, f'supply-{provider}-{include_best}-{restricted}', config)
            row = decisions.decision_rows(actor, country, [sku], include_best=include_best)[0]
            pipeline = row['pipeline']
            expected = 35 if restricted else 100
            assert pipeline['transporting'] == pipeline['effective_incoming'] == expected
            assert {batch['batch_id'] for batch in pipeline['shipment_outstanding']} == (
                {assigned_batches[authorized.pk]} if restricted else set(assigned_batches.values()))
            assert ('warehouse_supply_scope_incomplete' in pipeline['issues']) == restricted
            assert {item['id'] for item in row['warehouses']} == (
                {observed.pk} if provider == decisions.JIFENG and not restricted else set())
