import pytest

from tests.test_supply_chain_v2_costs import pilot
from tests.test_supply_chain_v2_foundation import world, internal_user
from rest_framework.test import APIClient
from apps.tenants.models import Tenant

BASE = '/api/internal/supply-chain/v2/'


@pytest.mark.django_db
def test_payable_classification_roundtrip_replay_and_no_cash_posted(world):
    from apps.supply_chain.models import PaymentRecord
    from apps.supply_chain.cost_models import PaymentPlanRecord
    actor, client, shipment = pilot(world)
    path = BASE + f'costs/shipment/{shipment.pk}/payable-classification/'
    initial = client.get(path)
    assert initial.status_code == 200, initial.data
    data = initial.data['data']
    assert data['version'] == 0 and data['source_version'] == shipment.version
    payload = {'expected_version': 0, 'expected_source_version': shipment.version,
        'expected_payable_amount': data['payable_amount'],
        'currency': data['currency'] or 'CNY', 'corporate_amount': '1.0000',
        'personal_amount': '2.0000', 'reason': '按供应商要求区分付款性质'}
    before = PaymentRecord.objects.count()
    first = client.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='payclass-1')
    assert first.status_code == 200, first.data
    assert first.data['data']['corporate_amount'] == '1.0000'
    assert first.data['data']['personal_amount'] == '2.0000'
    assert Decimal(first.data['data']['unclassified_amount']) == Decimal(data['payable_amount']) - 3
    assert PaymentRecord.objects.count() == before
    assert not PaymentPlanRecord.objects.exists()
    assert client.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='payclass-1').status_code == 200
    too_much = {**payload, 'expected_version': 1, 'corporate_amount': '99999999999999999999.0000'}
    assert client.post(path, too_much, format='json', HTTP_IDEMPOTENCY_KEY='payclass-over').status_code == 400


@pytest.mark.django_db
def test_payable_amount_drift_is_rejected_without_source_version_change(world, monkeypatch):
    from apps.supply_chain import costs
    _, client, shipment = pilot(world)
    path = BASE + f'costs/shipment/{shipment.pk}/payable-classification/'
    data = client.get(path).data['data']
    original = costs.payment_summary
    def changed(actor, kind, pk):
        result = original(actor, kind, pk)
        result['summary']['due_amount'] = str(Decimal(result['summary']['due_amount']) + Decimal('10'))
        return result
    monkeypatch.setattr(costs, 'payment_summary', changed)
    payload = {'expected_version': 0, 'expected_source_version': data['source_version'],
        'expected_payable_amount': data['payable_amount'], 'currency': data['currency'] or 'CNY',
        'corporate_amount': '1.0000', 'personal_amount': '0.0000', 'reason': '金额复核'}
    response = client.post(path, payload, format='json', HTTP_IDEMPOTENCY_KEY='payclass-drift')
    assert response.status_code == 400


@pytest.mark.django_db
def test_payable_classification_reader_and_tenant_scope(world):
    _, _, shipment = pilot(world)
    path = BASE + f'costs/shipment/{shipment.pk}/payable-classification/'
    reader = internal_user(world, 'payclass-reader', codes=('supply.v2.view',))
    client = APIClient(); client.force_authenticate(reader)
    assert client.get(path).status_code == 200
    assert client.get(path).data['data']['can_manage'] is False
    assert client.post(path, {}, format='json').status_code in (403, 404)
    tenant = Tenant.objects.create(name='Payclass other tenant', code='payclass-other')
    stranger = internal_user({'tenant': tenant}, 'payclass-stranger')
    client.force_authenticate(stranger)
    assert client.get(path).status_code == 404


from decimal import Decimal


def payload_for(client, path, **changes):
    d = client.get(path).data['data']
    return {'expected_version':d['version'],'expected_source_version':d['source_version'],
        'expected_payable_amount':d['payable_amount'],'currency':d['currency'] or 'CNY',
        'corporate_amount':d['payable_amount'],'personal_amount':'0','reason':'确认依据',**changes}


@pytest.mark.django_db
def test_paid_cash_does_not_reduce_classification_and_currency_locks_both_ways(world):
    from apps.supply_chain.models import PaymentRecord, domain_write
    _, client, shipment = pilot(world)
    actor = shipment.created_by
    with domain_write():
        PaymentRecord.objects.create(tenant=world['tenant'], created_by=actor, shipment=shipment,
            amount=Decimal('10'), date='2026-11-10', idempotency_key='paid-before-split')
    path = BASE + f'costs/shipment/{shipment.pk}/payable-classification/'
    payload = payload_for(client, path)
    response=client.post(path,payload,format='json',HTTP_IDEMPOTENCY_KEY='full-obligation')
    assert response.status_code==200, response.data
    assert Decimal(response.data['data']['corporate_amount'])==20
    plan_path=BASE + f'costs/shipment/{shipment.pk}/payment-plans/'
    plan=client.get(plan_path).data['data']
    assert plan['currency']=='CNY'
    bad=client.post(plan_path, {'expected_version':0,'expected_source_version':shipment.version,
        'currency':'USD','reason':'wrong currency','lines':[]},format='json',HTTP_IDEMPOTENCY_KEY='different-plan-currency')
    assert bad.status_code==400
    invalid={**payload,'expected_version':1,'currency':'USD'}
    assert client.post(path,invalid,format='json',HTTP_IDEMPOTENCY_KEY='different-classification-currency').status_code==400
    assert client.post(path,{**payload,'corporate_amount':'-1'},format='json',HTTP_IDEMPOTENCY_KEY='negative').status_code==400
    assert client.post(path,payload,format='json',HTTP_IDEMPOTENCY_KEY='stale').status_code==400


@pytest.mark.django_db
def test_itemized_freight_has_authoritative_read_only_classification(world, monkeypatch):
    from tests.test_supply_chain_v2_foundation import freight
    from tests.test_supply_chain_v2_costs import mark, fee
    from tests.test_supply_chain_v2_logistics import create, arrive
    from apps.supply_chain import costs
    actor, client, shipment=pilot(world)
    shipment=mark(actor,shipment)
    batch,_=create(client,[shipment],freight(world))
    batch=arrive(client,batch)
    fee(client,'batch',batch['id'],'10')
    original=costs.payment_summary
    def itemized(*args,**kwargs):
        result=original(*args,**kwargs)
        result['itemized']=True
        result['fee_items']=[{'amount':'7','nature':'corporate'},{'amount':'3','nature':'personal'}]
        return result
    monkeypatch.setattr(costs,'payment_summary',itemized)
    path=BASE + f"costs/batch/{batch['id']}/payable-classification/"
    data=client.get(path).data['data']
    assert data['can_manage'] is False and data['read_only_reason']
    assert Decimal(data['corporate_amount'])==7 and Decimal(data['personal_amount'])==3
    assert client.post(path,payload_for(client,path),format='json',HTTP_IDEMPOTENCY_KEY='itemized-split').status_code==400
