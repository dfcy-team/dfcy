from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError

from apps.sales_management.aftersales import calendar_deadline, refresh_case, ingest_receipt, allocate_line, track_source
from apps.sales_management.aftersales_models import AftersalesCase, WarehouseReturnReceipt, ReturnAllocation
from tests.test_sales_management import create_scope, create_order, user_for, grant, client_for


pytestmark = pytest.mark.django_db


@pytest.fixture
def case_data():
    tenant, _, store, warehouse = create_scope('aftersales')
    user = user_for(tenant, 'aftersales-user')
    grant(user, 'sales_management.returns.view')
    grant(user, 'sales_management.aftersales.manage')
    order = create_order(tenant, store, 'aftersales')
    order.normalized_status = 'cancelled'
    order.save(update_fields=['normalized_status'])
    case = track_source(order, requires_return=True)
    return user, warehouse, order, case


def test_deadline_is_two_calendar_months_in_business_timezone():
    assert calendar_deadline(datetime(2026, 12, 31, 3, tzinfo=UTC)) == datetime(2027, 2, 28, 3, tzinfo=UTC)
    assert calendar_deadline(datetime(2026, 10, 22, 3, tzinfo=UTC)) == datetime(2026, 12, 22, 3, tzinfo=UTC)


def receipt(order, warehouse, quantity=1, number='RETURN-1'):
    return {'return_no': number, 'platform_order_no': order.external_order_id,
            'tracking_no': '', 'received_at': '2026-09-01T03:00:00Z',
            'lines': [{'sku': 'SKU-aftersales', 'received_quantity': quantity}]}


def test_partial_receipt_and_late_receipt_repair_status_without_erasing_timeout(case_data):
    user, warehouse, order, case = case_data
    case.pending_since = datetime(2026, 7, 31, 3, tzinfo=UTC)
    case.due_at = calendar_deadline(case.pending_since)
    case.save()
    refresh_case(case, now=datetime(2026, 10, 1, tzinfo=UTC))
    assert case.return_status == 'failed'
    timed_out = case.timed_out_at
    ingest_receipt(user, warehouse, receipt(order, warehouse), auto_match=True)
    case.refresh_from_db()
    assert case.return_status == 'failed'  # One outstanding unit remains overdue.
    ingest_receipt(user, warehouse, receipt(order, warehouse, number='RETURN-2'), auto_match=True)
    case.refresh_from_db()
    assert case.return_status == 'received'
    assert case.timed_out_at == timed_out


def test_partial_before_deadline_and_receipt_idempotency(case_data):
    user, warehouse, order, case = case_data
    original = case.pending_since
    ingest_receipt(user, warehouse, receipt(order, warehouse), auto_match=True)
    ingest_receipt(user, warehouse, receipt(order, warehouse), auto_match=True)
    case.refresh_from_db()
    assert case.return_status == 'partial'
    assert case.pending_since == original
    assert WarehouseReturnReceipt.objects.count() == 1
    assert ReturnAllocation.objects.count() == 1


def test_wrong_sku_remains_unallocated_and_preserves_received_fact(case_data):
    user, warehouse, order, case = case_data
    value = receipt(order, warehouse, quantity=2)
    value['lines'][0]['sku'] = 'WRONG-SKU'
    row, _ = ingest_receipt(user, warehouse, value, source='api')
    case.refresh_from_db()
    assert row.lines.get().received_quantity == 2
    assert not ReturnAllocation.objects.exists()
    assert case.return_status == 'pending'


