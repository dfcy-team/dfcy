"""Database-backed coverage for the read-only fee source summary."""
import pytest

from apps.supply_chain import costs
from apps.supply_chain.domestic_expense_models import DomesticExpenseGroup
from apps.supply_chain.models import domain_write
from tests.test_supply_chain_v2_costs import mark, pilot, fee
from tests.test_supply_chain_v2_foundation import world


@pytest.mark.django_db
def test_shipment_context_keeps_domestic_detail_separate_from_own_fee(world):
    actor, _, shipment = pilot(world)
    shipment = mark(actor, shipment)
    fee_data, _ = fee(_, 'shipment', shipment, '12')
    with domain_write():
        DomesticExpenseGroup.objects.create(
            tenant=world['tenant'], created_by=actor, shipment=shipment,
            supplier=shipment.order.supplier, currency='USD', amount='3.5000',
            lines=[{'description': '费用明细'}],
        )

    data = costs.context(actor, 'shipment', shipment.pk)

    assert data['fee']['amount'] == fee_data['fee']['amount']
    assert len(data['related_fees']) == 1
    detail = data['related_fees'][0]
    assert (detail['label'], detail['amount'], detail['currency']) == (
        '本单国内费用明细', '3.5000', 'USD')
    assert detail['basis'] == 'source_total'


@pytest.mark.django_db
def test_inbound_context_lists_accessible_shipment_and_batch_totals(world):
    from tests.test_partial_inbound_costs import setup_batch, receipt

    actor, api, batch, line = setup_batch(world)
    inbound, _ = receipt(world, actor, batch, line, 3, 3, 'summary535')
    fee(api, 'shipment', line.shipment, '6')
    fee(api, 'batch', batch.pk, '18')

    data = costs.context(actor, 'inbound', inbound.pk)

    assert {(row['kind'], row['basis']) for row in data['related_fees']} == {
        ('shipment', 'source_total'), ('batch', 'source_total')}
    assert {row['label'] for row in data['related_fees']} == {'关联发货费用', '关联批次费用'}
