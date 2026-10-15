from datetime import date, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch
import pytest
from django.utils import timezone
from apps.permissions.models import DataScope
from apps.supply_chain import services
from apps.supply_chain.models import OperatingAllocation, PurchaseOrder, BusinessEvent
from apps.sales_management import operating
from apps.sales_management.operating_models import OperatingOrder, OperatingSuggestion
from tests.test_supply_chain_v2_foundation import world, internal_user
from tests.test_supply_chain_v2_logistics import client
from tests.test_sales_management import grant, create_scope, create_run, create_order

OPS = '/api/internal/commerce/operating-orders/'
SUPPLY = '/api/internal/supply-chain/v2/'


def operator(world, name='operator', scope=DataScope.ScopeType.ALL, config=None):
    return internal_user(world, name, scope, config, codes=(operating.VIEW, operating.MANAGE))


def write(api, path, body, key, method='post'):
    return getattr(api, method)(path, body, format='json', HTTP_IDEMPOTENCY_KEY=key)


def demand(world, user, key='demand'):
    body = {'country_id': world['country'].pk, 'source_kind': 'new_goods',
            'lines': [{'sku_id': world['sku'].pk, 'quantity': 10}], 'notes': '新货订货'}
    response = write(client(user), OPS, body, key)
    assert response.status_code == 201, response.data
    obj = response.data['data']
    submitted = write(client(user), OPS + f"{obj['id']}/submit/", {'expected_version': obj['version']}, key + '-submit')
    assert submitted.status_code == 200, submitted.data
    return submitted.data['data'], body


def split_body(world, obj, quantity, supplier=None):
    return {'expected_version': obj['version'], 'supplier_id': (supplier or world['supplier']).pk,
            'reference_number': '业务备注可重复', 'notes': '按剩余需求拆单',
            'lines': [{'operating_line_id': obj['lines'][0]['id'], 'quantity': quantity, 'unit_price': '2.5'}]}


def test_partial_split_prices_confirm_and_release_cancelled_draft(world):
    ops, buyer = operator(world), internal_user(world)
    obj, body = demand(world, ops)
    api = client(buyer)
    assert client(ops).get(SUPPLY + 'purchase-orders/').status_code == 403
    assert api.get(OPS).status_code == 403
    path = SUPPLY + f"operating-orders/{obj['id']}/split/"
    first_body = split_body(world, obj, 4)
    response = write(api, path, first_body, 'first')
    assert response.status_code == 201, response.data
    result = response.data['data']; first = result['purchase_order']; obj = result['operating_order']
    assert first['source_kind'] == 'operating' and first['country_code'] == 'US'
    assert obj['lines'][0]['remaining_quantity'] == 6
    assert write(api, path, first_body, 'first').data['data']['purchase_order']['id'] == first['id']
    assert write(api, path, {**first_body, 'notes': 'different'}, 'first').status_code == 422
    assert write(api, path, split_body(world, obj, 7), 'too-much').status_code == 422
    assert PurchaseOrder.objects.count() == 1
    edit = {'expected_version': first['version'], 'supplier_id': first['supplier_id'], 'country_id': first['country_id'],
            'notes': '调价', 'lines': [{'sku_id': world['sku'].pk, 'quantity': 4, 'unit_price': '3.5'}]}
    updated = write(api, SUPPLY + f"purchase-orders/{first['id']}/", edit, 'price', 'patch')
    assert updated.status_code == 200, updated.data
    first = updated.data['data']; assert first['total_amount'] == '14.0000'
    assert write(api, SUPPLY + f"purchase-orders/{first['id']}/", {**edit, 'expected_version': first['version'],
        'lines': [{'sku_id': world['sku'].pk, 'quantity': 5, 'unit_price': '3.5'}]}, 'quantity', 'patch').status_code == 422
    assert client(ops).get(OPS + f"{obj['id']}/").data['data']['lines'][0]['remaining_quantity'] == 6
    second = write(api, path, split_body(world, obj, 6, world['supplier_b']), 'second')
    assert second.status_code == 201, second.data
    obj = second.data['data']['operating_order']; other = second.data['data']['purchase_order']
    assert obj['lines'][0]['remaining_quantity'] == 0
    assert write(client(ops), OPS + f"{obj['id']}/cancel/", {'expected_version': obj['version']}, 'allocated').status_code == 422
    assert write(api, SUPPLY + f"purchase-orders/{other['id']}/cancel/", {'expected_version': other['version']}, 'release').status_code == 200
    current = client(ops).get(OPS + f"{obj['id']}/").data['data']
    assert current['version'] == obj['version'] + 1 and current['lines'][0]['remaining_quantity'] == 6
    assert write(api, path, split_body(world, obj, 6), 'stale-source').status_code == 422
    final = write(api, path, split_body(world, current, 6), 'reallocate')
    assert final.status_code == 201, final.data
    assert OperatingAllocation.objects.filter(operating_line__isnull=False).count() == 4, 'original price rows preserved'
    assert write(api, SUPPLY + f"purchase-orders/{first['id']}/confirm/", {'expected_version': first['version']}, 'confirm').status_code == 200


