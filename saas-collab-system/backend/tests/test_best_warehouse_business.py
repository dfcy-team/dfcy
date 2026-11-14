from copy import deepcopy
from datetime import datetime, UTC
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.best_business import count, packages, return_receipt, utc_time
from apps.sales_management.best_warehouse_orders import fetch_packages
from tests.test_order_aftersales import case_data


def authorization():
    return SimpleNamespace(pk=1, provider='best_ecapi', external_warehouse_code='BEST-PH',
        warehouse=SimpleNamespace(country_code='PH'), warehouse_id=3, external_warehouse_region='PH',
        integration_config_id=2, integration_config=SimpleNamespace(environment='production',
            platform_config={'customer_code': 'TEST-CUSTOMER'}))


def outbound():
    return {'warehouseCode': 'BEST-PH', 'customerCode': 'TEST-CUSTOMER', 'extCode': 'PLATFORM-1',
        'salesOrderNo': 'WMS-1', 'orderCode': 'ERP-1', 'orderType': 'NORMAL', 'status': 'DELIVERED',
        'deliveryTime': '2026-09-02T12:00:00+08:00', 'packageList': {'packageItem': {
            'packCode': 'PACK-1', 'customerCode': 'TEST-CUSTOMER', 'orderCode': 'ERP-1',
            'packShippingOrderNo': 'TRACK-1', 'packProduct': {'packProduct': {
                'packSkuCode': 'SKU-A', 'packQuantity': '2', 'packDecimalQty': '2.0'}}}}}


def returned():
    return {'rma': {'rmaCode': 'RMA-1', 'rmaStatus': 'FULFILLED',
        'receiveTime': '2026-09-03T12:00:00+08:00', 'products': {'product': {
            'skuCode': 'SKU-A', 'normalQuantity': '2', 'defectiveQuantity': '1'}}}}


@pytest.mark.parametrize('value', [None, '', '-1', '1.5', 'NaN', True, '2147483648'])
def test_invalid_quantity_is_not_zero_or_truncated(value):
    with pytest.raises(ValidationError):
        count(value)


def test_packages_never_repeat_order_quantity_and_reject_duplicate_identity():
    value = outbound()
    second = deepcopy(value['packageList']['packageItem'])
    second['packCode'] = 'PACK-2'
    value['packageList']['packageItem'] = [value['packageList']['packageItem'], second]
    assert sum(p['items'][0]['quantity'] for p in packages(value, authorization())) == 4
    second['packCode'] = 'PACK-1'
    with pytest.raises(ValidationError):
        packages(value, authorization())


@pytest.mark.parametrize('field', ['warehouseCode', 'customerCode'])
def test_response_identity_is_checked(field):
    value = outbound()
    value[field] = 'OTHER'
    with pytest.raises(ValidationError):
        packages(value, authorization())


def test_pending_delivery_cannot_supply_costs():
    value = outbound()
    value['status'] = 'WMS_PACKAGE'
    result = packages(value, authorization())
    assert result[0]['shipped_at_utc'] is None


def test_return_good_and_defective_counts_are_both_real_receipts():
    result = return_receipt(returned(), 'RMA-1')
    assert result['lines'] == [{'sku': 'SKU-A', 'received_quantity': 3}]
    assert result['tracking_no'] == result['platform_order_no'] == ''
    assert result['received_at'] is None  # receiveTime is not putaway completion.


def test_return_identity_and_quantity_missing_never_post():
    with pytest.raises(ValidationError):
        return_receipt(returned(), 'OTHER')
    value = returned()
    del value['rma']['products']['product']['defectiveQuantity']
    with pytest.raises(ValidationError):
        return_receipt(value, 'RMA-1')


def test_cancelled_receipt_is_not_received():
    value = returned()
    value['rma']['rmaStatus'] = 'CANCELED'
    assert return_receipt(value, 'RMA-1')['lines'] == []


def test_naive_best_clock_is_not_assumed_to_be_jifeng_clock():
    assert utc_time('2026-09-02 12:00:00') is None
    assert utc_time('2026-09-02T12:00:00+07:00') == '2026-09-02T05:00:00+00:00'


@pytest.mark.parametrize('broken', ['', 'total', 'page', 'duplicate', 'erp'])
def test_pagination_and_erp_detail_fallback(broken):
    auth, actor = authorization(), Mock()
    order = SimpleNamespace(created_at_utc=datetime(2026, 9, 1, tzinfo=UTC),
                            external_order_id='PLATFORM-1', store=SimpleNamespace(country_code='PH'))
    value = outbound()
    del value['packageList']['packageItem']['packProduct']
    def execute(**kwargs):
        if kwargs['name'] == 'WMS_SO_STATUS_QUERY':
            assert '<orderCode>ERP-1</orderCode>' in kwargs['payload']['bizData']
            return {'data': {'salesOrder': {'orderCode': 'OTHER' if broken == 'erp' else 'ERP-1',
                'orderStatus': 'DELIVERED', 'products': {'product': {
                    'skuCode': 'ACTUAL-B', 'normalQuantity': '1', 'defectiveQuantity': '0'}}}}}
        wdo = '<orderType>WDO</orderType>' in kwargs['payload']['bizData']
        return {'data': {'currentPage': '2' if broken == 'page' else '1',
            'totalCount': '0' if wdo else '2' if broken == 'total' else '1', 'totalPage': '1',
            'orders': '' if wdo else {'order': [value, value] if broken == 'duplicate' else value}}}
    module = 'apps.sales_management.best_warehouse_orders.'
    with patch(module + 'WarehouseAuthorization') as model, patch(module + 'execute_operation', side_effect=execute), \
            patch(module + 'integration_values_allowed', return_value=True), \
            patch('apps.sales_management.warehouse_orders.require_access'), \
            patch(module + 'timezone.now', return_value=datetime(2026, 9, 3, tzinfo=UTC)):
        model.objects.select_related.return_value.get.return_value = auth
        if broken:
            with pytest.raises(ValidationError):
                fetch_packages(actor, auth, order, lambda: True)
        else:
            result = fetch_packages(actor, auth, order, lambda: True)
            assert len(result) == 1
            assert result[0]['warehouse_order_no'] == 'WMS-1'
            assert result[0]['items'] == [{'sku': 'ACTUAL-B', 'quantity': 1}]


