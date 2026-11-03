import gzip
import hashlib
import json

import pytest
from rest_framework.exceptions import ValidationError

from apps.finance.models import FinanceAuditLog
from apps.finance.summary_models import FinanceSummaryDataset, FinanceSummaryState
from apps.finance.summary_service import READ_PERMISSIONS, pack_values, unpack_values
from tests.test_sales_management import create_scope, user_for, grant, client_for

URL = '/api/finance/summary/'


def test_native_bootstrap_excludes_settings_and_closed_books(context):
    client, _, _, state = context
    state.values = {'html2-profit-closed-periods-v1': '{"large":"book"}'}
    state.save()
    response = client.get(URL, {'native': '1'})
    assert response.status_code == 200
    assert 'values' not in response.data['data']
    assert 'values' in client.get(URL).data['data']


def test_native_query_validates_pagination_and_forwards_filters(context, monkeypatch):
    client, _, dataset, _ = context
    calls = []
    monkeypatch.setattr('apps.finance.summary_native.query', lambda dataset, payload: calls.append(payload) or {'rows': [], 'total': 0})
    url = URL + f'{dataset.pk}/table/'
    assert client.get(url, {'page_size': 101}).status_code == 400
    assert client.get(url, {'view': 'invalid'}).status_code == 400
    response = client.get(url, {'view': 'sku', 'page': 2, 'filter_store': '50', 'filter_keyword': '佣金'})
    assert response.status_code == 202
    from apps.finance.summary_jobs import run_calculation
    run_calculation(response.data['data']['job']['id'])
    assert calls == [{'action': 'table', 'view': 'sku', 'mode': 'operations', 'scope': 'store', 'page': 2,
                      'page_size': 20, 'filters': {'store': '50', 'keyword': '佣金'}}]
    assert response['Cache-Control'] == 'no-store'


def test_native_routes_enforce_tenant_and_write_access(context, monkeypatch):
    client, _, dataset, _ = context
    monkeypatch.setattr('apps.finance.summary_native.query', lambda *args: pytest.fail('Unauthorized engine call'))
    assert client.post(URL+f'{dataset.pk}/fee/', {'revision': 0, 'record': {}}, format='json').status_code == 403
    tenant, _, _, _ = create_scope('native-other')
    other = user_for(tenant, 'native-other')
    for code in READ_PERMISSIONS:
        grant(other, code)
    for route in ['table', 'table-detail', 'history']:
        assert client_for(other).get(URL+f'{dataset.pk}/{route}/').status_code == 404


def test_pending_attribution_is_an_explicit_detail_scope(context, monkeypatch):
    client, _, dataset, _ = context
    calls = []
    monkeypatch.setattr('apps.finance.summary_native.query', lambda dataset, payload: calls.append(payload) or {'rows': [], 'total': 0})
    url = URL + f'{dataset.pk}/table/'
    assert client.get(url, {'filter_attribution': 'invalid'}).status_code == 400
    assert client.get(url, {'view': 'store', 'filter_attribution': 'pending'}).status_code == 400
    response = client.get(url, {'view': 'detail', 'filter_month': '2026-09', 'filter_attribution': 'pending'})
    assert response.status_code == 202
    from apps.finance.summary_jobs import run_calculation
    run_calculation(response.data['data']['job']['id'])
    assert calls[0]['filters'] == {'month': '2026-09', 'attribution': 'pending'}


def test_cost_detail_pagination_is_validated_and_forwarded(context, monkeypatch):
    client, _, dataset, _ = context
    calls = []
    monkeypatch.setattr('apps.finance.summary_native.query', lambda dataset, payload: calls.append(payload) or {})
    url = URL+f'{dataset.pk}/table-detail/'
    params = {'view': 'store', 'row_key': 'shop', 'kind': 'product_cost', 'cost_page': 0}
    assert client.get(url, params).status_code == 400
    params['cost_page'] = 2
    params['flow_page'] = 0
    assert client.get(url, params).status_code == 400
    params['flow_page'] = 2
    response = client.get(url, params)
    assert response.status_code == 202
    from apps.finance.summary_jobs import run_calculation
    run_calculation(response.data['data']['job']['id'])
    assert calls[0]['cost_page'] == 2
    assert calls[0]['flow_page'] == 2
    assert calls[0]['kind'] == 'product_cost'


