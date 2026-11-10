import pytest

from tests.test_supply_chain_v2_costs import pilot
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_payment_request_evidence import _setup_request, write
from tests.test_supply_payment_batch import _second_shipment


BASE = '/api/internal/supply-chain/v2/'


@pytest.mark.django_db
def test_plan_lines_get_stable_ids_and_boolean_reference_state(world):
    _, client, shipment = pilot(world)
    endpoint = BASE + f'costs/shipment/{shipment.pk}/payment-plans/'
    payload = {'expected_source_version': shipment.version, 'expected_version': 0,
        'currency': 'CNY', 'reason': '稳定编号测试',
        'lines': [{'nature': 'corporate', 'amount': '1.0000'}]}
    created = client.post(endpoint, payload, format='json', HTTP_IDEMPOTENCY_KEY='stable-plan-line')
    assert created.status_code == 200, created.data
    line = created.data['data']['lines'][0]
    assert line['line_id']
    assert line['has_references'] is False
    fetched = client.get(endpoint).data['data']['lines'][0]
    assert fetched['line_id'] == line['line_id']

    update = {**payload, 'expected_version': 1,
        'lines': [{'line_id': line['line_id'], 'nature': 'corporate', 'amount': '1.0000'},
                  {'nature': 'personal', 'amount': '1.0000'}]}
    saved = client.post(endpoint, update, format='json', HTTP_IDEMPOTENCY_KEY='stable-plan-add-line')
    assert saved.status_code == 200, saved.data
    assert saved.data['data']['lines'][0]['line_id'] == line['line_id']
    assert saved.data['data']['lines'][1]['line_id'] != line['line_id']


@pytest.mark.django_db
def test_batch_line_can_link_plan_line(world, monkeypatch):
    buyer, client, shipment, account, original_request, reviewer, reviewer_api = _setup_request(world, monkeypatch)
    second = _second_shipment(world, buyer, 'plan-linked-batch')
    plan_endpoint = BASE + f'costs/shipment/{shipment.pk}/payment-plans/'
    state = client.get(plan_endpoint).data['data']
    plan_response = write(client, f'costs/shipment/{shipment.pk}/payment-plans/', {
        'expected_source_version': state['source_version'], 'expected_version': state['version'],
        'currency': 'CNY', 'reason': '批次付款计划',
        'lines': [{'nature': 'corporate', 'amount': '0.2500'}]}, 'linked-batch-plan')
    assert plan_response.status_code == 200, plan_response.data
    plan = plan_response.data['data']
    line = plan['lines'][0]
    created = write(client, 'payment-batches/', {'payee_account_id': account['id'], 'currency': 'CNY', 'reason': '链接计划的批次',
        'lines': [{'kind': 'shipment', 'source_id': shipment.pk, 'amount': '0.2500',
                   'plan_line_id': line['line_id'], 'plan_version': plan['version']},
                  {'kind': 'shipment', 'source_id': second.pk, 'amount': '0.2500'}]}, 'linked-plan-batch')
    assert created.status_code == 201, created.data
    matched = next(row for row in created.data['data']['lines'] if row['source_id'] == shipment.pk)
    assert matched['plan_line_id'] == line['line_id']
    assert matched['plan_snapshot']['line_id'] == line['line_id']

    from decimal import Decimal
    from apps.supply_chain.payment_plan_links import line_balances
    from apps.supply_chain.cost_models import PaymentPlanRecord
    from tests.test_supply_payment_request_evidence import _png
    from tests.test_supply_payment_approval_posting import approve
    record=PaymentPlanRecord.objects.get(shipment=shipment,kind='shipment')
    assert line_balances(record)[line['line_id']]['reserved_amount']==0
    batch=created.data['data']
    submitted=write(client,f'payment-batches/{batch["id"]}/submit/',
        {'expected_version':batch['version']},'linked-batch-submit')
    assert submitted.status_code==200,submitted.data
    assert line_balances(record)[line['line_id']]['reserved_amount']==Decimal('.25')
    uploaded=reviewer_api.post(BASE+f'payment-batches/{batch["id"]}/vouchers/',
        {'expected_version':submitted.data['data']['version'],'file':_png()},format='multipart',HTTP_IDEMPOTENCY_KEY='linked-batch-voucher')
    assert uploaded.status_code==201,uploaded.data
    approved=approve(reviewer_api,uploaded.data['data'])
    assert approved.status_code==200,approved.data
    assert line_balances(record)[line['line_id']]['paid_amount']==Decimal('.25')
    assert line_balances(record)[line['line_id']]['remaining_amount']==0
    assert approve(reviewer_api,uploaded.data['data']).status_code==200
    detail=client.get(BASE+f'payment-batches/{batch["id"]}/').data['data']
    reversed_result=write(client,f'payment-batches/{batch["id"]}/reverse/',
        {'expected_version':detail['version'],'reason':'test'},'linked-batch-reverse')
    assert reversed_result.status_code==200,reversed_result.data
    assert line_balances(record)[line['line_id']]['paid_amount']==0
    assert line_balances(record)[line['line_id']]['available_amount']==Decimal('.25')

    from apps.supply_chain import payment_plans
    from apps.supply_chain.cost_models import PaymentPlanRecord
    original_party_id = PaymentPlanRecord.objects.get(shipment=shipment, kind='shipment').party_snapshot['id']
    monkeypatch.setattr(payment_plans, '_party', lambda kind, obj: {
        'type': 'carrier', 'id': original_party_id, 'name': '同 ID 不同类型'})
    refreshed = client.get(plan_endpoint).data['data']
    changed_party = write(client, f'costs/shipment/{shipment.pk}/payment-plans/', {
        'expected_source_version': refreshed['source_version'], 'expected_version': refreshed['version'],
        'currency': 'CNY', 'reason': '同 ID 更换往来单位类型',
        'lines': [{'line_id': line['line_id'], 'nature': 'corporate', 'amount': '0.2500'}]}, 'linked-party-type-change')
    assert changed_party.status_code == 400, changed_party.data
