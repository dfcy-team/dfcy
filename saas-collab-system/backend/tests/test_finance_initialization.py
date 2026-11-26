import gzip
import hashlib
import json
import pytest
from apps.finance.summary_initialization import template_bytes, runtime_status
from apps.finance.summary_models import FinanceSummaryDataset, FinanceSummaryCalculation
from apps.finance.summary_service import READ_PERMISSIONS, engine
from tests.test_sales_management import create_scope, user_for, grant, client_for


@pytest.fixture
def setup_initialization(settings, tmp_path, monkeypatch):
    settings.FINANCE_SUMMARY_ROOT = tmp_path
    tenant, _, store, _ = create_scope('summary-initialize')
    user = user_for(tenant, 'summary-initialize')
    for code in (*READ_PERMISSIONS, 'finance.import'):
        grant(user, code)
    monkeypatch.setattr('apps.finance.summary_jobs.enqueue', lambda row: None)
    return user, store, client_for(user)


@pytest.mark.django_db
def test_uninitialized_metadata_is_explicit_and_does_not_scan_sources(setup_initialization, monkeypatch):
    user, store, client = setup_initialization
    monkeypatch.setattr('apps.finance.summary_service.source_checkpoint', lambda *a: pytest.fail('metadata must not scan source tables'))
    response = client.get('/api/finance/summary/', {'native':1})
    assert response.status_code == 200
    assert response.data['data']['initialized'] is False
    assert response.data['data']['scope_stores'] == [{'id':store.pk,'code':store.code}]
    assert 'total' not in response.data['data']


@pytest.mark.django_db
def test_first_request_is_idempotent_tenant_scoped_and_inactive(setup_initialization):
    user, store, client = setup_initialization
    body = {'scope':{'from':'2026-10-01','to':'2026-10-31','stores':[store.pk]}}
    first = client.post('/api/finance/summary/initialize/', body, format='json')
    assert first.status_code == 202, first.data
    second = client.post('/api/finance/summary/initialize/', body, format='json')
    assert second.data['data']['job']['id'] == first.data['data']['job']['id']
    assert FinanceSummaryCalculation.objects.count() == 1
    assert not FinanceSummaryDataset.objects.filter(active=True).exists()
    other, _, foreign_store, _ = create_scope('summary-foreign')
    body['scope']['stores'] = [foreign_store.pk]
    assert client.post('/api/finance/summary/initialize/', body, format='json').status_code == 400
    assert FinanceSummaryCalculation.objects.count() == 1


@pytest.mark.django_db
def test_missing_runtime_cannot_queue_a_calculation(setup_initialization, monkeypatch):
    _, store, client = setup_initialization
    monkeypatch.setattr('apps.finance.summary_initialization.runtime_status', lambda: {'ready':False,'missing':['node']})
    response = client.post('/api/finance/summary/initialize/', {'scope':{'from':'2026-10-01','to':'2026-10-31','stores':[store.pk]}}, format='json')
    assert response.status_code == 400
    assert not FinanceSummaryCalculation.objects.exists()


@pytest.mark.django_db
def test_metadata_restores_previous_scope_without_foreign_stores(setup_initialization):
    user, store, client = setup_initialization
    body = {'scope': {'from': '2026-10-01', 'to': '2026-10-31', 'stores': [store.pk]}}
    response = client.post('/api/finance/summary/initialize/', body, format='json')
    job = FinanceSummaryCalculation.objects.get(pk=response.data['data']['job']['id'])
    job.status = 'superseded'
    job.request['scope']['stores'].append(999999)
    job.save(update_fields=['status', 'request'])
    data = client.get('/api/finance/summary/', {'native': 1}).data['data']
    assert data['initialization_job']['status'] == 'superseded'
    assert data['initialization_job']['scope'] == body['scope']
    assert not FinanceSummaryDataset.objects.filter(active=True).exists()


def test_template_contains_no_business_rows_and_runs_with_empty_settings(settings, tmp_path):
    settings.FINANCE_SUMMARY_ROOT = tmp_path
    raw, manifest = template_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest['sha256']
    file = tmp_path / 'template.html.gz'
    file.write_bytes(gzip.compress(raw))
    dataset = FinanceSummaryDataset(document_file=file.name, source_hash=manifest['sha256'])
    assert engine(dataset, {'action':'inspect','state':{}}) == {'stores':[],'rawStores':[],'snapshot':'','rawRows':0}
    report = engine(dataset, {'action':'reconcile','month':'2026-10','state':{}})
    assert report['passed'] is True and report['results'] == []
    assert b"LZ7PH:'49'" not in raw


def test_source_conservation_rejects_duplicate_flows_and_keeps_missing_separate_from_zero():
    from apps.finance.summary_source_checks import check_sources
    from rest_framework.exceptions import ValidationError
    source = {'raw': [{'id': 1, 'currency': 'PHP', 'amount': '-3'},
                      {'id': 2, 'currency': 'PHP', 'amount': '10'}],
        'raw_flows': [{'source_id': 'finance-transaction:1', 'currency': 'PHP', 'amount': '-3', 'kind': 'order_fee'},
                      {'source_id': 'finance-transaction:2', 'currency': 'PHP', 'amount': '10', 'kind': 'settlement', 'status': 'reference'}],
        'facts': [{'store_id': 1, 'kind': 'advertising', 'amount': '0'},
                  {'store_id': 1, 'kind': 'product_cost', 'amount': None}], 'scope': {'stores': [1]}}
    result = check_sources(source)
    assert result['original_totals_by_currency'] == {'PHP': '7'}
    statuses = {row['kind']: row['status'] for row in result['coverage']}
    assert statuses['advertising'] == 'observed_zero'
    assert statuses['product_cost'] == 'pending' and statuses['warehouse_order'] == 'missing'
    source['raw_flows'][1] = source['raw_flows'][0].copy()
    with pytest.raises(ValidationError):
        check_sources(source)


