"""State separation, lifecycle, background consistency and menu cost contracts."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import connection
from django.db.models import QuerySet
from django.test.utils import CaptureQueriesContext

from apps.alerts.models import (InventoryAlert, InventoryAlertEvent, InventoryAlertRule,
    InventoryDecisionAssessment, InventoryDecisionView, InventoryDecisionRow)
from apps.alerts.inventory_decisions import evaluate_country
from apps.alerts.inventory_refresh import invalidate_decisions, refresh_due_decisions
from apps.alerts.inventory_views import build_pending_views, invalidate_views, recover_views
from apps.permissions.models import UserRole
from apps.products.models import ProductSKU
from tests.test_country_inventory_decisions import facts, clock, NOW, BASE, stock
from tests.test_sales_management import grant
from tests.test_supply_chain_v2_logistics import client


def evaluator(f):
    grant(f['actor'], 'alerts.evaluate')
    grant(f['actor'], 'alerts.view')
    return type(f['actor']).objects.get(pk=f['actor'].pk)


def rule(f, *, version=1, threshold=30, enabled=True, kind='low_coverage'):
    return InventoryAlertRule.objects.create(tenant=f['tenant'], rule_code='WORKFLOW', version=version,
        alert_type=kind, threshold_config={'coverage_days': threshold} if kind != 'slow_moving' else {'average_daily_sales': threshold},
        severity='high', is_enabled=enabled, effective_at=NOW-timedelta(days=1))


def evaluate(f, actor=None):
    return evaluate_country(actor or f['actor'], f['country'], [f['sku']])


def build_all():
    for _ in range(20):
        if not InventoryDecisionView.objects.filter(state__in=['pending', 'building']).exists():
            return
        build_pending_views(limit=10)
    raise AssertionError('Background build did not complete')


def query(f, **extra):
    response = client(f['actor']).get(BASE, {'country_id': f['country'].pk, 'decision_state': 'positive', **extra})
    assert response.status_code == 200, response.data
    return response.data['data']


def test_grouped_menu_first_request_and_pagination_never_compute_catalog(facts):
    f = facts
    with patch('apps.commerce.country_decisions.decision_rows', side_effect=AssertionError('menu computed facts')):
        first = query(f)
    assert first['query_state'] == 'building' and first['results'] == []
    build_all()
    with patch('apps.commerce.country_decisions.decision_rows', side_effect=AssertionError('menu recomputed facts')):
        data = query(f)
        pending = query(f, decision_state='pending')
    assert data['query_state'] == 'ready' and data['results'][0]['suggested_quantity'] == 82
    assert data['summary']['positive'] == 1 and data['summary']['pending'] == 0
    assert pending['count'] == 0 and InventoryDecisionView.objects.count() == 1


def test_grouping_precedes_pagination_and_zero_is_ready(facts):
    f = facts
    zero = ProductSKU.objects.create(tenant=f['tenant'], spu=f['spu'], sku_code='AAA-ZERO')
    stock(f['tenant'], f['warehouse'], zero, quantity=10, suffix='zero-snapshot')
    for index in range(22):
        ProductSKU.objects.create(tenant=f['tenant'], spu=f['spu'], sku_code=f'BBB-MISSING-{index:02d}')
    query(f)
    build_all()
    data = query(f, limit=1)
    assert data['count'] == 1 and data['results'][0]['sku_id'] == f['sku'].pk
    ready = query(f, decision_state='ready')
    assert ready['count'] == 2 and ready['results'][0]['suggested_quantity'] == 0
    assert ready['results'][0]['replenishment_status'] == 'sufficient'
    pending = query(f, decision_state='pending', limit=20, offset=20)
    assert pending['count'] == 22 and len(pending['results']) == 2
    assert all(row['suggested_quantity'] is None and row['blocking_issues'] for row in pending['results'])


def test_pending_keeps_verified_stock_and_incomplete_sales_separate(facts):
    f = facts
    f['segment'].status = 'failed'; f['segment'].save()
    query(f)
    build_all()
    data = query(f, decision_state='pending')
    row = data['results'][0]
    assert row['available_stock'] == '40' and row['suggested_quantity'] is None
    assert row['evaluation_status'] == 'pending'
    assert 'collection_coverage_unproven' in row['blocking_issues']


def test_view_invalidated_during_build_cannot_publish_old_generation(facts):
    f = facts
    query(f)
    from apps.commerce.country_decisions import decision_rows
    def changed(*args, **kwargs):
        observations = decision_rows(*args, **kwargs)
        invalidate_views(f['tenant'].pk)
        return observations
    with patch('apps.commerce.country_decisions.decision_rows', side_effect=changed):
        build_pending_views()
    assert not InventoryDecisionRow.objects.exists()
    assert query(f)['query_state'] == 'building'
    build_all()
    assert query(f)['query_state'] == 'ready'


def test_view_permission_revocation_never_reuses_cached_facts(facts):
    f = facts
    query(f); build_all()
    role = UserRole.objects.get(user=f['actor']).role
    role.permissions.remove(role.permissions.get(code='sales_management.skus.view'))
    fresh = type(f['actor']).objects.get(pk=f['actor'].pk)
    response = client(fresh).get(BASE, {'country_id': f['country'].pk, 'decision_state': 'positive'})
    assert response.status_code == 403


def test_view_authorization_signature_changes_on_supply_revocation(facts):
    f = facts
    query(f); build_all()
    role = UserRole.objects.get(user=f['actor']).role
    role.permissions.remove(role.permissions.get(code='sales_management.supply_summary.view'))
    f['actor'] = type(f['actor']).objects.get(pk=f['actor'].pk)
    assert query(f)['query_state'] == 'building'
    build_all()
    data = query(f, decision_state='pending')
    assert data['results'][0]['pipeline']['authorized'] is False
    assert data['results'][0]['pipeline']['effective_incoming'] is None
    assert InventoryDecisionView.objects.count() == 2


def test_real_alert_resolves_only_on_complete_facts_and_reopens(facts):
    f = facts; actor = evaluator(f); rule(f)
    assert evaluate(f, actor)['created'] == 1
    alert = InventoryAlert.objects.get()
    f['snapshot'].available_qty = 300; f['snapshot'].save()
    f['segment'].status = 'failed'; f['segment'].save()
    outcome = evaluate(f, actor)
    alert.refresh_from_db()
    assert outcome['closed'] == 0 and alert.status == 'open' and alert.evaluation_state == 'pending'
    f['segment'].status = 'success'; f['segment'].save()
    assert evaluate(f, actor)['closed'] == 1
    alert.refresh_from_db()
    assert alert.status == 'closed' and alert.resolution and alert.events.filter(event_type='closed').exists()
    f['snapshot'].available_qty = 1; f['snapshot'].save()
    assert evaluate(f, actor)['updated'] == 1
    alert.refresh_from_db()
    assert alert.status == 'open' and alert.closed_at is None and InventoryAlert.objects.count() == 1


def test_real_rule_versions_update_same_alert_and_disabled_latest_never_falls_back(facts):
    f = facts; actor = evaluator(f); rule(f)
    evaluate(f, actor)
    original = InventoryAlert.objects.get()
    second = rule(f, version=2, threshold=25)
    evaluate(f, actor)
    original.refresh_from_db()
    assert original.rule_id == second.pk and InventoryAlert.objects.count() == 1
    rule(f, version=3, enabled=False)
    assert evaluate(f, actor)['closed'] == 1
    original.refresh_from_db()
    assert original.status == 'closed'
    assert InventoryDecisionAssessment.objects.get().state == 'no_rules'


def test_zero_available_with_verified_demand_triggers_stockout(facts):
    f = facts; actor = evaluator(f); rule(f, kind='stockout_risk', threshold=0)
    f['snapshot'].available_qty = 0; f['snapshot'].save()
    assert evaluate(f, actor)['created'] == 1
    assert '可用库存为零' in InventoryAlert.objects.get().reason


def test_assessment_distinguishes_never_evaluated_risk_and_normal(facts):
    f = facts; actor = evaluator(f); f['actor'] = actor; rule(f)
    query(f); build_all()
    assert query(f, decision_state='not_evaluated')['count'] == 1
    evaluate(f, actor); build_all()
    assert query(f, decision_state='risk')['count'] == 1
    f['snapshot'].available_qty = 300; f['snapshot'].save()
    evaluate(f, actor); build_all()
    assert query(f, decision_state='normal')['count'] == 1


def test_dirty_refresh_is_bounded_and_rechecks_authorizing_user(facts):
    f = facts; actor = evaluator(f); rule(f); evaluate(f, actor)
    invalidate_decisions(f['tenant'].pk)
    assert InventoryAlert.objects.get().evaluation_state == 'pending'
    role = UserRole.objects.get(user=actor, role__permissions__code='alerts.evaluate').role
    role.permissions.remove(role.permissions.get(code='alerts.evaluate'))
    result = refresh_due_decisions(limit=1)
    assert result['pending'] == 1
    assert InventoryAlert.objects.get().evaluation_state == 'pending'
    assert InventoryDecisionAssessment.objects.get().issues == ['alert_target_not_authorized']


def test_refresh_claim_locks_only_assessment_rows_before_loading_nullable_relations(facts, monkeypatch):
    from apps.alerts import inventory_decisions

    f = facts; actor = evaluator(f); evaluate(f, actor)
    assessment = InventoryDecisionAssessment.objects.get()
    assessment.needs_refresh = True
    assessment.refresh_after = NOW
    assessment.save(update_fields=['needs_refresh', 'refresh_after'])
    lock_queries = []
    original = QuerySet.select_for_update

    def observe(queryset, *args, **kwargs):
        locked = original(queryset, *args, **kwargs)
        lock_queries.append(str(locked.query))
        return locked

    monkeypatch.setattr(QuerySet, 'select_for_update', observe)
    monkeypatch.setattr(inventory_decisions, 'bind_actor_context', lambda *args: None)
    monkeypatch.setattr(inventory_decisions, 'evaluate_country', lambda *args, **kwargs: {'skipped': []})
    assert refresh_due_decisions(limit=1)['processed'] == 1
    assert len(lock_queries) == 1
    assert 'JOIN' not in lock_queries[0].upper()


def test_automatic_refresh_resolves_and_does_not_reset_followup_on_risk(facts):
    f = facts; actor = evaluator(f); rule(f); evaluate(f, actor)
    alert = InventoryAlert.objects.get()
    alert.action_plan = '检查到货'; alert.status = 'in_progress'; alert.save()
    invalidate_decisions(f['tenant'].pk)
    refresh_due_decisions()
    alert.refresh_from_db()
    assert alert.status == 'in_progress' and alert.action_plan == '检查到货'
    f['snapshot'].available_qty = 300; f['snapshot'].save()
    invalidate_decisions(f['tenant'].pk)
    refresh_due_decisions()
    alert.refresh_from_db()
    assert alert.status == 'closed'


def test_sync_and_rule_signals_invalidate_only_after_commit(facts, django_capture_on_commit_callbacks):
    f = facts; actor = evaluator(f); created_rule = rule(f); evaluate(f, actor)
    with django_capture_on_commit_callbacks(execute=True):
        created_rule.threshold_config = {'coverage_days': 40}; created_rule.save()
        assert InventoryAlert.objects.get().evaluation_state == 'risk'
    assert InventoryAlert.objects.get().evaluation_state == 'pending'
    evaluate(f, actor)
    with django_capture_on_commit_callbacks(execute=True):
        run = f['snapshot'].source_run
        run.save()
    assert InventoryDecisionAssessment.objects.get().needs_refresh


def test_alert_list_validity_and_list_does_not_load_event_history(facts):
    f = facts; actor = evaluator(f); rule(f); evaluate(f, actor)
    alert = InventoryAlert.objects.get()
    InventoryAlertEvent.objects.bulk_create([InventoryAlertEvent(tenant=f['tenant'], alert=alert,
        event_type='deduplicated') for _ in range(200)])
    api = client(actor)
    with CaptureQueriesContext(connection) as queries:
        data = api.get('/api/internal/alerts/inventory/', {'validity':'valid', 'source_mode':'real_observation'}).data['data']
    assert data['count'] == 1 and data['results'][0]['country_id'] == f['country'].pk
    assert data['results'][0]['events'] == []
    assert not any('alerts_inventoryalertevent' in q['sql'] for q in queries)
    invalidate_decisions(f['tenant'].pk)
    assert api.get('/api/internal/alerts/inventory/', {'validity':'valid'}).data['data']['count'] == 0
    pending = api.get('/api/internal/alerts/inventory/', {'validity':'pending'}).data['data']
    assert pending['count'] == 1
    assert pending['results'][0]['source_summary']['evaluation_status'] == 'pending'


def test_menu_sql_count_and_fact_reads_independent_of_catalog_size(facts):
    f = facts
    query(f); build_all()
    view = InventoryDecisionView.objects.get()
    skus = ProductSKU.objects.bulk_create([ProductSKU(tenant=f['tenant'], spu=f['spu'], sku_code=f'PERF-{i:04d}') for i in range(1000)])
    InventoryDecisionRow.objects.bulk_create([InventoryDecisionRow(view=view, revision=view.revision, sku=s,
        decision_state='pending', evaluation_status='pending', sku_code_snapshot=s.sku_code, payload={'sku_id':s.pk, 'sku':s.sku_code}) for s in skus])
    from time import perf_counter
    started = perf_counter()
    with CaptureQueriesContext(connection) as queries:
        data = query(f, decision_state='pending', offset=980)
    print(f'MENU_PERFORMANCE catalog=1000 page=20 sql={len(queries)} seconds={perf_counter()-started:.4f}')
    assert data['count'] == 1000 and len(data['results']) == 20
    assert len(queries) < 45
    assert not any('inventory_snapshot' in q['sql'] or 'sales_order' in q['sql'] for q in queries)


def test_continuous_polling_does_not_extend_dead_worker_lease(facts, monkeypatch):
    from django.utils import timezone
    f = facts; query(f)
    view = InventoryDecisionView.objects.get()
    InventoryDecisionView.objects.filter(pk=view.pk).update(state='claimed', updated_at=NOW)
    monkeypatch.setattr(timezone, 'now', lambda: NOW + timedelta(minutes=6))
    assert query(f)['query_state'] == 'building'
    recover_views()
    view.refresh_from_db()
    assert view.state == 'pending' and view.revision == 2


def test_long_build_result_ttl_starts_at_completion(facts, monkeypatch):
    from django.utils import timezone
    f = facts
    ProductSKU.objects.create(tenant=f['tenant'], spu=f['spu'], sku_code='SECOND-BATCH')
    query(f)
    build_pending_views(batch_size=1)
    monkeypatch.setattr(timezone, 'now', lambda: NOW + timedelta(minutes=6))
    build_all()
    view = InventoryDecisionView.objects.get()
    assert view.expires_at > NOW + timedelta(minutes=6)
    assert query(f)['query_state'] == 'ready'


def test_claimed_old_policy_cannot_reactivate_after_manual_switch(facts):
    f = facts; actor = evaluator(f); rule(f); evaluate(f, actor)
    old = InventoryDecisionAssessment.objects.get()
    evaluate_country(actor, f['country'], [f['sku']], target_days=90)
    with patch('apps.commerce.country_decisions.decision_rows', side_effect=AssertionError('old policy was evaluated')):
        evaluate_country(actor, f['country'], [f['sku']], target_days=60, automatic=True)
    old.refresh_from_db()
    assert not old.auto_refresh
    active = InventoryDecisionAssessment.objects.get(auto_refresh=True)
    assert active.target_days == 90


def test_empty_catalog_finishes_as_ready_not_permanent_building(facts):
    f = facts
    f['sku'].is_active = False; f['sku'].save()
    query(f); build_all()
    data = query(f)
    assert data['query_state'] == 'ready' and data['count'] == 0 and data['summary']['total'] == 0


def test_checked_rows_are_visible_while_remaining_chunks_build(facts):
    f = facts
    ProductSKU.objects.create(tenant=f['tenant'], spu=f['spu'], sku_code='SECOND-PARTIAL')
    query(f)
    build_pending_views(batch_size=1)
    data = query(f)
    assert data['query_state'] == 'building' and data['processed_count'] == 1
    assert len(data['results']) == 1 and data['results'][0]['suggested_quantity'] == 82
    assert data['counts_complete'] is False


def test_manual_recheck_rebuilds_own_snapshot_without_resolving_alerts(facts):
    f = facts; actor = evaluator(f); f['actor'] = actor; rule(f); evaluate(f, actor)
    query(f); build_all()
    assert query(f)['query_state'] == 'ready'
    assert query(f, refresh=True)['query_state'] == 'building'
    assert InventoryAlert.objects.get().status == 'open'


def test_background_jobs_restore_and_revalidate_department_identity(facts):
    from apps.permissions.models import OrgMembership
    from apps.tenants.models import Department
    f = facts; actor = evaluator(f); rule(f)
    department = Department.objects.create(tenant=f['tenant'], name='库存运营')
    membership = OrgMembership.objects.create(tenant=f['tenant'], user=actor, department=department)
    for binding in UserRole.objects.filter(user=actor):
        binding.membership = membership
        binding.context_key = f'department:{department.pk}'
        binding.save()
    actor._active_membership_id = membership.pk; f['actor'] = actor
    evaluate(f, actor)
    assert InventoryDecisionAssessment.objects.get().membership_id == membership.pk
    query(f); build_all()
    assert query(f)['query_state'] == 'ready'
    invalidate_decisions(f['tenant'].pk)
    assert refresh_due_decisions()['pending'] == 0
    membership.status = 'inactive'; membership.save()
    invalidate_decisions(f['tenant'].pk)
    assert refresh_due_decisions()['pending'] == 1
    assert InventoryAlert.objects.get().evaluation_state == 'pending'


def test_inventory_views_are_bound_to_membership_even_for_equal_scopes(facts):
    from apps.alerts.inventory_views import menu_page
    from apps.commerce.country_decisions import permission_signature
    from apps.permissions.models import OrgMembership
    from apps.tenants.models import Department

    f = facts; actor = evaluator(f)
    memberships = []
    for name in ('视图身份A', '视图身份B'):
        department = Department.objects.create(tenant=f['tenant'], name=name)
        memberships.append(OrgMembership.objects.create(tenant=f['tenant'], user=actor, department=department))

    views = []
    base_signatures = []
    for membership in memberships:
        contextual_actor = type(actor).objects.get(pk=actor.pk)
        contextual_actor._active_membership_id = membership.pk
        base_signatures.append(permission_signature(contextual_actor))
        menu_page(contextual_actor, f['country'], decision_state='positive', window_days=30, target_days=60,
            search='', offset=0, limit=20)
        views.append(InventoryDecisionView.objects.get(membership_id=membership.pk))

    assert base_signatures[0] == base_signatures[1]
    assert views[0].scope_signature != views[1].scope_signature
    assert views[0].membership_id == memberships[0].pk and views[1].membership_id == memberships[1].pk

    # A legacy base-only cache entry must neither be reused nor publish rows.
    legacy_signature = permission_signature(actor)
    legacy = InventoryDecisionView.objects.create(tenant=f['tenant'], actor=actor, country=f['country'],
        scope_signature=legacy_signature, membership_id=memberships[0].pk, window_days=30, target_days=60,
        requested_at=NOW)
    from apps.commerce.country_decisions import decision_rows
    def build_other_identity_first(*args, **kwargs):
        result = decision_rows(*args, **kwargs)
        if getattr(args[0], '_active_membership_id', None) == memberships[0].pk:
            # The first identity is claimed while another worker builds B.
            build_pending_views(limit=1)
            assert InventoryDecisionView.objects.get(pk=views[0].pk).state == 'claimed'
            assert InventoryDecisionView.objects.get(pk=views[1].pk).state == 'ready'
        return result
    with patch('apps.commerce.country_decisions.decision_rows', side_effect=build_other_identity_first):
        build_pending_views(limit=1)
    build_all()
    legacy.refresh_from_db()
    assert legacy.state == 'failed' and not legacy.rows.exists()
    assert all(v.state == 'ready' for v in InventoryDecisionView.objects.exclude(pk=legacy.pk))
    assert set(InventoryDecisionRow.objects.values_list('view_id', flat=True)) == {v.pk for v in views}


@pytest.mark.parametrize('invalidity', ['inactive', 'expired'])
def test_invalid_membership_view_fails_while_other_membership_builds(facts, invalidity):
    from apps.alerts.inventory_views import menu_page
    from apps.permissions.models import OrgMembership
    from apps.tenants.models import Department

    f = facts; actor = evaluator(f)
    memberships = []
    for name in ('无效视图身份', '有效视图身份'):
        department = Department.objects.create(tenant=f['tenant'], name=name)
        memberships.append(OrgMembership.objects.create(tenant=f['tenant'], user=actor, department=department))
    for membership in memberships:
        contextual_actor = type(actor).objects.get(pk=actor.pk)
        contextual_actor._active_membership_id = membership.pk
        menu_page(contextual_actor, f['country'], decision_state='positive', window_days=30, target_days=60,
            search='', offset=0, limit=20)
    invalid, valid = memberships
    if invalidity == 'inactive':
        invalid.status = 'inactive'
    else:
        invalid.valid_until = NOW - timedelta(seconds=1)
    invalid.save()

    build_all()
    invalid_view = InventoryDecisionView.objects.get(membership_id=invalid.pk)
    valid_view = InventoryDecisionView.objects.get(membership_id=valid.pk)
    assert invalid_view.state == 'failed' and not invalid_view.rows.exists()
    assert valid_view.state == 'ready' and valid_view.rows.exists()


def test_source_delete_invalidates_after_commit_and_rolls_back_cleanly(facts, django_capture_on_commit_callbacks):
    from django.db import transaction
    from apps.alerts.signals import connect_sources
    from apps.tenants.models import Tenant

    f = facts; query(f); build_all()
    view = InventoryDecisionView.objects.get()
    source = ProductSKU.objects.create(tenant=f['tenant'], spu=f['spu'], sku_code='DELETE-SOURCE')
    source_id = source.pk
    other_tenant = Tenant.objects.create(name='其他租户', code='inventory-delete-isolation')
    other_view = InventoryDecisionView.objects.create(tenant=other_tenant, actor=f['actor'], country=f['country'],
        scope_signature='other-tenant-view', requested_at=NOW, state='ready')
    connect_sources(); connect_sources()

    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            source.delete()
            assert InventoryDecisionView.objects.get(pk=view.pk).state == 'ready'
            transaction.set_rollback(True)
    assert ProductSKU.objects.filter(pk=source_id).exists()
    assert InventoryDecisionView.objects.get(pk=view.pk).state == 'ready'

    with django_capture_on_commit_callbacks(execute=True):
        ProductSKU.objects.get(pk=source_id).delete()
    assert InventoryDecisionView.objects.get(pk=view.pk).state == 'pending'
    assert InventoryDecisionView.objects.get(pk=other_view.pk).state == 'ready'


def test_sku_and_country_scopes_allow_full_country_evaluation_but_partial_warehouse_does_not(facts):
    from apps.permissions.models import RoleResourcePolicy
    f = facts; actor = evaluator(f); rule(f)
    role = UserRole.objects.get(user=actor, role__permissions__code='sales_management.view').role
    policy = RoleResourcePolicy.objects.create(tenant=f['tenant'], role=role, resource_code='commerce.inventory',
        permission_code='sales_management.view', scope_type='custom', config={'sku_ids':[f['sku'].pk]})
    RoleResourcePolicy.objects.create(tenant=f['tenant'], role=role, resource_code='sales_management.supply_summary',
        permission_code='sales_management.supply_summary.view', scope_type='custom', config={'site_ids':[f['country'].pk]})
    assert evaluate(f, type(actor).objects.get(pk=actor.pk))['created'] == 1
    policy.config = {'warehouse_ids':[f['warehouse'].pk]}; policy.save()
    result = evaluate(f, type(actor).objects.get(pk=actor.pk))
    assert result['skipped'][0]['issues'] == ['alert_target_not_authorized']
