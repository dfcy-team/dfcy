from datetime import datetime, timedelta, timezone as utc
import uuid
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.finance import summary_schedule as scheduled
from apps.finance.summary_jobs import run_calculation, job_data, prune_expired_results
from apps.finance.summary_models import FinanceSummaryCalculation as C, FinanceSummarySnapshot as Snapshot
from apps.finance.summary_models import FinanceSummaryBuildLease as Lease
from apps.finance.summary_read_query import query_scope
from apps.finance.summary_service import private_root
from tests.test_finance_summary import context

pytestmark=pytest.mark.django_db
URL='/api/finance/summary/'


@pytest.fixture(autouse=True)
def mode(settings):
    settings.FINANCE_SUMMARY_SCHEDULED_READS_ENABLED=True


def scope(user, month='2026-10'):
    return query_scope(user,{'month':month})


def table():
    return {'rows':[{'key':'synthetic','values':{'sales':'10'},'compositions':{}}], 'total':1,
        'page':1,'options':{'months':['2026-10'],'stores':[],'countries':{},'platforms':[],'currencies':['PHP']}}


def complete(job,monkeypatch):
    def calculate(dataset,user,payload,*,snapshot_job_id):
        file=f'scheduled-source-{snapshot_job_id}.html.gz'
        (private_root()/file).write_bytes(b'synthetic frozen source')
        return {**table(),'scheduled_summary':True,'source_read_at':timezone.now().isoformat(),
            '_prepared_source_info':{'file':file,'sha256':'a'*64,'read_at':timezone.now().isoformat()}}
    with monkeypatch.context() as patch:
        patch.setattr('apps.finance.summary_read_query.execute',calculate)
        assert run_calculation(job.pk)['status']=='ready'
    job.refresh_from_db()
    return job


def test_open_and_query_do_not_start_summary(context,monkeypatch):
    client,user,_,_=context
    forbidden=Mock(side_effect=AssertionError('ordinary browsing must not read business sources'))
    monkeypatch.setattr('apps.finance.summary_read_query.launch_source_worker',forbidden)
    meta=client.get(URL,{'direct':1}).data['data']
    assert meta['scheduled_summary'] and meta['summary_schedule']==['02:00','12:30']
    response=client.get(URL+'query/',{'filter_month':'2026-10','filter_attribution':'assigned'})
    assert response.status_code==200 and response.data['data']['rows']==[]
    assert '手动汇总' in response.data['data']['period_warning']
    assert not C.objects.exists() and not forbidden.called


def test_manual_deduplicates_and_reads_completed_time_without_new_job(context,monkeypatch):
    client,user,_,_=context
    first=client.get(URL+'query/',{'filter_month':'2026-10','refresh':1})
    assert first.status_code==202
    pk=first.data['data']['job']['id']
    assert client.get(URL+'query/',{'filter_month':'2026-10','refresh':1}).data['data']['job']['id']==pk
    job=complete(C.objects.get(pk=pk),monkeypatch)
    response=client.get(URL+'query/',{'filter_month':'2026-10','filter_attribution':'assigned'})
    assert response.status_code==200 and response.data['data']['rows']==table()['rows']
    assert response.data['data']['summary_completed_at']==job.finished_at.isoformat()
    assert response.data['data']['source_read_at']
    assert C.objects.count()==1 and Snapshot.objects.get().active_job_id==pk
    assert Lease.objects.get().job_id is None


def test_failed_replacement_keeps_last_success(context,monkeypatch):
    client,user,_,_=context
    good=complete(scheduled.request_build(user,scope(user)),monkeypatch)
    next_job=scheduled.request_build(user,scope(user))
    monkeypatch.setattr('apps.finance.summary_read_query.execute',Mock(side_effect=RuntimeError('synthetic failure')))
    assert run_calculation(next_job.pk)['status']=='failed'
    assert Snapshot.objects.get().active_job_id==good.pk
    response=client.get(URL+'query/',{'filter_month':'2026-10','filter_attribution':'assigned'}).data['data']
    assert response['rows']==table()['rows'] and response['summary_state']['status']=='failed'
    assert response['summary_completed_at']==good.finished_at.isoformat()


def test_success_survives_query_cache_expiry_and_pruning(context,monkeypatch):
    client,user,_,_=context
    job=complete(scheduled.request_build(user,scope(user)),monkeypatch)
    C.objects.filter(pk=job.pk).update(created_at=timezone.now()-timedelta(days=2),finished_at=timezone.now()-timedelta(days=2))
    prune_expired_results()
    job.refresh_from_db();assert job.status=='ready' and job.result
    response=client.get(URL+'query/',{'filter_month':'2026-10','filter_attribution':'assigned'})
    assert response.status_code==200 and response.data['data']['total']==1


