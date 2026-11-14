from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.integrations.models import PlatformIntegrationConfig, WarehouseAuthorization
from apps.masterdata.models import WarehouseMaster
from apps.sales_management.warehouse_order_models import OrderWarehouseLookup
from apps.sales_management.warehouse_orders import request_lookup, synchronize, fetch_packages, lookup_data
from tests.test_sales_management import create_scope, create_order

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup_order(settings):
    settings.SALES_ORDER_WAREHOUSE_SYNC_ENABLED = False
    tenant, _, store, warehouse = create_scope('warehouse-lookup')
    order = create_order(tenant, store, 'lookup')
    actor = order.authorization.created_by
    actor.is_superuser = True
    actor.save(update_fields=['is_superuser'])
    settings.SALES_ORDER_WAREHOUSE_SYNC_ENABLED = True
    return order, actor, warehouse


def binding(order, actor, warehouse, suffix='1'):
    config = PlatformIntegrationConfig.objects.create(tenant=order.tenant, platform='jifeng_wms',
        account_alias='lookup-' + suffix, created_by=actor)
    return WarehouseAuthorization.objects.create(tenant=order.tenant, integration_config=config,
        warehouse=warehouse, provider='jifeng_wms', status='active', external_warehouse_code='WH-' + suffix,
        external_warehouse_region=warehouse.country_code, created_by=actor, updated_by=actor,
        oauth_expires_at=timezone.now() + timedelta(days=365),
        credential_id='FAKE-REFERENCE')


def package(order, code='WH-1', erp='ERP-1'):
    return {'platformOrderNo': order.external_order_id, 'warehouse': code, 'erpNo': erp,
        'orderNo': 'WHORDER-1', 'status': 7, 'shippedTime': '2026-09-11 03:00:00',
        'trackingNo': 'FAKE-TRACKING', 'skuList': [{'sku': 'SKU-A', 'num': 2}],
        'invoiceInfo': {'invoiceSecretKey': 'MUST-NOT-PERSIST'}, 'recipientPhone': 'MUST-NOT-PERSIST'}


def response(rows, page=1, pages=1, total=None):
    return {'data': {'rows': rows, 'pageNo': page, 'totalPage': pages,
                     'totalSize': len(rows) if total is None else total}}


def run(order, actor):
    row = request_lookup(order.pk, actor, manual=True)
    state = synchronize(row.pk, str(row.revision))
    row.refresh_from_db()
    return state, row


def test_first_sync_and_status_changes_only(settings, django_capture_on_commit_callbacks):
    settings.SALES_ORDER_WAREHOUSE_SYNC_ENABLED = True
    tenant, _, store, _ = create_scope('event-test')
    with patch('apps.sales_management.warehouse_orders.publish_lookup') as publish:
        with django_capture_on_commit_callbacks(execute=True):
            order = create_order(tenant, store, 'event')
        assert publish.call_count == 1
        row = OrderWarehouseLookup.objects.get(order=order)
        old_revision = row.revision
        with django_capture_on_commit_callbacks(execute=True):
            order.save()
            order.source_details = {'booking_sn': 'BOOK-TEST'}
            order.save(update_fields=['source_details'])
        assert publish.call_count == 1
        with django_capture_on_commit_callbacks(execute=True):
            order.raw_status = 'SHIPPED'
            order.save(update_fields=['raw_status'])
        row.refresh_from_db()
        assert row.revision != old_revision
        assert publish.call_count == 2


def test_rollback_does_not_publish(setup_order, django_capture_on_commit_callbacks):
    order, actor, _ = setup_order
    with patch('apps.sales_management.warehouse_orders.publish_lookup') as publish:
        with django_capture_on_commit_callbacks(execute=True):
            with pytest.raises(RuntimeError), transaction.atomic():
                request_lookup(order.pk, actor, manual=True)
                raise RuntimeError('rollback')
        assert not publish.called
    assert not OrderWarehouseLookup.objects.filter(order=order).exists()


def test_lookup_database_failure_does_not_rollback_order(setup_order, caplog):
    from django.db import DatabaseError
    order, _, _ = setup_order
    with patch('apps.sales_management.warehouse_orders.request_lookup',
               side_effect=DatabaseError('SECRET-MUST-NOT-LOG')):
        with transaction.atomic():
            order.raw_status = 'SHIPPED'
            order.save(update_fields=['raw_status'])
    order.refresh_from_db()
    assert order.raw_status == 'SHIPPED'
    assert 'manual retry required' in caplog.text
    assert 'SECRET-MUST-NOT-LOG' not in caplog.text


