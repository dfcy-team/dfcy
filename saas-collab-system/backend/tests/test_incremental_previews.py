from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.commerce.decision_metrics import collect_decision_metrics
from apps.commerce.models import InventorySnapshot, SalesOrderItem
from apps.integrations.missing_jobs import preview_missing_jobs
from apps.integrations.models import SyncJob, SyncRun
from apps.permissions.models import DataScope
from apps.replenishment.models import ReplenishmentRecommendation
from tests.test_commerce_fact_contract import create_order, create_run, create_tenant_scope, HASH, NOW
from tests.test_phase3_replenishment import create_sku, grant
from tests.test_sync_capability_gate import make_job, grant_workspace_view


pytestmark = pytest.mark.django_db


def test_missing_preview_is_readonly_and_does_not_duplicate_existing_disabled_job():
    job, authorization = make_job()
    user = authorization.created_by
    grant_workspace_view(user)
    job.is_enabled = False
    job.save(update_fields=["is_enabled"])
    before = (SyncJob.objects.count(), SyncRun.objects.count())
    with patch('apps.integrations.sync_services.run_sync_job', side_effect=AssertionError('No execution')):
        first = preview_missing_jobs(user)
        second = preview_missing_jobs(user)
    assert first == second
    assert first['preview_only'] and first['created_count'] == 0
    assert all(row['resource_type'] != 'sales_order' for row in first['items'])
    assert all(row['status'] == 'blocked' and row['blockers'] for row in first['items'])
    assert (SyncJob.objects.count(), SyncRun.objects.count()) == before
    assert 'credential-ref' not in str(first) and 'token-ref' not in str(first)


def test_missing_preview_enforces_permission_and_custom_subject_scope():
    job, authorization = make_job()
    user = authorization.created_by
    client = APIClient()
    url = '/api/internal/integrations/sync-jobs/missing-preview/'
    assert client.get(url).status_code == 401
    client.force_authenticate(user)
    assert client.get(url).status_code == 403
    grant_workspace_view(user)
    assert client.get(url).status_code == 200
    DataScope.objects.filter(tenant=user.tenant).update(scope_type='custom', config={'store_ids': [999999]})
    response = client.get(url)
    assert response.status_code == 403 or response.json()['data']['items'] == []


@pytest.mark.parametrize('status', ['active', 'pending', 'expired', 'error'])
def test_missing_preview_ignores_revoked_warehouse_history_but_keeps_current_issues(status):
    from apps.integrations.models import WarehouseAuthorization
    from tests.test_warehouse_api_binding_closure import _fixture

    user, warehouse, config, _ = _fixture()
    common = dict(tenant=user.tenant, warehouse=warehouse, integration_config=config,
                  provider='jifeng_wms', credential_id='FAKE_REFERENCE', created_by=user, updated_by=user)
    old = WarehouseAuthorization.objects.create(**common, status='revoked')
    current = WarehouseAuthorization.objects.create(**common, status=status)
    before = (SyncJob.objects.count(), SyncRun.objects.count(), WarehouseAuthorization.objects.count())
    rows = preview_missing_jobs(user)['items']
    assert [row['authorization_id'] for row in rows] == [current.pk]
    assert rows[0]['status'] == 'blocked'
    assert (SyncJob.objects.count(), SyncRun.objects.count(), WarehouseAuthorization.objects.count()) == before
    old.refresh_from_db()
    assert old.status == 'revoked'


def test_missing_preview_ignores_revoked_store_authorization():
    from apps.integrations.models import authorization_service_write

    _, authorization = make_job()
    user = authorization.created_by
    grant_workspace_view(user)
    with authorization_service_write():
        authorization.status = 'revoked'
        authorization.active_store_binding_key = None
        authorization.active_platform_identity_key = None
        authorization.save(update_fields=['status', 'active_store_binding_key', 'active_platform_identity_key'])
    assert preview_missing_jobs(user)['items'] == []


