from unittest.mock import patch

import pytest

from apps.sales_management import operating
from apps.sales_management.operating_models import OperatingSuggestion
from apps.products.models import ProductSKU
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from tests.test_supply_chain_v2_foundation import internal_user, world
from tests.test_supply_chain_v2_logistics import client


PATH = '/api/internal/commerce/operating-orders/references/'
METRICS_AND_OPERATING = (operating.MANAGE, 'sales_management.view', 'sales_management.skus.view')


def grant_sales_store_scope(user, store):
    permission, _ = Permission.objects.get_or_create(code='sales_management.skus.view', defaults={
        'name': 'SKU sales view', 'module': 'sales_management', 'action': 'view'})
    role = Role.objects.create(tenant=user.tenant, name='Scoped sales access', code=f'scoped-sales-{user.pk}')
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.CUSTOM,
        config={'store_ids': [store.pk]})


def request_body(country_id, **extra):
    return {'country_id': country_id, 'source_kind': 'season',
        'sales_start': '2026-10-01', 'sales_end': '2026-10-10',
        'target_stock_sales_ratio': '2.0000', 'include_in_transit': True, **extra}


@pytest.mark.django_db
def test_references_calculate_only_authorized_searched_page_without_preview_token(world):
    user = internal_user(world, 'reference-operator', codes=METRICS_AND_OPERATING)
    world['sku_b'].legacy_sku_code = 'LEGACY-REFERENCE'
    world['sku_b'].save(update_fields=['legacy_sku_code'])
    body = request_body(world['country'].pk, search='SC2-SKU', limit=1, offset=1)
    with patch('apps.sales_management.operating_reference.country_decisions.decision_rows') as calculate:
        calculate.side_effect = lambda actor, country, skus, **kwargs: [
            {'sku_id': sku.pk, 'sales_windows': [{'units': 4, 'direct_sales_quantity': 4,
                'bundle_sales_quantity': 0, 'total_demand_quantity': 4}], 'suggested_quantity': 3,
             'pipeline': {'authorized': True, 'effective_incoming': 2}, 'issues': []}
            for sku in skus]
        response = client(user).post(PATH, body, format='json')

    assert response.status_code == 200, response.data
    data = response.data['data']
    assert data['count'] == 2 and data['limit'] == 1 and data['offset'] == 1
    assert data['candidate_scope'] == 'authorized_standard_products'
    assert [row['sku_id'] for row in data['lines']] == [world['sku_b'].pk]
    assert data['lines'][0]['source_kind'] == 'season'
    assert data['lines'][0]['sales_quantity'] == 4
    assert '手动选择' in data['notice'] and '季节预测模型' in data['notice']
    assert calculate.call_count == 1
    assert [sku.pk for sku in calculate.call_args.args[2]] == [world['sku_b'].pk]
    assert calculate.call_args.kwargs['windows'] == (10,)
    assert OperatingSuggestion.objects.count() == 0

    legacy_response = client(user).post(PATH,
        request_body(world['country'].pk, search='LEGACY-REFERENCE', quantity_filter='all'), format='json')
    assert legacy_response.status_code == 200, legacy_response.data
    assert legacy_response.data['data']['count'] == 1
    assert legacy_response.data['data']['lines'][0]['sku_id'] == world['sku_b'].pk

    no_facts_row = {'sku_id': world['sku'].pk, 'sales_windows': [{'units': 0, 'direct_sales_quantity': None,
        'bundle_sales_quantity': None, 'total_demand_quantity': None, 'coverage_complete': False}],
        'daily_sales': '0.0000', 'issues': ['no_sales_facts'],
        'pipeline': {'authorized': True, 'effective_incoming': 0}}
    with patch('apps.sales_management.operating_reference.country_decisions.decision_rows', return_value=[no_facts_row]):
        no_facts = client(user).post(PATH,
            request_body(world['country'].pk, search='SC2-SKU', limit=1, quantity_filter='all'), format='json')
    assert no_facts.status_code == 200, no_facts.data
    assert no_facts.data['data']['lines'][0]['sales_quantity'] is None
    assert no_facts.data['data']['lines'][0]['daily_sales'] is None