def test_native_detail_requires_row_and_kind(context, monkeypatch):
    client, _, dataset, _ = context
    monkeypatch.setattr('apps.finance.summary_native.query', lambda dataset, payload: payload)
    url = URL+f'{dataset.pk}/table-detail/'
    assert client.get(url).status_code == 400
    response = client.get(url, {'row_key': 'row', 'kind': 'rate:order_fee'})
    assert response.status_code == 202
    from apps.finance.summary_jobs import run_calculation
    run_calculation(response.data['data']['job']['id'])
    response = client.get(url, {'row_key': 'row', 'kind': 'rate:order_fee'})
    assert response.status_code == 200
    assert response.data['data']['action'] == 'table_detail'


def test_native_fee_rejects_stale_revision_before_validation(context, monkeypatch):
    client, user, dataset, _ = context
    grant(user, 'finance.import')
    monkeypatch.setattr('apps.finance.summary_views.engine', lambda *args: pytest.fail('Stale fee reached engine'))
    assert client.post(URL+f'{dataset.pk}/fee/', {'revision': 9, 'record': {'reason': '测试'}}, format='json').status_code == 409


def test_native_fee_uses_existing_validator_and_audit(context, monkeypatch):
    client, user, dataset, state = context
    grant(user, 'finance.import')
    monkeypatch.setattr('apps.finance.summary_views.engine', lambda dataset, payload: {
        'key': 'html2-ledger-fees-v1', 'value': '{"version":1}'})
    monkeypatch.setattr('apps.finance.summary_service.engine', lambda dataset, payload: {
        'values': {payload['key']: payload['value']}})
    url = URL+f'{dataset.pk}/fee/'
    assert client.post(url, {'revision': 0, 'record': {'reason': '测试', 'unexpected': 'x'}}, format='json').status_code == 400
    response = client.post(url, {'revision': 0, 'record': {'reason': '测试修改', 'amount': '-10'}}, format='json')
    assert response.status_code == 200
    assert response.data['data']['revision'] == 1
    assert 'values' not in response.data['data']
    state.refresh_from_db()
    assert state.revision == 1
    assert FinanceAuditLog.objects.filter(object_id=str(dataset.pk), action='summary_setting').exists()


def test_large_close_snapshot_is_compressed_losslessly_and_verified():
    original = {'html2-profit-closed-periods-v1': json.dumps({'rows':['金融来源'*100 for _ in range(1000)]})}
    stored = pack_values(original)
    assert stored['html2-profit-closed-periods-v1']['encoding'] == 'gzip-base64-v1'
    assert len(json.dumps(stored)) < len(json.dumps(original)) / 10
    assert unpack_values(stored) == original
    stored['html2-profit-closed-periods-v1']['sha256'] = 'broken'
    with pytest.raises(ValidationError):
        unpack_values(stored)


@pytest.fixture
def context(db, settings, tmp_path, monkeypatch):
    tenant, _, store, _ = create_scope('financial-summary')
    user = user_for(tenant, 'summary-user')
    for code in READ_PERMISSIONS:
        grant(user, code)
    settings.FINANCE_SUMMARY_ROOT = str(tmp_path)
    source = b'<html>\r\n<head></head>\r\n<body><script>localStorage.getItem("x")</script></body></html>'
    (tmp_path / 'batch.html.gz').write_bytes(gzip.compress(source))
    dataset = FinanceSummaryDataset.objects.create(tenant=tenant, created_by=user, label='验收批次',
        source_hash=hashlib.sha256(source).hexdigest(), document_file='batch.html.gz', metadata={'store_ids':[store.pk], 'checkpoint':{}})
    state = FinanceSummaryState.objects.create(dataset=dataset, updated_by=user)
    monkeypatch.setattr('apps.finance.summary_service.source_checkpoint', lambda ids: {})
    return client_for(user), user, dataset, state


def payload(**kw):
    return {'revision':0, 'key':'html2-ledger-fees-v1', 'value':'{}', 'reason':'测试调整', **kw}


def test_batch_read_requires_auth_and_full_scopes(context):
    from rest_framework.test import APIClient
    client, user, dataset, state = context
    assert APIClient().get(URL).status_code in [401, 403]
    response = client.get(URL)
    assert response.status_code == 200
    assert response.data['data']['revision'] == 0
    assert response.data['data']['can_edit'] is False
    assert 'document_file' not in response.data['data']
    partial = user_for(user.tenant, 'partial-summary')
    for code in READ_PERMISSIONS:
        grant(partial, code, scope_type='self' if code == 'finance.view' else 'all')
    assert client_for(partial).get(URL).status_code == 403