@pytest.mark.parametrize('conflict', [False, True])
def test_warehouse_legacy_sku_requires_unique_identity_and_preserves_raw_line(case_data, conflict):
    from apps.products.models import ProductSPU, ProductSKU
    user, warehouse, order, case = case_data
    spu = ProductSPU.objects.create(tenant=user.tenant, spu_code='RETURN', product_name='Return')
    ProductSKU.objects.create(tenant=user.tenant, spu=spu, sku_code='SKU-aftersales',
                              legacy_sku_code='HY174-Khaki-70-150')
    if conflict:
        ProductSKU.objects.create(tenant=user.tenant, spu=spu, sku_code='OTHER',
                                  legacy_sku_code='HY174-Khaki-70-150')
    value = receipt(order, warehouse, quantity=2)
    value['received_at'] = None  # The real warehouse samples omit arrival time.
    value['lines'][0]['sku'] = 'HY174-Khaki-70-150'
    row, _ = ingest_receipt(user, warehouse, value, source='api')
    ingest_receipt(user, warehouse, value, source='api')
    assert row.lines.get().sku == 'HY174-Khaki-70-150'
    assert row.received_at is None
    case.refresh_from_db()
    if conflict:
        assert not ReturnAllocation.objects.exists()
        assert case.return_status == 'pending'
    else:
        allocation = ReturnAllocation.objects.get(case=case)
        assert allocation.case_sku == 'SKU-aftersales'
        assert allocation.quantity == 2
        assert case.return_status == 'received'


def test_shared_parcel_requires_manual_split_and_cannot_be_counted_twice(case_data):
    user, warehouse, order, case = case_data
    case.tracking_no = 'SHARED-PARCEL'
    case.save()
    other = AftersalesCase.objects.create(tenant=user.tenant, store=order.store, order=order,
        source_key='synthetic-second-return', requires_return=True,
        expected_skus={'SKU-aftersales': 2}, tracking_no='SHARED-PARCEL')
    value = receipt(order, warehouse, quantity=2)
    value['tracking_no'] = 'SHARED-PARCEL'
    row, _ = ingest_receipt(user, warehouse, value, source='api')
    assert not ReturnAllocation.objects.exists()
    line = row.lines.get()
    for target in (case, other):
        allocate_line(user, line.pk, target, 'SKU-aftersales', 1,
            reason='核对同包裹两笔售后', expected_version=row.version)
        row.refresh_from_db()
    ingest_receipt(user, warehouse, value, source='api')
    assert list(line.allocations.order_by('pk').values_list('quantity', flat=True)) == [1, 1]
    with pytest.raises(ValidationError):
        allocate_line(user, line.pk, other, 'SKU-aftersales', 1,
            reason='重复分配', expected_version=row.version)


def test_api_receipt_quantity_increase_tops_up_once(case_data):
    user, warehouse, order, case = case_data
    ingest_receipt(user, warehouse, receipt(order, warehouse), source='api')
    ingest_receipt(user, warehouse, receipt(order, warehouse, quantity=2), source='api')
    ingest_receipt(user, warehouse, receipt(order, warehouse, quantity=2), source='api')
    case.refresh_from_db()
    assert case.return_status == 'received'
    assert ReturnAllocation.objects.get(case=case).quantity == 2


def test_manual_split_can_add_to_same_order_without_duplicate_allocation(case_data):
    user, warehouse, order, case = case_data
    row, _ = ingest_receipt(user, warehouse, receipt(order, warehouse, quantity=2), auto_match=False)
    line = row.lines.get()
    allocate_line(user, line.pk, case, 'SKU-aftersales', 1, reason='先核对一件', expected_version=row.version)
    row.refresh_from_db()
    allocate_line(user, line.pk, case, 'SKU-aftersales', 1, reason='补核对第二件', expected_version=row.version)
    assert ReturnAllocation.objects.get(case=case).quantity == 2


def test_later_cancellation_preserves_the_existing_warehouse_case(case_data):
    user, warehouse, previous, _ = case_data
    order = create_order(user.tenant, previous.store, 'later-cancelled')
    case = track_source(order, from_warehouse=True)
    order.normalized_status = 'cancelled'
    order.save(update_fields=['normalized_status'])
    changed = track_source(order, requires_return=True)
    assert changed.pk == case.pk and changed.source_key == f'cancelled:{order.pk}'
    assert AftersalesCase.objects.filter(order=order).count() == 1


