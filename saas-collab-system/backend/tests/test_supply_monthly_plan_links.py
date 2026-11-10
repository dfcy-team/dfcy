from decimal import Decimal
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_v2_costs import pilot
from tests.test_supply_monthly_payables import monthly, set_day, cash, BASE
from tests.test_supply_chain_v2_logistics import write
from apps.supply_chain.models import domain_write
from apps.supply_chain.cost_models import PaymentPlanRecord
from apps.supply_chain.payment_request_models import SupplyPaymentRequest


def test_monthly_plan_deducts_linked_cash_and_restores_reversal(world):
    actor, api, shipment = pilot(world)
    set_day(shipment)
    account = write(api, f'costs/shipment/{shipment.pk}/payee-accounts/', {
        'nature':'corporate','account_name':'测试户','account_holder':'供应商','bank_name':'测试银行',
        'account_number':'6222000000001111','active':True}, 'monthly-plan-account').data['data']['account']
    paid = cash(world, actor, shipment, '3', '2026-10-05', 'linked-paid',
                account_snapshot={'nature':'corporate','currency':'CNY'})
    with domain_write():
        plan = PaymentPlanRecord.objects.create(tenant=world['tenant'], created_by=actor,
            shipment=shipment, kind='shipment', currency='CNY', reason='test',
            party_snapshot={'type':'supplier','id':shipment.order.supplier_id,'name':shipment.order.supplier.name},
            lines=[{'line_id':'line-a','nature':'corporate','amount':'10','currency':'CNY','due_date':'2026-10-20'}])
        SupplyPaymentRequest.objects.create(tenant=world['tenant'],created_by=actor,
            kind='shipment',source_id=shipment.pk,amount=Decimal('3'),currency='CNY',
            payee_account_id=account['id'],account_snapshot={'nature':'corporate'},reason='test',
            plan=plan,plan_line_id='line-a',payment=paid,status='paid',
            idempotency_key='linked-request',request_hash='test')
    data=monthly(api)
    row=data['current_plan_rows'][0]
    assert Decimal(row['amount']) == 7
    assert Decimal(row['paid_amount']) == 3
    assert Decimal(row['original_amount']) == 10
    assert Decimal(data['summary']['current_plan_by_currency'][0]['corporate']) == 7
    classified=next(r for r in data['summary']['nature_balances'] if r['nature']=='corporate')
    assert Decimal(classified['current_plan_amount']) == 7
    cash(world,actor,shipment,'3','2026-11-02','linked-reversed',reverses=paid,reversal_reason='test')
    assert Decimal(monthly(api)['current_plan_rows'][0]['amount']) == 10
    # Plans are current balances even when viewing an older month; actual cash remains date-bound.
    assert Decimal(monthly(api)['summary']['paid_amount']) == 3


def test_approval_posts_plan_once_and_failed_approval_keeps_reservation(world, monkeypatch):
    from tests.test_supply_payment_approval_posting import pending, approve
    from tests.test_supply_payment_request_evidence import _upload
    from apps.supply_chain.payment_plan_links import line_balances
    actor, api, shipment, account, row, reviewer, reviewer_api = pending(world, monkeypatch)
    with domain_write():
        plan = PaymentPlanRecord.objects.create(tenant=world['tenant'], created_by=actor,
            shipment=shipment, kind='shipment', currency='CNY', reason='test',
            party_snapshot={'type':'supplier','id':shipment.order.supplier_id,'name':shipment.order.supplier.name},
            lines=[{'line_id':'approval-line','nature':'corporate','amount':'5','currency':'CNY','due_date':'2026-10-20'}])
        request=SupplyPaymentRequest.objects.get(pk=row['id'])
        request.plan=plan; request.plan_line_id='approval-line'; request.currency='CNY'
        request.save(update_fields=['plan','plan_line_id','currency'])
    balance=line_balances(plan)['approval-line']
    assert balance['reserved_amount']==1 and balance['paid_amount']==0
    failed=approve(reviewer_api,row)
    assert failed.status_code==400
    assert line_balances(plan)['approval-line']['reserved_amount']==1
    row=_upload(reviewer_api,shipment,row).data['data']
    response=approve(reviewer_api,row)
    assert response.status_code==200, response.data
    balance=line_balances(plan)['approval-line']
    assert balance['reserved_amount']==0 and balance['paid_amount']==1 and balance['remaining_amount']==4
    assert approve(reviewer_api,row).status_code==200
    assert line_balances(plan)['approval-line']['paid_amount']==1


def test_linked_drafts_submit_capacity_cancel_and_reject_release(world, monkeypatch):
    from tests.test_supply_payment_request_evidence import _setup_request
    from apps.supply_chain.payment_plan_links import line_balances
    from apps.workflows.models import ApprovalRequest
    actor, api, shipment, account, *_ = _setup_request(world,monkeypatch)
    path=f'costs/shipment/{shipment.pk}/'
    state=api.get(BASE+path+'payment-plans/').data['data']
    response=write(api,path+'payment-plans/',{'expected_version':0,'expected_source_version':state['source_version'],
        'currency':'CNY','reason':'test','lines':[{'nature':'corporate','amount':'5'}]},'capacity-plan')
    assert response.status_code==200,response.data
    plan_data=response.data['data']; line=plan_data['lines'][0]
    plan=PaymentPlanRecord.objects.get(shipment=shipment,kind='shipment')
    payload={'amount':'3','currency':'CNY','payee_account_id':account['id'],'reason':'test',
        'plan_line_id':line['line_id'],'plan_version':plan_data['version']}
    drafts=[]
    for i in range(2):
        response=write(api,path+'payment-requests/',payload,f'capacity-draft-{i}')
        assert response.status_code==201,response.data
        drafts.append(response.data['data'])
    assert line_balances(plan)[line['line_id']]['reserved_amount']==0
    def action(row,verb,key):
        return write(api,path+f'payment-requests/{row["id"]}/{verb}/',
            {'expected_version':row['version'],'reason':'test'},key)
    first=action(drafts[0],'submit','capacity-submit-first')
    assert first.status_code==200,first.data
    assert line_balances(plan)[line['line_id']]['reserved_amount']==3
    blocked=action(drafts[1],'submit','capacity-submit-second-blocked')
    assert blocked.status_code==400,blocked.data
    # A referenced line cannot be deleted or reduced below active commitments.
    base={'expected_version':plan_data['version'],'expected_source_version':state['source_version'],'currency':'CNY','reason':'test'}
    for i,lines in enumerate([[],[{'line_id':line['line_id'],'nature':'corporate','amount':'2'}]]):
        response=write(api,path+'payment-plans/',{**base,'lines':lines},f'capacity-plan-block-{i}')
        assert response.status_code==400,response.data
    cancelled=action(first.data['data'],'cancel','capacity-cancel')
    assert cancelled.status_code==200,cancelled.data
    assert line_balances(plan)[line['line_id']]['reserved_amount']==0
    second=action(drafts[1],'submit','capacity-submit-second')
    assert second.status_code==200,second.data
    ApprovalRequest.objects.filter(pk=second.data['data']['approval_id']).update(status='rejected')
    assert line_balances(plan)[line['line_id']]['reserved_amount']==0
    assert line_balances(plan)[line['line_id']]['available_amount']==5
