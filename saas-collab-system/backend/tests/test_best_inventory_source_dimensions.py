from datetime import timedelta
from hashlib import sha256
from unittest.mock import MagicMock, patch

import pytest
from django.db import connection

from apps.commerce import country_decisions as decisions
from apps.commerce.models import InventorySnapshot
from apps.integrations.models import SyncJob
from apps.masterdata.models import WarehouseMaster
from apps.tenants.models import Tenant
from tests.test_country_inventory_decisions import NOW, facts
from tests.test_sales_management import create_run


def dimension_queryset(ids):
    qs = MagicMock()
    qs.values_list.return_value.__getitem__.return_value = ids
    return qs


@pytest.mark.parametrize(('run_count', 'warehouse_count', 'fallback'), [
    (2000, 1000, False), (2001, 1, True), (1, 1001, True),
])
def test_best_dimension_boundaries(run_count, warehouse_count, fallback):
    actor = MagicMock(tenant_id=17)
    warehouses = dimension_queryset(list(range(warehouse_count)))
    runs = dimension_queryset(list(range(run_count)))
    with patch.object(decisions.SyncRun.objects, 'filter', return_value=runs) as run_filter, \
         patch.object(decisions.InventorySnapshot.objects, 'filter') as facts, \
         patch.object(decisions, '_provider_facts', return_value=MagicMock()) as joined:
        facts.return_value.filter.return_value = 'bounded-source'
        result = decisions._best_country_inventory_source(actor, MagicMock(country_code='PH'), 'now', warehouses)
    if fallback:
        joined.assert_called_once_with(actor, (decisions.BEST,))
        assert result == joined.return_value.filter.return_value
    else:
        joined.assert_not_called()
        assert result == 'bounded-source'
        facts.return_value.filter.assert_called_once_with(
            source_run_id__in=list(range(run_count)), warehouse_id__in=list(range(warehouse_count)))
    run_filters = run_filter.call_args.kwargs
    assert run_filters == {'tenant_id': 17, 'sync_job__tenant_id': 17,
        'sync_job__integration_config__tenant_id': 17, 'sync_job__resource_type': 'inventory_snapshot',
        'sync_job__integration_config__platform': decisions.BEST}
    runs.values_list.assert_called_once_with('pk', flat=True)
    assert runs.values_list.return_value.__getitem__.call_args.args == (slice(None, 2001),)
    assert warehouses.values_list.return_value.__getitem__.call_args.args == (slice(None, 1001),)


@pytest.mark.parametrize('empty_runs,empty_warehouses', [(True, False), (False, True), (True, True)])
def test_empty_best_dimensions_do_not_read_inventory(empty_runs, empty_warehouses):
    actor = MagicMock(tenant_id=17)
    warehouse_ids = [] if empty_warehouses else [31]
    run_ids = [] if empty_runs else [21]
    warehouses = dimension_queryset(warehouse_ids)
    with patch.object(decisions.SyncRun.objects, 'filter', return_value=dimension_queryset(run_ids)), \
         patch.object(decisions.InventorySnapshot.objects, 'filter') as facts:
        result = decisions._best_country_inventory_source(actor, MagicMock(country_code='PH'), 'now', warehouses)
    assert result is facts.return_value.none.return_value
    facts.return_value.none.assert_called_once_with()


