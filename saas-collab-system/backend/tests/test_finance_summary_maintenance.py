"""Synthetic coverage and unattended scheduling tests; no business database."""
import pytest
from django.core.cache import cache
from rest_framework.exceptions import ValidationError
from apps.finance.summary_maintenance import schedule_changed_summaries, validate_scope
from apps.finance.summary_models import FinanceSummaryCalculation
from tests.test_finance_summary import context, URL
from tests.test_sales_management import grant, create_scope

pytestmark = pytest.mark.django_db(transaction=True)


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
    assert job.request == {'revision': state.revision, 'automatic_scope': dataset.metadata['automatic_scope']}
    cache.clear()
    schedule_changed_summaries()
    assert FinanceSummaryCalculation.objects.count() == 1
    dataset.refresh_from_db()
    assert dataset.active


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
    from types import SimpleNamespace
    from unittest.mock import Mock
    from apps.finance.summary_jobs import enqueue, run_calculation
    settings.FINANCE_SUMMARY_REBUILD_QUEUE = 'finance-summary-rebuild'
    send = Mock()
    monkeypatch.setattr(run_calculation, 'apply_async', send)
    enqueue(SimpleNamespace(pk=1, kind='rebuild'))
    assert send.call_args.kwargs['queue'] == 'finance-summary-rebuild'
    enqueue(SimpleNamespace(pk=2, kind='query'))
    assert send.call_args.kwargs['queue'] == 'finance-summary'
