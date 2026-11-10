from decimal import Decimal
import pytest
from tests.test_supply_chain_v2_foundation import world, internal_user
from tests.test_supply_chain_v2_logistics import write, BASE
from tests.test_supply_chain_v2_costs import pilot
from tests.test_supply_monthly_nature_balances import split, rows
from tests.test_supply_monthly_payables import set_day, cash
from tests.test_supply_payment_approval_posting import pending, approve
from tests.test_supply_payment_request_evidence import _upload, _png
from tests.test_supply_payment_batch import _second_shipment
from apps.supply_chain.models import domain_write, PaymentRecord
from apps.supply_chain.payment_request_models import SupplyPaymentRequest

pytestmark=pytest.mark.django_db


def test_historical_confirmed_currency_reaches_monthly_and_reversal_without_mutation(world):
    actor,api,shipment=pilot(world);set_day(shipment);split(world,actor,shipment)
    paid=cash(world,actor,shipment,'3','2026-10-01','missing-currency',account_snapshot={'nature':'corporate'})
    rev=cash(world,actor,shipment,'1','2026-11-01','currency-reverse',reverses=paid,reversal_reason='test')
    assert any(r['currency']=='币种未记录' for r in rows(api))
    path=BASE+f'costs/shipment/{shipment.pk}/payment-currencies/payment/{paid.pk}/'
    body={'expected_version':0,'currency':'CNY','reason':'原始回单确认'}
    result=api.put(path,body,format='json',HTTP_IDEMPOTENCY_KEY='confirmed-currency')
    assert result.status_code==200,result.data
    assert len(result.data['data']['history'])==1
    assert api.put(path,body,format='json',HTTP_IDEMPOTENCY_KEY='confirmed-currency').status_code==200
    paid.refresh_from_db();assert paid.account_snapshot=={'nature':'corporate'} and paid.amount==Decimal('3')
    result=next(r for r in rows(api) if r['nature']=='corporate')
    assert result['currency']=='CNY' and Decimal(result['remaining_amount'])==9
    november=next(r for r in rows(api,month='2026-11') if r['nature']=='corporate')
    assert Decimal(november['remaining_amount'])==10
    reverse_path=BASE+f'costs/shipment/{shipment.pk}/payment-currencies/payment/{rev.pk}/'
    assert api.get(reverse_path).data['data']['currency']=='CNY'
    assert api.get(reverse_path).data['data']['can_edit'] is False
    assert api.put(reverse_path,body,format='json',HTTP_IDEMPOTENCY_KEY='no-reverse-edit').status_code==400
    reader=internal_user(world,'currency-reader',codes=('supply.v2.view',))
    api.force_authenticate(reader)
    assert api.get(path).data['data']['can_edit'] is False


@pytest.mark.parametrize('batch',[False,True])
def test_explicit_request_currency_survives_approval_posting(world,monkeypatch,batch):
    buyer,api,shipment,account,oldrow,actor,client=pending(world,monkeypatch)
    with domain_write():
        old=SupplyPaymentRequest.objects.get(pk=oldrow['id']);old.status='cancelled';old.save()
    if batch:
        second=_second_shipment(world,buyer,'currency-batch')
        created=write(api,'payment-batches/',{'currency':'CNY','payee_account_id':account['id'],'reason':'currency',
            'lines':[{'kind':'shipment','source_id':shipment.pk,'amount':'0.25'},
                     {'kind':'shipment','source_id':second.pk,'amount':'0.25'}]},'currency-batch-create')
        assert created.status_code==201,created.data
        row=write(api,f"payment-batches/{created.data['data']['id']}/submit/",{'expected_version':created.data['data']['version']},'currency-batch-submit').data['data']
        upload=client.post(f"{BASE}payment-batches/{row['id']}/vouchers/",{'expected_version':row['version'],'file':_png()},format='multipart',HTTP_IDEMPOTENCY_KEY='currency-batch-file')
    else:
        created=write(api,f'costs/shipment/{shipment.pk}/payment-requests/',{'currency':'CNY','amount':'1','payee_account_id':account['id'],'reason':'currency'},'currency-single-create')
        assert created.status_code==201,created.data
        row=write(api,f"costs/shipment/{shipment.pk}/payment-requests/{created.data['data']['id']}/submit/",{'expected_version':created.data['data']['version']},'currency-single-submit').data['data']
        upload=_upload(client,shipment,row)
    assert upload.status_code==201,upload.data
    row=upload.data['data'];assert row['currency']=='CNY'
    result=approve(client,row);assert result.status_code==200,result.data
    assert PaymentRecord.objects.count()==(2 if batch else 1)
    assert all(p.account_snapshot.get('currency')=='CNY' for p in PaymentRecord.objects.all())
    assert approve(client,row).status_code==200


