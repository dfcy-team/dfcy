import pytest
from rest_framework.exceptions import PermissionDenied

from apps.alerts.models import InventoryAlert, InventoryDecisionAssessment
from apps.alerts.inventory_decisions import evaluate_country
from apps.alerts.inventory_refresh import refresh_due_decisions
from apps.products.models import ProductSKU
from tests.test_country_inventory_decisions import facts, clock, NOW, stock
from tests.test_inventory_decision_workflow import evaluator, rule
from tests.test_supply_chain_v2_logistics import client


@pytest.mark.django_db
def test_automatic_mixed_legacy_watch_isolates_virtual_and_evaluates_physical(facts):
    f = facts
    actor = evaluator(f)
    rule(f)
    physical = InventoryDecisionAssessment.objects.create(
        tenant=f['tenant'], country=f['country'], sku=f['sku'], actor=actor,
        window_days=30, target_days=60, scope_signature='a', source_signature='b',
        rules_signature='c', state='risk', evaluated_at=NOW, refresh_after=NOW,
        needs_refresh=True,
    )
    virtual = ProductSKU.objects.create(tenant=f['tenant'], spu=f['spu'], sku_code='VIRTUAL-CUTOVER',
                                        inventory_type='virtual')
    stock(f['tenant'], f['warehouse'], virtual, quantity=999, suffix='virtual-cutover')
    InventoryDecisionAssessment.objects.create(
        tenant=f['tenant'], country=f['country'], sku=virtual, actor=actor,
        window_days=30, target_days=60, scope_signature='a', source_signature='b',
        rules_signature='c', state='risk', evaluated_at=NOW, refresh_after=NOW,
        needs_refresh=True,
    )

    result = refresh_due_decisions()
    physical.refresh_from_db()
    virtual_watch = InventoryDecisionAssessment.objects.get(sku=virtual)
    assert result['processed'] == 2
    assert physical.state == 'risk'
    assert InventoryAlert.objects.filter(sku=f['sku'], status='open').exists()
    assert virtual_watch.state == 'pending'
    assert virtual_watch.issues == ['virtual_inventory_not_eligible']


@pytest.mark.django_db
def test_manual_virtual_sku_still_rejected(facts):
    f = facts
    actor = evaluator(f)
    virtual = ProductSKU.objects.create(tenant=f['tenant'], spu=f['spu'], sku_code='VIRTUAL-MANUAL',
                                        inventory_type='virtual')
    with pytest.raises(PermissionDenied):
        evaluate_country(actor, f['country'], [virtual])


@pytest.mark.django_db
def test_automatic_refresh_preserves_risk_when_another_rule_is_deferred(facts):
    f = facts
    actor = evaluator(f)
    low_rule = rule(f)
    low_rule.rule_code = 'LOW-CUTOVER'
    low_rule.save(update_fields=['rule_code'])
    rule(f, kind='slow_moving', threshold=100)
    evaluate_country(actor, f['country'], [f['sku']])
    watch = InventoryDecisionAssessment.objects.get(sku=f['sku'])
    assert watch.state == 'risk'
    watch.needs_refresh = True
    watch.save(update_fields=['needs_refresh'])
    refresh_due_decisions()
    watch.refresh_from_db()
    assert watch.state == 'risk'
    assert 'availability_history_unproven' in watch.issues


@pytest.mark.django_db
def test_old_real_observation_policy_is_invalid_and_new_policy_is_valid(facts):
    f = facts
    actor = evaluator(f)
    rule(f)
    evaluate_country(actor, f['country'], [f['sku']])
    alert = InventoryAlert.objects.get(sku=f['sku'])
    assert alert.source_summary['policy_version'] == 'mapped-physical-inventory-v3'
    alert.source_summary = {k: v for k, v in alert.source_summary.items() if k != 'policy_version'}
    alert.save(update_fields=['source_summary'])
    version, events = alert.version, alert.events.count()
    api = client(actor)
    assert api.get('/api/internal/alerts/inventory/', {'validity': 'valid', 'source_mode': 'real_observation'}).data['data']['count'] == 0
    invalid = api.get('/api/internal/alerts/inventory/', {'validity': 'pending', 'source_mode': 'real_observation'}).data['data']
    assert invalid['count'] == 1
    assert invalid['results'][0]['evaluation_status'] == 'stale'
    alert.refresh_from_db()
    assert alert.version == version and alert.events.count() == events
    alert.source_summary['policy_version'] = 'mapped-physical-inventory-v3'
    alert.save(update_fields=['source_summary'])
    assert api.get('/api/internal/alerts/inventory/', {'validity': 'valid', 'source_mode': 'real_observation'}).data['data']['count'] == 1
    # Historical rows can predate model-level non-empty provenance validation.
    InventoryAlert.objects.filter(pk=alert.pk).update(source_summary={})
    assert api.get('/api/internal/alerts/inventory/', {'validity': 'valid'}).data['data']['count'] == 1