def test_unknown_receipt_line_returns_not_found(case_data):
    user, _, _, case = case_data
    response = client_for(user).post('/api/internal/commerce/aftersales/receipts/999999/allocate/',
        {'source_key': case.source_key, 'sku': 'SKU-aftersales', 'quantity': 1,
         'expected_version': 1, 'reason': '核对不存在的记录'}, format='json')
    assert response.status_code == 404


def test_unshipped_and_unknown_cancellations_do_not_timeout(case_data):
    _, _, order, case = case_data
    case.requires_return = False
    case.save()
    refresh_case(case)
    assert case.return_status == 'not_required'
    case.requires_return = None
    case.save()
    refresh_case(case, now=datetime(2030, 1, 1, tzinfo=UTC))
    assert case.return_status == 'unknown'


def test_missing_order_and_ambiguous_order_stay_unmatched(case_data):
    user, warehouse, order, _ = case_data
    value = receipt(order, warehouse)
    value['platform_order_no'] = 'NOT-IN-LOCAL'
    row, _ = ingest_receipt(user, warehouse, value, auto_match=True)
    assert not row.lines.first().allocations.exists()
    assert row.lines.first().received_quantity == 1


def test_manual_allocation_prevents_overallocation_and_cross_tenant_link(case_data):
    user, warehouse, order, case = case_data
    row, _ = ingest_receipt(user, warehouse, receipt(order, warehouse), auto_match=False)
    line = row.lines.first()
    allocate_line(user, line.pk, case, 'SKU-aftersales', 1, reason='核对原运单', expected_version=row.version)
    with pytest.raises(ValidationError):
        allocate_line(user, line.pk, case, 'SKU-aftersales', 2, reason='超量', expected_version=row.version)
    other = user_for(create_scope('aftersales-other')[0], 'other-operator')
    with pytest.raises(ValidationError):
        ingest_receipt(other, warehouse, receipt(order, warehouse))


def test_read_page_contains_cancellations_without_creating_fake_refunds(case_data):
    user, _, order, _ = case_data
    before = AftersalesCase.objects.count()
    response = client_for(user).get('/api/internal/commerce/aftersales/')
    assert response.status_code == 200
    rows = response.json()['data']['results']
    assert any(row['source_key'] == f'cancelled:{order.pk}' and row['refund_amount'] is None for row in rows)
    assert AftersalesCase.objects.count() == before


def test_unbound_sync_is_blocked_even_when_called_directly(case_data):
    user, _, _, _ = case_data
    response = client_for(user).post('/api/internal/commerce/aftersales/sync/', {}, format='json')
    assert response.status_code == 400
    assert '仓库' in response.json()['message']


def test_return_client_checks_warehouse_and_does_not_guess_integer_status():
    from types import SimpleNamespace
    from apps.integrations.readonly_clients import JifengWmsReadonlyClient
    client = JifengWmsReadonlyClient.__new__(JifengWmsReadonlyClient)
    client.authorization = SimpleNamespace(external_warehouse_code='PH-ONLY')
    client.now = lambda: datetime(2026, 10, 23, tzinfo=UTC)
    data = {'returnId': 'WMS-1', 'trackingNo': 'TRACK-1', 'warehouseCode': 'PH-ONLY', 'status': 999,
            'skuList': [{'sku': 'SKU-1', 'returnCount': 500, 'receiveCount': 4, 'goodCount': 0, 'badCount': 1}]}
    client._signed_post = Mock(return_value={'code': 0, 'data': data})
    result = client.fetch_return_detail(tracking_no='TRACK-1')
    assert result['received_at'] is None
    assert result['lines'] == []
    data['finishTime'] = '2026-10-01T08:00:00+08:00'
    data['status'] = 1
    result = client.fetch_return_detail(tracking_no='TRACK-1')
    assert result['lines'][0]['received_quantity'] == 4
    assert result['received_at'] == '2026-10-01T00:00:00+00:00'
    data.pop('finishTime')
    data['status'] = 4
    assert client.fetch_return_detail(tracking_no='TRACK-1')['lines'][0]['received_quantity'] == 4
    data['skuList'][0].pop('receiveCount')
    with pytest.raises(ValidationError):
        client.fetch_return_detail(tracking_no='TRACK-1')
    client._signed_post.assert_called_with('/api/inbound/return/getSingle', {'trackingNo': 'TRACK-1'})
    data['warehouseCode'] = 'OTHER'
    with pytest.raises(ValidationError):
        client.fetch_return_detail(tracking_no='TRACK-1')


