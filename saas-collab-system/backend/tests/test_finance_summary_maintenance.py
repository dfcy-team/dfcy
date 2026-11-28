"""Synthetic coverage and unattended scheduling tests; no business database."""
import pytest
from django.core.cache import cache
from rest_framework.exceptions import ValidationError
from apps.finance.summary_maintenance import schedule_changed_summaries, validate_scope
from apps.finance.summary_models import FinanceSummaryCalculation
from tests.test_finance_summary import context, URL
from tests.test_sales_management import grant, create_scope

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def legacy_refresh_mode(settings):
    """Compatibility coverage; the new default mode has its own schedule suite."""
    settings.FINANCE_SUMMARY_SCHEDULED_READS_ENABLED = False



@pytest.fixture
def scheduled(context, monkeypatch):
    cache.clear()
    client, actor, dataset, state = context
    grant(actor, 'finance.import')
    dataset.metadata['database_scope'] = {'from': '2026-08-01', 'to': '2026-09-30', 'stores': dataset.metadata['store_ids']}
    dataset.metadata['automatic_scope'] = {'from': '2026-10-01', 'to': '2026-11-14', 'stores': dataset.metadata['store_ids']}
    dataset.save()
    monkeypatch.setattr('apps.finance.summary_recent.recent_scope', lambda ids: {'from':'2026-10-01','to':'2026-11-14','stores':ids})
    monkeypatch.setattr('apps.finance.summary_maintenance.source_checkpoint', lambda ids: {'changed': True})
    monkeypatch.setattr('apps.finance.summary_jobs.enqueue', lambda row: None)
    yield context
    cache.clear()


def test_unattended_scheduler_queues_once_and_preserves_scope(scheduled):
    _, actor, dataset, state = scheduled
    schedule_changed_summaries()
    job = FinanceSummaryCalculation.objects.get()
    assert job.kind == 'rebuild' and job.actor_id == actor.pk
    from apps.finance.summary_jobs import logical_payload, queue_status
    assert logical_payload(job.request) == {'revision': state.revision, 'automatic_scope': dataset.metadata['automatic_scope']}
    assert queue_status(job.status, job.request)['phase'] == 'merging'
    cache.clear()
    schedule_changed_summaries()
    assert FinanceSummaryCalculation.objects.count() == 1
    dataset.refresh_from_db()
    assert dataset.active


def test_manual_only_batch_never_scans_or_schedules(scheduled, monkeypatch):
    _, _, dataset, _ = scheduled
    dataset.metadata['automatic_update_enabled'] = False
    dataset.save()
    monkeypatch.setattr('apps.finance.summary_maintenance.source_checkpoint', lambda ids: pytest.fail('manual batch source scan'))
    schedule_changed_summaries()
    assert not FinanceSummaryCalculation.objects.exists()


def test_new_calendar_window_schedules_without_source_changes(scheduled, monkeypatch):
    _, _, dataset, _ = scheduled
    monkeypatch.setattr('apps.finance.summary_maintenance.source_checkpoint', lambda ids: {})
    dataset.metadata.pop('automatic_scope')
    dataset.save()
    schedule_changed_summaries()
    assert FinanceSummaryCalculation.objects.get().request['automatic_scope']['from'] == '2026-10-01'


def test_unchanged_or_inactive_actor_does_not_schedule(scheduled, monkeypatch):
    _, actor, _, _ = scheduled
    monkeypatch.setattr('apps.finance.summary_maintenance.source_checkpoint', lambda ids: {})
    schedule_changed_summaries()
    assert not FinanceSummaryCalculation.objects.exists()
    cache.clear()
    actor.is_active = False
    actor.save()
    monkeypatch.setattr('apps.finance.summary_maintenance.source_checkpoint', lambda ids: {'changed': True})
    schedule_changed_summaries()
    assert not FinanceSummaryCalculation.objects.exists()


def test_scope_expansion_requires_owned_stores_and_preserves_history(scheduled):
    client, actor, dataset, _ = scheduled
    old = dataset.metadata['database_scope']
    expanded = {**old, 'from': '2026-07-01'}
    assert validate_scope(actor, expanded, old) == expanded
    for bad in ({**old, 'from': '2026-09-01'}, {**old, 'stores': []}, {**old, 'to': '2099-01-01'}):
        with pytest.raises(ValidationError):
            validate_scope(actor, bad, old)
    _, _, foreign, _ = create_scope('summary-foreign-scope')
    with pytest.raises(ValidationError):
        validate_scope(actor, {**old, 'stores': old['stores'] + [foreign.pk]}, old)
    response = client.post(URL + f'{dataset.pk}/rebuild/', {'revision': 0, 'scope': expanded}, format='json')
    assert response.status_code == 202
    assert FinanceSummaryCalculation.objects.get().request['scope'] == expanded