def bind_best(user, warehouse):
    from apps.integrations.models import PlatformIntegrationConfig, WarehouseAuthorization, authorization_service_write
    with authorization_service_write():
        config = PlatformIntegrationConfig.objects.create(tenant=user.tenant, platform='best_ecapi',
            account_alias='best-business-test', created_by=user,
            platform_config={'customer_code': 'TEST-CUSTOMER'})
        return WarehouseAuthorization.objects.create(tenant=user.tenant, warehouse=warehouse,
            integration_config=config, provider='best_ecapi', status='active',
            external_warehouse_code='BEST-PH', credential_id='synthetic-reference',
            created_by=user, updated_by=user)


@pytest.mark.django_db
def test_best_case_query_uses_reviewed_rma_and_allocates_idempotently(case_data):
    from apps.sales_management.return_lookup import query_return
    from apps.sales_management.aftersales_models import WarehouseReturnReceipt, ReturnAllocation
    user, warehouse, order, case = case_data
    bind_best(user, warehouse)
    case.warehouse, case.warehouse_return_no, case.expectation_reviewed = warehouse, 'RMA-1', True
    case.save()
    value = returned()
    value['rma']['products']['product'].update(skuCode='SKU-aftersales', normalQuantity='2', defectiveQuantity='0')
    with patch('apps.integrations.warehouse_api_service.execute_operation', return_value={'data': value}) as execute, \
            patch('apps.permissions.ui_p6_scopes.integration_values_allowed', return_value=True):
        for _ in range(2):
            report = query_return(user, case)
            case.refresh_from_db()
            assert report['status'] == 'matched'
        assert '<rmaCode>RMA-1</rmaCode>' in execute.call_args.kwargs['payload']['bizData']
    assert WarehouseReturnReceipt.objects.count() == 1
    assert ReturnAllocation.objects.get(case=case).quantity == 2
    assert case.return_status == 'received'
    receipt = WarehouseReturnReceipt.objects.get()
    assert receipt.platform_order_no == receipt.tracking_no == ''


@pytest.mark.django_db
def test_best_never_uses_tracking_as_rma(case_data):
    from apps.sales_management.return_lookup import query_return
    user, warehouse, _, case = case_data
    bind_best(user, warehouse)
    case.warehouse, case.tracking_no = warehouse, 'TRACKING-NOT-RMA'
    case.save()
    with patch('apps.integrations.warehouse_api_service.execute_operation') as execute:
        with pytest.raises(ValidationError, match='百世须先核对'):
            query_return(user, case)
    execute.assert_not_called()


@pytest.mark.django_db
def test_case_api_saves_explicit_warehouse_number_and_audits(case_data):
    from tests.test_sales_management import client_for
    user, warehouse, _, case = case_data
    response = client_for(user).patch(f'/api/internal/commerce/aftersales/cases/{case.source_key}/', {
        'expected_version': case.version, 'requires_return': True, 'expected_skus': case.expected_skus,
        'warehouse_id': warehouse.pk, 'warehouse_return_no': 'RMA-1', 'reason': '核对百世退货单据'}, format='json')
    assert response.status_code == 200
    case.refresh_from_db()
    assert case.warehouse_return_no == 'RMA-1' and case.expectation_reviewed
    from apps.audit.models import OperationLog
    assert OperationLog.objects.filter(object_id=str(case.pk),
        action='return_expectation_reviewed').latest('pk').after_data['warehouse_return_no'] == 'RMA-1'


@pytest.mark.django_db
def test_best_does_not_poll_completed_quantities_for_unavailable_putaway_time(case_data):
    from apps.sales_management.aftersales import ingest_receipt
    from apps.sales_management.aftersales_models import AftersalesSyncSettings
    from apps.sales_management.tasks import synchronize_aftersales
    user, warehouse, _, case = case_data
    auth = bind_best(user, warehouse)
    case.warehouse, case.warehouse_return_no, case.expectation_reviewed = warehouse, 'RMA-1', True
    case.save()
    value = returned()
    value['rma']['products']['product'].update(skuCode='SKU-aftersales', normalQuantity='2', defectiveQuantity='0')
    ingest_receipt(user, warehouse, return_receipt(value, 'RMA-1'), source='api')
    case.refresh_from_db()
    assert case.return_status == 'received'
    schedule = AftersalesSyncSettings.objects.create(tenant=user.tenant, authorization=auth, requested_by=user)
    with patch('apps.integrations.warehouse_api_service.execute_operation', return_value={'data': value}) as execute, \
            patch('apps.permissions.ui_p6_scopes.integration_values_allowed', return_value=True):
        result = synchronize_aftersales(schedule.pk)
    execute.assert_not_called()
    assert result['queried'] == 0 and result['failed'] == 0
