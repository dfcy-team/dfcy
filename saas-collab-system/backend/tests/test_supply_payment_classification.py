import pytest
from rest_framework.test import APIClient
from tests.test_supply_chain_v2_costs import pilot
from tests.test_supply_chain_v2_foundation import world, internal_user
from tests.test_supply_chain_v2_logistics import write
from apps.supply_chain.models import PaymentRecord, domain_write
from apps.supply_chain.payment_voucher_models import PaymentVoucher
from apps.supply_chain.cost_models import SettlementRecord, SettlementRevision
from apps.tenants.models import Tenant
BASE='/api/internal/supply-chain/v2/'

@pytest.mark.django_db
def test_payment_classification_split_pending_replay_and_immutable_cash(world):
    actor,client,shipment=pilot(world)
    response=write(client,f'costs/shipment/{shipment.pk}/payments/',{'amount':'10','date':'2026-10-01','payee_account_id':1,'expected_version':0},'x')
    # Seed the existing immutable ledger directly; classification API must not depend on bank accounts.
    with domain_write():
        payment=PaymentRecord.objects.create(tenant=actor.tenant,created_by=actor,shipment=shipment,amount='10',date='2026-10-01',idempotency_key='historic-payment')
        PaymentVoucher.objects.create(tenant=actor.tenant,created_by=actor,payment=payment,file_name='proof.pdf',media_type='application/pdf',byte_size=1,sha256='0'*64,idempotency_key='proof',content=b'x')
    path=BASE+f'costs/shipment/{shipment.pk}/classifications/payment/{payment.pk}/'
    before=(payment.amount,payment.date,payment.vouchers.count())
    assert client.get(path).data['data']['nature']=='unclassified'
    body={'expected_version':0,'allocations':[{'nature':'corporate','amount':'6'},{'nature':'personal','amount':'4'}],'reason':'核对原付款凭证'}
    saved=client.put(path,body,format='json',HTTP_IDEMPOTENCY_KEY='classify-1')
    assert saved.status_code==200,saved.data
    assert saved.data['data']['nature']=='mixed'
    assert client.put(path,body,format='json',HTTP_IDEMPOTENCY_KEY='classify-1').status_code==200
    bad=client.put(path,{**body,'allocations':[{'nature':'personal','amount':'9'}]},format='json',HTTP_IDEMPOTENCY_KEY='classify-bad')
    assert bad.status_code==400
    payment.refresh_from_db();assert (payment.amount,payment.date,payment.vouchers.count())==before
    listing=client.get(BASE+f'costs/shipment/{shipment.pk}/payments/').data['data']
    entry=next(x for x in listing['entries'] if x['id']==payment.pk)
    assert entry['classification']['allocations']==saved.data['data']['allocations']

@pytest.mark.django_db
def test_classification_authoritative_and_reader_tenant_checks(world):
    actor,client,shipment=pilot(world)
    with domain_write():
        from apps.supply_chain.cost_models import PayeeAccount
        account=PayeeAccount.objects.create(tenant=actor.tenant,created_by=actor,supplier=shipment.order.supplier,nature='corporate',account_name='x',account_holder='x',bank_name='x',account_number='1')
        payment=PaymentRecord.objects.create(tenant=actor.tenant,created_by=actor,shipment=shipment,amount='3',date='2026-10-01',idempotency_key='authoritative',payee_account=account,account_snapshot={'nature':'corporate'})
    path=BASE+f'costs/shipment/{shipment.pk}/classifications/payment/{payment.pk}/'
    assert client.get(path).data['data']['can_edit'] is False
    assert client.put(path,{'expected_version':0,'allocations':[],'reason':'no'},format='json',HTTP_IDEMPOTENCY_KEY='locked').status_code==400
    reader=internal_user(world,'classification-reader',codes=('supply.v2.view',));read=APIClient();read.force_authenticate(reader)
    assert read.get(path).status_code==200
    assert read.put(path,{'expected_version':0,'allocations':[],'reason':'no'},format='json',HTTP_IDEMPOTENCY_KEY='reader').status_code in (403,404)
    tenant=Tenant.objects.create(name='Other',code='classification-other');stranger=internal_user({'tenant':tenant},'classification-stranger');read.force_authenticate(stranger)
    assert read.get(path).status_code==404

@pytest.mark.django_db
def test_opening_classification_and_application_is_inherited(world):
    actor,client,shipment=pilot(world)
    with domain_write():
        settlement=SettlementRecord.objects.create(tenant=actor.tenant,created_by=actor,shipment=shipment)
        revision=SettlementRevision.objects.create(tenant=actor.tenant,created_by=actor,settlement=settlement,sequence=1,recorded_amount='5',reference_number='hist',date='2026-01-01',reason='opening',source_snapshot={'amount':'5'})
        settlement.current_revision=revision;settlement.save()
    path=BASE+f'costs/shipment/{shipment.pk}/classifications/opening/{revision.pk}/'
    resp=client.put(path,{'expected_version':0,'allocations':[{'nature':'personal','amount':'5'}],'reason':'人工核对期初凭证'},format='json',HTTP_IDEMPOTENCY_KEY='opening-classification')
    assert resp.status_code==200,resp.data
    assert resp.data['data']['nature']=='personal'
    row=client.get(BASE+f'costs/shipment/{shipment.pk}/payments/').data['data']['entries']
    opening=next(x for x in row if x['entry_type']=='opening')
    assert opening['classification']['nature']=='personal'