def test_changed_view_uses_frozen_source_and_original_completion_time(context,monkeypatch):
    client,user,_,_=context
    parent=complete(scheduled.request_build(user,scope(user)),monkeypatch)
    forbidden=Mock(side_effect=AssertionError('view switch must not collect sources'))
    monkeypatch.setattr('apps.finance.summary_read_query.launch_source_worker',forbidden)
    native=Mock(return_value=table())
    monkeypatch.setattr('apps.finance.summary_native.query',native)
    response=client.get(URL+'query/',{'filter_month':'2026-10','view':'order'})
    pk=response.data['data']['job']['id']
    assert run_calculation(pk)['status']=='ready' and not forbidden.called
    data=job_data(C.objects.get(pk=pk),user)['result']
    assert data['summary_completed_at']==parent.finished_at.isoformat()
    assert native.call_args.args[0].document_file==f'scheduled-source-{parent.pk}.html.gz'


def test_global_lease_excludes_second_build_and_old_owner_cannot_release_new(context):
    _,user,_,_=context
    a=scheduled.request_build(user,scope(user));b=scheduled.request_build(user,scope(user,'2026-11'))
    for job in [a,b]:
        job.status='running';job.lease=uuid.uuid4();job.running_until=timezone.now()+timedelta(minutes=15);job.save()
    assert scheduled.acquire_build(a,a.lease)
    assert not scheduled.acquire_build(b,b.lease)
    Lease.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
    assert scheduled.acquire_build(b,b.lease)
    scheduled.release_build(a.pk,a.lease)
    assert Lease.objects.get().job_id==b.pk


def test_daily_slots_use_beijing_time_and_are_idempotent(context,monkeypatch):
    _,user,_,_=context
    scheduled.register_scope(user,scope(user,'2026-11'))
    now=datetime(2026,11,26,17,59,tzinfo=utc.utc)
    monkeypatch.setattr(scheduled.timezone,'now',lambda:now)
    assert scheduled.dispatch_due_summaries()['queued']==0 and not C.objects.exists()
    now=datetime(2026,11,26,18,0,tzinfo=utc.utc)
    scheduled.dispatch_due_summaries();scheduled.dispatch_due_summaries()
    assert C.objects.count()==1
    first=complete(C.objects.get(),monkeypatch)
    assert Snapshot.objects.get().scheduled_slot=='2026-11-27T02:00'
    now=datetime(2026,11,27,4,30,tzinfo=utc.utc)
    scheduled.dispatch_due_summaries();scheduled.dispatch_due_summaries()
    assert C.objects.count()==2 and Snapshot.objects.get().active_job_id==first.pk
    assert Snapshot.objects.get().scheduled_slot=='2026-11-27T12:30'


def test_manual_summary_rejects_unbounded_history(context):
    _,user,_,_=context
    from rest_framework.exceptions import ValidationError
    with pytest.raises(ValidationError):scheduled.request_build(user,query_scope(user,{}))
    assert not C.objects.exists()


def test_snapshot_detail_pagination_reuses_source_and_never_publishes_head(context,monkeypatch):
    client,user,_,_=context
    parent=complete(scheduled.request_build(user,scope(user)),monkeypatch)
    forbidden=Mock(side_effect=AssertionError('detail must not reread business sources'))
    monkeypatch.setattr('apps.finance.summary_read_query.launch_source_worker',forbidden)
    native=Mock(return_value={'records':[],'records_total':0})
    monkeypatch.setattr('apps.finance.summary_native.query',native)
    response=client.get(URL+'query-detail/',{'query_context':parent.pk,'row_key':'synthetic',
        'kind':'sales','include_records':1})
    assert response.status_code==202
    child=C.objects.get(pk=response.data['data']['job']['id'])
    assert '_snapshot_build' not in child.request and child.request['_database_query']['source_job']==parent.pk
    assert run_calculation(child.pk)['status']=='ready' and not forbidden.called
    assert Snapshot.objects.get().active_job_id==parent.pk
    assert native.call_args.args[0].document_file==f'scheduled-source-{parent.pk}.html.gz'


def test_existing_dispatcher_runs_daily_slots_without_source_change_scan(context,monkeypatch):
    from apps.finance.summary_jobs import dispatch_calculations
    due=Mock();forbidden=Mock(side_effect=AssertionError('no source-change scan'))
    monkeypatch.setattr(scheduled,'dispatch_due_summaries',due)
    monkeypatch.setattr('apps.finance.summary_maintenance.schedule_changed_summaries',forbidden)
    dispatch_calculations()
    assert due.call_count==1 and not forbidden.called