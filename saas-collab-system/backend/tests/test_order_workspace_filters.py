from types import SimpleNamespace
from unittest.mock import patch
import pytest
from django.http import QueryDict
from apps.commerce.models import SalesOrder
from apps.sales_management.warehouse_order_models import OrderWarehouseLookup
from apps.sales_management.order_workspace_filters import filter_workspace, workspace_summary
from tests.test_order_warehouse_lookup import setup_order, binding
pytestmark = pytest.mark.django_db

def request(actor, **params):
    query = QueryDict('', mutable=True)
    query.update(params)
    return SimpleNamespace(user=actor, query_params=query)

def test_search_and_counts_respect_warehouse_visibility(setup_order):
    order, actor, warehouse = setup_order
    auth = binding(order, actor, warehouse)
    OrderWarehouseLookup.objects.create(order=order, warehouse=warehouse, status='matched', snapshot={'authorization_id': auth.pk, 'packages': [{'tracking_no': 'TRACK-EXAMPLE', 'carrier': 'NotSearchable', 'items': [{'warehouse_sku': 'WH-SKU-EXAMPLE', 'quantity': 1}]}]})
    scope = SalesOrder.objects.filter(pk=order.pk)
    with patch('apps.sales_management.order_workspace_filters.visible_authorizations', return_value=[auth]), patch('apps.sales_management.order_workspace_filters.check_stored_business_read_permission', return_value=True):
        assert filter_workspace(request(actor, search='TRACK-EXAMPLE'), scope).count() == 1
        assert filter_workspace(request(actor, search='WH-SKU-EXAMPLE'), scope).count() == 1
        assert filter_workspace(request(actor, search='NotSearchable'), scope).count() == 0
        assert filter_workspace(request(actor, warehouse_id=str(warehouse.pk), warehouse_status='matched'), scope).count() == 1
        summary = workspace_summary(request(actor), scope)
        assert summary['warehouse_counts']['matched'] == 1
        assert sum(row['count'] for row in summary['statuses']) == 1
        assert summary['warehouses'][0]['value'] == warehouse.pk
    with patch('apps.sales_management.order_workspace_filters.visible_authorizations', return_value=[]), patch('apps.sales_management.order_workspace_filters.check_stored_business_read_permission', return_value=True):
        assert filter_workspace(request(actor, search='TRACK-EXAMPLE'), scope).count() == 0
        assert workspace_summary(request(actor), scope)['warehouse_counts'].get('matched', 0) == 0

def test_no_warehouse_permission_does_not_disclose_status(setup_order):
    order, actor, _ = setup_order
    scope = SalesOrder.objects.filter(pk=order.pk)
    with patch('apps.sales_management.order_workspace_filters.check_stored_business_read_permission', return_value=False):
        assert filter_workspace(request(actor, warehouse_status='not_requested'), scope).count() == 0
        assert workspace_summary(request(actor), scope)['warehouse_counts'] is None
        assert filter_workspace(request(actor, search=order.external_order_id), scope).count() == 1


def test_endpoint_counts_before_pagination_and_retains_other_filters(setup_order, settings):
    from tests.test_sales_management import create_order, client_for
    order, actor, warehouse = setup_order
    settings.SALES_ORDER_WAREHOUSE_SYNC_ENABLED = False
    second = create_order(order.tenant, order.store, 'workspace-second')
    SalesOrder.objects.filter(pk=second.pk).update(normalized_status='cancelled')
    response = client_for(actor).get('/api/internal/sales-management/orders/', {
        'presentation': 'workspace', 'include_summary': 'false', 'page_size': 1,
        'status': 'cancelled', 'store_id': order.store_id})
    assert response.status_code == 200
    data = response.json()['data']
    assert data['count'] == 1
    assert len(data['results']) == 1
    assert sum(row['count'] for row in data['workspace_summary']['statuses']) == 2
    assert 'subtotal_amount' in data['results'][0]
