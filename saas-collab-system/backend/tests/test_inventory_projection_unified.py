from types import SimpleNamespace

from unittest.mock import Mock, patch

import pytest

from django.core.cache import cache

from apps.products.models import ProductSKU, ProductSPU

from apps.sales_management.category_inventory import operations_summary

from apps.sales_management.decision_api import DecisionQuery, _group_inventory_spus, _known_sum

from tests.test_country_inventory_decisions import BASE, clock, facts, stock

from tests.test_sales_management import client_for

@pytest.mark.parametrize('raw', ['0', '-1', '1,,2', '１', '9223372036854775808', ','.join(map(str, range(1, 102)))])
def test_decision_multicategory_input_is_bounded_and_positive(raw):
    query = DecisionQuery(data={'mapped_only': True, 'group_by': 'spu', 'category_ids': raw})
    assert not query.is_valid()

def test_decision_multicategory_input_is_parsed_to_set_once():
    query = DecisionQuery(data={'mapped_only': True, 'group_by': 'spu', 'category_ids': '1, 2,1'})
    assert query.is_valid(), query.errors
    assert query.validated_data['category_ids'] == {1, 2}

def test_read_projection_is_opt_in_for_mapped_inventory_only():
    assert DecisionQuery(data={}).is_valid()
    assert DecisionQuery(data={'mapped_only': True, 'read_projection': 'summary'}).is_valid()
    assert not DecisionQuery(data={'read_projection': 'list'}).is_valid()
    assert not DecisionQuery(data={'mapped_only': True, 'read_projection': 'everything'}).is_valid()

@pytest.mark.parametrize('values', [[1, None], [1, True], ['NaN'], ['Infinity'], []])
def test_unknown_or_nonfinite_aggregate_never_becomes_zero(values):
    assert _known_sum(values) is None

def test_spu_missing_variant_window_and_unknown_inventory_propagate():
    rows = [
        {'sku_id': 1, 'sku': 'A', 'available_stock': '5', 'mapped_sales_units': 0,
         'inventory_complete': True, 'mapped_sales_complete': True,
         'sales_windows': [{'days': 30, 'units': 0, 'coverage_complete': True}],
         'operations': {'inventory_status': 'observed', 'sales_status': 'no_sales'}},
        {'sku_id': 2, 'sku': 'B', 'available_stock': None, 'mapped_sales_units': None,
         'inventory_complete': False, 'mapped_sales_complete': False,
         'sales_windows': [], 'operations': {'inventory_status': 'unknown', 'sales_status': 'unknown'}},
    ]
    metadata = {1: {'spu_id': 7, 'spu_code': 'SPU7'}, 2: {'spu_id': 7, 'spu_code': 'SPU7'}}
    parent = _group_inventory_spus(rows, metadata, 30)[0]
    assert len(parent['variants']) == 2
    assert parent['available_stock'] is None and parent['mapped_sales_units'] is None
    assert parent['inventory_complete'] is False and parent['mapped_sales_complete'] is False
    assert parent['sales_windows'][0]['units'] is None
    assert parent['sales_windows'][0]['coverage_complete'] is False
    assert parent['operations']['sales_status'] == 'unknown'
    assert parent['pipeline'] == {'authorized': False}

def test_summary_consumes_scoped_generator_once_and_empty_never_falls_back():
    cache.clear()
    actor, country = SimpleNamespace(tenant_id=3, pk=5), SimpleNamespace(pk=7)
    skus = Mock()
    skus.order_by.return_value.values_list.return_value = [11, 12]
    source = ({'internal_sku_id': pk, 'available_qty': 4} for pk in (11, 12))
    with patch('apps.sales_management.category_inventory.domain.permission_signature', return_value='synthetic'), \
         patch('apps.sales_management.category_inventory.sales_facts', return_value=[]), \
         patch('apps.sales_management.category_inventory.stock_facts') as fallback:
        result = operations_summary(actor, country, skus, 30, {}, snapshots=source)
        assert result['stocked'] == 2 and result['unknown_stock'] == 0
        empty = operations_summary(actor, country, skus, 30, {}, snapshots=[])
        assert empty['stocked'] == 0 and empty['unknown_stock'] == 2
        fallback.assert_not_called()

@pytest.mark.django_db
def test_spu_page_search_includes_all_scoped_siblings(facts):
    f = facts
    sibling = ProductSKU.objects.create(tenant=f['tenant'], spu=f['spu'], sku_code='SIBLING')
    stock(f['tenant'], f['warehouse'], sibling, suffix='spu-sibling', quantity=8)
    response = client_for(f['actor']).get(BASE, {'country_id': f['country'].pk,
        'mapped_only': True, 'group_by': 'spu', 'search': f['sku'].sku_code, 'limit': 1})
    assert response.status_code == 200, response.data
    data = response.data['data']
    assert data['count'] == 1 and len(data['results']) == 1
    assert {v['sku_id'] for v in data['results'][0]['variants']} == {f['sku'].pk, sibling.pk}
    assert data['summary']['stocked'] == 2