def test_api_received_quantity_does_not_invent_arrival_date(case_data):
    user, warehouse, order, case = case_data
    value = receipt(order, warehouse, quantity=2)
    value['received_at'] = None
    row, _ = ingest_receipt(user, warehouse, value, source='api')
    case.refresh_from_db()
    assert case.return_status == 'received'
    assert row.received_at is None
    with pytest.raises(ValidationError):
        ingest_receipt(user, warehouse, value, source='file')


def test_cancelled_order_uses_unique_reverse_tracking_and_matched_warehouse(case_data):
    from apps.sales_management.warehouse_order_models import OrderWarehouseLookup
    _, warehouse, order, case = case_data
    case.requires_return = None
    case.save()
    order.source_details = {'platform_logistics': {'order_sn': order.external_order_id,
        'packages': [{'tracking_number': 'OUTBOUND', 'failed_delivery_return': {'tracking_number': 'REVERSE'}}]}}
    order.save()
    OrderWarehouseLookup.objects.create(order=order, warehouse=warehouse, status='matched',
        snapshot={'packages': [{'shipped_at_utc': '2026-09-01T00:00:00Z'}]})
    tracked = track_source(order)
    assert tracked.tracking_no == 'REVERSE'
    assert tracked.warehouse_id == warehouse.pk
    assert tracked.requires_return is True
    tracked.expectation_reviewed = True
    tracked.tracking_no = 'MANUAL'
    tracked.save()
    assert track_source(order).tracking_no == 'MANUAL'


def test_reverse_tracking_never_uses_outbound_or_ambiguous_numbers(case_data):
    from apps.sales_management.aftersales import return_tracking_number
    _, _, order, _ = case_data
    order.source_details = {'platform_logistics': {'order_sn': order.external_order_id,
        'packages': [{'tracking_number': 'OUTBOUND'}]}}
    assert return_tracking_number(order) == ''
    order.source_details['platform_logistics']['packages'] = [
        {'failed_delivery_return': {'tracking_number': number}} for number in ['ONE', 'TWO']]
    assert return_tracking_number(order) == ''


def test_refund_tracking_requires_matching_return_identity(case_data):
    from apps.commerce.models import RefundReturn
    from apps.sales_management.aftersales import return_tracking_number
    _, _, order, _ = case_data
    refund = RefundReturn(sales_order=order, external_return_id='RETURN-SN')
    snapshot = {'return_sn': 'RETURN-SN', 'buyer_return': {'tracking_number': 'BUYER-RETURN'},
                'post_return': {'tracking_number': 'OTHER-LEG'}}
    order.source_details = {'platform_return_logistics': {'RETURN-SN': snapshot}}
    assert return_tracking_number(refund) == 'BUYER-RETURN'
    snapshot['return_sn'] = 'DIFFERENT'
    assert return_tracking_number(refund) == ''


def test_settings_save_does_not_bind_or_enable_a_warehouse(case_data):
    from apps.sales_management.aftersales_models import AftersalesSyncSettings
    user, _, _, _ = case_data
    client = client_for(user)
    response = client.patch('/api/internal/commerce/aftersales/settings/',
        {'expected_version': 0, 'interval_minutes': 120, 'is_enabled': False}, format='json')
    assert response.status_code == 200
    row = AftersalesSyncSettings.objects.get(tenant=user.tenant)
    assert row.interval_minutes == 120 and row.authorization_id is None and not row.is_enabled
    response = client.patch('/api/internal/commerce/aftersales/settings/',
        {'expected_version': row.version, 'interval_minutes': 60, 'is_enabled': True}, format='json')
    assert response.status_code == 400