@pytest.mark.django_db
def test_reference_defaults_to_positive_and_uses_bounded_candidate_continuation(world):
    user = internal_user(world, 'reference-positive-filter', codes=METRICS_AND_OPERATING)
    sku_unknown = ProductSKU.objects.create(tenant=world['tenant'], spu=world['sku'].spu,
        sku_code='SC2-SKU-C')
    suggestion = {world['sku'].pk: 4, world['sku_b'].pk: 0, sku_unknown.pk: None}

    def rows(_actor, _country, skus, **_kwargs):
        return [{'sku_id': sku.pk, 'suggested_quantity': suggestion[sku.pk],
            'sales_windows': [{'units': 2, 'direct_sales_quantity': 2, 'bundle_sales_quantity': 0,
                'total_demand_quantity': 2, 'coverage_complete': True}],
            'daily_sales': '0.2000', 'issues': [],
            'pipeline': {'authorized': True, 'effective_incoming': 0}}
            for sku in skus]

    with patch('apps.sales_management.operating_reference.country_decisions.decision_rows', side_effect=rows) as calculate:
        first = client(user).post(PATH, request_body(world['country'].pk, limit=2), format='json')
        second = client(user).post(PATH, request_body(world['country'].pk, limit=2, offset=2), format='json')
        zero = client(user).post(PATH,
            request_body(world['country'].pk, limit=2, quantity_filter='zero'), format='json')
        unknown = client(user).post(PATH,
            request_body(world['country'].pk, limit=2, offset=2, quantity_filter='unknown'), format='json')
        all_rows = client(user).post(PATH,
            request_body(world['country'].pk, limit=2, quantity_filter='all'), format='json')

    assert first.status_code == 200, first.data
    first_data = first.data['data']
    assert [row['sku_id'] for row in first_data['lines']] == [world['sku'].pk]
    assert first_data['candidate_count'] == 3 and first_data['scanned_count'] == 2
    assert first_data['next_offset'] == 2 and first_data['has_more'] is True
    assert first_data['quantity_filter'] == 'positive'
    second_data = second.data['data']
    assert second_data['lines'] == [] and second_data['scanned_count'] == 1
    assert second_data['next_offset'] == 3 and second_data['has_more'] is False
    assert [row['suggested_quantity'] for row in zero.data['data']['lines']] == [0]
    assert [row['suggested_quantity'] for row in unknown.data['data']['lines']] == [None]
    assert len(all_rows.data['data']['lines']) == 2
    assert len(calculate.call_args_list[0].args[2]) == 2


@pytest.mark.django_db
def test_virtual_sku_is_excluded_from_references_options_and_preview(world):
    user = internal_user(world, 'reference-no-virtual', codes=(*METRICS_AND_OPERATING, operating.VIEW))
    world['sku_b'].inventory_type = 'virtual'
    world['sku_b'].save(update_fields=['inventory_type'])
    user_response = client(user)
    with patch('apps.sales_management.operating_reference.country_decisions.decision_rows') as calculate:
        reference = user_response.post(PATH, request_body(world['country'].pk, quantity_filter='all'), format='json')
    assert reference.status_code == 200, reference.data
    assert world['sku_b'].pk not in [line['sku_id'] for line in reference.data['data']['lines']]
    assert reference.data['data']['candidate_count'] == 1
    assert calculate.call_args.args[2] == [world['sku']]

    options = user_response.get('/api/internal/commerce/operating-options/?kind=skus')
    assert options.status_code == 200, options.data
    option_rows = options.data.get('data', [])
    assert world['sku_b'].pk not in [row['id'] for row in option_rows]

    preview = user_response.post('/api/internal/commerce/operating-orders/preview/', {
        'country_id': world['country'].pk, 'sku_ids': [world['sku_b'].pk],
        'sales_start': '2026-10-01', 'sales_end': '2026-10-10',
        'target_stock_sales_ratio': '2.0000', 'include_in_transit': True,
    }, format='json', HTTP_IDEMPOTENCY_KEY='virtual-preview')
    assert preview.status_code in (400, 422), preview.data
    assert '虚拟商品' in str(preview.data)

    manual = user_response.post('/api/internal/commerce/operating-orders/', {
        'country_id': world['country'].pk, 'source_kind': 'new_goods',
        'lines': [{'sku_id': world['sku_b'].pk, 'quantity': 1}],
    }, format='json', HTTP_IDEMPOTENCY_KEY='virtual-manual')
    assert manual.status_code in (400, 422), manual.data
    assert '虚拟商品' in str(manual.data)


