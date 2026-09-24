from datetime import timedelta
from unittest.mock import patch

import pytest

from apps.commerce.models import InventorySnapshot
from apps.integrations.models import IntegrationAuditLog
from apps.permissions.models import DataScope
from tests.test_inventory_auto_sku_links import inventory_link
from tests.test_sales_management import NOW, client_for, grant, user_for

pytestmark = pytest.mark.django_db
URL = '/api/internal/listings/warehouse-skus/'
EXPORT_URL = URL + 'export/'


def viewer(tenant, confirm=True, scope=None):
    user = user_for(tenant, f'warehouse-viewer-{tenant.id}-{confirm}-{bool(scope)}')
    for code in ['view'] + (['confirm'] if confirm else []):
        grant(user, 'integrations.product_mapping.' + code,
              DataScope.ScopeType.CUSTOM if scope else DataScope.ScopeType.ALL, scope)
    return client_for(user)


def test_list_is_readonly_and_latest_per_warehouse(inventory_link):
    tenant, warehouse, _, sku, ingest, history = inventory_link
    history('OLD-SKU', at=NOW - timedelta(days=1))
    row = ingest()
    client = viewer(tenant)
    before = IntegrationAuditLog.objects.count()
    data = client.get(URL).json()['data']
    assert data['count'] == 1
    assert data['results'][0]['id'] == row.id
    assert data['results'][0]['warehouse_name'] == warehouse.name
    assert client.get(URL, {'status': 'unmapped'}).json()['data']['count'] == 0
    info = client.get(f'{URL}{row.id}/mapping/').json()['data']
    assert info['suggested_sku_id'] == sku.id
    assert IntegrationAuditLog.objects.count() == before


def test_export_uses_current_filters_and_chinese_headers(inventory_link):
    tenant, _, _, _, ingest, _ = inventory_link
    ingest('OLD-SKU')
    ingest('UNKNOWN')

    response = viewer(tenant).get(EXPORT_URL, {'status': 'mapped'})

    assert response.status_code == 200
    assert response['Content-Type'].startswith('text/csv')
    content = response.content.decode('utf-8-sig')
    assert '平台,店铺/仓库,仓库编码,来源 SKU' in content
    assert 'OLD-SKU' in content
    assert 'UNKNOWN' not in content


def test_confirm_updates_links_only_and_future_sync_inherits(inventory_link):
    tenant, _, _, sku, ingest, history = inventory_link
    old = history('ALIAS', target=None)
    row = ingest('ALIAS')
    client = viewer(tenant)
    url = f'{URL}{row.id}/mapping/'
    payload = {'sku_id': sku.id, 'expected_sku_ids': [], 'confirmed': True}
    result = client.patch(url, payload, format='json')
    assert result.status_code == 200, result.data
    assert result.data['data']['updated_count'] == 2
    old.refresh_from_db(); row.refresh_from_db()
    assert old.internal_sku_id == row.internal_sku_id == sku.id
    assert (row.on_hand_qty, row.available_qty, row.reserved_qty) == (10, 8, 2)
    assert IntegrationAuditLog.objects.filter(action='inventory_manual_sku_link').count() == 1
    # A replay with stale expectations is rejected, not applied again.
    assert client.patch(url, payload, format='json').status_code == 400
    payload['expected_sku_ids'] = [sku.id]
    assert client.patch(url, payload, format='json').data['data']['updated_count'] == 0
    future = ingest('ALIAS', seller_sku='DIFFERENT', snapshot_at_utc=NOW + timedelta(days=1))
    assert future.internal_sku_id == sku.id


def test_permissions_tenant_scope_and_confirmation(inventory_link):
    from tests.test_sales_management import create_scope
    tenant, warehouse, _, sku, ingest, _ = inventory_link
    row = ingest('UNKNOWN')
    url = f'{URL}{row.id}/mapping/'
    payload = {'sku_id': sku.id, 'expected_sku_ids': [], 'confirmed': True}
    assert viewer(tenant, confirm=False).patch(url, payload, format='json').status_code == 403
    other, _, _, _ = create_scope('other-warehouse-tenant')
    other_client = viewer(other)
    assert other_client.get(URL).data['data']['count'] == 0
    assert other_client.get(url).status_code == 404
    assert other_client.patch(url, payload, format='json').status_code == 404
    scoped = viewer(tenant, scope={'warehouse_ids': [warehouse.id + 100]})
    assert scoped.get(URL).data['data']['count'] == 0
    assert scoped.patch(url, payload, format='json').status_code == 404
    client = viewer(tenant)
    assert client.patch(url, {**payload, 'confirmed': 'true'}, format='json').status_code == 400
    assert client.patch(url, {**payload, 'sku_id': sku.id + 100}, format='json').status_code == 404


def test_audit_failure_rolls_back_manual_link(inventory_link):
    tenant, _, _, sku, ingest, _ = inventory_link
    row = ingest('UNKNOWN')
    client = viewer(tenant)
    with patch('apps.listings.warehouse_sku_views.IntegrationAuditLog.objects.create', side_effect=RuntimeError('audit unavailable')):
        with pytest.raises(RuntimeError):
            client.patch(f'{URL}{row.id}/mapping/', {'sku_id': sku.id, 'expected_sku_ids': [], 'confirmed': True}, format='json')
    row.refresh_from_db()
    assert row.internal_sku_id is None
