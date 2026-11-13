from decimal import Decimal
from datetime import date

from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_v2_costs import pilot
from tests.test_supply_monthly_payables import monthly, set_day, cash, BASE
from apps.supply_chain.models import domain_write, PaymentRecord, PaymentApplication
from apps.supply_chain.cost_models import PayableClassificationRecord, SettlementRecord, SettlementRevision


def split(world,actor,shipment,corp='12',personal='8',currency='CNY'):
    with domain_write():
        return PayableClassificationRecord.objects.create(tenant=world['tenant'],created_by=actor,
            shipment=shipment,kind='shipment',currency=currency,payable_amount=Decimal('20'),
            corporate_amount=Decimal(corp),personal_amount=Decimal(personal),
            party_snapshot={'id':shipment.order.supplier_id,'type':'supplier','name':shipment.order.supplier.name},reason='confirmed')


def rows(api,**params):
    return monthly(api,**params)['summary']['nature_balances']


def test_classified_opening_cash_and_later_reversal(world):
    actor,api,shipment=pilot(world);set_day(shipment);split(world,actor,shipment)
    cash(world,actor,shipment,'2','2026-09-30','before',account_snapshot={'nature':'corporate','currency':'CNY'})
    paid=cash(world,actor,shipment,'3','2026-10-02','now',account_snapshot={'nature':'personal','currency':'CNY'})
    cash(world,actor,shipment,'3','2026-11-02','reverse',reverses=paid,reversal_reason='test')
    data={r['nature']:r for r in rows(api)}
    assert Decimal(data['corporate']['opening_payable'])==10
    assert Decimal(data['corporate']['remaining_amount'])==10
    assert Decimal(data['personal']['remaining_amount'])==5
    assert data['personal']['needs_review'] is False
    november={r['nature']:r for r in rows(api,month='2026-11')}
    assert Decimal(november['personal']['paid_amount'])==-3
    assert Decimal(november['personal']['remaining_amount'])==8


def test_supplier_payment_without_currency_defaults_to_cny(world):
    actor,api,shipment=pilot(world);set_day(shipment);split(world,actor,shipment)
    cash(world,actor,shipment,'3','2026-10-02','no-currency',account_snapshot={'nature':'corporate'})
    data=rows(api)
    known=next(r for r in data if r['currency']=='CNY' and r['nature']=='corporate')
    assert Decimal(known['remaining_amount'])==9 and Decimal(known['paid_amount'])==3
    assert all(r['currency']=='CNY' and not r['needs_review'] for r in data)


def test_excludes_zero_rows_after_cash_and_reversal_net_to_zero(world):
    actor, api, shipment = pilot(world)
    set_day(shipment)
    split(world, actor, shipment)
    payment = cash(world, actor, shipment, '3', '2026-09-20', 'unknown-currency',
                   account_snapshot={})
    cash(world, actor, shipment, '3', '2026-09-21', 'unknown-reversed',
         reverses=payment, reversal_reason='test')
    result = rows(api)
    assert all(row['nature'] != 'unknown' for row in result)
    assert {row['nature']: Decimal(row['reference_remaining_amount']) for row in result} == {
        'corporate': Decimal('12'), 'personal': Decimal('8'),
    }


def test_stale_classification_becomes_unknown_and_partial_split_preserves_remainder(world):
    actor,api,shipment=pilot(world);set_day(shipment);record=split(world,actor,shipment,'12','3')
    result={r['nature']:r for r in rows(api)}
    assert Decimal(result['unknown']['reference_remaining_amount'])==5
    with domain_write():
        record.payable_amount=Decimal('19');record.save()
    result=rows(api)
    assert len(result)==1 and result[0]['nature']=='unknown'
    assert Decimal(result[0]['reference_remaining_amount'])==20 and result[0]['needs_review']


def test_supplier_deposit_is_cash_but_application_is_not_duplicate(world):
    actor,api,shipment=pilot(world);set_day(shipment);split(world,actor,shipment)
    with domain_write():
        prepay=PaymentRecord.objects.create(tenant=world['tenant'],created_by=actor,purchase_order=shipment.order,
            amount=Decimal('5'),date='2026-10-02',idempotency_key='deposit-nature',account_snapshot={'nature':'corporate','currency':'CNY'})
        PaymentApplication.objects.create(tenant=world['tenant'],created_by=actor,prepayment=prepay,
            shipment=shipment,amount=Decimal('3'),date='2026-10-03',idempotency_key='application-nature')
    row=next(r for r in rows(api) if r['nature']=='corporate')
    assert Decimal(row['paid_amount'])==5
    assert Decimal(row['remaining_amount'])==7
    assert rows(api,party_id=999999)==[]


def test_export_contains_classified_balance_sheet(world):
    from io import BytesIO
    from openpyxl import load_workbook
    actor,api,shipment=pilot(world);set_day(shipment);split(world,actor,shipment)
    response=api.get(BASE+'dashboard/monthly/',{'month':'2026-10','queue':'supplier','export':'xlsx'})
    assert response.status_code==200
    book=load_workbook(BytesIO(response.content),read_only=True,data_only=True)
    data=list(book['往来单位性质对账'].values)
    assert any(r[2]=='对公/正报' and Decimal(r[3])==12 for r in data[1:])


