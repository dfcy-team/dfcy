import pytest

from tests.test_supply_chain_v2_costs import pilot
from tests.test_supply_chain_v2_foundation import world, internal_user
from rest_framework.test import APIClient
from apps.tenants.models import Tenant

BASE = '/api/internal/supply-chain/v2/'


@pytest.mark.django_db
def test_plan_create_replay_currency_lock_and_no_cash_posted(world):
    from apps.supply_chain.models import PaymentRecord
    actor, client, shipment = pilot(world)
    path = BASE + f'costs/shipment/{shipment.pk}/payment-plans/'
    original_payments = PaymentRecord.objects.count()
    payload = {'expected_source_version': shipment.version, 'expected_version': 0, 'currency': 'CNY', 'reason': '按供应商约定计划付款',
        'lines': [{'nature': 'corporate', 'amount': '1.0000', 'due_date': None,
                   'note': '正报'}]}
    first = client.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='plan-1')
    assert first.status_code == 200, first.data
    assert first.data['data']['currency'] == 'CNY'
    assert first.data['data']['lines'][0]['amount'] == '1.0000'
    assert PaymentRecord.objects.count() == original_payments
    assert client.get(path).data['data']['version'] == 1
    replay = client.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='plan-1')
    assert replay.status_code == 200, replay.data
    assert replay.data['data']['version'] == 1
    changed = {**payload, 'expected_version': 1, 'currency': 'MYR'}
    rejected = client.post(path, changed, format='json', HTTP_IDEMPOTENCY_KEY='plan-currency-change')
    assert rejected.status_code == 400


@pytest.mark.django_db
def test_plan_rejects_reader_and_other_tenant(world):
    owner, _, shipment = pilot(world)
    path = BASE + f'costs/shipment/{shipment.pk}/payment-plans/'
    reader = internal_user(world, 'payment-plan-reader', codes=('supply.v2.view',))
    client = APIClient(); client.force_authenticate(reader)
    response = client.post(path, {'expected_source_version': shipment.version, 'expected_version': 0, 'currency': 'CNY', 'reason': 'x', 'lines': []},
                           format='json', HTTP_IDEMPOTENCY_KEY='plan-reader')
    assert response.status_code in (403, 404)
    tenant = Tenant.objects.create(name='Other tenant', code='plan-other')
    stranger = internal_user({'tenant': tenant}, 'payment-plan-stranger')
    client.force_authenticate(stranger)
    response = client.get(path)
    assert response.status_code == 404


def plan_payload(client, path, **overrides):
    state = client.get(path).data['data']
    return {'expected_version': state['version'], 'expected_source_version': state['source_version'],
            'currency': state['currency'] or 'CNY', 'reason': '核对原单付款安排',
            'lines': [{'nature': 'corporate', 'amount': '1.0000', 'due_date': '2026-12-20'}], **overrides}


@pytest.mark.django_db
def test_plan_validation_and_source_change(world):
    actor, client, shipment = pilot(world)
    path = BASE + f'costs/shipment/{shipment.pk}/payment-plans/'
    payload = plan_payload(client, path)
    for index, change in enumerate([
        {'expected_source_version': 999}, {'lines': [{'nature': 'corporate', 'amount': '999999'}]},
        {'lines': [{'nature': 'personal', 'amount': '-1'}]},
        {'lines': [{'nature': 'unclassified', 'amount': '1'}]},
        {'lines': [{'nature': 'corporate', 'amount': '1', 'currency': 'USD'}]},
        {'lines': [{'nature': 'corporate', 'amount': '1'}] * 101},
    ]):
        response = client.post(path, {**payload, **change}, format='json', HTTP_IDEMPOTENCY_KEY=f'invalid-{index}')
        assert response.status_code == 400, response.data
    saved = client.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='valid-dated')
    assert saved.status_code == 200, saved.data
    assert saved.data['data']['lines'][0]['due_date'] == '2026-12-20'
    assert client.put(path, payload, format='json').status_code == 405
    assert client.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='stale-plan').status_code == 400


