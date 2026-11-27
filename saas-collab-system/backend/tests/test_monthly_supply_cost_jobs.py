import pytest
from django.test import override_settings

from apps.supply_chain import costs
from apps.supply_chain.monthly_cost_jobs import run_daily_batch_costs
from apps.supply_chain.models import CostVersion
from tests.test_supply_chain_v2_foundation import world
from tests.test_partial_inbound_costs import setup_batch, receipt
from tests.test_supply_chain_v2_costs import calculate


@pytest.mark.django_db
@override_settings(MONTHLY_PRODUCT_COST_ENABLED=True)
def test_missing_non_goods_inbound_fee_does_not_block_batch_cost(world):
    actor, api, batch, line = setup_batch(world)
    receipt(world, actor, batch, line, 4, 4, 'no-fee')

    result, _ = calculate(api, 'batch', batch.pk, key='no-inbound-fee')

    entry = next(row for row in result['entries'] if row['shipment_line_id'] == line.pk)
    assert result['calculated_status'] == 'confirmed'
    assert entry['clearance_fee'] == '0.0000'
    assert not any('费用未维护' in issue for issue in result['issues'])


@pytest.mark.django_db
@override_settings(SUPPLY_MONTHLY_COST_JOBS_ENABLED=True)
def test_daily_job_skips_unchanged_batch(world):
    actor, api, batch, line = setup_batch(world)
    receipt(world, actor, batch, line, 4, 4, 'daily')
    first = run_daily_batch_costs(actor, limit=9999)
    result = run_daily_batch_costs(actor, limit=9999)

    assert first['processed'] == 1
    assert result['processed'] == 0
    assert result['skipped'] == 1
    assert result['limit'] == 500
    assert result['payment_reconciliation'] == 'checked'


@pytest.mark.django_db
@override_settings(SUPPLY_MONTHLY_COST_JOBS_ENABLED=True)
def test_daily_job_creates_estimate_without_publishing_received_cost(world):
    from unittest.mock import patch
    actor, api, batch, line = setup_batch(world)
    receipt(world, actor, batch, line, 4, 4, 'estimate-only')

    with patch('apps.supply_chain.product_cost_sync.publish_received_costs') as publish:
        result = run_daily_batch_costs(actor, limit=1)

    version = CostVersion.objects.filter(batch=batch).order_by("-sequence").first()
    assert result['processed'] == 1
    assert version.state == 'estimated'
    assert version.summary['payment_audit']['snapshot']['ready'] is False
    publish.assert_not_called()


@pytest.mark.django_db
@override_settings(SUPPLY_MONTHLY_COST_JOBS_ENABLED=True, MONTHLY_PRODUCT_COST_ENABLED=True)
def test_payment_change_appends_audit_version_without_repricing(world):
    from unittest.mock import patch
    actor, api, batch, line = setup_batch(world)
    receipt(world, actor, batch, line, 4, 4, 'payment-audit')
    with patch('apps.supply_chain.monthly_cost_jobs.payment_state', return_value={
            'goods': {'state': 'paid'}, 'recorded_fees': [], 'recorded_fees_state': 'paid',
            'coverage_incomplete': False, 'ready': True}):
        run_daily_batch_costs(actor, limit=1)
        original = CostVersion.objects.filter(batch=batch).order_by("sequence").first()
        second = run_daily_batch_costs(actor, limit=1)
        assert second['errors'] == []
        audit = CostVersion.objects.filter(batch=batch).order_by('-sequence').first()
        assert audit.pk != original.pk
        assert audit.summary['payment_audit']['snapshot']['goods']['state'] == 'paid'
        original.refresh_from_db()
        assert 'payment_audit' not in original.summary
        assert audit.state == 'confirmed'
        assert list(original.entries.values_list('received_total', flat=True)) == list(
            audit.entries.values_list('received_total', flat=True))


@pytest.mark.django_db
@override_settings(SUPPLY_MONTHLY_COST_JOBS_ENABLED=True)
def test_unchanged_payment_snapshot_is_idempotent(world):
    from unittest.mock import patch
    actor, api, batch, line = setup_batch(world)
    receipt(world, actor, batch, line, 4, 4, 'payment-idempotent')
    payment = {'goods': {'state': 'paid'}, 'recorded_fees': [],
               'recorded_fees_state': 'paid', 'coverage_incomplete': False, 'ready': True}
    with patch('apps.supply_chain.monthly_cost_jobs.payment_state', return_value=payment):
        run_daily_batch_costs(actor, limit=1)
        run_daily_batch_costs(actor, limit=1)
        count = CostVersion.objects.filter(batch=batch).count()
        run_daily_batch_costs(actor, limit=1)
    assert CostVersion.objects.filter(batch=batch).count() == count