def test_operator_country_scope_tenant_supplier_denied_and_source_freeze(world):
    ops = operator(world, scope=DataScope.ScopeType.CUSTOM, config={'site_ids': [world['country'].pk]})
    obj, body = demand(world, ops)
    api = client(ops)
    assert write(api, OPS, {**body, 'country_id': world['country_ca'].pk}, 'wrong-country').status_code == 403
    assert write(api, OPS + f"{obj['id']}/", {**body, 'expected_version': obj['version']}, 'submitted-edit', 'patch').status_code == 422
    other = operator(world, 'canada', DataScope.ScopeType.CUSTOM, {'site_ids': [world['country_ca'].pk]})
    assert client(other).get(OPS + f"{obj['id']}/").status_code == 404
    own = operator(world, 'own', DataScope.ScopeType.OWN)
    assert client(own).get(OPS).data['count'] == 0
    from tests.test_supply_chain_v2_foundation import supplier_user
    assert client(supplier_user(world, world['supplier'], 'supplier')).get(OPS).status_code in (401, 403)
    from apps.tenants.models import Tenant
    foreign = operator({**world, 'tenant': Tenant.objects.create(name='other', code='other')}, 'foreign')
    assert client(foreign).get(OPS + f"{obj['id']}/").status_code == 404
    buyer = internal_user(world)
    assert write(client(buyer), SUPPLY + 'purchase-orders/', {**body, 'source_kind': 'operating', 'supplier_id': world['supplier'].pk}, 'forged').status_code == 400


def test_procurement_source_scope_requires_country_or_creator_and_supplier(world):
    obj, body = demand(world, operator(world))
    own = internal_user(world, 'own-buyer', DataScope.ScopeType.OWN)
    supplier_only = internal_user(world, 'supplier-only', DataScope.ScopeType.CUSTOM,
                                  {'supplier_ids': [world['supplier'].pk]})
    detail = SUPPLY + f"operating-orders/{obj['id']}/"
    for buyer in [own, supplier_only]:
        api = client(buyer)
        assert api.get(SUPPLY + 'operating-orders/').data['count'] == 0
        assert api.get(detail).status_code == 404
        assert write(api, detail + 'split/', split_body(world, obj, 2), 'hidden-source').status_code == 404
    country_buyer = internal_user(world, 'country-buyer', DataScope.ScopeType.CUSTOM,
        {'site_ids': [world['country'].pk], 'supplier_ids': [world['supplier'].pk]})
    api = client(country_buyer)
    assert [r['id'] for r in api.get(SUPPLY + 'operating-orders/').data['data']] == [obj['id']]
    assert write(api, detail + 'split/', split_body(world, obj, 2, world['supplier_b']), 'hidden-supplier').status_code == 403
    assert write(api, detail + 'split/', split_body(world, obj, 2), 'allowed').status_code == 201
    body['country_id'] = world['country_ca'].pk
    ca = write(client(operator(world, 'ca-operator')), OPS, body, 'ca-source').data['data']
    ca = write(client(operator(world, 'ca-submitter')), OPS + f"{ca['id']}/submit/",
               {'expected_version': ca['version']}, 'ca-submit').data['data']
    assert api.get(SUPPLY + f"operating-orders/{ca['id']}/").status_code == 404
    assert PurchaseOrder.objects.count() == 1


def test_procurement_read_scope_cannot_grant_manage_scope(world):
    obj, _ = demand(world, operator(world))
    buyer = internal_user(world, 'read-all-write-own', codes=('supply.v2.view',))
    grant(buyer, 'supply.v2.manage', DataScope.ScopeType.OWN)
    api = client(buyer)
    path = SUPPLY + f"operating-orders/{obj['id']}/"
    assert api.get(path).status_code == 200
    assert write(api, path + 'split/', split_body(world, obj, 1), 'read-not-write').status_code == 404
    assert not PurchaseOrder.objects.exists()


