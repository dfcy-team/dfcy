import pytest
from datetime import datetime, timezone as dt_timezone
from django.db.models import QuerySet
from django.utils import timezone

from apps.commerce.models import InboundRecord
from apps.masterdata.models import CountrySiteMaster, StoreMaster, WarehouseMaster, SupplierMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.sales_management.outbound_movements import replace_shipment_lines, shipment_projection
from apps.sales_management.scopes import filter_inventory_queryset
from apps.sales_management.warehouse_order_models import OrderWarehouseLookup, WarehouseOutboundLine
from tests.test_order_warehouse_lookup import setup_order
from tests.test_sales_management import client_for, create_order, create_run, create_scope, grant, user_for

pytestmark = pytest.mark.django_db


@pytest.fixture
def movements(setup_order):
    order, admin, ph = setup_order
    tenant = order.tenant
    th = WarehouseMaster.objects.create(tenant=tenant, code='scope-th', name='TH warehouse', country_code='TH')
    th_store = StoreMaster.objects.create(tenant=tenant, platform=order.store.platform, code='scope-th',
        name='TH store', country_code='TH', currency='THB', timezone='Asia/Bangkok')
    th_order = create_order(tenant, th_store, 'scope-th')
    for country, warehouse, source_order in [('PH', ph, order), ('TH', th, th_order)]:
        lookup, _ = OrderWarehouseLookup.objects.get_or_create(order=source_order, defaults={'warehouse':warehouse})
        lookup.warehouse = warehouse
        lookup.save(update_fields=['warehouse'])
        replace_shipment_lines(lookup.pk, tenant.pk, warehouse.pk, [{
            'warehouse_order_no': country+'-DOC', 'status': 'SHIPPED',
            'shipped_at_utc': '2026-01-01T01:00:00Z',
            'items': [{'warehouse_sku':'SKU','sku':'SKU','quantity':'2'}],
        }], site_code=country)
        run = create_run(tenant, 'inbound', country, platform='jifeng_wms')
        run.status = 'success'
        run.save(update_fields=['status'])
        InboundRecord.objects.create(tenant=tenant, warehouse=warehouse, site_code=country,
            external_inbound_id=country+'-IN', external_line_id='1', inbound_type='purchase',
            source_sku='SKU', received_quantity=2, planned_quantity=2, status='received',
            source_run=run, received_at_utc=timezone.now(), updated_at_utc=timezone.now())
    ph_site = CountrySiteMaster.objects.get(tenant=tenant, country_code='PH')
    th_site = CountrySiteMaster.objects.create(tenant=tenant, code='th', name='Thailand', country_code='TH')
    # Historical PH facts must remain PH even after the warehouse archive moves.
    ph.country_code = 'TH'
    ph.save(update_fields=['country_code'])
    return order, admin, ph, th, ph_site, th_site


@pytest.mark.parametrize('branches,expected', [
    ([{'site_ids':['PH']}], {'PH'}),
    ([{'site_ids':['PH'],'warehouse_ids':['PH']}], {'PH'}),
    ([{'site_ids':['PH'],'warehouse_ids':['TH']}], set()),
    ([{'site_ids':['PH'],'regions':['TH']}], set()),
    ([{'site_ids':['PH']},{'warehouse_ids':['TH']}], {'PH','TH'}),
])
def test_movement_site_scope_is_branch_local_and_matches_inbound_outbound_api(movements, branches, expected):
    order, _, ph, th, ph_site, th_site = movements
    actor = user_for(order.tenant, 'movement-scope-reader')
    grant(actor, 'supply.v2.view')
    permission, _ = Permission.objects.get_or_create(code='sales_management.view',
        defaults={'name':'Sales','module':'sales_management','action':'view'})
    for index, raw in enumerate(branches):
        config = {key: [({'PH':ph_site.pk,'TH':th_site.pk} if key=='site_ids'
                       else {'PH':ph.pk,'TH':th.pk})[value] if key!='regions' else value
                       for value in values] for key, values in raw.items()}
        role = Role.objects.create(tenant=order.tenant, code=f'movement-{index}', name=f'Movement {index}')
        role.permissions.add(permission)
        UserRole.objects.create(tenant=order.tenant, user=actor, role=role)
        DataScope.objects.create(tenant=order.tenant, role=role, scope_type='custom', config=config)
    api = client_for(actor)
    url = '/api/internal/supply-chain/v2/wms-inbound-movements/'
    for direction in ('inbound','outbound'):
        response = api.get(url, {'direction':direction})
        assert response.status_code == 200, response.data
        data = response.data['data']
        assert {row['site_code'] for row in data['items']} == expected
        assert data['total'] == len(expected)
        assert {row['site_code'] for row in data['coverage']} == expected
        exported = api.get(url, {'direction':direction,'export':'csv'})
        assert exported.status_code == 200
        content = exported.content.decode('utf-8-sig')
        for country in {'PH','TH'}-expected:
            assert country+('-IN' if direction=='inbound' else '-DOC') not in content


