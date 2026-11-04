"""Durable financial results, synthetic fixtures only; no provider requests."""
import pytest
from unittest.mock import Mock
from django.utils import timezone
from datetime import timedelta
from django.db import transaction

from apps.finance.summary_models import FinanceSummaryCalculation
from apps.finance.summary_jobs import run_calculation, dispatch_calculations
from tests.test_finance_summary import context, URL
from apps.finance.summary_service import READ_PERMISSIONS
from tests.test_sales_management import create_scope, user_for, grant, client_for

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def broker(monkeypatch):
    send = Mock()
    monkeypatch.setattr(run_calculation, 'apply_async', send)
    return send


def test_rollback_never_dispatches_uncommitted_work(context, broker):
    from apps.finance.summary_jobs import request_calculation
    _, user, dataset, _ = context
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            request_calculation(dataset, user, {'action': 'history', 'page': 1})
            assert not broker.called
            raise RuntimeError('synthetic rollback')
    assert not broker.called and not FinanceSummaryCalculation.objects.exists()


def test_job_permission_manifest_registration():
    import json
    from pathlib import Path
    from django.urls import resolve
    from apps.permissions.catalog_governance import classify_endpoint
    import apps.permissions
    manifest = json.loads(Path(apps.permissions.__file__).with_name('permission_manifest.json').read_text(encoding='utf8'))
    route = 'api/finance/summary/jobs/<int:pk>/'
    current = classify_endpoint(route, resolve('/' + route.replace('<int:pk>', '1')).func,
                                {row['code']: row for row in manifest['permissions']})
    registered = [row for row in manifest['endpoints'] if row['route'] == route]
    assert sorted(current, key=lambda row: row['method']) == registered


def test_cache_survives_calculator_restart_and_duplicate_requests(context, monkeypatch, broker):
    client, actor, dataset, state = context
    calculate = Mock(return_value={'rows': [{'amount': '-1.000001'}], 'total': 1, 'page': 1})
    monkeypatch.setattr('apps.finance.summary_native.query', calculate)
    url = URL + f'{dataset.pk}/table/'
    first = client.get(url)
    assert first.status_code == 202
    assert client.get(url).status_code == 202
    assert FinanceSummaryCalculation.objects.count() == 1 and broker.call_count == 1
    run_calculation(first.data['data']['job']['id'])
    calculate.side_effect = AssertionError('No recalculation after memory loss')
    result = client.get(url)
    assert result.status_code == 200
    assert result.data['data']['rows'] == [{'amount': '-1.000001'}]
    assert calculate.call_count == 1


def test_revision_change_does_not_reuse_an_old_result(context, monkeypatch):
    client, _, dataset, state = context
    monkeypatch.setattr('apps.finance.summary_native.query', Mock(return_value={'rows': []}))
    job = client.get(URL + f'{dataset.pk}/table/').data['data']['job']['id']
    state.revision += 1
    state.save()
    run_calculation(job)
    assert FinanceSummaryCalculation.objects.get(pk=job).status == 'superseded'
    assert client.get(URL + f'{dataset.pk}/table/').status_code == 202
    assert FinanceSummaryCalculation.objects.count() == 2


def test_scope_and_tenant_are_checked_even_for_persisted_results(context, monkeypatch):
    client, _, dataset, _ = context
    monkeypatch.setattr('apps.finance.summary_native.query', Mock(return_value={'rows': []}))
    job = client.get(URL + f'{dataset.pk}/table/').data['data']['job']['id']
    run_calculation(job)
    tenant, _, _, _ = create_scope('summary-cache-other')
    other = user_for(tenant, 'cache-other')
    for code in READ_PERMISSIONS:
        grant(other, code)
    assert client_for(other).get(URL + f'jobs/{job}/').status_code == 404
    partial = user_for(dataset.tenant, 'cache-partial')
    for code in READ_PERMISSIONS:
        grant(partial, code, scope_type='self' if code == 'finance.view' else 'all')
    assert client_for(partial).get(URL + f'jobs/{job}/').status_code == 403


def test_revoked_actor_and_corrupt_payload_are_not_served(context, monkeypatch):
    client, actor, dataset, _ = context
    monkeypatch.setattr('apps.finance.summary_native.query', Mock(return_value={'rows': []}))
    job = client.get(URL + f'{dataset.pk}/table/').data['data']['job']['id']
    actor.is_active = False
    actor.save(update_fields=['is_active'])
    run_calculation(job)
    assert FinanceSummaryCalculation.objects.get(pk=job).status == 'blocked'
    actor.is_active = True
    actor.save(update_fields=['is_active'])
    job = client.get(URL + f'{dataset.pk}/table/').data['data']['job']['id']
    run_calculation(job)
    FinanceSummaryCalculation.objects.filter(pk=job).update(result_hash='0' * 64)
    assert client.get(URL + f'jobs/{job}/').status_code == 400