def test_role_page_country_supplier_scope_roundtrip_and_sales_scope_separation(world):
    from apps.permissions.models import Role, RoleResourcePolicy
    ops = operator(world, scope=DataScope.ScopeType.CUSTOM, config={'site_ids': [world['country'].pk]})
    ops_role = Role.objects.get(user_roles__user=ops)
    RoleResourcePolicy.objects.create(tenant=world['tenant'], role=ops_role,
        resource_code='sales_management.sales', scope_type='all', config={'all': True})
    obj, body = demand(world, ops)
    assert write(client(ops), OPS, {**body, 'country_id': world['country_ca'].pk}, 'sales-all-not-demand-all').status_code == 403
    manager = internal_user(world, 'scope-manager', codes=('system.roles.view', 'system.roles.manage', 'supply.v2.view', 'supply.v2.manage'))
    buyer = internal_user(world, 'page-configured-buyer')
    target = Role.objects.get(user_roles__user=buyer)
    payload = {'menu_permission_codes': [], 'action_permission_codes': ['supply.v2.view', 'supply.v2.manage'],
               'field_permission_codes': [], 'scope_type': 'custom',
               'scope_config': {'site_ids': [world['country'].pk], 'supplier_ids': [world['supplier'].pk]}}
    response = client(manager).put(f'/api/internal/system/roles/{target.pk}/permissions/', payload, format='json')
    assert response.status_code == 200, response.data
    assert target.data_scopes.get().config == payload['scope_config']
    api = client(type(buyer).objects.get(pk=buyer.pk))
    assert api.get(SUPPLY + 'operating-orders/').data['data'][0]['id'] == obj['id']
    assert write(api, SUPPLY + f"operating-orders/{obj['id']}/split/", split_body(world, obj, 2), 'page-allowed').status_code == 201


def test_split_atomic_rollback_and_competing_versions(world):
    ops, buyer = operator(world), internal_user(world)
    obj, _ = demand(world, ops)
    body = split_body(world, obj, 8)
    with patch('apps.sales_management.operating.services._event', side_effect=RuntimeError('injected failure')):
        with pytest.raises(RuntimeError):
            operating.split(buyer, obj['id'], {**body, 'reference_number': '', 'notes': ''}, 'rollback')
    assert PurchaseOrder.objects.count() == OperatingAllocation.objects.count() == 0
    assert OperatingOrder.objects.get(pk=obj['id']).version == obj['version']
    api = client(buyer); path = SUPPLY + f"operating-orders/{obj['id']}/split/"
    assert write(api, path, body, 'winner').status_code == 201
    assert write(api, path, body, 'loser').status_code == 422
    assert PurchaseOrder.objects.count() == 1


def test_demand_draft_update_idempotence_cancel_and_generated_token_ownership(world):
    ops = operator(world); api = client(ops)
    body = {'country_id': world['country'].pk, 'source_kind': 'new_goods', 'lines': [{'sku_id': world['sku'].pk, 'quantity': 10}]}
    obj = write(api, OPS, body, 'new').data['data']
    assert write(api, OPS, body, 'new').data['data']['id'] == obj['id']
    assert write(api, OPS + f"{obj['id']}/", body, 'missing-version', 'patch').status_code == 400
    assert write(api, OPS, {**body, 'lines': body['lines'] * 2}, 'dup').status_code == 422
    edited = write(api, OPS + f"{obj['id']}/", {**body, 'expected_version': obj['version'], 'lines': [{'sku_id': world['sku'].pk, 'quantity': 12}]}, 'edit', 'patch')
    assert edited.status_code == 200, edited.data
    obj = edited.data['data']; assert obj['total_quantity'] == 12
    assert write(api, OPS + f"{obj['id']}/cancel/", {'expected_version': obj['version']}, 'cancel').status_code == 200
    assert write(api, OPS, {**body, 'source_kind': 'season', 'preview_token': 'forged'}, 'forged').status_code == 422
    assert api.get('/api/internal/commerce/operating-options/?kind=countries').status_code == 200