def test_csv_preview_has_no_writes_and_confirm_is_idempotent(case_data):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from apps.sales_management.aftersales_import import HEADERS
    user, warehouse, order, _ = case_data
    text = ','.join(HEADERS) + '\n' + ','.join([warehouse.code, 'IMPORT-1', order.external_order_id, '',
        'SKU-aftersales', '1', '2026-09-01T03:00:00Z']) + '\n'
    client = client_for(user)
    file = lambda: SimpleUploadedFile('returns.csv', text.encode('utf-8'))
    before = (WarehouseReturnReceipt.objects.count(), ReturnAllocation.objects.count())
    response = client.post('/api/internal/commerce/aftersales/import/', {'file': file(), 'operation': 'preview'}, format='multipart')
    assert response.status_code == 200
    assert before == (WarehouseReturnReceipt.objects.count(), ReturnAllocation.objects.count())
    digest = response.json()['data']['sha256']
    for expected in (1, 0):
        response = client.post('/api/internal/commerce/aftersales/import/',
            {'file': file(), 'operation': 'confirm', 'sha256': digest}, format='multipart')
        assert response.status_code == 200
        assert response.json()['data']['created_documents'] == expected


def test_store_scoped_user_cannot_read_unassigned_receipts(case_data):
    from apps.permissions.models import DataScope
    user, warehouse, order, _ = case_data
    value = receipt(order, warehouse)
    value['platform_order_no'] = 'UNKNOWN'
    ingest_receipt(user, warehouse, value)
    limited = user_for(user.tenant, 'limited-aftersales')
    grant(limited, 'sales_management.returns.view', DataScope.ScopeType.CUSTOM, {'store_ids': [str(order.store_id)]})
    grant(limited, 'sales_management.aftersales.manage', DataScope.ScopeType.CUSTOM, {'store_ids': [str(order.store_id)]})
    assert client_for(limited).get('/api/internal/commerce/aftersales/').status_code == 200
    assert client_for(limited).get('/api/internal/commerce/aftersales/receipts/').status_code == 403


def test_unlink_preserves_receipt_and_recalculates_partial_state(case_data):
    from apps.sales_management.aftersales import unlink_allocation
    user, warehouse, order, case = case_data
    row, _ = ingest_receipt(user, warehouse, receipt(order, warehouse, quantity=2))
    case.refresh_from_db()
    assert case.return_status == 'received'
    allocation = ReturnAllocation.objects.get(case=case)
    unlink_allocation(user, allocation.pk, reason='核对后解除误关联', expected_version=row.version)
    case.refresh_from_db()
    assert case.return_status == 'pending'
    assert WarehouseReturnReceipt.objects.filter(pk=row.pk).exists()


def test_dispatch_without_binding_never_enqueues_provider_work(case_data):
    from unittest.mock import patch
    from apps.sales_management.aftersales_models import AftersalesSyncSettings
    from apps.sales_management.tasks import dispatch_aftersales_sync
    user, _, _, _ = case_data
    AftersalesSyncSettings.objects.create(tenant=user.tenant, requested_by=user)
    with patch('apps.sales_management.tasks.synchronize_aftersales.apply_async') as queued:
        dispatch_aftersales_sync()
    queued.assert_not_called()