@pytest.mark.django_db
def test_purchase_prepayment_application_inherits_classification_without_double_allocation(world):
    from apps.supply_chain.cost_models import PaymentApplication
    actor,client,shipment=pilot(world)
    with domain_write():
        payment=PaymentRecord.objects.create(tenant=actor.tenant,created_by=actor,purchase_order=shipment.order,amount='8',date='2026-10-01',idempotency_key='purchase-historical')
        application=PaymentApplication.objects.create(tenant=actor.tenant,created_by=actor,prepayment=payment,shipment=shipment,amount='3',date='2026-10-02',idempotency_key='apply-historical')
    path=BASE+f'costs/purchase/{shipment.order_id}/classifications/payment/{payment.pk}/'
    response=client.put(path,{'expected_version':0,'allocations':[{'nature':'corporate','amount':'8'}],'reason':'核对采购定金'},format='json',HTTP_IDEMPOTENCY_KEY='purchase-classification')
    assert response.status_code==200,response.data
    result=client.get(BASE+f'costs/shipment/{shipment.pk}/payments/').data['data']['entries']
    inherited=next(row for row in result if row['entry_type']=='application' and row['id']==application.pk)
    assert inherited['classification']['nature']=='corporate'
    assert inherited['classification']['allocations']==[]
    assert inherited['classification']['inherited'] is True
    assert inherited['classification']['can_edit'] is False

@pytest.mark.django_db
def test_reversed_payment_is_view_only_and_successful_replay_survives_reversal(world):
    actor,client,shipment=pilot(world)
    with domain_write():
        payment=PaymentRecord.objects.create(tenant=actor.tenant,created_by=actor,shipment=shipment,amount='2',date='2026-10-01',idempotency_key='reversing-source')
    path=BASE+f'costs/shipment/{shipment.pk}/classifications/payment/{payment.pk}/'
    body={'expected_version':0,'allocations':[{'nature':'personal','amount':'2'}],'reason':'原凭证确认'}
    first=client.put(path,body,format='json',HTTP_IDEMPOTENCY_KEY='classify-before-reversal')
    assert first.status_code==200,first.data
    with domain_write():
        reversal=PaymentRecord.objects.create(tenant=actor.tenant,created_by=actor,shipment=shipment,amount='2',date='2026-10-03',idempotency_key='reversal-row',reverses=payment,reversal_reason='撤销原登记')
    view=client.get(BASE+f'costs/shipment/{shipment.pk}/classifications/payment/{payment.pk}/')
    assert view.status_code==200 and view.data['data']['can_edit'] is False
    replay=client.put(path,body,format='json',HTTP_IDEMPOTENCY_KEY='classify-before-reversal')
    assert replay.status_code==200,replay.data
    blocked=client.put(path,{**body,'expected_version':1,'reason':'再次修改'},format='json',HTTP_IDEMPOTENCY_KEY='change-reversed')
    assert blocked.status_code==400
    assert reversal.reverses_id==payment.pk

@pytest.mark.django_db
def test_stale_opening_revision_cannot_be_viewed_or_reclassified(world):
    actor,client,shipment=pilot(world)
    with domain_write():
        settlement=SettlementRecord.objects.create(tenant=actor.tenant,created_by=actor,shipment=shipment)
        first=SettlementRevision.objects.create(tenant=actor.tenant,created_by=actor,settlement=settlement,sequence=1,recorded_amount='5',reference_number='one',date='2026-01-01',reason='opening',source_snapshot={'amount':'5'})
        settlement.current_revision=first;settlement.save()
    path=BASE+f'costs/shipment/{shipment.pk}/classifications/opening/{first.pk}/'
    assert client.put(path,{'expected_version':0,'allocations':[],'reason':'待确认'},format='json',HTTP_IDEMPOTENCY_KEY='opening-pending').status_code==200
    with domain_write():
        second=SettlementRevision.objects.create(tenant=actor.tenant,created_by=actor,settlement=settlement,sequence=2,recorded_amount='5',reference_number='two',date='2026-01-02',reason='corrected opening',source_snapshot={'amount':'5'})
        settlement.current_revision=second;settlement.version+=1;settlement.save()
    assert client.get(path).status_code==404

@pytest.mark.django_db
def test_historical_currency_confirmation_is_audited_and_preserves_payment(world):
    actor,client,shipment=pilot(world)
    with domain_write():
        payment=PaymentRecord.objects.create(tenant=actor.tenant,created_by=actor,shipment=shipment,amount='10',date='2026-10-01',idempotency_key='historic-currency')
    path=BASE+f'costs/shipment/{shipment.pk}/payment-currencies/payment/{payment.pk}/'
    assert client.get(path).data['data']['currency'] is None
    body={'expected_version':0,'currency':'USD','reason':'核对银行回单'}
    saved=client.put(path,body,format='json',HTTP_IDEMPOTENCY_KEY='currency-confirm-1')
    assert saved.status_code==200,saved.data
    assert saved.data['data']['currency']=='USD' and saved.data['data']['version']==1
    assert len(saved.data['data']['history'])==1
    assert client.put(path,body,format='json',HTTP_IDEMPOTENCY_KEY='currency-confirm-1').status_code==200
    assert client.put(path,{**body,'expected_version':0,'currency':'EUR'},format='json',HTTP_IDEMPOTENCY_KEY='currency-stale').status_code==400
    payment.refresh_from_db();assert payment.account_snapshot=={}
