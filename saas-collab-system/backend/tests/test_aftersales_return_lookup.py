from unittest.mock import Mock, patch

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.models import PlatformIntegrationConfig, WarehouseAuthorization, authorization_service_write
from apps.masterdata.models import WarehouseMaster
from apps.sales_management.return_lookup import query_return
from apps.sales_management.aftersales_models import WarehouseReturnReceipt
from tests.test_order_aftersales import case_data, receipt
from tests.test_sales_management import client_for

pytestmark = pytest.mark.django_db


def authorize(user, warehouse):
    with authorization_service_write():
        config = PlatformIntegrationConfig.objects.create(tenant=user.tenant, platform='jifeng_wms',
            account_alias=warehouse.code, credential_id='synthetic-reference', created_by=user)
        return WarehouseAuthorization.objects.create(tenant=user.tenant, warehouse=warehouse,
            integration_config=config, provider='jifeng_wms', credential_id='synthetic-reference',
            status='active', created_by=user, updated_by=user)


@pytest.mark.parametrize('second_result', ['not_found', 'failure', 'match'])
def test_outbound_warehouse_limits_lookup_even_when_other_warehouse_matches(case_data, second_result):
    from apps.sales_management.warehouse_order_models import OrderWarehouseLookup
    user, warehouse, order, case = case_data
    OrderWarehouseLookup.objects.create(order=order, warehouse=warehouse, status='matched',
        snapshot={'packages': [{'shipped_at_utc': '2026-09-01T00:00:00Z'}]})
    authorize(user, warehouse)
    other = WarehouseMaster.objects.create(tenant=user.tenant, code='SECOND', name='Second',
        country_code=warehouse.country_code, warehouse_type='third_party')
    authorize(user, other)
    case.tracking_no = 'REVERSE'
    case.save()
    value = receipt(order, warehouse, quantity=2)
    value.update(tracking_no='REVERSE', received_at=None)

    def client(config, auth):
        if auth.warehouse_id == warehouse.pk or second_result == 'match':
            return Mock(fetch_return_detail=Mock(return_value=value))
        error = ValidationError('not found', code='return_not_found') if second_result == 'not_found' else RuntimeError('private')
        return Mock(fetch_return_detail=Mock(side_effect=error))

    with patch('apps.sales_management.return_lookup.JifengWmsReadonlyClient', side_effect=client) as factory:
        report = query_return(user, case)
    assert factory.call_count == 1
    case.refresh_from_db()
    assert report['status'] == 'matched'
    assert case.warehouse_id == warehouse.pk
    assert case.return_status == 'received'
    assert WarehouseReturnReceipt.objects.get().received_at is None
    assert 'private' not in str(report)


@pytest.mark.parametrize('status,packages', [('ambiguous', [{'shipped_at_utc': '2026-09-01T00:00:00Z'}]),
    ('matched', []), ('not_found', [])])
def test_unconfirmed_outbound_warehouse_never_queries_all_country_warehouses(case_data, status, packages):
    from apps.sales_management.warehouse_order_models import OrderWarehouseLookup
    user, warehouse, order, case = case_data
    authorize(user, warehouse)
    OrderWarehouseLookup.objects.create(order=order, warehouse=warehouse, status=status,
        snapshot={'packages': packages})
    case.tracking_no = 'REVERSE'
    case.save()
    with patch('apps.sales_management.return_lookup.JifengWmsReadonlyClient') as factory:
        with pytest.raises(ValidationError, match='实际出库仓库'):
            query_return(user, case)
    factory.assert_not_called()
    assert not WarehouseReturnReceipt.objects.exists()


def test_bound_case_does_not_query_other_warehouse_and_no_result_is_not_failure(case_data):
    user, warehouse, _, case = case_data
    authorize(user, warehouse)
    other = WarehouseMaster.objects.create(tenant=user.tenant, code='OTHER', name='Other',
        country_code='TH', warehouse_type='third_party')
    authorize(user, other)
    case.warehouse, case.tracking_no = warehouse, 'REVERSE'
    case.save()
    with patch('apps.sales_management.return_lookup.JifengWmsReadonlyClient') as factory:
        factory.return_value.fetch_return_detail.side_effect = ValidationError('empty', code='return_not_found')
        report = query_return(user, case)
    assert factory.call_count == 1 and report['status'] == 'not_found'
    case.refresh_from_db()
    assert case.return_status == 'pending'


def test_single_case_endpoint_does_not_allow_arbitrary_provider_parameters(case_data):
    user, _, _, case = case_data
    response = client_for(user).post(f'/api/internal/commerce/aftersales/cases/{case.source_key}/',
        {'url': 'https://example.invalid'}, format='json')
    assert response.status_code == 400


def test_endpoint_uses_outbound_warehouse_and_repeated_query_is_idempotent(case_data):
    from apps.sales_management.warehouse_order_models import OrderWarehouseLookup
    from apps.sales_management.aftersales_models import ReturnAllocation
    user, warehouse, order, case = case_data
    authorize(user, warehouse)
    OrderWarehouseLookup.objects.create(order=order, warehouse=warehouse, status='matched',
        snapshot={'packages': [{'shipped_at_utc': '2026-09-01T00:00:00Z'}]})
    case.tracking_no = 'REVERSE'
    case.save()
    value = receipt(order, warehouse, quantity=2)
    value.update(tracking_no='REVERSE', received_at=None)
    client = client_for(user)
    with patch('apps.sales_management.return_lookup.JifengWmsReadonlyClient') as factory:
        factory.return_value.fetch_return_detail.return_value = value
        for _ in range(2):
            response = client.post(f'/api/internal/commerce/aftersales/cases/{case.source_key}/', {}, format='json')
            assert response.status_code == 200
            assert response.json()['data']['status'] == 'matched'
    case.refresh_from_db()
    assert case.warehouse_id == warehouse.pk and case.return_status == 'received'
    assert WarehouseReturnReceipt.objects.count() == 1
    assert ReturnAllocation.objects.get(case=case).quantity == 2


def test_endpoint_blocks_missing_outbound_before_calling_warehouse(case_data):
    user, warehouse, _, case = case_data
    authorize(user, warehouse)
    case.tracking_no = 'REVERSE'
    case.save()
    with patch('apps.sales_management.return_lookup.JifengWmsReadonlyClient') as factory:
        response = client_for(user).post(f'/api/internal/commerce/aftersales/cases/{case.source_key}/', {}, format='json')
    assert response.status_code == 400
    assert '实际出库仓库' in response.json()['message']
    factory.assert_not_called()
    assert not WarehouseReturnReceipt.objects.exists()