def test_new_obligation_and_different_currency_never_net(world):
    actor,api,shipment=pilot(world);set_day(shipment,'2026-10-01');split(world,actor,shipment)
    cash(world,actor,shipment,'3','2026-10-02','usd',account_snapshot={'nature':'corporate','currency':'USD'})
    data=rows(api)
    cny=next(r for r in data if r['currency']=='CNY' and r['nature']=='corporate')
    usd=next(r for r in data if r['currency']=='USD')
    assert Decimal(cny['opening_payable'])==0 and Decimal(cny['new_payable'])==12
    assert Decimal(cny['remaining_amount'])==12 and Decimal(usd['credit_balance'])==3


def test_historical_paid_is_separate_from_cash_and_uses_only_latest_revision(world):
    actor,api,shipment=pilot(world);set_day(shipment);split(world,actor,shipment)
    with domain_write():
        record=SettlementRecord.objects.create(tenant=world['tenant'],created_by=actor,shipment=shipment)
        for sequence,amount in ((1,'3'),(2,'5')):
            revision=SettlementRevision.objects.create(tenant=world['tenant'],created_by=actor,
                settlement=record,sequence=sequence,recorded_amount=Decimal(amount),reference_number='history',
                date=date(2026,10,1),reason='test',source_snapshot={'shipment_id':shipment.pk},
                payee_allocations=[{'amount':amount,'account_snapshot':{'nature':'corporate','currency':'CNY'}}])
        record.current_revision=revision;record.save()
    row=next(r for r in rows(api) if r['nature']=='corporate')
    assert Decimal(row['paid_amount'])==0
    assert Decimal(row['historical_paid_amount'])==5
    assert Decimal(row['remaining_amount'])==7


def test_partial_mixed_reversal_preserves_exact_total(world):
    from apps.supply_chain.cost_models import PaymentClassification
    actor,api,shipment=pilot(world);set_day(shipment);split(world,actor,shipment)
    paid=cash(world,actor,shipment,'3','2026-09-01','mixed',account_snapshot={'currency':'CNY'})
    with domain_write():
        PaymentClassification.objects.create(tenant=world['tenant'],created_by=actor,payment=paid,
            allocations=[{'nature':'corporate','amount':'1'},{'nature':'personal','amount':'2'}],reason='test')
    cash(world,actor,shipment,'1','2026-10-01','mixed-reverse',reverses=paid,reversal_reason='test')
    result=rows(api)
    assert sum((Decimal(r['paid_amount']) for r in result),Decimal(0))==-1
    assert all(len(r['paid_amount'].split('.')[-1])<=4 for r in result)


def test_zero_fee_item_does_not_discard_valid_corporate_classification(world):
    from tests.test_supply_chain_v2_foundation import freight
    from tests.test_supply_chain_v2_costs import mark, fee
    from tests.test_supply_chain_v2_logistics import create, arrive
    from apps.supply_chain.cost_models import FeeRecord
    actor,api,shipment=pilot(world);shipment=mark(actor,shipment)
    batch,_=create(api,[shipment],freight(world));batch=arrive(api,batch)
    fee(api,'batch',batch['id'],'10')
    record=FeeRecord.objects.get(batch_id=batch['id'])
    # Historical fixture update only: current confirmed items can legally include zero.
    with domain_write():
        revision=record.current_revision
        revision.pk=None;revision.sequence+=1
        revision.item_breakdown=[{'nature':'corporate','amount':'10'},{'nature':'personal','amount':'0'}]
        revision.save()
        record.current_revision=revision;record.save()
    result=monthly(api,queue='carrier',month='2099-01')['summary']['nature_balances']
    assert any(r['nature']=='corporate' and Decimal(r['reference_remaining_amount'])==10 for r in result)
    assert not any(r['nature']=='unknown' for r in result)


def test_unknown_purchase_payable_never_reports_confirmed_overpayment(world):
    from apps.supply_chain.models import PurchaseLine
    actor,api,shipment=pilot(world)
    with domain_write():
        for line in PurchaseLine.objects.filter(order=shipment.order):
            line.unit_price=None;line.save()
    with domain_write():
        PaymentRecord.objects.create(tenant=world['tenant'],created_by=actor,purchase_order=shipment.order,
            amount=Decimal('5'),date='2026-10-02',idempotency_key='unknown-due-deposit',
            account_snapshot={'nature':'corporate','currency':'CNY'})
    result=rows(api,queue='deposit')
    assert len(result)==1
    assert result[0]['remaining_amount'] is None and result[0]['credit_balance'] is None
    assert Decimal(result[0]['paid_amount'])==5 and result[0]['needs_review']


def test_changed_party_plan_is_excluded_from_all_monthly_views(world):
    from apps.supply_chain.cost_models import PaymentPlanRecord
    actor,api,shipment=pilot(world);set_day(shipment)
    with domain_write():
        PaymentPlanRecord.objects.create(tenant=world['tenant'],created_by=actor,shipment=shipment,
            kind='shipment',currency='CNY',party_snapshot={'type':'supplier','id':999999,'name':'old party'},
            lines=[{'nature':'corporate','amount':'10','due_date':'2026-10-10'}])
    result=monthly(api)
    assert result['summary']['current_plan_by_currency']==[]
    assert result['current_plan_rows']==[]
    assert all(Decimal(r['current_plan_amount'])==0 for r in result['summary']['nature_balances'])