def test_broker_failure_is_durable_and_dispatcher_recovers_expired_lease(context, monkeypatch, broker):
    client, _, dataset, _ = context
    broker.side_effect = RuntimeError('SYNTHETIC_PRIVATE')
    response = client.get(URL + f'{dataset.pk}/table/')
    job = FinanceSummaryCalculation.objects.get()
    assert response.status_code == 202 and job.error_code == 'BROKER_UNAVAILABLE'
    assert 'SYNTHETIC_PRIVATE' not in str(response.data)
    job.status, job.running_until = 'running', timezone.now() - timedelta(seconds=1)
    job.save()
    broker.side_effect = None
    dispatch_calculations()
    job.refresh_from_db()
    assert job.status == 'queued'


def test_failed_rebuild_keeps_active_dataset_and_settings(context, monkeypatch):
    client, actor, dataset, state = context
    grant(actor, 'finance.import')
    dataset.metadata['database_scope'] = {'stores': [], 'from': '2026-09-01', 'to': '2026-09-30'}
    dataset.save()
    monkeypatch.setattr('apps.finance.summary_rebuild.rebuild', Mock(side_effect=RuntimeError('PRIVATE_PROVIDER_URL')))
    first = client.post(URL + f'{dataset.pk}/rebuild/', {'revision': 0}, format='json')
    assert first.status_code == 202
    job = first.data['data']['job']['id']
    run_calculation(job)
    dataset.refresh_from_db(); state.refresh_from_db()
    assert dataset.active and state.revision == 0
    status = client.get(URL + f'jobs/{job}/')
    assert status.data['data']['job']['status'] == 'failed'
    assert 'PRIVATE_PROVIDER_URL' not in str(status.data)


def test_inflight_revision_change_and_duplicate_delivery_do_not_publish(context, monkeypatch):
    client, _, dataset, state = context
    def calculate(*args):
        assert run_calculation(job)['status'] == 'not_claimed'
        state.revision += 1
        state.save()
        return {'amount': '99999999999999.000001'}
    monkeypatch.setattr('apps.finance.summary_native.query', calculate)
    job = client.get(URL + f'{dataset.pk}/table/').data['data']['job']['id']
    run_calculation(job)
    row = FinanceSummaryCalculation.objects.get(pk=job)
    assert row.status == 'superseded' and row.result is None


def test_successful_rebuild_metadata_uses_requesting_users_permissions(context, monkeypatch):
    from apps.finance.summary_models import FinanceSummaryDataset, FinanceSummaryState
    client, actor, dataset, _ = context
    grant(actor, 'finance.import')
    dataset.metadata['database_scope'] = {'stores': [], 'from': '2026-09-01', 'to': '2026-09-30'}
    dataset.save()
    def rebuild(*args, publication_guard):
        publication_guard()
        dataset.active = False
        dataset.save()
        fresh = FinanceSummaryDataset.objects.create(tenant=dataset.tenant, created_by=actor,
            document_file=dataset.document_file, source_hash='1' * 64, metadata={'store_ids': [], 'checkpoint': {}})
        FinanceSummaryState.objects.create(dataset=fresh, updated_by=actor)
        return fresh
    monkeypatch.setattr('apps.finance.summary_rebuild.rebuild', rebuild)
    job = client.post(URL + f'{dataset.pk}/rebuild/', {'revision': 0}, format='json').data['data']['job']['id']
    run_calculation(job)
    reader = user_for(dataset.tenant, 'cache-reader')
    for code in READ_PERMISSIONS:
        grant(reader, code)
    response = client_for(reader).get(URL + f'jobs/{job}/')
    assert response.data['data']['result']['can_edit'] is False
    assert client.get(URL + f'jobs/{job}/').data['data']['result']['can_edit'] is True


@pytest.mark.parametrize('failure', ['reconciliation', 'lease', 'permission'])
def test_rebuild_publication_guards_keep_previous_batch(context, monkeypatch, failure):
    from apps.finance import summary_rebuild as service
    client, actor, dataset, _ = context
    grant(actor, 'finance.import')
    dataset.metadata['database_scope'] = {'stores': [], 'from': '2026-08-01', 'to': '2026-09-30'}
    dataset.save()
    monkeypatch.setattr(service, 'source_checkpoint', lambda stores: {})
    monkeypatch.setattr(service, 'collect', lambda *args: {'source_counts': {}})
    monkeypatch.setattr(service, 'render', lambda *args: '<html>candidate</html>')
    months = []
    def engine(candidate, payload):
        if payload['action'] == 'inspect':
            return {}
        months.append(payload['month'])
        if failure == 'lease':
            FinanceSummaryCalculation.objects.filter(pk=job).update(running_until=timezone.now()-timedelta(seconds=1))
        if failure == 'permission':
            actor.is_active = False
            actor.save(update_fields=['is_active'])
        return {'passed': failure != 'reconciliation' or payload['month'] != '2026-08', 'checks': 1, 'results': []}
    monkeypatch.setattr(service, 'engine', engine)
    job = client.post(URL + f'{dataset.pk}/rebuild/', {'revision': 0}, format='json').data['data']['job']['id']
    run_calculation(job)
    dataset.refresh_from_db()
    assert dataset.active and FinanceSummaryCalculation.objects.get(pk=job).status in {'failed', 'blocked'}
    assert months == ['2026-08', '2026-09']
