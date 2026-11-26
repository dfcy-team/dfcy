import pytest
from tests.test_sales_management import create_scope, create_order, user_for, grant, client_for


@pytest.mark.django_db
def test_order_sorting_is_numeric_global_stable_and_tenant_scoped():
    tenant, _, store, _ = create_scope('sort-orders')
    low = create_order(tenant, store, 'low', '9')
    high = create_order(tenant, store, 'high', '100')
    high.items.update(quantity=12)
    other, _, other_store, _ = create_scope('sort-hidden')
    create_order(other, other_store, 'hidden', '999')
    user = user_for(tenant, 'sort-viewer')
    grant(user, 'sales_management.orders.view')
    client = client_for(user)
    path = '/api/internal/sales-management/orders/'
    for field in ('order_total_amount', 'item_count'):
        for ordering, expected in [(field, low.id), ('-' + field, high.id)]:
            response = client.get(path, {'ordering': ordering, 'page_size': 1})
            assert response.status_code == 200
            assert response.json()['data']['results'][0]['id'] == expected
        response = client.get(path, {'ordering': '-' + field, 'page_size': 1, 'page': 2})
        assert response.json()['data']['results'][0]['id'] == low.id
    for field in ('platform', 'store.name', 'store.region', 'external_order_id',
                  'raw_status', 'normalized_status', 'created_at_utc', 'currency'):
        response = client.get(path, {'ordering': field, 'external_order_id': 'high'})
        assert response.status_code == 200
        assert [row['id'] for row in response.json()['data']['results']] == [high.id]
    assert client.get(path, {'ordering': 'tenant_id'}).status_code == 400
    assert client.get(path, {'ordering': '--item_count'}).status_code == 400

@pytest.mark.django_db
def test_order_list_pages_facts_before_loading_presentation_joins():
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    tenant, _, store, _ = create_scope('page-facts')
    create_order(tenant, store, 'first', '9')
    create_order(tenant, store, 'second', '10')
    user = user_for(tenant, 'page-facts-viewer')
    grant(user, 'sales_management.orders.view')
    with CaptureQueriesContext(connection) as queries:
        response = client_for(user).get('/api/internal/sales-management/orders/',
                                       {'page_size': 1, 'include_summary': 'false'})
    assert response.status_code == 200
    sql = [row['sql'].lower() for row in queries.captured_queries]
    count = next(q for q in sql if 'count(' in q and 'sales_order' in q)
    assert ' in (select ' not in count
    page = next(q for q in sql if 'sales_order' in q and 'order by' in q and 'limit 1' in q)
    assert 'businesssync' not in page
    assert 'select sum(' not in page
    assert 'select count(' not in page

@pytest.mark.django_db
def test_workspace_summary_is_explicit_and_skips_order_page_reads():
    from unittest.mock import patch
    tenant, _, store, _ = create_scope('summary-lazy')
    create_order(tenant, store, 'one', '9')
    user = user_for(tenant, 'summary-lazy-viewer')
    grant(user, 'sales_management.orders.view')
    client = client_for(user)
    path = '/api/internal/sales-management/orders/'
    summary = {'statuses': [], 'warehouse_counts': None, 'warehouses': []}
    with patch('apps.sales_management.order_workspace_filters.workspace_summary', return_value=summary) as compute:
        response = client.get(path, {'presentation': 'workspace', 'workspace_summary': 'false', 'include_summary': 'false'})
        assert response.status_code == 200
        assert len(response.json()['data']['results']) == 1
        assert response.json()['data']['workspace_warehouses'] == []
        compute.assert_not_called()
        with patch('apps.sales_management.views.paginated_data', side_effect=AssertionError('must not load list')):
            response = client.get(path, {'workspace_summary': 'only'})
        assert response.status_code == 200
        assert response.json()['data'] == {'workspace_summary': summary}
        compute.assert_called_once()
    assert client.get(path, {'workspace_summary': 'invalid'}).status_code == 400


@pytest.mark.django_db
def test_default_page_sort_has_tenant_created_id_covering_index():
    from django.db import connection
    from apps.commerce.models import SalesOrder
    tenant, _, store, _ = create_scope('page-index')
    create_order(tenant, store, 'index-one', '9')
    index = next(i for i in SalesOrder._meta.indexes if i.name == 'idx_sales_tenant_created_id')
    assert index.fields == ['tenant', 'created_at_utc', 'id']
    if connection.vendor == 'sqlite':
        plan = SalesOrder.objects.filter(tenant=tenant).order_by('-created_at_utc', '-id').values('pk')[:20].explain()
        assert 'idx_sales_tenant_created_id' in plan
        assert 'TEMP B-TREE' not in plan