def test_broker_failure_keeps_pending_without_failing_order(setup_order, django_capture_on_commit_callbacks):
    order, actor, _ = setup_order
    with patch('apps.sales_management.tasks.synchronize_order_warehouse.apply_async', side_effect=RuntimeError('FAKE-SECRET')):
        with django_capture_on_commit_callbacks(execute=True):
            row = request_lookup(order.pk, actor, manual=True)
    row.refresh_from_db()
    assert row.status == 'pending'
    assert 'FAKE-SECRET' not in row.message


def test_unique_match_preserves_all_packages_and_sales_facts(setup_order):
    order, actor, warehouse = setup_order
    binding(order, actor, warehouse)
    before = (order.order_total_amount, order.source_details, order.raw_status)
    rows = [package(order), package(order, erp='ERP-2')]
    with patch('apps.sales_management.warehouse_orders.execute_operation', return_value=response(rows)) as execute:
        state, row = run(order, actor)
    assert state == 'matched' and row.warehouse_id == warehouse.pk
    assert len(row.snapshot['packages']) == 2
    assert row.snapshot['packages'][0]['shipped_at_utc'] == '2026-09-11T03:00:00+00:00'
    assert row.snapshot['packages'][0]['items'][0] == {'sku': 'SKU-A', 'quantity': 2}
    assert 'MUST-NOT-PERSIST' not in str(row.snapshot)
    assert 'pickup_at_utc' not in row.snapshot['packages'][0]
    assert execute.call_args.kwargs['payload']['platformOrderNo'] == order.external_order_id
    order.refresh_from_db()
    assert (order.order_total_amount, order.source_details, order.raw_status) == before


def test_all_same_country_warehouses_but_no_cross_tenant_or_country(setup_order):
    order, actor, warehouse = setup_order
    binding(order, actor, warehouse)
    other = WarehouseMaster.objects.create(tenant=order.tenant, code='PH-2', name='PH2', country_code='PH', warehouse_type='third_party')
    binding(order, actor, other, '2')
    foreign = WarehouseMaster.objects.create(tenant=order.tenant, code='TH-1', name='TH1', country_code='TH', warehouse_type='third_party')
    binding(order, actor, foreign, '3')
    def execute(**kwargs):
        auth = kwargs['authorization']
        assert auth.warehouse.country_code == 'PH' and auth.tenant_id == order.tenant_id
        return response([package(order)]) if auth.warehouse_id == warehouse.pk else response([])
    with patch('apps.sales_management.warehouse_orders.execute_operation', side_effect=execute) as mocked:
        state, row = run(order, actor)
    assert state == 'matched' and mocked.call_count == 2
    assert len(row.checks) == 2


@pytest.mark.parametrize('second', ['match', 'error', 'blocked'])
def test_multiple_matches_or_partial_errors_never_associate(setup_order, second):
    order, actor, warehouse = setup_order
    binding(order, actor, warehouse)
    other = WarehouseMaster.objects.create(tenant=order.tenant, code='PH-2', name='PH2', country_code='PH', warehouse_type='third_party')
    binding(order, actor, other, '2')
    value = response([package(order, 'WH-2')]) if second == 'match' else (
        PermissionDenied('blocked') if second == 'blocked' else TimeoutError('MUST-NOT-PERSIST'))
    with patch('apps.sales_management.warehouse_orders.execute_operation', side_effect=[response([package(order)]), value]):
        state, row = run(order, actor)
    assert state == ('conflict' if second == 'match' else 'partial')
    assert row.warehouse_id is None and row.snapshot == {}
    assert 'MUST-NOT-PERSIST' not in str(row.checks)


def test_no_match_and_unsupported_provider_are_not_success(setup_order):
    order, actor, warehouse = setup_order
    auth = binding(order, actor, warehouse)
    with patch('apps.sales_management.warehouse_orders.execute_operation', return_value=response([])):
        assert run(order, actor)[0] == 'not_found'
    auth.provider = 'other'
    auth.save(update_fields=['provider'])
    with patch('apps.sales_management.warehouse_orders.execute_operation') as execute:
        state, row = run(order, actor)
    assert state == 'partial' and not execute.called
    assert '尚未适配' in row.checks[0]['message']


def test_existing_association_only_queries_that_warehouse_and_keeps_old_snapshot_on_error(setup_order):
    order, actor, warehouse = setup_order
    binding(order, actor, warehouse)
    with patch('apps.sales_management.warehouse_orders.execute_operation', return_value=response([package(order)])):
        _, row = run(order, actor)
    snapshot = row.snapshot
    with patch('apps.sales_management.warehouse_orders.execute_operation', side_effect=TimeoutError):
        _, row = run(order, actor)
    assert row.snapshot == snapshot and row.warehouse_id == warehouse.pk
    assert lookup_data(order)['stale'] is True