@pytest.mark.django_db
def test_preview_idempotent_replay_rejects_sku_changed_to_virtual(world):
    user = internal_user(world, 'reference-virtual-replay', codes=METRICS_AND_OPERATING)
    api = client(user)
    payload = {
        'country_id': world['country'].pk,
        'sku_ids': [world['sku'].pk],
        'sales_start': '2026-10-01',
        'sales_end': '2026-10-10',
        'target_stock_sales_ratio': '2.0000',
        'include_in_transit': True,
    }
    path = '/api/internal/commerce/operating-orders/preview/'
    first = api.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='virtual-preview-replay')
    assert first.status_code == 200, first.data

    world['sku'].inventory_type = 'virtual'
    world['sku'].save(update_fields=['inventory_type'])
    replay = api.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='virtual-preview-replay')
    assert replay.status_code in (400, 422), replay.data
    assert '虚拟商品' in str(replay.data)


@pytest.mark.django_db
def test_historical_cycle_draft_cannot_submit_after_sku_becomes_virtual(world):
    user = internal_user(world, 'reference-virtual-submit', codes=METRICS_AND_OPERATING)
    api = client(user)
    created = api.post('/api/internal/commerce/operating-orders/', {
        'country_id': world['country'].pk,
        'source_kind': 'new_goods',
        'lines': [{'sku_id': world['sku'].pk, 'quantity': 2}],
    }, format='json', HTTP_IDEMPOTENCY_KEY='virtual-submit-draft')
    assert created.status_code == 201, created.data

    from apps.sales_management.operating_models import OperatingOrder
    from apps.supply_chain.models import domain_write
    order = OperatingOrder.objects.get(pk=created.data['data']['id'])
    with domain_write():
        order.source_kind = 'cycle'
        order.calculation_snapshot = {'demand_basis': 'direct_and_bundle_snapshot_v1'}
        order.save(update_fields=['source_kind', 'calculation_snapshot'])
    world['sku'].inventory_type = 'virtual'
    world['sku'].save(update_fields=['inventory_type'])

    submitted = api.post(f'/api/internal/commerce/operating-orders/{order.pk}/submit/',
        {'expected_version': order.version}, format='json', HTTP_IDEMPOTENCY_KEY='virtual-submit')
    assert submitted.status_code in (400, 422), submitted.data
    assert '虚拟商品' in str(submitted.data)
    order.refresh_from_db()
    assert order.status == 'draft'


@pytest.mark.django_db
def test_references_requires_operating_manage_permission(world):
    user = internal_user(world, 'reference-viewer', codes=('sales_management.view', 'sales_management.skus.view'))
    response = client(user).post(PATH, request_body(world['country'].pk), format='json')
    assert response.status_code == 403