def test_other_tenant_cannot_read_or_change_batch(context):
    _, _, dataset, _ = context
    tenant, _, _, _ = create_scope('other-summary')
    user = user_for(tenant, 'other-summary-user')
    for code in (*READ_PERMISSIONS, 'finance.import'):
        grant(user, code)
    client = client_for(user)
    assert client.get(URL).status_code == 404
    assert client.get(URL+f'{dataset.pk}/document/').status_code == 404
    assert client.post(URL+f'{dataset.pk}/settings/', payload(), format='json').status_code == 404


def test_read_only_user_cannot_save(context):
    client, _, dataset, state = context
    assert client.post(URL+f'{dataset.pk}/settings/', payload(), format='json').status_code == 403
    state.refresh_from_db(); assert state.revision == 0


def test_server_validation_atomic_revision_and_audit(context, monkeypatch):
    client, user, dataset, state = context
    grant(user, 'finance.import')
    monkeypatch.setattr('apps.finance.summary_service.engine', lambda *a: {'values':{'html2-ledger-fees-v1':'{"verified":true}'}})
    response = client.post(URL+f'{dataset.pk}/settings/', payload(), format='json')
    assert response.status_code == 200, response.data
    state.refresh_from_db()
    assert state.values['html2-ledger-fees-v1'] == '{"verified":true}'
    assert state.revision == 1
    audit = FinanceAuditLog.objects.get(action='summary_setting', object_id=str(dataset.pk))
    assert audit.actor == user and audit.masked_detail['reason'] == '测试调整'
    assert client.post(URL+f'{dataset.pk}/settings/', payload(), format='json').status_code == 409
    assert FinanceAuditLog.objects.filter(action='summary_setting').count() == 1
    def reject(*args):
        raise ValidationError('原始费用只读')
    monkeypatch.setattr('apps.finance.summary_service.engine', reject)
    assert client.post(URL+f'{dataset.pk}/settings/', payload(revision=1), format='json').status_code == 400
    state.refresh_from_db(); assert state.revision == 1


@pytest.mark.parametrize('data', [payload(key='arbitrary'), payload(reason=''), payload(value='not json'), payload(revision=-1)])
def test_invalid_save_does_not_reach_engine(context, monkeypatch, data):
    client, user, dataset, state = context; grant(user, 'finance.import')
    def never(*args):
        pytest.fail('invalid request reached engine')
    monkeypatch.setattr('apps.finance.summary_service.engine', never)
    assert client.post(URL+f'{dataset.pk}/settings/', data, format='json').status_code == 400
    state.refresh_from_db(); assert state.revision == 0


def test_private_document_uses_api_bridge_and_no_browser_storage(context):
    client, _, dataset, _ = context
    response = client.get(URL+f'{dataset.pk}/document/')
    assert response.status_code == 200
    text = gzip.decompress(response.content).decode()
    assert 'globalThis.SAAS_STORAGE.getItem' in text
    assert 'finance-summary-write' in text
    assert '__SAAS_FINANCE_BOOTSTRAP__' in text
    assert 'Authorization' not in text
    assert response['Cache-Control'] == 'no-store'


def test_changed_source_is_rejected_before_rendering(context, settings):
    from pathlib import Path
    client, _, dataset, _ = context
    (Path(settings.FINANCE_SUMMARY_ROOT) / dataset.document_file).write_bytes(gzip.compress(b'<html>changed</html>'))
    assert client.get(URL+f'{dataset.pk}/document/').status_code == 400


def test_report_validates_view_and_uses_current_state(context, monkeypatch):
    client, _, dataset, _ = context
    assert client.get(URL+f'{dataset.pk}/report/', {'view':'bad'}).status_code == 400
    seen=[]
    def report(batch, data):
        seen.append(data); return [{'amount':'-1.000000'}]
    monkeypatch.setattr('apps.finance.summary_views.engine', report)
    response=client.get(URL+f'{dataset.pk}/report/', {'view':'sku','mode':'finance','store':'1','month':'2026-09'})
    assert response.status_code == 200
    assert seen[0]['view']=='sku' and seen[0]['mode']=='finance'
    assert seen[0]['state']=={}
