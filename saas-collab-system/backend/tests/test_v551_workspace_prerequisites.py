from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from apps.integrations.models import WebhookEvent
from apps.sales_management.order_presentation import attach_event_milestones
from tests.test_sales_management import create_scope, create_order, user_for, grant, client_for


@pytest.mark.django_db
def test_verified_milestones_use_real_orm_and_exact_tenant_shop_order_pairs():
    tenant, _, store, _ = create_scope('v551-events')
    other, _, _, _ = create_scope('v551-foreign')
    stamp = datetime(2026, 11, 26, tzinfo=timezone.utc)
    common = dict(platform='shopee', event_type='shopee.order_status', order_status='COMPLETED',
                  completed_scenario='NORMAL', event_at=stamp, payload_hash='synthetic-only')
    for key, owner, shop, order, signature in [
        ('good', tenant, 'shop-a', 'order-a', 'valid'),
        ('wrong-shop', tenant, 'shop-b', 'order-a', 'valid'),
        ('wrong-order', tenant, 'shop-a', 'order-b', 'valid'),
        ('unsigned', tenant, 'shop-a', 'order-a', 'invalid'),
        ('wrong-tenant', other, 'shop-a', 'order-a', 'valid'),
    ]:
        WebhookEvent.objects.create(**common, tenant=owner, event_id=key,
                                    external_shop_id=shop, external_order_id=order,
                                    signature_status=signature)
    rows = [{'store': {'id': store.pk}, 'platform': 'shopee', 'external_order_id': order}
            for order in ('order-a', 'not-in-page')]
    # Only the authorization fixture is isolated; WebhookEvent query parsing,
    # joins, predicates and aggregates execute against the real test database.
    with patch('apps.integrations.models.MarketplaceStoreAuthorization.objects.filter') as authorizations:
        authorizations.return_value.values_list.return_value = [(store.pk, 'shopee', 'PH', 'shop-a')]
        attach_event_milestones(tenant.pk, rows)
    assert rows[0]['completed_at_utc'] == stamp.isoformat()
    assert 'completed_at_utc' not in rows[1]
    assert WebhookEvent.objects.count() == 5


@pytest.mark.django_db
def test_existing_detail_and_event_routes_work_without_marketplace_authorization():
    tenant, _, store, _ = create_scope('v551-detail')
    order = create_order(tenant, store, 'v551-detail')
    user = user_for(tenant, 'v551-detail-viewer')
    grant(user, 'sales_management.orders.view')
    client = client_for(user)
    path = '/api/internal/sales-management/orders/'
    assert client.get(f'{path}{order.pk}/').status_code == 200
    result = client.get(f'{path}{order.pk}/events/')
    assert result.status_code == 200
    assert isinstance(result.json()['data']['events'], list)
    foreign, _, foreign_store, _ = create_scope('v551-detail-hidden')
    hidden = create_order(foreign, foreign_store, 'v551-detail-hidden')
    assert client.get(f'{path}{hidden.pk}/events/').status_code == 404


@pytest.mark.django_db
def test_workspace_list_and_summary_keep_tenant_and_warehouse_permissions():
    tenant, _, store, _ = create_scope('v551-summary')
    order = create_order(tenant, store, 'v551-summary')
    foreign, _, foreign_store, _ = create_scope('v551-summary-hidden')
    create_order(foreign, foreign_store, 'v551-summary-hidden')
    user = user_for(tenant, 'v551-summary-viewer')
    grant(user, 'sales_management.orders.view')
    result = client_for(user).get('/api/internal/sales-management/orders/',
                                {'presentation': 'workspace', 'include_summary': 'false'})
    assert result.status_code == 200
    data = result.json()['data']
    assert [row['id'] for row in data['results']] == [order.pk]
    assert sum(row['count'] for row in data['workspace_summary']['statuses']) == 1
    assert data['workspace_summary']['warehouse_counts'] is None
    assert data['workspace_summary']['warehouses'] == []