def test_new_revision_fences_inflight_result(setup_order):
    order, actor, warehouse = setup_order
    binding(order, actor, warehouse)
    def execute(**kwargs):
        order.raw_status = 'CHANGED-IN-FLIGHT'
        order.save(update_fields=['raw_status'])
        return response([package(order)])
    with patch('apps.sales_management.warehouse_orders.execute_operation', side_effect=execute):
        state, row = run(order, actor)
    assert state == 'superseded' and row.status == 'pending' and row.snapshot == {}


def test_duplicate_delivery_and_manual_click_do_not_duplicate_running_job(setup_order):
    order, actor, _ = setup_order
    row = request_lookup(order.pk, actor, manual=True)
    revision = row.revision
    assert request_lookup(order.pk, actor, manual=True).revision == revision
    row.status = 'running'
    row.lease_until = timezone.now() + timedelta(minutes=5)
    row.save()
    with patch('apps.sales_management.warehouse_orders.execute_operation') as execute:
        assert synchronize(row.pk, str(revision)) == 'already_running'
    assert not execute.called


def test_complete_pagination_and_shared_credential_warehouse_filter(setup_order):
    order, actor, warehouse = setup_order
    auth = binding(order, actor, warehouse)
    pages = [response([package(order)], page=1, pages=2, total=2),
             response([package(order, 'ANOTHER-WAREHOUSE', 'ERP-OTHER')], page=2, pages=2, total=2)]
    with patch('apps.sales_management.warehouse_orders.execute_operation', side_effect=pages) as execute:
        items = fetch_packages(actor, auth, order, lambda: True)
    assert len(items) == 1 and execute.call_count == 2


@pytest.mark.parametrize('kind', ['identity', 'missing_count', 'repeated', 'missing_warehouse', 'incomplete', 'bad_time'])
def test_untrusted_or_incomplete_response_rejected(setup_order, kind):
    order, actor, warehouse = setup_order
    auth = binding(order, actor, warehouse)
    item = package(order)
    data = response([item])
    if kind == 'identity': item['platformOrderNo'] = 'DIFFERENT-ORDER'
    if kind == 'missing_count': data['data'].pop('totalSize')
    if kind == 'repeated': data = response([item, item])
    if kind == 'missing_warehouse': item.pop('warehouse')
    if kind == 'incomplete': data['data']['totalSize'] = 2
    if kind == 'bad_time': item['shippedTime'] = 'not-a-date'
    with patch('apps.sales_management.warehouse_orders.execute_operation', return_value=data):
        with pytest.raises(ValidationError):
            fetch_packages(actor, auth, order, lambda: True)


def test_api_read_is_side_effect_free_and_permissions_rechecked(setup_order):
    order, actor, warehouse = setup_order
    client = APIClient()
    client.force_authenticate(actor)
    url = f'/api/internal/commerce/orders/{order.pk}/warehouse/'
    with patch('apps.sales_management.warehouse_orders.execute_operation') as execute:
        read = client.get(url)
        assert read.status_code == 200, read.data
        assert read.data['data']['status'] == 'not_requested'
        assert not execute.called and not OrderWarehouseLookup.objects.exists()
        assert client.post(url, {}, format='json').status_code == 200
    actor.is_superuser = False
    actor.save(update_fields=['is_superuser'])
    assert client.post(url, {}, format='json').status_code == 403


def test_worker_does_not_bypass_existing_live_gate(setup_order, settings):
    order, actor, warehouse = setup_order
    binding(order, actor, warehouse)
    settings.WAREHOUSE_BUSINESS_API_ENABLED = False
    with patch('apps.integrations.warehouse_api_service.JifengWmsReadonlyClient') as network:
        state, row = run(order, actor)
    assert state == 'partial' and row.checks[0]['status'] == 'blocked'
    assert not network.called


def test_expired_warehouse_token_reports_actionable_reason_without_network(setup_order):
    order, actor, warehouse = setup_order
    auth = binding(order, actor, warehouse)
    auth.oauth_expires_at = timezone.now() - timedelta(seconds=1)
    auth.save(update_fields=['oauth_expires_at'])
    with patch('apps.sales_management.warehouse_orders.execute_operation') as execute:
        state, row = run(order, actor)
    assert state == 'partial'
    assert row.checks[0]['status'] == 'blocked'
    assert '令牌已过期' in row.checks[0]['message']
    assert not execute.called


def test_dispatcher_only_resumes_requested_records_not_historical_orders(setup_order):
    from apps.sales_management.tasks import dispatch_order_warehouse
    order, actor, _ = setup_order
    with patch('apps.sales_management.warehouse_orders.publish_lookup') as publish:
        assert dispatch_order_warehouse()['submitted'] == 0
        row = request_lookup(order.pk, actor, manual=True)
        assert dispatch_order_warehouse()['submitted'] == 1
        publish.assert_called_with(row.pk, row.revision)
        row.status, row.lease_until = 'running', timezone.now() - timedelta(seconds=1)
        row.save()
        assert dispatch_order_warehouse()['submitted'] == 1
        row.status = 'failed'
        row.save(update_fields=['status'])
        assert dispatch_order_warehouse()['submitted'] == 0