def test_request_rejects_currency_conflicting_with_confirmed_payable(world):
    actor,api,shipment=pilot(world);split(world,actor,shipment)
    account=write(api,f'costs/shipment/{shipment.pk}/payee-accounts/',{'nature':'corporate','account_name':'test','account_holder':'supplier','bank_name':'bank','account_number':'6222000000001111','active':True},'currency-account').data['data']['account']
    response=write(api,f'costs/shipment/{shipment.pk}/payment-requests/',{'currency':'USD','amount':'1','payee_account_id':account['id'],'reason':'wrong'},'wrong-currency')
    assert response.status_code in (400,422)


def test_direct_payment_captures_currency_and_locks_original(world):
    actor,api,shipment=pilot(world);split(world,actor,shipment)
    account=write(api,f'costs/shipment/{shipment.pk}/payee-accounts/',{'nature':'corporate','account_name':'test','account_holder':'supplier','bank_name':'bank','account_number':'6222000000001111','active':True},'direct-currency-account').data['data']['account']
    state=api.get(BASE+f'costs/shipment/{shipment.pk}/payments/').data['data']
    response=write(api,f'costs/shipment/{shipment.pk}/payments/',{'currency':'CNY','amount':'1','date':'2026-10-01','payee_account_id':account['id'],'expected_version':state['version']},'direct-currency')
    assert response.status_code==201,response.data
    payment=PaymentRecord.objects.get(idempotency_key='direct-currency')
    assert payment.account_snapshot['currency']=='CNY'
    path=BASE+f'costs/shipment/{shipment.pk}/payment-currencies/payment/{payment.pk}/'
    assert api.get(path).data['data']['can_edit'] is False
    rejected=api.put(path,{'expected_version':0,'currency':'USD','reason':'cannot overwrite'},format='json',HTTP_IDEMPOTENCY_KEY='overwrite')
    assert rejected.status_code in (400,422)


def test_batch_rejects_known_different_source_currencies(world,monkeypatch):
    buyer,api,shipment,account,oldrow,actor,client=pending(world,monkeypatch)
    second=_second_shipment(world,buyer,'currency-other-source')
    split(world,buyer,shipment,currency='CNY');split(world,buyer,second,currency='USD')
    response=write(api,'payment-batches/',{'currency':'CNY','payee_account_id':account['id'],'reason':'mixed currency',
        'lines':[{'kind':'shipment','source_id':shipment.pk,'amount':'0.25'},
                 {'kind':'shipment','source_id':second.pk,'amount':'0.25'}]},'different-currencies')
    assert response.status_code in (400,422)


def test_mixed_historical_currencies_are_read_only(world):
    from apps.supply_chain.cost_models import SettlementRecord,SettlementRevision
    actor,api,shipment=pilot(world)
    with domain_write():
        record=SettlementRecord.objects.create(tenant=actor.tenant,created_by=actor,shipment=shipment)
        revision=SettlementRevision.objects.create(tenant=actor.tenant,created_by=actor,settlement=record,sequence=1,
            recorded_amount='5',reference_number='mixed',date='2026-10-01',reason='history',source_snapshot={'id':shipment.pk},
            payee_allocations=[{'amount':'2','account_snapshot':{'currency':'CNY'}},{'amount':'3','account_snapshot':{'currency':'USD'}}])
        record.current_revision=revision;record.save()
    path=BASE+f'costs/shipment/{shipment.pk}/payment-currencies/opening/{revision.pk}/'
    assert api.get(path).data['data']['can_edit'] is False
    response=api.put(path,{'expected_version':0,'currency':'CNY','reason':'mixed'},format='json',HTTP_IDEMPOTENCY_KEY='mixed-history')
    assert response.status_code in (400,422)
