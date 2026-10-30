from decimal import Decimal

import pytest

from apps.permissions.models import DataScope
from apps.supply_chain import services
from apps.supply_chain.cost_models import PaymentRecord
from apps.supply_chain.models import domain_write
from apps.supply_chain.shipments import save_domestic_transport
from tests.test_supply_chain_v2_costs import pilot, mark, fee
from tests.test_supply_chain_v2_foundation import (world, internal_user, confirmed_order,
    po_payload, shipment_payload, freight)
from tests.test_supply_chain_v2_logistics import BASE, client, write


def account(api, kind, obj):
    response = write(api, f'costs/{kind}/{obj.pk}/payee-accounts/', {'nature':'corporate',
        'account_name':'Test account','account_holder':'Test','bank_name':'Bank',
        'account_number':'9988776655','active':True}, f'dashboard-account-{kind}-{obj.pk}')
    assert response.status_code == 201, response.data
    return response.data['data']['account']['id']


@pytest.mark.django_db(transaction=True)
def test_dashboard_domestic_freight_is_separate_and_unselected_carrier_is_visible(world):
    buyer, api, seed_shipment = pilot(world)
    carrier = freight(world)
    carrier.service_scopes = ['domestic']
    with domain_write():
        carrier.save(update_fields=['service_scopes'])
    shipment = services.create_supplier_shipment(buyer, shipment_payload(world, seed_shipment.order,
        'domestic-shipment', number='SH-DOMESTIC'), idempotency_key='domestic-shipment')
    shipment = save_domestic_transport(buyer, shipment.pk, {'expected_version':shipment.version,
        'domestic_carrier_id':carrier.pk,'domestic_tracking_number':''}, 'set-domestic-carrier')
    shipment = mark(buyer, shipment)
    fee(api, 'shipment', shipment, '6')
    with domain_write():
        PaymentRecord.objects.create(tenant=world['tenant'], created_by=buyer, shipment=shipment,
            amount=Decimal('4'), purpose='domestic_freight', date='2026-10-14', idempotency_key='domestic-cash')
    base = api.get(BASE + 'dashboard/?section=costs').data['data']['groups']
    assert Decimal(base['supplier']['paid']) == 0
    assert Decimal(base['domestic']['paid']) == 4
    assert Decimal(base['domestic']['amount']) == 6
    assert Decimal(base['domestic']['unsettled']) == 2
    queue = api.get(BASE + 'dashboard/queue/?queue=domestic&status=all').data
    selected = next(row for row in queue['data'] if row['id'] == shipment.pk)
    assert selected['party_id'] == carrier.pk
    assert selected['kind'] == 'domestic_freight'
    assert selected['href'] == f'/supply-chain/costs?kind=domestic_freight&id={shipment.pk}'
    assert queue['summary']['documents'] == 2
    unassigned_shipment = services.create_supplier_shipment(buyer, shipment_payload(world, seed_shipment.order,
        'domestic-no-carrier', number='SH-DOMESTIC-NONE'), idempotency_key='domestic-no-carrier')
    unassigned_shipment = mark(buyer, unassigned_shipment, key='domestic-no-carrier-arrive')
    unassigned = api.get(BASE + 'dashboard/queue/?queue=domestic&status=all').data['data'][0]
    assert unassigned['party_name'] == '未选择国内承运商'
    assert unassigned['party_id'] is None
    assert unassigned['kind'] == 'shipment'
    assert unassigned['href'].endswith(f'kind=shipment&id={unassigned_shipment.pk}')