def test_cross_tenant_actor_cannot_read_or_retry(setup_order):
    from tests.test_sales_management import user_for
    order, actor, _ = setup_order
    tenant, _, _, _ = create_scope('other-tenant')
    stranger = user_for(tenant, 'other-tenant-user')
    stranger.is_superuser = True
    stranger.save(update_fields=['is_superuser'])
    client = APIClient()
    client.force_authenticate(stranger)
    url = f'/api/internal/commerce/orders/{order.pk}/warehouse/'
    assert client.get(url).status_code == 404
    assert client.post(url, {}, format='json').status_code == 404
    with pytest.raises(PermissionDenied):
        request_lookup(order.pk, stranger, manual=True)


def test_warehouse_scope_change_blocks_query_and_hides_snapshot(setup_order):
    order, actor, warehouse = setup_order
    binding(order, actor, warehouse)
    with patch('apps.sales_management.warehouse_orders.execute_operation', return_value=response([package(order)])):
        run(order, actor)
    client = APIClient()
    client.force_authenticate(actor)
    with patch('apps.sales_management.warehouse_order_api.integration_values_allowed', return_value=False):
        result = client.get(f'/api/internal/commerce/orders/{order.pk}/warehouse/').data['data']
    assert result['snapshot'] == {} and result['checks'] == []
    with patch('apps.sales_management.warehouse_orders.integration_values_allowed', return_value=False), \
            patch('apps.sales_management.warehouse_orders.execute_operation') as execute:
        assert run(order, actor)[0] == 'partial'
    assert not execute.called


def test_disabled_feature_does_not_create_jobs(setup_order, settings):
    order, _, _ = setup_order
    settings.SALES_ORDER_WAREHOUSE_SYNC_ENABLED = False
    order.raw_status = 'CHANGED-WHILE-DISABLED'
    order.save(update_fields=['raw_status'])
    assert not OrderWarehouseLookup.objects.exists()
    assert lookup_data(order)['status'] == 'disabled'


def test_business_reader_sees_snapshot_without_api_execution_access(setup_order):
    from tests.test_sales_management import user_for, grant
    from apps.permissions.services import check_user_permission
    order, actor, warehouse = setup_order
    binding(order, actor, warehouse)
    with patch('apps.sales_management.warehouse_orders.execute_operation', return_value=response([package(order)])):
        run(order, actor)
    reader = user_for(order.tenant, 'warehouse-business-reader')
    grant(reader, 'sales_management.orders.view')
    grant(reader, 'integrations.warehouse.view')
    assert not check_user_permission(reader, 'integrations.run_live_readonly')
    client = APIClient()
    client.force_authenticate(reader)
    url = f'/api/internal/commerce/orders/{order.pk}/warehouse/'
    result = client.get(url)
    assert result.status_code == 200
    assert result.data['data']['snapshot']['warehouse_code'] == warehouse.code
    assert result.data['data']['can_retry'] is False
    assert client.post(url, {}, format='json').status_code == 403


def test_reader_without_warehouse_grant_gets_no_snapshot(setup_order):
    from tests.test_sales_management import user_for, grant
    order, _, _ = setup_order
    reader = user_for(order.tenant, 'order-only-reader')
    grant(reader, 'sales_management.orders.view')
    client = APIClient()
    client.force_authenticate(reader)
    data = client.get(f'/api/internal/commerce/orders/{order.pk}/warehouse/').data['data']
    assert data['status'] == 'forbidden' and data['can_retry'] is False
    assert 'snapshot' not in data and 'checks' not in data


def test_warehouse_query_uses_bounded_nonoverlapping_time_windows(setup_order):
    from datetime import datetime
    order, actor, warehouse = setup_order
    auth = binding(order, actor, warehouse)
    now = order.created_at_utc + timedelta(days=200)
    with patch('apps.sales_management.warehouse_orders.timezone.now', return_value=now), \
            patch('apps.sales_management.warehouse_orders.execute_operation', side_effect=[
                response([package(order)]), response([package(order, erp='ERP-2')])]) as execute:
        packages = fetch_packages(actor, auth, order, lambda: True)
    assert len(packages) == 2 and execute.call_count == 2
    windows = [(datetime.fromisoformat(c.kwargs['payload']['beginTime']),
                datetime.fromisoformat(c.kwargs['payload']['endTime'])) for c in execute.call_args_list]
    assert all(end - start < timedelta(days=180) for start, end in windows)
    assert windows[1][0] == windows[0][1] + timedelta(seconds=1)
    assert windows[-1][1] == now.replace(tzinfo=None, microsecond=0)