@pytest.mark.parametrize('case_count', [1, 21])
def test_worker_query_failure_never_proves_stock_receipt(case_data, case_count):
    from unittest.mock import patch
    from apps.integrations.models import PlatformIntegrationConfig, WarehouseAuthorization, authorization_service_write
    from apps.sales_management.aftersales_models import AftersalesSyncSettings
    from apps.sales_management.tasks import synchronize_aftersales
    user, warehouse, order, case = case_data
    with authorization_service_write():
        config = PlatformIntegrationConfig.objects.create(tenant=user.tenant, platform='jifeng_wms',
            account_alias='Synthetic return test', environment='pilot', status='verified',
            credential_id='synthetic-reference', created_by=user)
        authorization = WarehouseAuthorization.objects.create(tenant=user.tenant, warehouse=warehouse,
            integration_config=config, provider='jifeng_wms', credential_id='synthetic-reference',
            status='active', created_by=user, updated_by=user)
    settings = AftersalesSyncSettings.objects.create(tenant=user.tenant, authorization=authorization, requested_by=user)
    case.warehouse, case.tracking_no = warehouse, 'SYNTHETIC-TRACK'
    case.save()
    for index in range(1, case_count):
        other_order = create_order(user.tenant, order.store, f'poll-{index}')
        other_order.normalized_status = 'cancelled'
        other_order.save(update_fields=['normalized_status'])
        other_case = track_source(other_order, requires_return=True)
        other_case.warehouse, other_case.tracking_no = warehouse, f'SYNTHETIC-TRACK-{index}'
        other_case.save()
    with patch('apps.integrations.readonly_clients.JifengWmsReadonlyClient', side_effect=RuntimeError('synthetic private detail')):
        result = synchronize_aftersales(settings.pk)
    settings.refresh_from_db()
    case.refresh_from_db()
    assert result['status'] == 'partial' and result['failed'] == case_count
    assert settings.last_error_code == 'AFTERSALES_QUERY_FAILED' and settings.running_until is None
    assert case.return_status == 'pending' and not WarehouseReturnReceipt.objects.exists()
    assert 'private' not in str(result)


def test_exact_order_numbers_in_two_stores_never_choose_the_first(case_data):
    from apps.masterdata.models import StoreMaster
    user, warehouse, order, case = case_data
    other_store = StoreMaster.objects.create(tenant=user.tenant, platform=order.platform, code='OTHER-PH', name='Other store',
                                            country_code='PH', currency='PHP', timezone='Asia/Manila')
    other_order = create_order(user.tenant, other_store, 'other-store')
    other_order.external_order_id, other_order.normalized_status = order.external_order_id, 'cancelled'
    other_order.save(update_fields=['external_order_id', 'normalized_status'])
    track_source(other_order, requires_return=True)
    result, _ = ingest_receipt(user, warehouse, receipt(order, warehouse))
    assert not result.lines.first().allocations.exists()


def test_refund_only_does_not_start_a_return_clock(case_data):
    from apps.sales_management.services import upsert_normalized_refund
    from tests.test_sales_management import create_run, NOW
    user, _, order, _ = case_data
    refund = upsert_normalized_refund(tenant=user.tenant, source_run=create_run(user.tenant, 'refund_return', 'refund-only'),
        payload={'store_id': order.store_id, 'external_return_id': 'ONLY-REFUND', 'external_order_id': order.external_order_id,
                 'requested_at_utc': NOW.isoformat(), 'updated_at_utc': NOW.isoformat(), 'currency': 'PHP',
                 'requires_physical_return': False, 'items': []})
    case = AftersalesCase.objects.get(refund=refund)
    assert case.return_status == 'not_required' and case.pending_since is None


def test_known_normal_order_can_be_reviewed_and_manually_linked(case_data):
    user, warehouse, previous_order, _ = case_data
    order = create_order(user.tenant, previous_order.store, 'normal-return')
    value = receipt(order, warehouse, number='NORMAL-RETURN')
    value['lines'][0]['sku'] = 'SKU-normal-return'
    received, _ = ingest_receipt(user, warehouse, value)
    case = AftersalesCase.objects.get(source_key=f'order:{order.pk}')
    assert case.return_status == 'unknown' and not ReturnAllocation.objects.filter(case=case).exists()
    client = client_for(user)
    response = client.patch(f'/api/internal/commerce/aftersales/cases/order:{order.pk}/',
        {'expected_version': case.version, 'requires_return': True, 'expected_skus': {'SKU-normal-return': 1},
         'reason': '核对仓库原单，本次只退一件'}, format='json')
    assert response.status_code == 200
    response = client.post(f'/api/internal/commerce/aftersales/receipts/{received.lines.first().pk}/allocate/',
        {'source_key': case.source_key, 'sku': 'SKU-normal-return', 'quantity': 1,
         'expected_version': received.version, 'reason': '核对唯一原运单'}, format='json')
    assert response.status_code == 200
    case.refresh_from_db()
    assert case.return_status == 'received'