@pytest.mark.django_db
def test_empty_or_failed_calculation_never_publishes(setup_initialization, monkeypatch):
    from apps.finance.summary_jobs import run_calculation
    user, store, client = setup_initialization
    response = client.post('/api/finance/summary/initialize/',
        {'scope': {'from': '2026-10-01', 'to': '2026-10-31', 'stores': [store.pk]}}, format='json')
    monkeypatch.setattr('apps.finance.summary_rebuild.source_checkpoint', lambda ids: {})
    monkeypatch.setattr('apps.finance.summary_rebuild.collect', lambda *a, **kw: {'raw': []})
    job_id = response.data['data']['job']['id']
    assert run_calculation(job_id) == {'status': 'failed'}
    assert FinanceSummaryCalculation.objects.get(pk=job_id).error_code == 'CALCULATION_FAILED'
    assert not FinanceSummaryDataset.objects.filter(active=True).exists()


@pytest.mark.django_db
def test_candidate_publication_rechecks_tenant_sources_and_preserves_other_active_batch(setup_initialization, monkeypatch):
    from apps.finance.summary_models import FinanceSummaryState
    user, store, client = setup_initialization
    raw, manifest = template_bytes()
    from apps.finance.summary_service import private_root
    path = private_root() / 'synthetic-candidate.html.gz'
    path.write_bytes(gzip.compress(raw))
    candidate = FinanceSummaryDataset.objects.create(tenant=user.tenant, created_by=user, active=False,
        document_file=path.name, source_hash=manifest['sha256'], metadata={
            'bootstrap_candidate': True, 'automatic_update_enabled': False,
            'store_ids': [store.pk], 'database_scope': {'stores': [store.pk], 'from':'2026-10-01','to':'2026-10-31'},
            'checkpoint': {}, 'reconciliation': {'conservation_passed':True,'attribution_complete':True},
            'source_checks': {'coverage_complete':True}})
    FinanceSummaryState.objects.create(dataset=candidate, updated_by=user)
    FinanceSummaryCalculation.objects.create(tenant=user.tenant, dataset=candidate, actor=user,
        cache_key='b'*64, kind='rebuild', revision=0, request={'bootstrap': True},
        status='ready', result_dataset=candidate)
    monkeypatch.setattr('apps.finance.summary_jobs.current_dataset', lambda row: candidate)
    url = f'/api/finance/summary/{candidate.pk}/publish/'
    other_tenant, _, _, _ = create_scope('publish-other')
    other = user_for(other_tenant, 'publish-other')
    for code in (*READ_PERMISSIONS, 'finance.import'):
        grant(other, code)
    assert client_for(other).post(url, {'confirm':True}, format='json').status_code == 404
    assert client.post(url, {'confirm':False}, format='json').status_code == 400
    candidate.metadata['reconciliation']['attribution_complete'] = False
    candidate.save()
    assert client.post(url, {'confirm':True}, format='json').status_code == 400
    candidate.metadata['reconciliation']['attribution_complete'] = True
    candidate.metadata['source_checks']['coverage_complete'] = False
    candidate.save()
    assert client.post(url, {'confirm':True}, format='json').status_code == 400
    candidate.metadata['source_checks']['coverage_complete'] = True
    candidate.save()
    monkeypatch.setattr('apps.finance.summary_initialization.source_checkpoint', lambda ids: {'changed':True})
    assert client.post(url, {'confirm':True}, format='json').status_code == 400
    assert not FinanceSummaryDataset.objects.filter(active=True).exists()
    monkeypatch.setattr('apps.finance.summary_initialization.source_checkpoint', lambda ids: {})
    monkeypatch.setattr('apps.finance.summary_jobs.current_dataset', lambda row: None)
    assert client.post(url, {'confirm':True}, format='json').status_code == 400
    monkeypatch.setattr('apps.finance.summary_jobs.current_dataset', lambda row: candidate)
    active = FinanceSummaryDataset.objects.create(tenant=user.tenant, created_by=user, active=True,
        source_hash='a'*64, document_file='existing.gz')
    assert client.post(url, {'confirm':True}, format='json').status_code == 400
    assert FinanceSummaryDataset.objects.get(active=True).pk == active.pk
    active.active = False
    active.save()
    assert client.post(url, {'confirm':True}, format='json').status_code == 200
    assert client.post(url, {'confirm':True}, format='json').status_code == 200
    assert FinanceSummaryDataset.objects.get(active=True).pk == candidate.pk
    monkeypatch.setattr('apps.finance.summary_service.source_checkpoint', lambda ids: pytest.fail('manual batch polling must not scan sources'))
    response = client.get('/api/finance/summary/', {'native': 1})
    assert response.data['data']['source_checked'] is False
    assert response.data['data']['source_changed'] is None
    assert response.data['data']['automation']['enabled'] is False