@pytest.mark.django_db(transaction=True)
def test_dashboard_deposit_application_is_not_counted_as_cash_and_party_filter_pages(world):
    buyer, api, shipment = pilot(world)
    acct = account(api, 'purchase', shipment.order)
    payment = write(api, f'costs/purchase/{shipment.order_id}/payments/', {'amount':'1','date':'2026-10-14',
        'payee_account_id':acct,'expected_version':0}, 'deposit-cash')
    assert payment.status_code == 201, payment.data
    payment_id = payment.data['data']['entries'][0]['id']
    shipment = mark(buyer, shipment)
    application = write(api, f'costs/shipment/{shipment.pk}/prepayment-applications/', {'payment_id':payment_id,
        'amount':'0.3','date':'2026-10-15','expected_version':0}, 'deposit-apply')
    assert application.status_code == 201, application.data
    groups = api.get(BASE + 'dashboard/?section=costs').data['data']['groups']
    deposit = groups['deposit']
    assert Decimal(deposit['paid']) == 1
    assert Decimal(deposit['amount']) == Decimal('7.5')
    assert Decimal(deposit['unsettled']) == Decimal('6.5')
    assert Decimal(deposit['applied']) == Decimal('0.3')
    assert Decimal(deposit['available_prepayment']) == Decimal('0.7')
    assert Decimal(deposit['available']) == Decimal('0.7')
    assert Decimal(groups['supplier']['paid']) == 0
    assert Decimal(groups['supplier']['applied']) == Decimal('0.3')
    page = api.get(BASE + f'dashboard/queue/?queue=deposit&status=all&party_id={shipment.order.supplier_id}&limit=1')
    assert page.status_code == 200
    assert page.data['count'] == 1
    row = page.data['data'][0]
    assert row['party_id'] == shipment.order.supplier_id
    assert row['kind'] == 'purchase'
    assert page.data['summary']['documents'] == 1
    assert row['href'] == f'/supply-chain/costs?kind=purchase&id={shipment.order_id}'
    assert Decimal(row['paid_amount']) == 1
    assert Decimal(row['applied_amount']) == Decimal('0.3')
    assert Decimal(row['available_prepayment']) == Decimal('0.7')


@pytest.mark.django_db(transaction=True)
def test_dashboard_settled_drillthrough_country_and_party_permission_filters(world):
    buyer, api, shipment = pilot(world)
    acct = account(api, 'supplier', world['supplier'])
    paid = write(api, f'costs/shipment/{shipment.pk}/payments/', {'amount':'20','date':'2026-10-14',
        'payee_account_id':acct,'expected_version':0}, 'settle-cash')
    assert paid.status_code == 201, paid.data
    settled = api.get(BASE + f'dashboard/queue/?queue=supplier&status=settled&party_id={shipment.order.supplier_id}')
    assert settled.status_code == 200
    assert settled.data['count'] == 1
    assert settled.data['data'][0]['kind'] == 'shipment'
    assert settled.data['data'][0]['href'] == f'/supply-chain/costs?kind=shipment&id={shipment.pk}'
    assert Decimal(settled.data['data'][0]['remaining_amount']) == 0
    assert api.get(BASE + f'dashboard/queue/?queue=supplier&status=all&country_id={world["country_ca"].pk}').status_code == 404

    restricted = internal_user(world, 'dashboard-restricted', scope=DataScope.ScopeType.CUSTOM,
        config={'supplier_ids': [world['supplier_b'].pk]})
    result = client(restricted).get(BASE + f'dashboard/queue/?queue=supplier&status=all&party_id={shipment.order.supplier_id}')
    assert result.status_code == 200
    assert result.data['count'] == 0
    assert client(restricted).get(BASE + f'dashboard/queue/?queue=supplier&status=all&party_id={world["supplier_b"].pk}').data['count'] == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('queue', ['supplier', 'carrier', 'domestic', 'deposit'])
def test_queue_summary_totals_do_not_shadow_annotations(world, queue):
    buyer, api, shipment = pilot(world)
    response = api.get(BASE + f'dashboard/queue/?queue={queue}&status=all')
    assert response.status_code == 200
    assert response.data['summary']['documents'] == response.data['count']
    for key in ('due_amount', 'paid_amount', 'remaining_amount', 'available_prepayment'):
        assert Decimal(response.data['summary'][key]) >= 0