@pytest.mark.django_db
def test_platform_reference_uses_authorized_active_store_and_keeps_incomplete_sales_unknown(world):
    user = internal_user(world, 'platform-reference-operator', codes=(operating.MANAGE, 'sales_management.view'))
    platform = PlatformMaster.objects.create(tenant=world['tenant'], code='shopee', name='Shopee Main',
        platform_type='shopee')
    store = StoreMaster.objects.create(tenant=world['tenant'], platform=platform, code='shopee-us',
        name='US Shop', country_code='US', currency='USD')
    hidden_platform = PlatformMaster.objects.create(tenant=world['tenant'], code='amazon', name='Hidden Amazon',
        platform_type='amazon')
    StoreMaster.objects.create(tenant=world['tenant'], platform=hidden_platform, code='amazon-us',
        name='Hidden Shop', country_code='US', currency='USD')
    grant_sales_store_scope(user, store)
    body = request_body(world['country'].pk, analysis_mode='platform', platform_type='SHOPEE', limit=1,
        quantity_filter='all')
    country_row = {'sku_id': world['sku'].pk, 'sales_windows': [{'units': 4, 'direct_sales_quantity': 4,
        'bundle_sales_quantity': 0, 'total_demand_quantity': 4, 'coverage_complete': False}],
        'daily_sales': '0.4000', 'issues': ['collection_coverage_unproven'],
        'pipeline': {'authorized': True, 'effective_incoming': 0}}
    platform_result = {10: {'units_by_sku': {world['sku'].pk: 2},
        'direct_sales_by_sku': {world['sku'].pk: 2}, 'bundle_sales_by_sku': {world['sku'].pk: 0},
        'bundle_composition_unverified': False, 'coverage_complete': False,
        'unmapped': False, 'issues': ['collection_coverage_unproven']}}
    unknown_result = {10: {'units_by_sku': {world['sku'].pk: 0},
        'direct_sales_by_sku': {world['sku'].pk: 0}, 'bundle_sales_by_sku': {world['sku'].pk: 0},
        'bundle_composition_unverified': False, 'coverage_complete': False,
        'unmapped': False, 'issues': []}}
    unmapped_country_row = {**country_row, 'sales_windows': [{'units': 4, 'direct_sales_quantity': 4,
        'bundle_sales_quantity': 0, 'total_demand_quantity': 4, 'coverage_complete': True}],
        'daily_sales': '0.4000', 'issues': ['unmapped_sales_lines']}
    complete_platform_result = {10: {'units_by_sku': {world['sku'].pk: 2},
        'direct_sales_by_sku': {world['sku'].pk: 2}, 'bundle_sales_by_sku': {world['sku'].pk: 0},
        'bundle_composition_unverified': False, 'coverage_complete': True,
        'unmapped': False, 'issues': []}}
    with patch('apps.sales_management.operating_reference.country_decisions.decision_rows',
               side_effect=[[country_row], [country_row], [unmapped_country_row]]), \
         patch('apps.sales_management.operating_reference.country_decisions.sales_windows',
               side_effect=[platform_result, unknown_result, complete_platform_result]) as platform_sales:
        response = client(user).post(PATH, body, format='json')
        unknown = client(user).post(PATH, body, format='json')
        unmapped = client(user).post(PATH, body, format='json')
        denied = client(user).post(PATH, {**body, 'platform_type': 'amazon'}, format='json')

    assert response.status_code == 200, response.data
    data = response.data['data']
    assert data['platform_options'] == [{'platform_type': 'shopee', 'name': 'Shopee Main'}]
    analysis = data['lines'][0]['platform_analysis']
    assert analysis == {'platform_type': 'shopee', 'sales_quantity': 2, 'direct_sales_quantity': 2,
        'bundle_sales_quantity': 0, 'total_demand_quantity': 2, 'daily_sales': '0.2000',
        'country_sales_share': None, 'complete': False,
        'issues': ['collection_coverage_unproven', 'country_sales_coverage_unproven']}
    assert platform_sales.call_count == 3
    assert platform_sales.call_args.args[2] == [world['sku'].pk]
    assert platform_sales.call_args.kwargs['platform_type'] == 'shopee'
    unknown_analysis = unknown.data['data']['lines'][0]['platform_analysis']
    assert unknown_analysis['sales_quantity'] is None and unknown_analysis['daily_sales'] is None
    unmapped_analysis = unmapped.data['data']['lines'][0]['platform_analysis']
    assert unmapped_analysis['country_sales_share'] is None
    assert denied.status_code == 400


@pytest.mark.django_db
def test_empty_reference_page_skips_country_and_platform_calculations(world):
    user = internal_user(world, 'empty-reference-page', codes=METRICS_AND_OPERATING)
    with patch('apps.sales_management.operating_reference.country_decisions.decision_rows') as calculate, \
         patch('apps.sales_management.operating_reference.country_decisions.sales_windows') as platform_sales:
        response = client(user).post(PATH,
            request_body(world['country'].pk, offset=20), format='json')

    assert response.status_code == 200, response.data
    assert response.data['data']['lines'] == []
    calculate.assert_not_called()
    platform_sales.assert_not_called()