def test_operating_legacy_sku_metadata_and_protected_image_route(world):
    from apps.tenants.models import Tenant
    from apps.products.models import ProductSPU, ProductSKU

    world['sku'].legacy_sku_code = 'OLD-42'
    world['sku'].save(update_fields=['legacy_sku_code'])
    ops = operator(world)
    api = client(ops)
    options = api.get('/api/internal/commerce/operating-options/?kind=skus&search=OLD-42')
    assert options.status_code == 200
    option = options.data['data'][0]
    assert option['legacy_sku_code'] == 'OLD-42'
    created, _ = demand(world, ops, 'legacy-demand')
    line = client(ops).get(OPS + f"{created['id']}/").data['data']['lines'][0]
    assert line['legacy_sku_code'] == 'OLD-42' and line['product_details'] == option['product_details']

    image_path = f"/api/internal/commerce/operating-options/skus/{world['sku'].pk}/image/"
    with patch('apps.sales_management.operating_api.load_product_images', return_value={world['sku'].pk: {'body': b'image'}}):
        image = api.get(image_path)
    assert image.status_code == 200 and image['Content-Type'] == 'image/jpeg'
    assert image['Cache-Control'] == 'private, no-store'
    assert client(internal_user(world)).get(image_path).status_code == 403

    foreign_tenant = Tenant.objects.create(name='foreign', code='foreign-image')
    foreign_spu = ProductSPU.objects.create(tenant=foreign_tenant, spu_code='FOREIGN', product_name='Foreign')
    foreign_sku = ProductSKU.objects.create(tenant=foreign_tenant, spu=foreign_spu, sku_code='FOREIGN-1')
    assert api.get(f"/api/internal/commerce/operating-options/skus/{foreign_sku.pk}/image/").status_code == 404


@pytest.mark.django_db
def test_ratio_preview_real_source_latest_stock_intransit_and_reviewed_order():
    from apps.masterdata.models import CountrySiteMaster
    from apps.products.models import ProductSPU, ProductSKU
    from apps.commerce.models import InventorySnapshot
    tenant, platform, store, warehouse = create_scope('ratio', country='US', currency='USD')
    country = CountrySiteMaster.objects.create(tenant=tenant, code='us', name='US', country_code='US')
    spu = ProductSPU.objects.create(tenant=tenant, spu_code='RATIO', product_name='Ratio')
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code='RATIO-A')
    sales = create_order(tenant, store, 'ratio')
    store.timezone = 'America/Los_Angeles'; store.save()
    sales.paid_at_utc = sales.created_at_utc; sales.save()
    sales.source_run.status = 'success'; sales.source_run.save()
    line = sales.items.first(); line.internal_sku = sku; line.quantity = 10; line.save()
    # UTC dates and a stale business_date must not bypass the store-local window.
    from datetime import datetime
    before = create_order(tenant, store, 'before-period')
    before.created_at_utc = datetime(2026, 8, 1, 6, 59, 59, tzinfo=dt_timezone.utc)
    before.paid_at_utc = before.created_at_utc
    before.business_date = date(2026, 8, 17); before.save()
    before.source_run.status = 'success'; before.source_run.save()
    before_line = before.items.first(); before_line.internal_sku = sku; before_line.quantity = 80; before_line.save()
    late = create_order(tenant, store, 'paid-after-period')
    late.paid_at_utc = datetime(2026, 9, 1, 7, 0, tzinfo=dt_timezone.utc); late.save()
    late.source_run.status = 'success'; late.source_run.save()
    late_line = late.items.first(); late_line.internal_sku = sku; late_line.quantity = 90; late_line.save()
    run = create_run(tenant, 'inventory_snapshot', 'ratio-stock', platform='jifeng_wms')
    run.status = 'success'; run.save()
    earlier = timezone.now().astimezone(dt_timezone.utc) - timedelta(hours=2)
    InventorySnapshot.objects.create(tenant=tenant, warehouse=warehouse, source_run=run, site_code='US',
        source_sku='RATIO-A', internal_sku=sku, available_qty=99, snapshot_at_utc=earlier, payload_hash='a'*64)
    recent = InventorySnapshot.objects.create(tenant=tenant, warehouse=warehouse, source_run=run, site_code='US',
        source_sku='RATIO-A', internal_sku=sku, available_qty=2, in_transit_qty=3,
        provided_quantity_fields=['available_qty','in_transit_qty'],
        snapshot_at_utc=earlier + timedelta(hours=1), payload_hash='b'*64)
    ops = internal_user({'tenant': tenant}, 'ratio-operator', codes=(operating.VIEW, operating.MANAGE))
    grant(ops, 'sales_management.skus.view'); grant(ops, 'sales_management.view')
    grant(ops, 'sales_management.supply_summary.view')
    from tests.test_country_inventory_decisions import history_coverage
    history_coverage(tenant, store, ops, lower=datetime(2026,7,31,tzinfo=dt_timezone.utc),
                     upper=datetime(2026,9,2,tzinfo=dt_timezone.utc))
    api = client(ops)
    payload = {'country_id': country.pk, 'sku_ids': [sku.pk], 'sales_start': '2026-08-01', 'sales_end': '2026-08-31',
               'target_stock_sales_ratio': '2.0', 'include_in_transit': True}
    response = write(api, OPS + 'preview/', payload, 'preview')
    assert response.status_code == 200, response.data
    data = response.data['data']; row = data['lines'][0]
    assert row['suggested_quantity'] == 18 and row['sales_quantity'] == 10
    assert row['in_transit_stock'] == '0' and row['wms_in_transit_stock'] == '3'
    assert data['sales_date_basis'] == 'store.timezone'
    assert row['source_snapshot_ids'] == [recent.pk] and data['needs_review'] is True
    assert 'collection_coverage_unproven' not in row['issues']
    recent.available_qty = 4; recent.save()
    assert write(api, OPS + 'preview/', payload, 'preview').data['data'] == data
    body = {'country_id': country.pk, 'source_kind': 'season', 'preview_token': data['preview_token'],
            'lines': [{'sku_id': sku.pk, 'quantity': 14}]}
    order = write(api, OPS, body, 'reviewed')
    assert order.status_code == 201, order.data
    assert order.data['data']['calculation_snapshot']['operator_reviewed_quantities'][0]['quantity'] == 14
    assert OperatingSuggestion.objects.count() == 1
    grant_user = internal_user({'tenant': tenant}, 'other-operator', codes=(operating.VIEW, operating.MANAGE))
    assert write(client(grant_user), OPS, body, 'stolen').status_code == 422


