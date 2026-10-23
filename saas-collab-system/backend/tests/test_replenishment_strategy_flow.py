"""HTTP workflow regression: only warehouse/sales facts are synthetic, demand reservations are real."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.commerce.supply_pipeline import open_demand_breakdown
from apps.sales_management.operating_models import OperatingOrder
from apps.supply_chain.dates import business_date
from apps.supply_chain.models import ReplenishmentStrategy, domain_write
from tests.test_supply_chain_v2_foundation import internal_user, world
from tests.test_supply_chain_v2_logistics import client


OPS = '/api/internal/commerce/operating-orders/'
STRATEGY = '/api/internal/supply-chain/v2/replenishment-strategies/'
REFERENCES = '/api/internal/supply-chain/v2/replenishment-references/'
CODES = ('supply.v2.view', 'supply.v2.manage', 'sales_management.operating_orders.view',
         'sales_management.operating_orders.manage', 'sales_management.view',
         'sales_management.skus.view', 'sales_management.supply_summary.view')
pytestmark = pytest.mark.django_db


@pytest.fixture
def configured(world):
    actor = internal_user(world, 'strategy-flow', codes=CODES)
    world['spu'].lifecycle_status = 'active'
    world['spu'].sales_status = 'on_sale'
    world['spu'].save(update_fields=['lifecycle_status', 'sales_status'])
    with domain_write():
        strategy = ReplenishmentStrategy.objects.create(tenant=actor.tenant, created_by=actor,
            country=world['country'], name='US normal', cycle_days=10, lead_days=45,
            safety_days=35, sales_weights={'7': 50, '15': 30, '30': 20})
    state = {'stock': '400'}

    def facts(user, country, skus, **kwargs):
        pending, signature = open_demand_breakdown(user, country, [s.pk for s in skus],
            exclude_order_id=kwargs.get('exclude_order_id'))
        rows = []
        for sku in skus:
            submitted = pending[sku.pk]['submitted']
            draft = pending[sku.pk]['draft_reserved']
            rows.append({'sku_id': sku.pk, 'sku': sku.sku_code, 'product_name': 'Synthetic fact',
                'available_stock': state['stock'], 'inventory_complete': True,
                'source_snapshot_ids': [1], 'source_run_ids': [2], 'issues': [], 'blocking_issues': [],
                'sales_windows': [{'days': d, 'units': q, 'daily_units': str(Decimal(q) / d),
                    'coverage_complete': True} for d, q in ((7, 140), (15, 240), (30, 420))],
                'pipeline': {'authorized': True, 'issues': [], 'unknown_eta': 0,
                    'received_awaiting_wms': 0, 'effective_incoming': 0, 'eta_rows': [],
                    'submitted_operating_demand': submitted, 'draft_reserved_demand': draft,
                    'open_operating_demand': submitted + draft, 'open_demand_signature': signature,
                    'supply_basis_signature': 'stable-synthetic-supply'}})
        return rows
    with patch('apps.commerce.country_decisions.decision_rows', side_effect=facts), \
            patch('apps.commerce.country_decisions.sales_platform_options', return_value=[]):
        yield actor, strategy, state


def preview(api, world, strategy, key='preview', **extra):
    return api.post(OPS + 'preview/', {'country_id': world['country'].pk,
        'strategy_id': strategy.pk, 'source_kind': 'cycle', 'sku_ids': [world['sku'].pk], **extra},
        format='json', HTTP_IDEMPOTENCY_KEY=key)


def order_body(world, token, quantity=1184):
    return {'country_id': world['country'].pk, 'source_kind': 'cycle',
        'order_date': business_date().isoformat(), 'notes': 'reviewed', 'preview_token': token,
        'lines': [{'sku_id': world['sku'].pk, 'quantity': quantity}]}


def test_preview_create_edit_same_token_and_submit_preserves_own_reservation(world, configured):
    actor, strategy, _ = configured
    api = client(actor)
    response = preview(api, world, strategy)
    assert response.status_code == 200, response.data
    result = response.data['data']
    assert result['parameters']['sku_ids'] == [world['sku'].pk]
    assert result['lines'][0]['suggested_quantity'] == 1184
    assert OperatingOrder.objects.count() == 0
    body = order_body(world, result['preview_token'])
    created = api.post(OPS, body, format='json', HTTP_IDEMPOTENCY_KEY='create')
    assert created.status_code == 201, created.data
    obj = created.data['data']
    edited = api.patch(OPS + f"{obj['id']}/", {**body, 'notes': 'adjusted',
        'expected_version': obj['version']}, format='json', HTTP_IDEMPOTENCY_KEY='edit')
    assert edited.status_code == 200, edited.data
    submitted = api.post(OPS + f"{obj['id']}/submit/", {'expected_version': edited.data['data']['version']},
        format='json', HTTP_IDEMPOTENCY_KEY='submit')
    assert submitted.status_code == 200, submitted.data
    assert submitted.data['data']['status'] == 'submitted'
    duplicate = api.post(OPS, body, format='json', HTTP_IDEMPOTENCY_KEY='duplicate')
    assert duplicate.status_code >= 400
    assert OperatingOrder.objects.count() == 1


def test_stock_change_invalidates_preview_before_creation(world, configured):
    actor, strategy, state = configured
    api = client(actor)
    result = preview(api, world, strategy).data['data']
    state['stock'] = '401'
    out = api.post(OPS, order_body(world, result['preview_token']), format='json', HTTP_IDEMPOTENCY_KEY='stale')
    assert out.status_code >= 400
    assert OperatingOrder.objects.count() == 0


def test_strategy_update_has_version_check_and_invalidates_preview(world, configured):
    actor, strategy, _ = configured
    api = client(actor)
    result = preview(api, world, strategy).data['data']
    body = {'country_id': world['country'].pk, 'name': 'US revised', 'cycle_days': 12,
        'lead_days': 45, 'safety_days': 35, 'sales_weights': {'7': 50, '15': 30, '30': 20},
        'expected_version': strategy.version}
    saved = api.put(STRATEGY, body, format='json')
    assert saved.status_code == 200, saved.data
    conflict = api.put(STRATEGY, body, format='json')
    assert conflict.status_code >= 400
    stale = api.post(OPS, order_body(world, result['preview_token']), format='json', HTTP_IDEMPOTENCY_KEY='stale-strategy')
    assert stale.status_code >= 400


def test_procurement_reference_without_operating_permission_is_read_only(world, configured):
    _, strategy, _ = configured
    actor = internal_user(world, 'procurement-reference', codes=('supply.v2.view',
        'sales_management.view', 'sales_management.skus.view', 'sales_management.supply_summary.view'))
    api = client(actor)
    out = api.post(REFERENCES, {'country_id': world['country'].pk, 'strategy_id': strategy.pk,
        'source_kind': 'cycle', 'quantity_filter': 'all'}, format='json')
    assert out.status_code == 200, out.data
    assert out.data['data']['lines'][0]['suggested_quantity'] == 1184
    assert api.get(STRATEGY).data['data']['can_manage'] is False
    assert api.get(OPS).status_code == 403
    assert OperatingOrder.objects.count() == 0


def test_outside_period_demand_is_not_deducted_and_undated_draft_is_reserved(world, configured):
    actor, _, _ = configured
    api = client(actor)
    for key, quantity, dates in [('future', 50, {
        'demand_start': (business_date() + timedelta(days=400)).isoformat(),
        'demand_end': (business_date() + timedelta(days=410)).isoformat()}), ('undated', 20, {})]:
        body = {'country_id': world['country'].pk, 'source_kind': 'new_goods',
            'order_date': business_date().isoformat(), 'notes': key,
            'lines': [{'sku_id': world['sku'].pk, 'quantity': quantity}], **dates}
        response = api.post(OPS, body, format='json', HTTP_IDEMPOTENCY_KEY=key)
        assert response.status_code == 201, response.data
    totals, _ = open_demand_breakdown(actor, world['country'], [world['sku'].pk],
        horizon_start=business_date() + timedelta(days=1), horizon_end=business_date() + timedelta(days=90))
    assert totals[world['sku'].pk] == {'submitted': 0, 'draft_reserved': 20}