def test_long_rebuild_uses_dedicated_queue(context, monkeypatch, settings):
    from unittest.mock import Mock
    from apps.finance.summary_jobs import request_calculation, run_calculation
    settings.FINANCE_SUMMARY_REBUILD_QUEUE = 'finance-summary-rebuild'
    send = Mock()
    monkeypatch.setattr(run_calculation, 'apply_async', send)
    _, actor, dataset, _ = context
    grant(actor, 'finance.import')
    request_calculation(dataset, actor, {}, kind='rebuild')
    assert send.call_args.kwargs['queue'] == 'finance-summary-rebuild'
    request_calculation(dataset, actor, {}, kind='query')
    assert send.call_args.kwargs['queue'] == 'finance-summary'


def test_vm_queue_isolates_new_work_from_retained_backlog(context, monkeypatch, settings):
    from unittest.mock import Mock
    from apps.finance.summary_jobs import request_calculation, run_calculation
    settings.FINANCE_SUMMARY_QUEUE = 'finance-summary-v517'
    settings.FINANCE_SUMMARY_REBUILD_QUEUE = 'finance-summary-v517'
    send = Mock()
    monkeypatch.setattr(run_calculation, 'apply_async', send)
    _, actor, dataset, _ = context
    grant(actor, 'finance.import')
    for kind in ('query', 'rebuild'):
        request_calculation(dataset, actor, {}, kind=kind)
    assert [call.kwargs['queue'] for call in send.call_args_list] == [
        'finance-summary-v517', 'finance-summary-v517',
    ]


def test_source_detection_runs_without_transaction_and_rechecks_revision(scheduled, monkeypatch):
    from django.db import connection
    _, _, dataset, state = scheduled
    def detect(ids):
        assert not connection.in_atomic_block
        state.revision += 1
        state.save(update_fields=['revision'])
        return {'changed': True}
    monkeypatch.setattr('apps.finance.summary_maintenance.source_checkpoint', detect)
    schedule_changed_summaries()
    assert not FinanceSummaryCalculation.objects.exists()


@pytest.mark.parametrize('failure,expected',[('actor','executor_inactive'),('permission','permission_denied'),('file','source_unavailable')])
def test_scheduler_diagnostics_survive_cache_reset_without_changing_accounting(scheduled,monkeypatch,failure,expected):
    from rest_framework.exceptions import PermissionDenied
    from apps.finance.summary_models import FinanceSummaryAutomationCheck
    from apps.finance.summary_health import automation_health
    _,actor,dataset,state=scheduled
    original=dict(dataset.metadata)
    if failure=='actor':
        actor.is_active=False;actor.save(update_fields=['is_active'])
    elif failure=='permission':
        monkeypatch.setattr('apps.finance.summary_maintenance.require_access',lambda *args,**kwargs: (_ for _ in ()).throw(PermissionDenied('DO_NOT_EXPOSE_RAW')))
    else:
        monkeypatch.setattr('apps.finance.summary_maintenance.document_path',lambda *args: (_ for _ in ()).throw(ValidationError('DO_NOT_EXPOSE_RAW')))
    schedule_changed_summaries()
    check=FinanceSummaryAutomationCheck.objects.get(dataset=dataset)
    assert check.code==expected
    cache.clear()
    health=automation_health(dataset)
    assert health['state']=='paused' and health['checked_at']
    assert 'DO_NOT_EXPOSE_RAW' not in str(health)
    dataset.refresh_from_db();state.refresh_from_db()
    assert dataset.metadata==original and state.revision==0
    assert not FinanceSummaryCalculation.objects.exists()


def test_scheduler_health_unchanged_disabled_and_stale(scheduled,monkeypatch):
    from apps.finance.summary_health import automation_health
    from apps.finance.summary_models import FinanceSummaryAutomationCheck
    from django.utils import timezone
    from datetime import timedelta
    _,_,dataset,_=scheduled
    assert automation_health(dataset)['state']=='unknown'
    monkeypatch.setattr('apps.finance.summary_maintenance.source_checkpoint',lambda ids:{})
    schedule_changed_summaries()
    assert automation_health(dataset)['state']=='healthy'
    FinanceSummaryAutomationCheck.objects.filter(dataset=dataset).update(checked_at=timezone.now()-timedelta(minutes=16))
    assert automation_health(dataset)['state']=='stale'
    dataset.metadata['automatic_update_enabled']=False;dataset.save()
    cache.clear();schedule_changed_summaries()
    assert automation_health(dataset)['state']=='disabled'