def test_ratio_missing_facts_not_fabricated_and_permissions(world):
    ops = operator(world); api = client(ops)
    payload = {'country_id': world['country'].pk, 'sku_ids': [world['sku'].pk], 'sales_start': '2026-08-01',
               'sales_end': '2026-08-31', 'target_stock_sales_ratio': '1.5'}
    assert write(api, OPS + 'preview/', payload, 'denied').status_code == 403
    grant(ops, 'sales_management.skus.view'); grant(ops, 'sales_management.view')
    # Authentication permission caches are request-scoped; requery the user after grants.
    api = client(type(ops).objects.get(pk=ops.pk))
    response = write(api, OPS + 'preview/', payload, 'missing')
    assert response.status_code == 200, response.data
    data = response.data['data']; row = data['lines'][0]
    assert row['suggested_quantity'] is None and row['available_stock'] is None
    assert 'missing_inventory_snapshot' in row['issues'] and 'no_sales_facts' in row['issues']
    assert write(api, OPS, {'country_id': world['country'].pk, 'source_kind': 'cycle', 'preview_token': data['preview_token'],
        'lines': [{'sku_id': world['sku'].pk, 'quantity': 10}]}, 'invalid-input').status_code == 422
    assert not OperatingOrder.objects.exists()


@pytest.mark.parametrize('sales,ratio,stock,expected', [(10,'1.5',7,8),(0,'2',0,0),(3,'1.5',2,3),(4,'1',8,0)])
def test_ratio_formula_rounding(sales, ratio, stock, expected):
    assert operating.demand_quantity(sales, Decimal(ratio), Decimal(stock)) == expected


def test_operating_and_procurement_country_search_respects_scope(world):
    ops = operator(world)
    obj, _ = demand(world, ops)
    for search in ('USA', 'us', ' USA ', obj['number']):
        assert client(ops).get(OPS, {'search': search}).data['count'] == 1
    buyer = internal_user(world, 'search-buyer', DataScope.ScopeType.CUSTOM,
                          {'site_ids': [world['country'].pk]})
    for search in ('USA', 'us', obj['number']):
        assert client(buyer).get(SUPPLY+'operating-orders/', {'search': search}).data['count'] == 1
    denied = operator(world, 'canada-only', DataScope.ScopeType.CUSTOM,
                      {'site_ids': [world['country_ca'].pk]})
    assert client(denied).get(OPS, {'search': 'US'}).data['count'] == 0