def test_unrestricted_movement_reader_does_not_require_country_archive(movements):
    order, admin, *_ = movements
    CountrySiteMaster.objects.filter(tenant=order.tenant).delete()
    response = client_for(admin).get('/api/internal/supply-chain/v2/wms-inbound-movements/',
        {'direction':'outbound'})
    assert response.status_code == 200
    assert {row['site_code'] for row in response.data['data']['items']} == {'PH','TH'}


def test_foreign_site_branch_cannot_grant_country_or_interrupt_valid_role(movements):
    order, _, _, th, *_ = movements
    foreign_tenant, *_ = create_scope('foreign-movement-country')
    foreign = CountrySiteMaster.objects.create(tenant=foreign_tenant, code='foreign-ph', name='Foreign PH', country_code='PH')
    actor = user_for(order.tenant, 'foreign-site-reader')
    grant(actor, 'supply.v2.view')
    permission, _ = Permission.objects.get_or_create(code='sales_management.view',
        defaults={'name':'Sales','module':'sales_management','action':'view'})
    for index, config in enumerate([{'site_ids':[foreign.pk]}, {'warehouse_ids':[th.pk]}]):
        role = Role.objects.create(tenant=order.tenant, code=f'foreign-scope-{index}', name='Scope')
        role.permissions.add(permission)
        UserRole.objects.create(tenant=order.tenant, user=actor, role=role)
        DataScope.objects.create(tenant=order.tenant, role=role, scope_type='custom', config=config)
    for direction in ('inbound','outbound'):
        response = client_for(actor).get('/api/internal/supply-chain/v2/wms-inbound-movements/', {'direction':direction})
        assert response.status_code == 200, response.data
        assert {row['site_code'] for row in response.data['data']['items']} == {'TH'}


def test_projection_quarantines_time_that_cannot_be_displayed_in_fact_country():
    rows, reasons = shipment_projection([{
        'warehouse_order_no':str(index), 'status':'SHIPPED', 'shipped_at_utc':stamp,
        'items':[{'sku':'SKU','quantity':'1'}],
    } for index, stamp in enumerate(['9999-12-31T18:00:00Z','9998-12-31T18:00:00Z','0001-01-01T00:00:00+14:00'])], site_code='PH')
    assert rows == []
    assert reasons == {'shipped_at_out_of_range':3}


def test_projection_keeps_zero_quantity_item_alongside_positive_items():
    rows, reasons = shipment_projection([{
        'warehouse_order_no':'mixed-zero', 'status':'SHIPPED', 'shipped_at_utc':'2026-01-01T00:00:00Z',
        'items':[{'warehouse_sku':'ZERO','sku':'Z','quantity':0},
                 {'warehouse_sku':'POS','sku':'P','quantity':2},
                 {'warehouse_sku':'ZERO-STRING','sku':'ZS','quantity':'0'}],
    }], site_code='PH')
    assert reasons == {}
    assert rows == [('mixed-zero', datetime(2026,1,1,tzinfo=dt_timezone.utc), 'POS', 'P', 2)]


@pytest.mark.parametrize('extra_key', ['platform_ids','supplier_ids'])
@pytest.mark.parametrize('sibling_role', [False, True])
def test_unimplemented_restriction_is_not_dropped_from_country_branch(movements, extra_key, sibling_role):
    order, _, _, th, ph_site, _ = movements
    supplier = SupplierMaster.objects.create(tenant=order.tenant, code='scope-supplier', name='Supplier')
    identifier = order.store.platform_id if extra_key=='platform_ids' else supplier.pk
    actor = user_for(order.tenant, 'compound-country-reader')
    grant(actor, 'supply.v2.view')
    permission, _ = Permission.objects.get_or_create(code='sales_management.view',
        defaults={'name':'Sales','module':'sales_management','action':'view'})
    configs = [{'site_ids':[ph_site.pk],extra_key:[identifier]}]
    if sibling_role: configs.append({'warehouse_ids':[th.pk]})
    for index, config in enumerate(configs):
        role = Role.objects.create(tenant=order.tenant, code=f'compound-{index}', name='Compound')
        role.permissions.add(permission)
        UserRole.objects.create(tenant=order.tenant, user=actor, role=role)
        DataScope.objects.create(tenant=order.tenant, role=role, scope_type='custom', config=config)
    expected = {'TH'} if sibling_role else set()
    for direction in ('inbound','outbound'):
        response = client_for(actor).get('/api/internal/supply-chain/v2/wms-inbound-movements/', {'direction':direction})
        assert response.status_code == 200, response.data
        assert {row['site_code'] for row in response.data['data']['items']} == expected
        assert {row['site_code'] for row in response.data['data']['coverage']} == expected