@pytest.mark.django_db
def test_successful_retry_after_remaining_balance_changes(world, monkeypatch):
    from apps.supply_chain import costs
    actor, client, shipment = pilot(world)
    path = BASE + f'costs/shipment/{shipment.pk}/payment-plans/'
    payload = plan_payload(client, path)
    assert client.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='committed').status_code == 200
    original = costs.payment_summary
    def depleted(*args, **kwargs):
        result = original(*args, **kwargs)
        result['summary']['remaining_amount'] = '0.0000'
        return result
    monkeypatch.setattr(costs, 'payment_summary', depleted)
    replay = client.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='committed')
    assert replay.status_code == 200, replay.data
    assert replay.data['data']['version'] == 1


@pytest.mark.django_db
def test_domestic_party_currency_and_change_warning(world):
    from tests.test_supply_chain_v2_foundation import freight
    from tests.test_supply_chain_v2_costs import mark, fee
    from apps.supply_chain.models import domain_write
    actor, client, shipment = pilot(world)
    shipment = mark(actor, shipment)
    carrier = freight(world)
    with domain_write():
        shipment.domestic_carrier = carrier
        shipment.domestic_terms_snapshot = {'currency': 'MYR', 'settlement_mode': 'company_direct'}
        shipment.save()
    fee(client, 'shipment', shipment, '10')
    path = BASE + f'costs/domestic_freight/{shipment.pk}/payment-plans/'
    loaded = client.get(path)
    assert loaded.status_code == 200, loaded.data
    assert loaded.data['data']['party_name'] == carrier.name
    assert loaded.data['data']['currency'] == 'MYR'
    payload = plan_payload(client, path)
    bad = client.post(path, {**payload, 'currency': 'CNY'}, format='json', HTTP_IDEMPOTENCY_KEY='wrong-currency')
    assert bad.status_code == 400
    saved = client.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='domestic-plan')
    assert saved.status_code == 200, saved.data
    shipment.refresh_from_db()
    with domain_write():
        shipment.domestic_terms_snapshot = {'currency': 'MYR', 'settlement_mode': 'supplier_advance'}
        shipment.version += 1
        shipment.save()
    changed = client.get(path).data['data']
    assert changed['party_changed'] is True
    assert changed['saved_party_name'] == carrier.name
    assert changed['party_name'] == shipment.order.supplier.name
    assert client.post(path, {**payload, 'expected_version': 1}, format='json', HTTP_IDEMPOTENCY_KEY='stale-party').status_code == 400


@pytest.mark.django_db
def test_batch_per_item_caps_and_nature(world, monkeypatch):
    from tests.test_supply_chain_v2_foundation import freight
    from tests.test_supply_chain_v2_costs import mark, fee
    from tests.test_supply_chain_v2_logistics import create, arrive
    from apps.supply_chain import costs
    actor, client, shipment = pilot(world)
    shipment = mark(actor, shipment)
    batch, _ = create(client, [shipment], freight(world))
    path = BASE + f'costs/batch/{batch["id"]}/payment-plans/'
    payload = plan_payload(client, path)
    assert client.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='unknown-fee').status_code == 400
    batch = arrive(client, batch)
    fee(client, 'batch', batch['id'], '10')
    original = costs.payment_summary
    def itemized(*args, **kwargs):
        result = original(*args, **kwargs)
        result['itemized'] = True
        result['fee_items'] = [{'fee_item_id': 71, 'name': '报关费', 'nature': 'corporate', 'remaining_amount': '2.0000'}]
        return result
    monkeypatch.setattr(costs, 'payment_summary', itemized)
    payload = plan_payload(client, path)
    for index, line in enumerate([
        {'nature': 'corporate', 'amount': '1'},
        {'nature': 'corporate', 'amount': '1', 'fee_item_id': 999},
        {'nature': 'personal', 'amount': '1', 'fee_item_id': 71},
        {'nature': 'corporate', 'amount': '3', 'fee_item_id': 71},
    ]):
        response = client.post(path, {**payload, 'lines': [line]}, format='json', HTTP_IDEMPOTENCY_KEY=f'bad-item-{index}')
        assert response.status_code == 400, response.data
    good = client.post(path, {**payload, 'lines': [{'nature': 'corporate', 'amount': '2', 'fee_item_id': 71}]}, format='json', HTTP_IDEMPOTENCY_KEY='good-item')
    assert good.status_code == 200, good.data