@pytest.mark.django_db
def test_mapped_list_projection_matches_default_rows_and_skips_summary(facts):
    f = facts
    api = client_for(f['actor'])
    params = {'country_id': f['country'].pk, 'mapped_only': True, 'search': f['sku'].sku_code}
    default = api.get(BASE, params)
    with patch('apps.sales_management.category_inventory.operations_summary', side_effect=AssertionError('summary calculated')):
        listed = api.get(BASE, {**params, 'read_projection': 'list'})
    assert default.status_code == listed.status_code == 200
    assert listed.data['data']['results'] == default.data['data']['results']
    assert listed.data['data']['count'] == default.data['data']['count']
    assert listed.data['data']['summary'] is None
    assert listed.data['data']['summary_state'] == 'not_requested'

@pytest.mark.django_db
def test_mapped_summary_projection_skips_page_and_keeps_spu_search_siblings(facts):
    f = facts
    sibling = ProductSKU.objects.create(tenant=f['tenant'], spu=f['spu'], sku_code='SUMMARY-SIBLING')
    stock(f['tenant'], f['warehouse'], sibling, suffix='summary-sibling', quantity=8)
    api = client_for(f['actor'])
    params = {'country_id': f['country'].pk, 'mapped_only': True, 'group_by': 'spu',
              'search': f['sku'].sku_code, 'limit': 1}
    default = api.get(BASE, params)
    with patch('apps.alerts.inventory_decisions.decision_page', side_effect=AssertionError('page calculated')):
        summary = api.get(BASE, {**params, 'read_projection': 'summary'})
    assert default.status_code == summary.status_code == 200
    assert summary.data['data']['results'] == []
    assert summary.data['data']['count'] == default.data['data']['count'] == 1
    assert summary.data['data']['summary'] == default.data['data']['summary']

@pytest.mark.django_db
def test_spu_offset_paginates_groups_not_variants(facts):
    f = facts
    sibling = ProductSKU.objects.create(tenant=f['tenant'], spu=f['spu'], sku_code='SIBLING')
    stock(f['tenant'], f['warehouse'], sibling, suffix='offset-sibling', quantity=8)
    other_spu = ProductSPU.objects.create(tenant=f['tenant'], spu_code='OTHER')
    other = ProductSKU.objects.create(tenant=f['tenant'], spu=other_spu, sku_code='OTHER-SKU')
    stock(f['tenant'], f['warehouse'], other, suffix='offset-other', quantity=3)
    api = client_for(f['actor'])
    pages = [api.get(BASE, {'country_id': f['country'].pk, 'mapped_only': True,
                          'group_by': 'spu', 'limit': 1, 'offset': offset}) for offset in (0, 1)]
    assert all(r.status_code == 200 for r in pages)
    assert all(r.data['data']['count'] == 2 for r in pages)
    variants = [{v['sku_id'] for v in r.data['data']['results'][0]['variants']} for r in pages]
    assert variants == [{f['sku'].pk, sibling.pk}, {other.pk}]
    assert all(r.data['data']['summary']['stocked'] == 3 for r in pages)


def test_spu_parent_does_not_inherit_single_variant_executable_advice():
    from copy import deepcopy
    ready = {'sku_id': 1, 'sku': 'A', 'inventory_complete': True, 'needs_review': False,
             'suggested_quantity': 7, 'suggestion_formula': 'first variant', 'decision_state': 'ready',
             'replenishment_status': 'ready', 'blocking_issues': [],
             'sales_windows': [], 'operations': {'action': 'first variant action', 'evidence': ['first']}}
    pending = {'sku_id': 2, 'sku': 'B', 'inventory_complete': False, 'needs_review': True,
               'suggested_quantity': None, 'decision_state': 'pending',
               'blocking_issues': ['warehouse_supply_scope_incomplete'], 'sales_windows': []}
    original = deepcopy([ready, pending])
    parent = _group_inventory_spus([ready, pending], {1: {'spu_id': 10}, 2: {'spu_id': 10}}, 30)[0]
    assert parent['inventory_complete'] is False and parent['needs_review'] is True
    for field in ('suggested_quantity', 'suggestion_formula', 'decision_state', 'replenishment_status', 'blocking_issues'):
        assert field not in parent
    assert 'action' not in parent['operations'] and 'evidence' not in parent['operations']
    assert parent['variants'] == original