def test_unrenderable_inbound_time_is_isolated_from_all_read_projections(movements):
    order, admin, *_ = movements
    original = InboundRecord.objects.filter(tenant=order.tenant, site_code='PH')
    ids = list(original.values_list('pk',flat=True))
    QuerySet.update(original, received_at_utc=datetime(9999,12,31,18,tzinfo=dt_timezone.utc))
    api = client_for(admin)
    url = '/api/internal/supply-chain/v2/wms-inbound-movements/'
    response = api.get(url, {'direction':'inbound'})
    assert response.status_code == 200, response.data
    data = response.data['data']
    assert data['total'] == 1 and data['received_quantity'] == 2
    assert {row['site_code'] for row in data['items']} == {'TH'}
    assert {row['site_code'] for row in data['coverage']} == {'TH'}
    exported = api.get(url, {'direction':'inbound','export':'csv'})
    assert exported.status_code == 200 and 'PH-IN' not in exported.content.decode('utf-8-sig')
    assert list(original.values_list('pk',flat=True)) == ids


def test_unrenderable_outbound_time_is_isolated_from_all_read_projections(movements):
    order, admin, *_ = movements
    original = WarehouseOutboundLine.objects.filter(tenant=order.tenant, site_code='PH')
    ids = list(original.values_list('pk', flat=True))
    QuerySet.update(original, shipped_at=datetime(9999, 12, 31, 18, tzinfo=dt_timezone.utc))
    api = client_for(admin)
    url = '/api/internal/supply-chain/v2/wms-inbound-movements/'
    response = api.get(url, {'direction':'outbound'})
    assert response.status_code == 200, response.data
    data = response.data['data']
    assert data['total'] == 1 and data['quantity'] == 2
    assert {row['site_code'] for row in data['items']} == {'TH'}
    assert {row['site_code'] for row in data['coverage']} == {'TH'}
    exported = api.get(url, {'direction':'outbound', 'export':'csv'})
    assert exported.status_code == 200 and 'PH-DOC' not in exported.content.decode('utf-8-sig')
    assert list(original.values_list('pk', flat=True)) == ids


def test_lowercase_historical_outbound_site_renders_and_filters_by_local_date(movements):
    order, admin, *_ = movements
    original = WarehouseOutboundLine.objects.filter(tenant=order.tenant, site_code='PH')
    QuerySet.update(original, site_code='ph')
    api = client_for(admin)
    url = '/api/internal/supply-chain/v2/wms-inbound-movements/'
    response = api.get(url, {'direction':'outbound', 'site_code':'PH', 'start_date':'2025-12-31'})
    assert response.status_code == 200, response.data
    data = response.data['data']
    assert data['total'] == 1 and {row['site_code'] for row in data['items']} == {'PH'}
    assert {row['site_code'] for row in data['coverage']} == {'PH'}
    exported = api.get(url, {'direction':'outbound', 'site_code':'PH', 'start_date':'2025-12-31', 'export':'csv'})
    assert exported.status_code == 200 and 'PH-DOC' in exported.content.decode('utf-8-sig')


def test_lowercase_historical_inbound_site_filters_by_local_date_and_exports(movements):
    order, admin, *_ = movements
    original = InboundRecord.objects.filter(tenant=order.tenant, site_code='PH')
    QuerySet.update(original, site_code='ph')
    api = client_for(admin)
    url = '/api/internal/supply-chain/v2/wms-inbound-movements/'
    response = api.get(url, {'direction':'inbound', 'site_code':'PH', 'start_date':'2025-12-31'})
    assert response.status_code == 200, response.data
    data = response.data['data']
    assert data['total'] == 1 and {row['site_code'] for row in data['items']} == {'PH'}
    assert {row['site_code'] for row in data['coverage']} == {'PH'}
    exported = api.get(url, {'direction':'inbound', 'site_code':'PH', 'start_date':'2025-12-31', 'export':'csv'})
    assert exported.status_code == 200 and 'PH-IN' in exported.content.decode('utf-8-sig')
