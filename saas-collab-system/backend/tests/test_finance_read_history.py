import pytest
from rest_framework.exceptions import ValidationError
from apps.finance.summary_read_query import accounting_source_scope, execute, request_query
from tests.test_finance_summary import context
from tests.test_finance_read_query import broker

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize('adjustment', [None, 'invalid', '2026-08', '2026-07'])
def test_invalid_adjustment_month_is_rejected(adjustment):
    import json
    from types import SimpleNamespace
    state=SimpleNamespace(values={'html2-profit-closed-periods-v1':json.dumps({
        'S|2026-08':{'month':'2026-08','adjustmentMonth':adjustment,'rows':[]}})})
    with pytest.raises(ValidationError):
        accounting_source_scope({'from':'2026-10-01','to':'2026-10-31','stores':[1]},state)


def test_pre_fix_ready_and_queued_direct_results_are_never_served_or_executed(context, monkeypatch):
    import gzip,hashlib,json
    from django.utils import timezone
    from unittest.mock import Mock
    from apps.finance.summary_models import FinanceSummaryCalculation
    from apps.finance.summary_jobs import calculation_key,run_calculation
    from tests.test_finance_summary import URL
    client,user,dataset,state=context
    run=Mock(return_value={'rows':[{'amount':'incorrect-old-cache'}]})
    monkeypatch.setattr('apps.finance.summary_read_query.execute',run)
    reply=client.get(URL+'query/',{'filter_month':'2026-10'})
    assert reply.status_code==202
    job=FinanceSummaryCalculation.objects.get(pk=reply.data['data']['job']['id'])
    job.request['_database_query'].pop('accounting_history_version')
    job.cache_key=calculation_key(job.dataset,'query',job.request)
    raw=json.dumps({'rows':[{'amount':'incorrect-old-cache'}]}).encode()
    job.result=gzip.compress(raw);job.result_hash=hashlib.sha256(raw).hexdigest()
    job.status='ready';job.finished_at=timezone.now();job.save()
    actual=client.get(URL+f'jobs/{job.pk}/').data['data']
    assert actual['job']['status']=='superseded' and actual['job']['error_code']=='VERSION_CHANGED'
    assert not actual.get('result')
    job.status='queued';job.result=None;job.result_hash='';job.save()
    run_calculation(job.pk);job.refresh_from_db()
    assert job.status=='superseded' and run.call_count==0
    state.refresh_from_db();assert state.values=={}


def test_closed_history_widens_source_months_but_preserves_store_and_display_filters(context, monkeypatch):
    _, user, dataset, state = context
    sid = dataset.metadata['store_ids'][0]
    state.values = {'html2-profit-closed-periods-v1': '{"shop|2026-08":{"shop":"shop","month":"2026-08","adjustmentMonth":"2026-10","rows":[{"amount":"17"}]}}'}
    state.save()
    calls = []
    monkeypatch.setattr('apps.finance.summary_jobs.request_calculation', lambda *args: calls.append(args) or 'job')
    request_query(user, {'filters': {'month': '2026-10'}})
    payload = calls[-1][2]
    spec = payload['_database_query']
    assert spec['scope'] == {'from': '2026-08-01', 'to': '2026-10-31', 'stores': [sid]}
    assert spec['accounting_history_version'] == 1
    assert payload['filters']['month'] == '2026-10'
    assert payload['filters']['_stores'] == [str(sid)]


def test_incomplete_or_stale_closed_history_fails_before_source_worker(context, monkeypatch):
    _, user, dataset, state = context
    state.values = {'html2-profit-closed-periods-v1': '{"shop|2026-08":{"rows":"invalid"}}'}
    state.save()
    scope = {'from':'2026-10-01','to':'2026-10-31','stores':dataset.metadata['store_ids']}
    with pytest.raises(ValidationError):
        accounting_source_scope(scope, state)
    monkeypatch.setattr('apps.finance.summary_read_query.launch_source_worker', lambda *a: pytest.fail('source worker ran'))
    with pytest.raises(ValidationError):
        execute(dataset, user, {'_database_query': {'scope': scope, 'settings': [state.dataset_id, state.revision+1], 'accounting_history_version': 1}})


def test_closed_book_rule_preserves_frozen_facts_and_emits_true_changed_and_deleted_deltas():
    import json
    import subprocess
    from pathlib import Path
    rules = json.loads((Path(__file__).parents[1] / 'apps/finance/summary_accounting_rules.json').read_text(encoding='utf-8'))
    replacement = next(rule['replace'] for rule in rules if rule['module'] == 'html2-profit-rules' and 'const current=new Map(out.filter(within)' in rule.get('replace', '')).split(' function closeMonth')[0]
    script = r"""
const closed={"S|2026-08":{shop:"S",month:"2026-08",adjustmentMonth:"2026-10",rows:[
 {source_id:"unchanged",store_code:"S",month:"2026-08",amount:"5.000000",currency:"PHP"},
 {source_id:"changed",store_code:"S",month:"2026-08",amount:"17.000000",currency:"PHP"},
 {source_id:"deleted",store_code:"S",month:"2026-08",amount:"17.000000",currency:"PHP"}
]}};
function leaf(f){return f.source_id}
function micro(v){if(v==null)return 0n;const [a,b='']=String(v).split('.');return BigInt(a)*1000000n+BigInt((b+'000000').slice(0,6))}
function fixed(v){const n=v<0n?-v:v;return (v<0n?'-':'')+(n/1000000n)+'.'+String(n%1000000n).padStart(6,'0')}
""" + replacement + r"""
const rows=applyClosed([
 {source_id:"unchanged",store_code:"S",month:"2026-08",amount:"5.000000",currency:"PHP"},
 {source_id:"changed",store_code:"S",month:"2026-08",amount:"20.000000",currency:"PHP"}
]);
process.stdout.write(JSON.stringify(rows.map(({source_id,month,amount,accounting_adjustment})=>({source_id,month,amount,accounting_adjustment}))));
"""
    actual = json.loads(subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True).stdout)
    assert {'source_id':'unchanged','month':'2026-08','amount':'5.000000'} in actual
    assert {'source_id':'changed','month':'2026-08','amount':'17.000000'} in actual
    adjustments = {row['source_id']: row['amount'] for row in actual if row.get('accounting_adjustment')}
    assert adjustments == {'closed-adjustment:S|2026-08:changed': '3.000000',
                            'closed-adjustment:S|2026-08:deleted': '-17.000000'}
