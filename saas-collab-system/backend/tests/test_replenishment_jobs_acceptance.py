"""HTTP/worker acceptance: full-country materialization, isolation and cancellation."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.products.models import ProductCategory, ProductSKU
from apps.permissions.models import OrgMembership
from apps.tenants.models import Department
from apps.supply_chain import replenishment_jobs as jobs
from apps.supply_chain.dates import business_date
from apps.supply_chain.models import ReplenishmentCalculationJob, ReplenishmentCalculationRow, domain_write
from tests.test_replenishment_strategy_flow import configured, CODES
from tests.test_supply_chain_v2_foundation import world, internal_user
from tests.test_supply_chain_v2_logistics import client

pytestmark = pytest.mark.django_db
BASE = '/api/internal/supply-chain/v2/replenishment-jobs/'


def test_later_chunk_serializes_typed_evidence(world, configured, django_capture_on_commit_callbacks):
    from datetime import date, datetime, timezone as dt_timezone
    from decimal import Decimal
    from apps.supply_chain.replenishment import ReplenishmentReferences

    actor, strategy, _ = configured
    ProductSKU.objects.bulk_create([ProductSKU(tenant=actor.tenant, spu=world['spu'],
        sku_code=f'TYPED-{i:03d}', product_type=ProductSKU.ProductType.STANDARD) for i in range(19)])
    api = client(actor)
    result = create_job(api, world, strategy, django_capture_on_commit_callbacks)
    with patch.object(jobs, '_enqueue'), django_capture_on_commit_callbacks(execute=True):
        jobs.run_replenishment_calculation(result['id'])
    job = ReplenishmentCalculationJob.objects.get(pk=result['id'])
    assert job.processed == 20
    original = ReplenishmentReferences.post

    def typed_response(self, request):
        response = original(self, request)
        for line in response.data['data']['lines']:
            line['typed_evidence'] = {'observed_at': datetime(2026, 10, 25, 12, tzinfo=dt_timezone.utc),
                'date': date(2026, 10, 25), 'amount': Decimal('12.3400'), 'missing': None}
        return response

    with patch.object(ReplenishmentReferences, 'post', typed_response):
        jobs.run_replenishment_calculation(job.pk)
    job.refresh_from_db()
    assert job.status == 'completed' and job.processed == 21
    payload = next(row.payload for row in job.rows.all() if 'typed_evidence' in row.payload)
    assert payload['typed_evidence'] == {'observed_at': '2026-10-25T12:00:00Z',
        'date': '2026-10-25', 'amount': '12.3400', 'missing': None}
    response = api.get(BASE + str(job.pk) + '/rows/', {'quantity_filter': 'all', 'limit': 20, 'offset': 20})
    assert response.status_code == 200
    assert response.data['data']['count'] == 21
    assert len(response.data['data']['rows']) == 1
    jobs.run_replenishment_calculation(job.pk)
    assert job.rows.count() == 21


def create_job(api, world, strategy, callbacks, **parameters):
    with patch.object(jobs, '_enqueue') as enqueue, callbacks(execute=True):
        response = api.post(BASE, {'country_id': world['country'].pk,
            'strategy_id': strategy.pk, 'source_kind': 'cycle', **parameters}, format='json')
    assert response.status_code == 202, response.data
    return response.data['data']


@pytest.mark.parametrize('source_evidence', [{'source_blocked': True}, {'pipeline': {'authorized': False}}, {'pipeline': {'issues': ['warehouse_supply_scope_incomplete']}}, {'formula_evidence': {'sales_model': 'low_frequency'}, 'business_decision': {}}])
def test_snapshot_transfer_rejects_hard_source_marker_but_allows_estimated_scope(world, configured, source_evidence):
    from django.core.exceptions import ValidationError
    from apps.sales_management.operating import _validate_daily_selection, _source_supply_blocked
    from apps.commerce.country_decisions import permission_signature

    actor, _, _ = configured
    assert _source_supply_blocked({'source_blocked': False,
        'blocking_issues': ['collection_coverage_unproven']}) is False
    assert _source_supply_blocked({'source_blocked': True}) is True
    sku_id = world['sku'].pk
    snapshot = {'country_id': world['country'].pk, 'source_kind': 'cycle',
        'permission_signature': permission_signature(actor),
        'lines': [{'sku_id': sku_id, 'suggested_quantity': 10, **source_evidence}]}
    payload = {'country_id': world['country'].pk, 'source_kind': 'cycle',
        'lines': [{'sku_id': sku_id, 'quantity': 10}]}
    with pytest.raises(ValidationError):
        _validate_daily_selection(actor, snapshot, payload)


def test_full_country_filters_later_chunks_and_reads_never_recalculate(world, configured, django_capture_on_commit_callbacks):
    actor, strategy, _ = configured
    for index, sku in enumerate((world['sku'], world['sku_b'])):
        sku.sku_code = f'J{index:03d}'
        sku.save(update_fields=['sku_code'])
    ProductSKU.objects.bulk_create([ProductSKU(tenant=actor.tenant, spu=world['spu'],
        sku_code=f'J{i:03d}', product_type=ProductSKU.ProductType.STANDARD) for i in range(2, 45)])
    from apps.commerce import country_decisions
    facts = country_decisions.decision_rows.side_effect
    batches = []

    def variable_facts(user, country, skus, **kwargs):
        batches.append(len(skus))
        rows = facts(user, country, skus, **kwargs)
        for row in rows:
            row['available_stock'] = '99999' if int(row['sku'][1:]) < 20 else '400'
            if row['sku'] == 'J000':
                row['blocking_issues'] = ['collection_coverage_unproven']
                for window in row['sales_windows']:
                    window.update(recognized_units=window['units'], coverage_complete=False)
        return rows

    api = client(actor)
    with patch.object(country_decisions, 'decision_rows', side_effect=variable_facts):
        result = create_job(api, world, strategy, django_capture_on_commit_callbacks,
            source_kind='season', activity_start=(business_date() + timedelta(days=10)).isoformat(),
            activity_end=(business_date() + timedelta(days=20)).isoformat(), activity_factor='1.25')
        assert batches == []  # enqueue endpoint does not calculate facts
        for _ in range(3):
            with patch.object(jobs, '_enqueue'), django_capture_on_commit_callbacks(execute=True):
                jobs.run_replenishment_calculation(result['id'])
        assert batches == [20, 20, 5]
    with patch.object(country_decisions, 'decision_rows', side_effect=AssertionError('GET recalculated facts')):
        metadata = api.get(BASE + result['id'] + '/').data['data']
        assert metadata['status'] == 'completed'
        assert metadata['counts']['positive'] == 25
        page = api.get(BASE + result['id'] + '/rows/').data['data']
        assert page['count'] == 25 and len(page['rows']) == 20
        assert page['rows'][0]['sku_code'] == 'J020'
        last = api.get(BASE + result['id'] + '/rows/', {'offset': 20}).data['data']
        assert len(last['rows']) == 5 and last['has_more'] is False
        parent = ProductCategory.objects.create(tenant=actor.tenant, level=1, code='1', name='Parent')
        child = ProductCategory.objects.create(tenant=actor.tenant, parent=parent, level=2, code='01', name='Child')
        leaf = ProductCategory.objects.create(tenant=actor.tenant, parent=child, level=3, code='01', name='Leaf')
        world['spu'].category_node = leaf
        world['spu'].save(update_fields=['category_node'])
        ranked = api.get(BASE + result['id'] + '/rows/', {
            'category_ids': f'{parent.pk},{leaf.pk}', 'sort': 'sku_code', 'direction': 'desc', 'limit': 2,
        })
        assert ranked.status_code == 200, ranked.data
        matching = ProductSKU.objects.filter(tenant=actor.tenant, spu=world['spu'], sku_code__gte='J020')
        assert ranked.data['data']['count'] == matching.count()
        assert [row['sku_code'] for row in ranked.data['data']['rows']] == ['J044', 'J043']
        search = api.get(BASE + result['id'] + '/rows/', {'search': 'J044'}).data['data']
        assert search['count'] == 1
        zero = api.get(BASE + result['id'] + '/rows/', {'quantity_filter': 'zero'}).data['data']
        assert zero['count'] == 20
        observed = api.get(BASE + result['id'] + '/rows/', {'quantity_filter': 'observed'}).data['data']
        assert observed['count'] == 25 and observed['counts']['observed'] == 25
        assert observed['rows'][0]['sku_code'] == 'J020'
        zero_rows = api.get(BASE + result['id'] + '/rows/', {'quantity_filter': 'zero'}).data['data']['rows']
        estimated = next(row for row in zero_rows if row['sku_code'] == 'J000')
        assert estimated['suggested_quantity'] == 0
        assert estimated['source_blocked'] is False
        unknown = api.get(BASE + result['id'] + '/rows/', {'quantity_filter': 'unknown'}).data['data']
        assert unknown['count'] == 0
    assert ReplenishmentCalculationRow.objects.count() == 45
    jobs.run_replenishment_calculation(result['id'])
    assert ReplenishmentCalculationRow.objects.count() == 45


def test_cancel_during_calculation_discards_chunk(world, configured, django_capture_on_commit_callbacks):
    actor, strategy, _ = configured
    api = client(actor)
    result = create_job(api, world, strategy, django_capture_on_commit_callbacks)
    from apps.commerce import country_decisions
    facts = country_decisions.decision_rows.side_effect

    def cancel_inflight(*args, **kwargs):
        assert api.delete(BASE + result['id'] + '/').status_code == 200
        return facts(*args, **kwargs)

    with patch.object(country_decisions, 'decision_rows', side_effect=cancel_inflight):
        jobs.run_replenishment_calculation(result['id'])
    job = ReplenishmentCalculationJob.objects.get(pk=result['id'])
    assert job.status == 'cancelled' and job.processed == 0
    assert not job.rows.exists()


def test_cached_rows_are_private_and_revoked_strategy_is_hidden(world, configured, django_capture_on_commit_callbacks):
    actor, strategy, _ = configured
    api = client(actor)
    result = create_job(api, world, strategy, django_capture_on_commit_callbacks)
    jobs.run_replenishment_calculation(result['id'])
    other = internal_user(world, 'other-job-owner', codes=CODES)
    assert client(other).get(BASE + result['id'] + '/rows/').status_code == 404
    with domain_write():
        strategy.version += 1
        strategy.save(update_fields=['version'])
    response = api.get(BASE + result['id'] + '/rows/')
    assert response.data['data']['rows'] == []
    assert response.data['data']['status'] in {'failed', 'expired'}


def test_running_job_survives_result_ttl_and_purge(world, configured, django_capture_on_commit_callbacks):
    actor, strategy, _ = configured
    result = create_job(client(actor), world, strategy, django_capture_on_commit_callbacks)
    ReplenishmentCalculationJob.objects.filter(pk=result['id']).update(
        expires_at=timezone.now() - timedelta(minutes=1))
    assert client(actor).get(BASE + result['id'] + '/').data['data']['status'] == 'queued'
    jobs.purge_replenishment_jobs()
    assert ReplenishmentCalculationJob.objects.filter(pk=result['id']).exists()
    jobs.run_replenishment_calculation(result['id'])
    assert client(actor).get(BASE + result['id'] + '/').data['data']['status'] == 'completed'


def test_checkpoint_with_lost_continuation_is_recovered(world, configured, django_capture_on_commit_callbacks):
    actor, strategy, _ = configured
    ProductSKU.objects.bulk_create([ProductSKU(tenant=actor.tenant, spu=world['spu'],
        sku_code=f'RECOVERY-{i:03d}', product_type=ProductSKU.ProductType.STANDARD) for i in range(19)])
    result = create_job(client(actor), world, strategy, django_capture_on_commit_callbacks)
    with patch.object(jobs, '_enqueue'), django_capture_on_commit_callbacks(execute=True):
        jobs.run_replenishment_calculation(result['id'])
    job = ReplenishmentCalculationJob.objects.get(pk=result['id'])
    assert job.processed == 20 and job.lease_token is None and job.status == 'running'
    ReplenishmentCalculationJob.objects.filter(pk=job.pk).update(
        updated_at=timezone.now() - timedelta(minutes=2))
    with patch.object(jobs, '_enqueue') as enqueue:
        with django_capture_on_commit_callbacks(execute=True):
            assert jobs.recover_replenishment_jobs() == 1
        enqueue.assert_called_once_with(job.pk)
    jobs.run_replenishment_calculation(result['id'])
    job.refresh_from_db()
    assert job.status == 'completed' and job.processed == 21 and job.rows.count() == 21


def test_old_worker_cannot_overwrite_reclaimed_lease(world, configured, django_capture_on_commit_callbacks):
    actor, strategy, _ = configured
    result = create_job(client(actor), world, strategy, django_capture_on_commit_callbacks)
    from apps.commerce import country_decisions
    facts = country_decisions.decision_rows.side_effect
    reclaimed = False

    def reclaim_during_calculation(*args, **kwargs):
        nonlocal reclaimed
        if not reclaimed:
            reclaimed = True
            ReplenishmentCalculationJob.objects.filter(pk=result['id']).update(
                lease_expires_at=timezone.now() - timedelta(seconds=1))
            jobs.run_replenishment_calculation(result['id'])
        return facts(*args, **kwargs)

    with patch.object(country_decisions, 'decision_rows', side_effect=reclaim_during_calculation):
        jobs.run_replenishment_calculation(result['id'])
    job = ReplenishmentCalculationJob.objects.get(pk=result['id'])
    assert job.status == 'completed' and job.processed == 2 and job.rows.count() == 2


def test_membership_switch_and_revocation_block_cached_rows(world, configured, django_capture_on_commit_callbacks):
    actor, strategy, _ = configured
    department = Department.objects.create(tenant=actor.tenant, name='Purchasing')
    member = OrgMembership.objects.create(tenant=actor.tenant, user=actor, department=department)
    actor._active_membership_id = member.pk
    api = client(actor)
    result = create_job(api, world, strategy, django_capture_on_commit_callbacks)
    jobs.run_replenishment_calculation(result['id'])
    assert api.get(BASE + result['id'] + '/').data['data']['status'] == 'completed'
    actor._active_membership_id = None
    assert api.get(BASE + result['id'] + '/rows/').status_code == 403
    actor._active_membership_id = member.pk
    member.status = 'inactive'
    member.save(update_fields=['status'])
    response = api.get(BASE + result['id'] + '/rows/')
    assert response.data['data']['status'] == 'failed' and response.data['data']['rows'] == []


def test_broker_failure_is_visible_without_inline_calculation(world, configured, django_capture_on_commit_callbacks):
    actor, strategy, _ = configured
    from apps.commerce import country_decisions
    with patch.object(jobs, '_enqueue', side_effect=RuntimeError('broker unavailable')), \
            patch.object(country_decisions, 'decision_rows') as calculator:
        with django_capture_on_commit_callbacks(execute=True):
            response = client(actor).post(BASE, {'country_id': world['country'].pk,
                'strategy_id': strategy.pk, 'source_kind': 'cycle'}, format='json')
        calculator.assert_not_called()
    job = ReplenishmentCalculationJob.objects.get(pk=response.data['data']['id'])
    assert job.status == 'failed' and job.error and not job.rows.exists()


def test_expired_completed_results_are_not_exposed(world, configured, django_capture_on_commit_callbacks):
    actor, strategy, _ = configured
    api = client(actor)
    result = create_job(api, world, strategy, django_capture_on_commit_callbacks)
    jobs.run_replenishment_calculation(result['id'])
    ReplenishmentCalculationJob.objects.filter(pk=result['id']).update(
        expires_at=timezone.now() - timedelta(seconds=1))
    response = api.get(BASE + result['id'] + '/rows/').data['data']
    assert response['status'] == 'expired' and response['rows'] == []


def test_matching_active_job_is_reused_even_when_another_job_is_newer(world, configured, django_capture_on_commit_callbacks):
    actor, strategy, _ = configured
    api = client(actor)
    first = create_job(api, world, strategy, django_capture_on_commit_callbacks)
    with patch.object(jobs, '_enqueue'), django_capture_on_commit_callbacks(execute=True):
        second = api.post(BASE, {'country_id': world['country'].pk, 'strategy_id': strategy.pk,
            'source_kind': 'cycle', 'sales_end': (business_date() - timedelta(days=2)).isoformat()}, format='json')
    assert second.status_code == 202
    duplicate = create_job(api, world, strategy, django_capture_on_commit_callbacks)
    assert duplicate['id'] == first['id'] and ReplenishmentCalculationJob.objects.count() == 2


@pytest.mark.parametrize('mode', ['low_frequency', 'ordinary'])
@pytest.mark.parametrize('editing', [False, True])
def test_actual_legacy_daily_payload_uses_matching_sku_strategy_without_model_projection(world, configured, mode, editing):
    from django.core.exceptions import ValidationError
    from types import SimpleNamespace
    from apps.sales_management.operating import _validate_daily_selection
    from apps.commerce.country_decisions import permission_signature
    actor, strategy, _ = configured
    sku_id = world['sku'].pk
    strategy.sku_policies = {str(sku_id): {'mode': mode}}
    from apps.supply_chain.models import domain_write
    with domain_write():
        strategy.save(update_fields=['sku_policies'])
    snapshot = {'country_id': world['country'].pk, 'source_kind': 'cycle',
        'strategy_id': strategy.pk, 'strategy_version': strategy.version,
        'permission_signature': permission_signature(actor),
        'lines': [{'sku_id': sku_id, 'suggested_quantity': 10,
            'formula_evidence': {'sales': {'30': {'units': 30}}}, 'business_decision': {}}]}
    payload = {'country_id': world['country'].pk, 'source_kind': 'cycle', 'lines': [{'sku_id': sku_id, 'quantity': 10}]}
    current = SimpleNamespace(pk=999) if editing else None
    with patch('apps.sales_management.operating._country', side_effect=AssertionError('eligible legacy proceeds to normal scope validation')) as scoped:
        if mode == 'low_frequency':
            with pytest.raises(ValidationError):
                _validate_daily_selection(actor, snapshot, payload, current)
            scoped.assert_not_called()
        else:
            with pytest.raises(AssertionError, match='eligible legacy proceeds'):
                _validate_daily_selection(actor, snapshot, payload, current)
            scoped.assert_called_once()
