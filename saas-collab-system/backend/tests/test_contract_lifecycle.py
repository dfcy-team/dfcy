from decimal import Decimal
import pytest
from apps.supply_chain import costs
from apps.supply_chain.models import SupplierShipment, PurchaseContractHistory, PaymentRecord, domain_write
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_purchase_contracts import submitted_shipment
from tests.test_supply_chain_v2_numbering import config
from tests.test_supply_chain_contract_signatures import pdf

BASE='/api/internal/supply-chain/v2/'


def issue_setup(submitted_shipment, world, treatment='exempt'):
    actor, api, data = submitted_shipment
    shipment = SupplierShipment.objects.get(pk=data['id'])
    base = BASE+f'supplier-shipments/{shipment.pk}/purchase-contract/'
    payload = api.get(base).data['data']['defaults']
    payload.update(tax_treatment=treatment, contract_date='2026-10-30')
    payload['buyer']['name']='buyer'; payload['lines'][0]['tax_rate']='6'
    saved=api.put(base, {'expected_version':0,'expected_source_version':shipment.version,'nature':'corporate','payload':payload},format='json')
    assert saved.status_code==200, saved.data
    config(world,actor,kind='corporate_contract',prefix='CC')
    issued=api.post(base+'issue/', {'expected_version':saved.data['data']['contract']['version'],'expected_source_version':shipment.version,'confirmed':True},format='json')
    assert issued.status_code==200, issued.data
    return actor,api,shipment,base,issued.data['data']['contract']


@pytest.mark.parametrize('treatment', ['refund','exempt'])
def test_void_reissue_preserves_history_and_separates_signatures(submitted_shipment,world,treatment):
    actor,api,shipment,base,contract=issue_setup(submitted_shipment,world,treatment)
    uploaded=api.post(base+'signatures/', {'file':pdf()},format='multipart',HTTP_IDEMPOTENCY_KEY='old-signature')
    assert uploaded.status_code==201, uploaded.data
    old_attachment=uploaded.data['data']['attachments'][0]
    old_due=Decimal(costs.payment_summary(actor,'shipment',shipment.pk)['summary']['due_amount'])
    # Calculate once to verify historical cost snapshots stay intact after void.
    from tests.test_supply_chain_v2_costs import calculate
    before,_=calculate(api,'shipment',shipment)
    stale=api.post(base+'void/',{'expected_version':0,'reason':'replace'},format='json')
    assert stale.status_code==409
    response=api.post(base+'void/',{'expected_version':contract['version'],'reason':'合同条款修订'},format='json')
    assert response.status_code==200,response.data
    assert response.data['data']['contract']['status']=='voided'
    summary=costs.payment_summary(actor,'shipment',shipment.pk)['summary']
    assert Decimal(summary['due_amount'])==old_due-Decimal('.60')
    assert Decimal(summary['contract_cost_tax_amount'])==0
    assert costs.version_for(actor,'shipment',shipment.pk,before['sequence'])['entries']==before['entries']
    if treatment=='exempt':
        assert costs.context(actor,'shipment',shipment.pk)['latest_cost']['status']=='recalculation_required'
    history=api.get(base+'history/').data['data']['history']
    assert len(history)==1 and history[0]['number']==contract['number']
    assert api.get(base+f"history/{history[0]['id']}/download/").status_code==200
    assert api.get(old_attachment['download_url']).status_code==200
    assert api.get(base+'signatures/').status_code==404
    assert api.post(base+'issue/',{'confirmed':True},format='json').status_code==400
    draft=api.post(base+'reissue/',{'expected_version':response.data['data']['contract']['version']},format='json')
    assert draft.status_code==200,draft.data
    assert draft.data['data']['contract']['number'] is None
    # Changing reset scope starts a fresh sequence; archived numbers stay reserved.
    from apps.supply_chain.models import DocumentNumberRule
    rule=DocumentNumberRule.objects.get(tenant=actor.tenant,kind='corporate_contract')
    with domain_write():
        rule.reset_period='never'; rule.save()
    issued=api.post(base+'issue/',{'expected_version':draft.data['data']['contract']['version'],'expected_source_version':shipment.version,'confirmed':True},format='json')
    assert issued.status_code==200,issued.data
    assert issued.data['data']['contract']['number']!=contract['number']
    assert Decimal(costs.payment_summary(actor,'shipment',shipment.pk)['summary']['due_amount'])==old_due
    assert api.get(base+'signatures/').data['data']['attachments']==[]
    assert api.get(old_attachment['download_url']).status_code==200
    assert PurchaseContractHistory.objects.get().snapshot['payload']==contract['payload']


def test_void_blocks_tax_already_paid(submitted_shipment,world):
    actor,api,shipment,base,contract=issue_setup(submitted_shipment,world)
    due=Decimal(costs.payment_summary(actor,'shipment',shipment.pk)['summary']['due_amount'])
    with domain_write():
        PaymentRecord.objects.create(tenant=actor.tenant,created_by=actor,shipment=shipment,amount=due,date='2026-10-31',idempotency_key='tax-paid')
    response=api.post(base+'void/',{'expected_version':contract['version'],'reason':'replace'},format='json')
    assert response.status_code==400,response.data
    assert not PurchaseContractHistory.objects.exists()
    assert api.get(base).data['data']['contract']['status']=='issued'


@pytest.mark.django_db
def test_lifecycle_routes_do_not_inherit_current_contract_editor(submitted_shipment):
    _, api, data = submitted_shipment
    base = BASE + f"supplier-shipments/{data['id']}/purchase-contract/"
    from apps.supply_chain.models import PurchaseContract
    before = list(PurchaseContract.objects.values('id', 'version', 'status', 'payload'))
    for method, suffix in [
        ('put', 'history/'), ('put', 'history/999/download/'),
        ('put', 'download/'), ('get', 'void/'), ('put', 'void/'),
        ('get', 'reissue/'), ('put', 'reissue/'),
    ]:
        response = getattr(api, method)(base + suffix, {}, format='json')
        assert response.status_code == 405, (method, suffix, response.status_code)
    assert list(PurchaseContract.objects.values('id', 'version', 'status', 'payload')) == before