def test_best_source_matches_joined_identity_set_across_tenant_and_latest_edges(facts):
    tenant, warehouse, sku = facts['tenant'], facts['warehouse'], facts['sku']
    active_other = WarehouseMaster.objects.create(tenant=tenant, code='BEST-ACTIVE-2', name='Active 2',
        country_code='PH', warehouse_type=warehouse.warehouse_type)
    inactive = WarehouseMaster.objects.create(tenant=tenant, code='BEST-INACTIVE', name='Inactive',
        country_code='PH', warehouse_type=warehouse.warehouse_type, status='inactive')
    foreign = Tenant.objects.create(name='Foreign inventory tenant', code='foreign-inventory-test')
    foreign_warehouse = WarehouseMaster.objects.create(tenant=foreign, code='BEST-FOREIGN', name='Foreign',
        country_code='PH', warehouse_type=warehouse.warehouse_type)

    def add_snapshot(target, label, at, *, tenant_override=tenant, run_tenant=tenant,
                     job_tenant=tenant, config_tenant=tenant, status='success', mapped=True):
        run = create_run(tenant, 'inventory_snapshot', label, platform=decisions.BEST)
        job = run.sync_job
        run.status = status
        run.save(update_fields=['status'])
        record = InventorySnapshot.objects.create(tenant=tenant,
            warehouse=target if target.tenant_id == tenant.pk else warehouse, source_run=run,
            site_code='PH', source_sku='EDGE-SKU' if label in {'best-old', 'best-failed-unmapped'} else label,
            internal_sku=sku if mapped else None,
            snapshot_at_utc=at, payload_hash=sha256(label.encode()).hexdigest())
        # Simulate legacy direct-SQL writes. The normal validated manager
        # correctly prevents these anomalies; database FK/unique keys stay on.
        with connection.cursor() as cursor:
            for model, pk, changed_tenant in (
                (type(run), run.pk, run_tenant),
                (SyncJob, job.pk, job_tenant),
                (type(job.integration_config), job.integration_config_id, config_tenant),
            ):
                if changed_tenant != tenant:
                    table = connection.ops.quote_name(model._meta.db_table)
                    cursor.execute(f'UPDATE {table} SET tenant_id=%s WHERE id=%s', [changed_tenant.pk, pk])
            if target.tenant_id != tenant.pk or tenant_override != tenant:
                cursor.execute('UPDATE inventory_snapshot SET warehouse_id=%s, tenant_id=%s WHERE id=%s',
                               [target.pk, tenant_override.pk, record.pk])
        return record

    old = add_snapshot(warehouse, 'best-old', NOW - timedelta(minutes=2))
    failed_latest = add_snapshot(warehouse, 'best-failed-unmapped', NOW - timedelta(minutes=1),
        status='failed', mapped=False)
    add_snapshot(active_other, 'best-active-2', NOW - timedelta(minutes=3))
    add_snapshot(inactive, 'best-inactive', NOW)
    add_snapshot(foreign_warehouse, 'best-foreign-warehouse', NOW)
    add_snapshot(warehouse, 'best-foreign-run', NOW, run_tenant=foreign)
    add_snapshot(warehouse, 'best-foreign-job', NOW, job_tenant=foreign)
    add_snapshot(warehouse, 'best-foreign-config', NOW, config_tenant=foreign)
    add_snapshot(warehouse, 'best-foreign-fact-tenant', NOW, tenant_override=foreign)

    country_warehouses = WarehouseMaster.objects.filter(tenant=tenant, country_code__iexact='PH', status='active')
    old_join = decisions._provider_facts(facts['actor'], (decisions.BEST,)).filter(
        warehouse__in=country_warehouses, snapshot_at_utc__lte=NOW)
    bounded = decisions._best_country_inventory_source(facts['actor'], facts['country'], NOW, country_warehouses)
    assert set(old_join.values_list('pk', flat=True)) == set(bounded.values_list('pk', flat=True))
    assert set(old_join.values_list('pk', flat=True)) == {old.pk, failed_latest.pk} | set(
        InventorySnapshot.objects.filter(warehouse=active_other).values_list('pk', flat=True))
    from apps.sales_management.inventory_queries import materialized_latest_inventory
    assert set(materialized_latest_inventory(old_join).values_list('pk', flat=True)) == set(
        materialized_latest_inventory(bounded).values_list('pk', flat=True))
    latest_ids = set(materialized_latest_inventory(bounded).values_list('pk', flat=True))
    assert failed_latest.pk in latest_ids and old.pk not in latest_ids


def test_best_latest_uses_unhinted_materialization_and_jifeng_keeps_wrapper():
    source = MagicMock()
    with patch('apps.sales_management.inventory_queries.materialized_latest_inventory', return_value='flat') as flat, \
         patch('apps.sales_management.inventory_queries.latest_country_inventory', return_value='wrapped') as wrapped:
        assert decisions._latest_country_inventory_for_provider(decisions.BEST, source) == 'flat'
        flat.assert_called_once_with(source)
        wrapped.assert_not_called()
        assert decisions._latest_country_inventory_for_provider(decisions.JIFENG, source) == 'wrapped'
        wrapped.assert_called_once_with(source)
