from decimal import Decimal
import pytest
from apps.supply_chain import dashboard, domestic_expenses, domestic_reconciliation
from apps.supply_chain.models import SupplierShipment, domain_write
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_v2_costs import pilot, mark


def payload(world, shipment, currencies):
    return {'expected_version': shipment.version, 'legacy_action': 'additional', 'lines': [
        {'name': 'Synthetic fee ' + currency, 'amount': '10', 'currency': currency,
         'payee_type': 'supplier', 'payee_id': world['supplier_b'].pk,
         'include_in_cost': False, 'method': 'quantity'} for currency in currencies]}


@pytest.mark.django_db(transaction=True)
def test_queue_and_card_keep_two_units_and_do_not_combine_equal_numbers(world):
    buyer, _, shipment = pilot(world)
    shipment = mark(buyer, shipment)
    domestic_expenses.save(buyer, shipment.pk, payload(world, shipment, ['CNY', 'PHP']), 'unit-separation')
    scoped = dashboard.scope(buyer)
    legacy = dashboard._with_fee_activity(dashboard._money_targets('domestic', scoped), 'domestic')
    rows = domestic_reconciliation.project(buyer, scoped, legacy)
    itemized = [r for r in rows if r['kind'] == 'domestic_expense']
    assert len(itemized) == 2 and {r['currency'] for r in itemized} == {'CNY', 'PHP'}
    table = domestic_reconciliation.table(itemized, {'status': 'all'})
    assert table['summary']['due_amount'] is None
    assert table['summary']['totals_by_currency']['CNY']['due_amount'] == '10.0000'
    assert table['summary']['totals_by_currency']['PHP']['due_amount'] == '10.0000'
    card = dashboard.costs_data(buyer, scoped, 'domestic')['groups']['domestic']
    assert card['amount'] is None and card['unsettled'] is None
    assert {r['currency'] for r in card['ranking'] if r['amount'] is not None} == {'CNY', 'PHP'}
    inaccessible = list(scoped); inaccessible[3] = scoped[3].none()
    assert domestic_reconciliation.project(buyer, tuple(inaccessible), legacy.none()) == []


@pytest.mark.django_db(transaction=True)
def test_draft_group_remains_pending_unknown_not_settled_or_numeric_due(world):
    buyer, _, shipment = pilot(world)
    with domain_write():
        shipment.status = SupplierShipment.Status.DRAFT
        shipment.save(update_fields=['status'])
    domestic_expenses.save(buyer, shipment.pk, payload(world, shipment, ['CNY']), 'draft-unit')
    scoped = list(dashboard.scope(buyer))
    scoped[3] = SupplierShipment.objects.filter(tenant_id=buyer.tenant_id, pk=shipment.pk)
    legacy = dashboard._with_fee_activity(dashboard._money_targets('domestic', tuple(scoped)), 'domestic').none()
    rows = domestic_reconciliation.project(buyer, tuple(scoped), legacy)
    assert len(rows) == 1 and rows[0]['due_amount'] is None and rows[0]['remaining_amount'] is None
    assert domestic_reconciliation.table(rows, {'status': 'settled'})['count'] == 0
    assert domestic_reconciliation.table(rows, {'status': 'pending'})['summary']['due_amount'] is None
    card = domestic_reconciliation.dashboard_data(domestic_reconciliation.rollup(buyer, tuple(scoped), legacy))
    assert card['amount'] is None and card['unsettled'] is None and card['unknown_documents'] == 1
