from decimal import Decimal

import pytest

from apps.supply_chain.models import PaymentRecord, domain_write
from tests.test_supply_chain_payments import itemized_batch, save_itemized_fee
from tests.test_supply_chain_v2_costs import fee_body, get, write
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_v2_logistics import BASE


@pytest.mark.django_db(transaction=True)
def test_dashboard_fee_item_status_uses_current_revision_and_reversal(world):
    buyer, api, batch, carrier, profiles = itemized_batch(world)
    save_itemized_fee(api, batch, profiles)
    base = f'{BASE}dashboard/queue/?queue=carrier&status=all'

    # Unpaid items are included even when no PaymentRecord exists for them.
    unpaid = api.get(base + '&item_status=unpaid&payment_item=海运费&limit=1&offset=0')
    assert unpaid.status_code == 200, unpaid.data
    assert unpaid.data['count'] == 1
    assert [row['id'] for row in unpaid.data['data']] == [batch.pk]
    assert api.get(base + '&item_status=partial').data['count'] == 0
    assert api.get(base + '&item_status=settled').data['count'] == 0
    assert api.get(base + '&item_status=all').data['count'] == 1
    assert api.get(base + '&item_status=unpaid&payment_item=missing').data['count'] == 0

    account_id = write(api, f'costs/freight_company/{carrier.pk}/payee-accounts/', {
        'nature': 'corporate', 'account_name': 'Corp', 'account_holder': 'Corp',
        'bank_name': 'Bank', 'account_number': '1234567890', 'active': True,
    }, 'fee-query-account').data['data']['account']['id']
    payments_url = f'costs/batch/{batch.pk}/payments/'
    state = api.get(BASE + payments_url).data['data']
    paid = write(api, payments_url, {'amount': '5', 'date': '2026-10-20',
        'payee_account_id': account_id, 'fee_item_id': profiles[0].pk,
        'expected_version': state['version']}, 'fee-query-partial')
    assert paid.status_code == 201, paid.data
    assert api.get(base + '&item_status=partial').data['count'] == 1
    assert api.get(base + '&item_status=unpaid&payment_item=海运费').data['count'] == 0

    state = paid.data['data']
    settled = write(api, payments_url, {'amount': '15', 'date': '2026-10-20',
        'payee_account_id': account_id, 'fee_item_id': profiles[0].pk,
        'expected_version': state['version']}, 'fee-query-settled')
    assert settled.status_code == 201, settled.data
    assert api.get(base + '&item_status=settled&payment_item=海运费').data['count'] == 1
    assert api.get(base + '&item_status=partial').data['count'] == 0

    state = settled.data['data']
    reversal = write(api, f'{payments_url}{state["entries"][0]["id"]}/reverse/', {
        'reason': 'restore unpaid status', 'expected_version': state['version'],
    }, 'fee-query-reversal')
    assert reversal.status_code == 200, reversal.data
    assert api.get(base + '&item_status=partial').data['count'] == 1
    assert api.get(base + '&item_status=settled&payment_item=海运费').data['count'] == 0
    reversal2 = write(api, f'{payments_url}{state["entries"][1]["id"]}/reverse/', {
        'reason': 'restore unpaid status', 'expected_version': reversal.data['data']['version'],
    }, 'fee-query-reversal-2')
    assert reversal2.status_code == 200, reversal2.data
    assert api.get(base + '&item_status=partial').data['count'] == 0
    assert api.get(base + '&item_status=unpaid&payment_item=海运费').data['count'] == 1

    # A later fee revision replaces the projection used by dashboard item state.
    context = get(api, 'batch', batch)
    revised_body = fee_body(context, '30.0000', item_breakdown=[
        {'fee_item_id': profiles[0].pk, 'amount': '4.0000', 'nature': 'corporate'},
        {'fee_item_id': profiles[1].pk, 'amount': '26.0000', 'nature': 'personal'},
    ])
    revised = write(api, f'costs/batch/{batch.pk}/fee/', revised_body,
        'fee-query-current-revision', 'put')
    assert revised.status_code == 200, revised.data
    assert api.get(base + '&item_status=unpaid&payment_item=海运费').data['count'] == 1
    assert api.get(base + '&item_status=unpaid&payment_item=清关费').data['count'] == 1
    paged = api.get(base + '&item_status=unpaid&limit=1&offset=1')
    assert paged.data['count'] == 1
    assert paged.data['data'] == []

    foreign = world['tenant'].__class__.objects.create(name='Foreign fee query', code='foreign-fee-query')
    from apps.accounts.models import CustomUser
    outsider = CustomUser.objects.create_user(username='fee-query-outsider', tenant=foreign,
        user_type=CustomUser.UserType.INTERNAL)
    foreign_api = api.__class__()
    foreign_api.force_authenticate(outsider)
    assert foreign_api.get(base + '&item_status=all').status_code == 403
