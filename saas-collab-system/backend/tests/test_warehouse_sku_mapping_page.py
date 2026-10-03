from datetime import timedelta
from unittest.mock import patch

import pytest

from apps.commerce.models import InventorySnapshot
from apps.integrations.models import (
    IntegrationAuditLog, MarketplaceProductMapping, MarketplaceStoreAuthorization,
    MarketplaceStoreMapping, PlatformIntegrationConfig, authorization_service_write,
    marketplace_identity_key, marketplace_store_binding_key, product_mapping_service_write,
    store_mapping_service_write,
)
from apps.listings.models import PlatformProductDetail
from apps.masterdata.models import PlatformMaster, StoreMaster, WarehouseMaster
from apps.permissions.models import DataScope, Permission, Role, RoleResourcePolicy, UserRole
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


def test_list_returns_total_with_page_and_only_visible_warehouse_options(inventory_link):
    tenant, warehouse, _, _, ingest, history = inventory_link
    history('OLD-SKU', at=NOW - timedelta(days=1))
    latest = ingest('OLD-SKU')
    another = ingest('UNKNOWN')
    client = viewer(tenant)

    first = client.get(URL, {'page': 1, 'page_size': 1}).json()['data']
    second = client.get(URL, {'page': 2, 'page_size': 1}).json()['data']
    assert first['count'] == second['count'] == 2
    assert {first['results'][0]['id'], second['results'][0]['id']} == {latest.id, another.id}
    assert first['next'] and 'page=2' in first['next'] and first['previous'] is None
    assert second['next'] is None and second['previous'] and 'page=1' in second['previous']
    assert first['warehouse_options'] == [{'value': warehouse.id, 'label': f'{warehouse.name}（{warehouse.code}）'}]
    assert client.get(URL, {'page': 3, 'page_size': 1}).status_code == 404

    hidden = viewer(tenant, scope={'warehouse_ids': [warehouse.id + 100]}).get(URL).json()['data']
    assert hidden['count'] == 0
    assert hidden['warehouse_options'] == []


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


def test_platform_only_scope_cannot_read_warehouse_skus_but_separate_warehouse_role_can(inventory_link):
    tenant, warehouse, _, _, ingest, _ = inventory_link
    row = ingest('WAREHOUSE-SKU')
    platform = PlatformMaster.objects.get(tenant=tenant)
    store = StoreMaster.objects.get(tenant=tenant)
    detail = PlatformProductDetail.objects.create(
        tenant=tenant, platform=platform, store=store, platform_variant_id='shopee-detail',
    )
    user = user_for(tenant, 'mixed-platform-warehouse-viewer')
    permission = Permission.objects.get(code='integrations.product_mapping.view')

    def add_role(code, config):
        role = Role.objects.create(tenant=tenant, name=code, code=code)
        role.permissions.add(permission)
        UserRole.objects.create(tenant=tenant, user=user, role=role)
        DataScope.objects.create(
            tenant=tenant, role=role, scope_type=DataScope.ScopeType.CUSTOM, config=config,
        )
        return role

    # The numeric platform ID may happen to equal a warehouse ID.  It must
    # never be interpreted as a warehouse grant or silently dropped to ALL.
    platform_role = add_role('platform-mapping-view', {'platform_ids': [platform.id]})
    platform_role.permissions.add(Permission.objects.get(code='listings.product_detail.view'))
    client = client_for(user)
    assert client.get(URL).status_code == 403
    assert client.get(EXPORT_URL).status_code == 403

    add_role('warehouse-mapping-view', {'warehouse_ids': [warehouse.id]})
    response = client.get(URL)
    assert response.status_code == 200, response.data
    assert response.data['data']['count'] == 1
    assert response.data['data']['results'][0]['id'] == row.id
    assert client.get(f'{URL}{row.id}/mapping/').status_code == 200
    assert client.get(URL, {'warehouse_id': warehouse.id + 1}).data['data']['count'] == 0
    store_result = client.get('/api/internal/listings/product-details/')
    assert store_result.status_code == 200, store_result.data
    assert store_result.data['data']['count'] == 1
    assert store_result.data['data']['results'][0]['id'] == detail.id