def test_fact_windows_exclude_unpaid_cancelled_and_current_day_and_use_latest_stock():
    tenant, platform, store, warehouse = create_tenant_scope('facts')
    sku = create_sku(tenant, 'facts')
    order = create_order(tenant, platform, store)
    order.paid_at_utc = NOW
    order.save()
    run = order.source_run
    run.status = 'success'
    run.save()
    SalesOrderItem.objects.create(sales_order=order, internal_sku=sku, external_line_id='line',
        platform_product_id='p', quantity=60, currency='PHP')
    _, inventory_run = create_run(tenant, 'inventory_snapshot', 'inventory', platform='jifeng_wms')
    inventory_run.status = 'success'
    inventory_run.save()
    as_of = datetime(2026, 9, 1, 12, tzinfo=UTC)
    for age, quantity in ((2, 90), (1, 10)):
        InventorySnapshot.objects.create(tenant=tenant, warehouse=warehouse, internal_sku=sku,
            site_code='PH', source_sku='external', available_qty=quantity, source_run=inventory_run,
            snapshot_at_utc=as_of-timedelta(hours=age), payload_hash=HASH)
    result = collect_decision_metrics(tenant=tenant, sku=sku, stores=[store], warehouses=[warehouse], as_of=as_of)
    assert [w['observed_units'] for w in result['windows']] == [60, 60, 60]
    assert result['inventory'][0]['available_qty'] == 10
    assert not result['evaluatable'] and 'collection_coverage_unproven' in result['issues']
    assert ReplenishmentRecommendation.objects.count() == 0
    order.normalized_status = 'cancelled'
    order.save()
    result = collect_decision_metrics(tenant=tenant, sku=sku, stores=[store], warehouses=[warehouse], as_of=as_of)
    assert result['windows'][0]['observed_units'] == 0
    order.normalized_status = 'completed'
    order.paid_at_utc = None
    order.save()
    assert collect_decision_metrics(tenant=tenant, sku=sku, stores=[store], warehouses=[warehouse], as_of=as_of)['windows'][0]['observed_units'] == 0
    order.paid_at_utc = as_of
    order.created_at_utc = as_of
    order.save()
    assert collect_decision_metrics(tenant=tenant, sku=sku, stores=[store], warehouses=[warehouse], as_of=as_of)['windows'][0]['observed_units'] == 0
    stale = collect_decision_metrics(tenant=tenant, sku=sku, stores=[store], warehouses=[warehouse], as_of=as_of + timedelta(days=2))
    assert 'stale_inventory_snapshot' in stale['issues']


def test_fact_preview_rejects_cross_tenant_and_does_not_generate_on_empty_data():
    tenant, _, store, warehouse = create_tenant_scope('empty-facts')
    other, _, other_store, _ = create_tenant_scope('other-facts')
    sku = create_sku(tenant, 'empty-facts')
    from apps.accounts.models import CustomUser
    user = CustomUser.objects.create_user(username='fact-user', tenant=tenant, user_type='internal')
    grant(user, 'replenishment.evaluate')
    client = APIClient()
    client.force_authenticate(user)
    body = {'sku_id': sku.id, 'store_ids': [store.id], 'warehouse_ids': [warehouse.id]}
    url = '/api/internal/replenishment/facts-preview/'
    response = client.post(url, body, format='json')
    assert response.status_code == 200
    assert 'no_sales_facts' in response.json()['data']['issues']
    assert not response.json()['data']['evaluatable']
    body['store_ids'] = [other_store.id]
    assert client.post(url, body, format='json').status_code == 403
    assert ReplenishmentRecommendation.objects.count() == 0


def test_fact_preview_requires_all_dimensions_in_one_permission_scope():
    tenant, _, store, warehouse = create_tenant_scope('scoped-facts')
    sku = create_sku(tenant, 'scoped-facts')
    from apps.accounts.models import CustomUser
    user = CustomUser.objects.create_user(username='limited-fact-user', tenant=tenant, user_type='internal')
    grant(user, 'replenishment.evaluate', scope_type='custom', config={'sku_ids': [sku.id]})
    client = APIClient()
    client.force_authenticate(user)
    body = {'sku_id': sku.id, 'store_ids': [store.id], 'warehouse_ids': [warehouse.id]}
    url = '/api/internal/replenishment/facts-preview/'
    assert client.post(url, body, format='json').status_code == 403
    DataScope.objects.filter(tenant=tenant).update(config={
        'sku_ids': [sku.id], 'store_ids': [store.id], 'warehouse_ids': [warehouse.id],
    })
    assert client.post(url, body, format='json').status_code == 200
    assert client.post(url, {**body, 'average_daily_sales': 999}, format='json').status_code == 400


def test_sync_query_evidence_does_not_certify_collection_coverage():
    from apps.integrations.adapters import MockPlatformAdapter
    from apps.integrations.sync_services import run_sync_job

    class LocalEvidenceAdapter(MockPlatformAdapter):
        execution_mode = 'live_readonly'
        scope = {'time_from': 100, 'time_to': 200, 'token': 'DO_NOT_COPY_TEST_VALUE'}

        def validate_configuration(self, job):
            return None

    job, _ = make_job()
    with patch('apps.integrations.sync_services.require_sync_read_capability', return_value=None), \
         patch('apps.integrations.sync_services.archive_raw_page'):
        run, _ = run_sync_job(job, adapter=LocalEvidenceAdapter(), idempotency_key='evidence-only')
    evidence = run.masked_log['decision_source']
    assert evidence['time_from'] == 100 and evidence['time_to'] == 200
    assert evidence['started_from_initial_cursor'] is True
    assert evidence['ended_without_cursor'] is False
    assert evidence['coverage_certified'] is False
    assert 'DO_NOT_COPY_TEST_VALUE' not in str(run.masked_log)
