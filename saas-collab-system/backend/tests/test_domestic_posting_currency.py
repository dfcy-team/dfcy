from decimal import Decimal
import pytest
from apps.supply_chain.cost_models import PaymentRecord
from apps.supply_chain.models import domain_write
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_v2_costs import pilot, mark, fee
from tests.test_supply_chain_v2_logistics import BASE


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('posting_unit', ['CNY', 'PHP', None])
def test_domestic_queue_does_not_subtract_a_different_or_unknown_posting_unit(world, posting_unit):
    buyer, api, shipment = pilot(world)
    shipment = mark(buyer, shipment)
    fee(api, 'shipment', shipment, '6', cost_exchange={'currency': 'CNY'})
    with domain_write():
        PaymentRecord.objects.create(tenant=buyer.tenant, created_by=buyer, shipment=shipment,
            amount=Decimal('4'), purpose='domestic_freight', date='2026-10-14',
            account_snapshot={'currency': posting_unit, 'nature': 'corporate'} if posting_unit else {'nature': 'corporate'},
            idempotency_key='posting-unit')
    response = api.get(BASE + 'dashboard/queue/?queue=domestic&status=all')
    assert response.status_code == 200, response.data
    row = next(r for r in response.data['data'] if r['id'] == shipment.pk and r['kind'] != 'domestic_expense')
    if posting_unit == 'CNY':
        assert row['currency'] == 'CNY'
        assert Decimal(row['paid_amount']) == 4 and Decimal(row['remaining_amount']) == 2
    else:
        assert row['currency'] is None and row['paid_amount'] is None and row['remaining_amount'] is None
        assert row['unresolved_currency_nonzero'] is True
        assert row['original_due']['currency'] == 'CNY' and Decimal(row['original_due']['amount']) == 6
        assert row['payment_natures'] == ['corporate']
        fact = row['payment_totals_by_currency'][posting_unit or 'UNKNOWN']['paid_amount']
        assert (Decimal(fact) == 4) if posting_unit else fact is None
        pending = api.get(BASE + 'dashboard/queue/?queue=domestic&status=pending&payment_nature=corporate').data
        assert any(r['id'] == shipment.pk for r in pending['data'])
    card = api.get(BASE + 'dashboard/?section=costs&costs_group=domestic').data['data']['groups']['domestic']
    if posting_unit != 'CNY':
        assert card['paid'] is None and card['unsettled'] is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('posting_unit,confirmed_unit,resolved', [(None, 'CNY', True), (None, 'PHP', False), ('CNY', 'PHP', True), ('bad', 'CNY', False)])
def test_confirmed_legacy_display_currency_never_overrides_original_posting_or_grants_access(world, posting_unit, confirmed_unit, resolved):
    from apps.supply_chain import costs
    from apps.supply_chain.cost_models import PaymentCurrencyConfirmation
    buyer, api, shipment = pilot(world)
    shipment = mark(buyer, shipment)
    fee(api, 'shipment', shipment, '6', cost_exchange={'currency': 'CNY'})
    with domain_write():
        payment = PaymentRecord.objects.create(tenant=buyer.tenant, created_by=buyer, shipment=shipment,
            amount=Decimal('4'), purpose='domestic_freight', date='2026-10-14',
            account_snapshot={'currency': posting_unit} if posting_unit is not None else {}, idempotency_key='legacy-confirmation')
        PaymentCurrencyConfirmation.objects.create(tenant=buyer.tenant, created_by=buyer, payment=payment,
            currency=confirmed_unit, reason='Synthetic display evidence only')
    assert costs.recorded_payment_currency(buyer, payment) == (posting_unit or '')
    data = api.get(BASE + 'dashboard/queue/?queue=domestic&status=all').data
    row = next(r for r in data['data'] if r['id'] == shipment.pk and r['kind'] != 'domestic_expense')
    if resolved:
        assert row['currency'] == 'CNY' and Decimal(row['remaining_amount']) == 2
    else:
        assert row['currency'] is None and row['remaining_amount'] is None
    assert row['payment_currency_evidence_sources'] == (['legacy_confirmation'] if posting_unit is None else ['posting_snapshot'])