@pytest.mark.parametrize('mixed_base_scope', [False, True], ids=['warehouse-only', 'mixed-legacy'])
def test_single_role_warehouse_policy_preserves_platform_mapping_scope(inventory_link, mixed_base_scope):
    tenant, warehouse, _, _, ingest, _ = inventory_link
    allowed_row = ingest('ALLOWED-WAREHOUSE-SKU')
    other_warehouse = WarehouseMaster.objects.create(
        tenant=tenant, code='other-warehouse', name='Other warehouse', country_code='PH',
        warehouse_type='third_party',
    )
    hidden_row = ingest('HIDDEN-WAREHOUSE-SKU', warehouse_id=other_warehouse.id)
    platform = PlatformMaster.objects.get(tenant=tenant)
    store = StoreMaster.objects.get(tenant=tenant)
    other_platform = PlatformMaster.objects.create(
        tenant=tenant, code='tiktok-other', name='TikTok', platform_type='tiktok',
    )
    other_store = StoreMaster.objects.create(
        tenant=tenant, platform=other_platform, code='other-store', name='Other store',
        country_code='PH', currency='PHP',
    )
    allowed_detail = PlatformProductDetail.objects.create(
        tenant=tenant, platform=platform, store=store, platform_variant_id='allowed-detail',
    )
    PlatformProductDetail.objects.create(
        tenant=tenant, platform=other_platform, store=other_store, platform_variant_id='hidden-detail',
    )
    user = user_for(tenant, 'single-role-warehouse-policy')
    role = Role.objects.create(tenant=tenant, name='Single mapping role', code='single-mapping-role')
    role.permissions.add(
        Permission.objects.get(code='integrations.product_mapping.view'),
        Permission.objects.get(code='listings.product_detail.view'),
    )
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    base_scope = {'warehouse_ids': [warehouse.id]}
    if mixed_base_scope:
        base_scope['platform_ids'] = [platform.id]
    DataScope.objects.create(
        tenant=tenant, role=role, scope_type=DataScope.ScopeType.CUSTOM,
        config=base_scope,
    )
    RoleResourcePolicy.objects.create(
        tenant=tenant, role=role, resource_code='platform_product_details',
        scope_type=DataScope.ScopeType.CUSTOM, config={'platform_ids': [platform.id]},
    )
    RoleResourcePolicy.objects.create(
        tenant=tenant, role=role, resource_code='integrations.product_mapping',
        scope_type=DataScope.ScopeType.CUSTOM, config={'platform_ids': [platform.id]},
    )

    def make_mapping(label, mapping_platform, mapping_store):
        platform_code = mapping_platform.platform_type
        config = PlatformIntegrationConfig.objects.create(
            tenant=tenant, platform=platform_code, account_alias=f'mapping-{label}',
            status=PlatformIntegrationConfig.Status.VERIFIED, regions=['PH'], created_by=user,
        )
        external_id = f'mapping-{label}'
        identity = marketplace_identity_key(platform_code, 'PH', external_id)
        with authorization_service_write():
            authorization = MarketplaceStoreAuthorization.objects.create(
                tenant=tenant, integration_config=config, store=mapping_store,
                platform=platform_code, region='PH', platform_store_id=external_id,
                platform_identity_key=identity, active_platform_identity_key=identity,
                active_store_binding_key=marketplace_store_binding_key(tenant.id, platform_code, mapping_store.id),
                merchant_subject_id=f'merchant-{label}', credential_id=f'credential-{label}',
                token_id=f'token-{label}', credential_mask={'token': '********'},
                shop_cipher=f'cipher-{label}' if platform_code == 'tiktok' else '',
                status=MarketplaceStoreAuthorization.Status.ACTIVE, created_by=user, updated_by=user,
            )
        with store_mapping_service_write():
            store_mapping = MarketplaceStoreMapping.objects.create(
                tenant=tenant, platform=platform_code, store=mapping_store,
                authorization=authorization, platform_store_id=external_id,
                platform_identity_key=identity, platform_subject_id=f'subject-{label}',
                region='PH', timezone='Asia/Manila', currency='PHP',
                status=MarketplaceStoreMapping.Status.ACTIVE,
                mapping_source=MarketplaceStoreMapping.MappingSource.SYNTHETIC_FIXTURE,
                mapped_by=user,
            )
        with product_mapping_service_write():
            return MarketplaceProductMapping.objects.create(
                tenant=tenant, platform=platform_code, store_mapping=store_mapping,
                platform_product_id=f'product-{label}', platform_variant_id=f'variant-{label}',
                platform_sku=f'sku-{label}', status=MarketplaceProductMapping.Status.UNMAPPED,
                mapping_source=MarketplaceProductMapping.MappingSource.MANUAL,
                created_by=user, updated_by=user,
            )

    allowed_mapping = make_mapping('allowed', platform, store)
    make_mapping('hidden', other_platform, other_store)
    client = client_for(user)
    mapping_url = '/api/internal/integrations/product-mappings/'
    detail_url = '/api/internal/listings/product-details/'

    # The legacy mixed scope fails closed without an inventory-specific policy.
    assert UserRole.objects.filter(user=user).count() == 1
    if mixed_base_scope:
        assert client.get(URL).status_code == 403
        assert client.get(EXPORT_URL).status_code == 403
    initial_mappings = client.get(mapping_url)
    assert initial_mappings.status_code == 200, initial_mappings.data
    assert [item['id'] for item in initial_mappings.data['data']['results']] == [allowed_mapping.id]
    initial_details = client.get(detail_url)
    assert initial_details.status_code == 200, initial_details.data
    assert [item['id'] for item in initial_details.data['data']['results']] == [allowed_detail.id]

    RoleResourcePolicy.objects.create(
        tenant=tenant, role=role, resource_code='commerce.inventory',
        scope_type=DataScope.ScopeType.CUSTOM, config={'warehouse_ids': [warehouse.id]},
    )
    response = client.get(URL)
    assert response.status_code == 200, response.data
    assert [item['id'] for item in response.data['data']['results']] == [allowed_row.id]
    assert [item['value'] for item in response.data['data']['warehouse_options']] == [warehouse.id]
    assert client.get(f'{URL}{allowed_row.id}/mapping/').status_code == 200
    assert client.get(f'{URL}{hidden_row.id}/mapping/').status_code == 404
    export = client.get(EXPORT_URL)
    assert export.status_code == 200
    assert 'ALLOWED-WAREHOUSE-SKU' in export.content.decode('utf-8-sig')
    assert 'HIDDEN-WAREHOUSE-SKU' not in export.content.decode('utf-8-sig')

    platform_mappings = client.get(mapping_url)
    assert platform_mappings.status_code == 200, platform_mappings.data
    assert [item['id'] for item in platform_mappings.data['data']['results']] == [allowed_mapping.id]
    platform_details = client.get(detail_url)
    assert platform_details.status_code == 200, platform_details.data
    assert [item['id'] for item in platform_details.data['data']['results']] == [allowed_detail.id]


def test_audit_failure_rolls_back_manual_link(inventory_link):
    tenant, _, _, sku, ingest, _ = inventory_link
    row = ingest('UNKNOWN')
    client = viewer(tenant)
    with patch('apps.listings.warehouse_sku_views.IntegrationAuditLog.objects.create', side_effect=RuntimeError('audit unavailable')):
        with pytest.raises(RuntimeError):
            client.patch(f'{URL}{row.id}/mapping/', {'sku_id': sku.id, 'expected_sku_ids': [], 'confirmed': True}, format='json')
    row.refresh_from_db()
    assert row.internal_sku_id is None
