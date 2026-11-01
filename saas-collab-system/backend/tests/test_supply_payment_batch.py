import pytest
from rest_framework.test import APIClient
from tests.test_supply_payment_request_evidence import _grant, _setup_request, write, _png
from tests.test_supply_payment_request_evidence import world
from tests.test_supply_chain_v2_foundation import confirmed_order,po_payload,shipment_payload
from apps.supply_chain import services
from tests.test_supply_chain_v2_foundation import internal_user
from apps.permissions.models import DataScope
from apps.supply_chain.models import PaymentItem,DispatchBatch,InboundOrder,domain_write
from tests.test_supply_chain_v2_costs import received_pilot,get,fee_body

pytestmark=pytest.mark.django_db

def _second_shipment(world,buyer,suffix):
    order=confirmed_order(world,buyer,key=f'{suffix}-order',payload=po_payload(world,key=f'{suffix}-order',number=f'PO-{suffix}',lines=[{'sku_id':world['sku'].pk,'quantity':3,'unit_price':'2.5'}]))
    return services.create_supplier_shipment(buyer,shipment_payload(world,order,suffix,number=f'SH-{suffix}',lines=[{'sku_id':world['sku'].pk,'quantity':2}]),idempotency_key=suffix)

def test_batch_has_one_approval_and_child_single_actions_are_blocked(world,monkeypatch):
    buyer,api,shipment,account,_row,approver,reviewer_api=_setup_request(world,monkeypatch)
    shipment2=_second_shipment(world,buyer,'batch-second')
    lines=[{'kind':'shipment','source_id':shipment.pk,'amount':'0.25'}, {'kind':'shipment','source_id':shipment2.pk,'amount':'0.25'}]
    result=write(api,'payment-batches/',{'payee_account_id':account['id'],'reason':'合并付款','lines':lines},'batch-create')
    assert result.status_code==201,result.data
    batch=result.data['data']; assert len(batch['lines'])==2 and batch['approval_id'] is None
    submitted=write(api,f'payment-batches/{batch["id"]}/submit/',{'expected_version':batch['version']},'batch-submit')
    assert submitted.status_code==200,submitted.data
    batch=submitted.data['data']; assert batch['approval_id']
    approval=reviewer_api.post(f'/api/internal/workflow/approvals/{batch["approval_id"]}/approve/',{'note':'通过'},format='json')
    assert approval.status_code==200,approval.data
    detail=api.get(f'/api/internal/supply-chain/v2/payment-batches/{batch["id"]}/')
    assert detail.status_code==200,detail.data
    child=detail.data['data']['lines'][0]
    bypass=write(api,f'costs/shipment/{shipment.pk}/payment-requests/{child["id"]}/cancel/',{'expected_version':1,'reason':'绕过批次'},'batch-child-bypass')
    assert bypass.status_code==400,bypass.data

def test_batch_confirmation_posts_all_lines_and_reversal_is_grouped(world,monkeypatch):
    from apps.supply_chain.cost_models import PaymentRecord
    from apps.supply_chain import costs
    buyer,api,shipment,account,_row,approver,reviewer_api=_setup_request(world,monkeypatch)
    shipment2=_second_shipment(world,buyer,'batch2')
    result=write(api,'payment-batches/',{'payee_account_id':account['id'],'reason':'合并付款','lines':[{'kind':'shipment','source_id':shipment.pk,'amount':'0.25'},{'kind':'shipment','source_id':shipment2.pk,'amount':'0.25'}]},'batch2-create')
    batch=result.data['data']
    submitted=write(api,f'payment-batches/{batch["id"]}/submit/',{'expected_version':batch['version']},'batch2-submit').data['data']
    reviewer_api.post(f'/api/internal/workflow/approvals/{submitted["approval_id"]}/approve/',{'note':'通过'},format='json')
    uploaded=api.post(f'/api/internal/supply-chain/v2/payment-batches/{batch["id"]}/vouchers/',{'expected_version':str(submitted['version']),'file':_png()},format='multipart',HTTP_IDEMPOTENCY_KEY='batch2-file')
    assert uploaded.status_code==201,uploaded.data
    confirmed=api.post(f'/api/internal/supply-chain/v2/payment-batches/{batch["id"]}/confirm/',{'expected_version':uploaded.data['data']['version'],'date':'2026-10-14','reference_number':'BATCH-REF','notes':'转账完成'},format='json',HTTP_IDEMPOTENCY_KEY='batch2-confirm')
    assert confirmed.status_code==200,confirmed.data
    result=confirmed.data['data']; assert result['status']=='paid' and len([x for x in result['lines'] if x['payment_id']])==2
    from apps.supply_chain.payment_voucher_models import PaymentVoucher
    payments=list(PaymentRecord.objects.filter(pk__in=[x['payment_id'] for x in result['lines']]))
    assert PaymentRecord.objects.count()==2
    assert PaymentVoucher.objects.filter(payment_id__in=[p.pk for p in payments]).count()==2
    replay=api.post(f'/api/internal/supply-chain/v2/payment-batches/{batch["id"]}/confirm/',{'expected_version':uploaded.data['data']['version'],'date':'2026-10-14','reference_number':'BATCH-REF','notes':'转账完成'},format='json',HTTP_IDEMPOTENCY_KEY='batch2-confirm')
    assert replay.status_code==200,replay.data
    assert PaymentRecord.objects.count()==2 and PaymentVoucher.objects.filter(payment_id__in=[p.pk for p in payments]).count()==2
    direct=api.post(f'/api/internal/supply-chain/v2/costs/shipment/{shipment.pk}/payments/{payments[0].pk}/reverse/',{'reason':'single bypass','expected_version':costs.payment_summary(buyer,'shipment',shipment.pk)['version']},format='json',HTTP_IDEMPOTENCY_KEY='batch-child-reverse')
    assert direct.status_code==422,direct.data
    reversed=api.post(f'/api/internal/supply-chain/v2/payment-batches/{batch["id"]}/reverse/',{'expected_version':result['version'],'reason':'整批冲销'},format='json',HTTP_IDEMPOTENCY_KEY='batch2-reverse')
    assert reversed.status_code==200,reversed.data
    assert all(PaymentRecord.objects.get(pk=p.pk).reversal.exists() for p in payments)

def test_competing_batches_cannot_overreserve_and_duplicate_source_is_rejected(world,monkeypatch):
    buyer,api,shipment,account,_row,_approver,_reviewer_api=_setup_request(world,monkeypatch)
    shipment2=_second_shipment(world,buyer,'reserve-race')
    lines=[{'kind':'shipment','source_id':shipment.pk,'amount':'3.0000'},{'kind':'shipment','source_id':shipment2.pk,'amount':'3.0000'}]
    duplicate=write(api,'payment-batches/',{'payee_account_id':account['id'],'reason':'重复来源','lines':[lines[0],lines[0]]},'duplicate-source')
    assert duplicate.status_code==400,duplicate.data
    first=write(api,'payment-batches/',{'payee_account_id':account['id'],'reason':'批次一','lines':lines},'reserve-first').data['data']
    second=write(api,'payment-batches/',{'payee_account_id':account['id'],'reason':'批次二','lines':lines},'reserve-second').data['data']
    submit1=write(api,f'payment-batches/{first["id"]}/submit/',{'expected_version':first['version']},'reserve-first-submit')
    assert submit1.status_code==200,submit1.data
    submit2=write(api,f'payment-batches/{second["id"]}/submit/',{'expected_version':second['version']},'reserve-second-submit')
    assert submit2.status_code==400,submit2.data

def test_batch_visibility_requires_source_access_for_list_detail_and_approval(world,monkeypatch):
    buyer,api,shipment,account,_row,_approver,_reviewer_api=_setup_request(world,monkeypatch)
    shipment2=_second_shipment(world,buyer,'restricted-batch')
    created=write(api,'payment-batches/',{'payee_account_id':account['id'],'reason':'受限来源','lines':[{'kind':'shipment','source_id':shipment.pk,'amount':'0.25'},{'kind':'shipment','source_id':shipment2.pk,'amount':'0.25'}]},'restricted-batch-create').data['data']
    submitted=write(api,f'payment-batches/{created["id"]}/submit/',{'expected_version':created['version']},'restricted-batch-submit').data['data']
    restricted=internal_user(world,'batch-scope-denied',scope=DataScope.ScopeType.CUSTOM,config={'approval_types':['finance'],'supplier_ids':[world['supplier_b'].pk]},codes=('supply.v2.view',))
    _grant(restricted,'workflow.approvals.view','workflow.approvals.review')
    client=APIClient(); client.force_authenticate(user=restricted)
    listing=client.get('/api/internal/supply-chain/v2/payment-batches/?party_kind=supplier&party_id='+str(world['supplier'].pk))
    assert listing.status_code==200 and created['id'] not in [x['id'] for x in listing.data['data']]
    assert client.get(f'/api/internal/supply-chain/v2/payment-batches/{created["id"]}/').status_code==404
    assert client.get(f'/api/internal/workflow/approvals/{submitted["approval_id"]}/').status_code==404
    assert client.post(f'/api/internal/workflow/approvals/{submitted["approval_id"]}/approve/',{'note':'must not see'},format='json').status_code==404
    approvals=client.get('/api/internal/workflow/approvals/?page_size=100')
    assert approvals.status_code==200
    assert submitted['approval_id'] not in [x['id'] for x in approvals.data['data']['results']]

def test_second_payment_failure_rolls_back_entire_batch(world,monkeypatch):
    from apps.supply_chain.cost_models import PaymentRecord
    from apps.supply_chain import costs
    buyer,api,shipment,account,_row,_approver,reviewer_api=_setup_request(world,monkeypatch)
    shipment2=_second_shipment(world,buyer,'batch-rollback')
    created=write(api,'payment-batches/',{'payee_account_id':account['id'],'reason':'故障回滚','lines':[{'kind':'shipment','source_id':shipment.pk,'amount':'0.25'},{'kind':'shipment','source_id':shipment2.pk,'amount':'0.25'}]},'batch-rollback-create').data['data']
    submitted=write(api,f'payment-batches/{created["id"]}/submit/',{'expected_version':created['version']},'batch-rollback-submit').data['data']
    reviewer_api.post(f'/api/internal/workflow/approvals/{submitted["approval_id"]}/approve/',{'note':'通过'},format='json')
    uploaded=api.post(f'/api/internal/supply-chain/v2/payment-batches/{created["id"]}/vouchers/',{'expected_version':str(submitted['version']),'file':_png()},format='multipart',HTTP_IDEMPOTENCY_KEY='batch-rollback-voucher')
    assert uploaded.status_code==201,uploaded.data
    replay_upload=api.post(f'/api/internal/supply-chain/v2/payment-batches/{created["id"]}/vouchers/',{'expected_version':str(uploaded.data['data']['version']),'file':_png()},format='multipart',HTTP_IDEMPOTENCY_KEY='batch-rollback-voucher')
    assert replay_upload.status_code==200,replay_upload.data
    assert len(replay_upload.data['data']['vouchers'])==1
    stale=api.post(f'/api/internal/supply-chain/v2/payment-batches/{created["id"]}/vouchers/',{'expected_version':str(submitted['version']),'file':_png()},format='multipart',HTTP_IDEMPOTENCY_KEY='batch-stale-voucher')
    assert stale.status_code==409,stale.data
    original=costs.create_payment; calls={'n':0}
    def fail_second(*args,**kwargs):
        calls['n']+=1
        if calls['n']==2: raise RuntimeError('injected second line failure')
        return original(*args,**kwargs)
    monkeypatch.setattr(costs,'create_payment',fail_second)
    with pytest.raises(RuntimeError):
        api.post(f'/api/internal/supply-chain/v2/payment-batches/{created["id"]}/confirm/',{'expected_version':uploaded.data['data']['version'],'date':'2026-10-14','reference_number':'ROLLBACK','notes':''},format='json',HTTP_IDEMPOTENCY_KEY='batch-rollback-confirm')
    assert PaymentRecord.objects.count()==0

def test_freight_batch_and_inbound_fee_items_candidates_nature_and_history(world,monkeypatch):
    buyer,api,_shipment,batch_id,inbound_id=received_pilot(world)
    _grant(buyer,'workflow.approvals.submit','finance.reconcile')
    batch=DispatchBatch.objects.get(pk=batch_id); inbound=InboundOrder.objects.get(pk=inbound_id)
    carrier=batch.freight_company
    with domain_write():
        corp=PaymentItem.objects.create(tenant=world['tenant'],created_by=buyer,name='批量公司费',party_type='carrier',default_nature='corporate',counts_as_cost=True)
        personal=PaymentItem.objects.create(tenant=world['tenant'],created_by=buyer,name='批量个人费',party_type='carrier',default_nature='personal',counts_as_cost=True)
    ctx=get(api,'batch',batch)
    body=fee_body(ctx,'30.0000',item_breakdown=[{'fee_item_id':corp.pk,'amount':'20.0000','nature':'corporate'},{'fee_item_id':personal.pk,'amount':'10.0000','nature':'personal'}])
    saved=write(api,f'costs/batch/{batch.pk}/fee/',body,'batch-group-items','put')
    assert saved.status_code==200,saved.data
    ctx=get(api,'inbound',inbound)
    body=fee_body(ctx,'7.0000',item_breakdown=[{'fee_item_id':corp.pk,'amount':'4.0000','nature':'corporate'},{'fee_item_id':personal.pk,'amount':'3.0000','nature':'personal'}])
    saved=write(api,f'costs/inbound/{inbound.pk}/fee/',body,'inbound-group-items','put')
    assert saved.status_code==200,saved.data
    account_path=f'costs/freight_company/{carrier.pk}/payee-accounts/'
    corp_account=write(api,account_path,{'nature':'corporate','account_name':'承运公司账户','account_holder':'承运公司','bank_name':'银行','account_number':'655544332211','active':True},'batch-carrier-corp').data['data']['account']
    personal_account=write(api,account_path,{'nature':'personal','account_name':'承运人账户','account_holder':'承运人','bank_name':'银行','account_number':'655544332212','active':True},'batch-carrier-personal').data['data']['account']
    base=f'/api/internal/supply-chain/v2/payment-batches/candidates/?party_kind=freight_company&party_id={carrier.pk}'
    candidates=api.get(base)
    assert candidates.status_code==200,candidates.data
    data=candidates.data['data']
    assert {row['kind'] for row in data}=={'batch','inbound'}
    assert {(row['kind'],row.get('fee_item_id')) for row in data}=={('batch',corp.pk),('batch',personal.pk),('inbound',corp.pk),('inbound',personal.pk)}
    assert len(candidates.data['accounts'])>=2
    searched=api.get(base+'&search='+inbound.number)
    assert searched.status_code==200 and {row['kind'] for row in searched.data['data']}=={'inbound'}
    page0=api.get(base+'&limit=1&offset=0'); page1=api.get(base+'&limit=1&offset=1')
    assert page0.status_code==page1.status_code==200
    assert page0.data['data'] and page1.data['data']
    mixed=write(api,'payment-batches/',{'payee_account_id':corp_account['id'],'reason':'不同性质混付','lines':[{'kind':'batch','source_id':batch.pk,'amount':'1.0000','fee_item_id':corp.pk},{'kind':'inbound','source_id':inbound.pk,'amount':'1.0000','fee_item_id':personal.pk}]},'mixed-nature-batch')
    assert mixed.status_code==400,mixed.data
    created=write(api,'payment-batches/',{'payee_account_id':corp_account['id'],'reason':'同性质合并','lines':[{'kind':'batch','source_id':batch.pk,'amount':'1.0000','fee_item_id':corp.pk},{'kind':'inbound','source_id':inbound.pk,'amount':'1.0000','fee_item_id':corp.pk}]},'same-nature-batch')
    assert created.status_code==201,created.data
    submitted=write(api,f'payment-batches/{created.data["data"]["id"]}/submit/',{'expected_version':created.data['data']['version']},'same-nature-submit')
    assert submitted.status_code==200,submitted.data
    history=api.get(f'/api/internal/supply-chain/v2/payment-batches/?party_kind=freight_company&party_id={carrier.pk}')
    assert history.status_code==200 and created.data['data']['id'] in [x['id'] for x in history.data['data']]
    detail=api.get(f'/api/internal/supply-chain/v2/payment-batches/{created.data["data"]["id"]}/')
    assert detail.status_code==200 and detail.data['data']['status']=='pending'


@pytest.mark.parametrize('requested_a,requested_b', [('20.0000', '10.0000'), ('15.0000', '5.0000')])
def test_same_source_multi_fee_batch_confirmation_excludes_its_own_reservations(world, monkeypatch, requested_a, requested_b):
    from apps.supply_chain import costs
    buyer, api, _shipment, batch_id, _inbound_id = received_pilot(world)
    _grant(buyer, 'workflow.approvals.submit', 'finance.reconcile')
    source = DispatchBatch.objects.get(pk=batch_id)
    with domain_write():
        item_a = PaymentItem.objects.create(tenant=world['tenant'], created_by=buyer, name='预占公司费',
            party_type='carrier', default_nature='corporate', counts_as_cost=True)
        item_b = PaymentItem.objects.create(tenant=world['tenant'], created_by=buyer, name='预占第二公司费',
            party_type='carrier', default_nature='corporate', counts_as_cost=True)
    saved = write(api, f'costs/batch/{source.pk}/fee/', fee_body(get(api, 'batch', source), '30.0000',
        item_breakdown=[{'fee_item_id': item_a.pk, 'amount': '20.0000', 'nature': 'corporate'},
                        {'fee_item_id': item_b.pk, 'amount': '10.0000', 'nature': 'corporate'}]),
        'same-source-reservation-fee', 'put')
    assert saved.status_code == 200, saved.data
    accounts = {}
    for item, nature, number in ((item_a, 'corporate', '655544332221'), (item_b, 'corporate', '655544332222')):
        accounts[item.pk] = write(api, f'costs/freight_company/{source.freight_company_id}/payee-accounts/', {
            'nature': nature, 'account_name': '批次收款户', 'account_holder': '承运人', 'bank_name': '银行',
            'account_number': number, 'active': True}, f'same-source-account-{item.pk}').data['data']['account']
    created = write(api, 'payment-batches/', {'reason': '同来源分项批次', 'payee_account_id': accounts[item_a.pk]['id'],
        'lines': [{'kind': 'batch', 'source_id': source.pk, 'amount': requested_a, 'fee_item_id': item_a.pk},
                  {'kind': 'batch', 'source_id': source.pk, 'amount': requested_b, 'fee_item_id': item_b.pk}]},
        'same-source-reservation-batch')
    assert created.status_code == 201, created.data
    batch = created.data['data']
    submitted = write(api, f'payment-batches/{batch["id"]}/submit/', {'expected_version': batch['version']},
        'same-source-reservation-submit').data['data']
    state = costs.payment_summary(buyer, 'batch', source.pk)
    direct = {'amount': '6.0000', 'date': '2026-10-14', 'payee_account_id': accounts[item_a.pk]['id'],
              'fee_item_id': item_a.pk, 'expected_version': state['version']}
    # In the partial case the source has 10 available, but this item has only 5.
    blocked = write(api, f'costs/batch/{source.pk}/payments/', {
        **direct, 'verified_batch': batch['id'], 'verified_request': batch['lines'][0]['id']},
        f'payment-request-{batch["lines"][0]["id"]}')
    assert blocked.status_code == 422, blocked.data
    assert '费用项目' in str(blocked.data)
    assert costs.payment_summary(buyer, 'batch', source.pk)['summary']['paid_amount'] == state['summary']['paid_amount']
    if requested_a == '15.0000':
        allowed = write(api, f'costs/batch/{source.pk}/payments/', {**direct, 'amount': '5.0000'},
            'same-source-unreserved-payment')
        assert allowed.status_code == 201, allowed.data
    approver = internal_user(world, 'same-source-reservation-approver', codes=('supply.v2.view', 'supply.v2.manage'))
    _grant(approver, 'workflow.approvals.review', 'workflow.approvals.view', 'finance.reconcile')
    reviewer = APIClient(); reviewer.force_authenticate(user=approver)
    assert reviewer.post(f'/api/internal/workflow/approvals/{submitted["approval_id"]}/approve/',
        {'note': '通过'}, format='json').status_code == 200
    uploaded = api.post(f'/api/internal/supply-chain/v2/payment-batches/{batch["id"]}/vouchers/',
        {'expected_version': str(submitted['version']), 'file': _png()}, format='multipart',
        HTTP_IDEMPOTENCY_KEY='same-source-reservation-voucher')
    assert uploaded.status_code == 201, uploaded.data
    confirmed = api.post(f'/api/internal/supply-chain/v2/payment-batches/{batch["id"]}/confirm/', {
        'expected_version': uploaded.data['data']['version'], 'date': '2026-10-14',
        'reference_number': 'SAME-SOURCE', 'notes': ''}, format='json',
        HTTP_IDEMPOTENCY_KEY='same-source-reservation-confirm')
    assert confirmed.status_code == 200, confirmed.data
    assert all(line['payment_id'] for line in confirmed.data['data']['lines'])


@pytest.mark.parametrize('approval_status', ['pending', 'approved', 'rejected', 'withdrawn'])
def test_source_history_uses_batch_approval_status_without_child_approval(world, monkeypatch, approval_status):
    from apps.supply_chain.payment_request_models import SupplyPaymentRequest
    from apps.workflows.models import ApprovalRequest
    buyer, api, shipment, account, _, _, _ = _setup_request(world, monkeypatch)
    shipment2 = _second_shipment(world, buyer, 'batch-status')
    created = write(api, 'payment-batches/', {
        'payee_account_id': account['id'], 'reason': '状态追溯',
        'lines': [{'kind': 'shipment', 'source_id': shipment.pk, 'amount': '0.25'},
                  {'kind': 'shipment', 'source_id': shipment2.pk, 'amount': '0.25'}],
    }, 'batch-status-create')
    assert created.status_code == 201, created.data
    batch = created.data['data']
    submitted = write(api, f'payment-batches/{batch["id"]}/submit/', {'expected_version': batch['version']}, 'batch-status-submit')
    assert submitted.status_code == 200, submitted.data
    ApprovalRequest.objects.filter(pk=submitted.data['data']['approval_id']).update(status=approval_status)
    child = SupplyPaymentRequest.objects.get(batch_id=batch['id'], source_id=shipment.pk)
    assert child.approval_id is None and child.status == 'submitted'
    response = api.get(f'/api/internal/supply-chain/v2/costs/shipment/{shipment.pk}/payment-requests/')
    assert response.status_code == 200, response.data
    rendered = next(row for row in response.data['data'] if row['id'] == child.pk)
    assert rendered['status'] == approval_status
    assert rendered['batch_id'] == batch['id']
    assert all(rendered['can_' + action] is False for action in ['submit', 'cancel', 'upload', 'notify', 'confirm'])


@pytest.mark.parametrize('resolution', ['rejected', 'withdrawn'])
def test_batch_rejection_or_withdrawal_releases_prepayment_reservation(world, monkeypatch, resolution):
    from apps.supply_chain import costs
    from apps.supply_chain.models import PaymentApplication
    from apps.supply_chain.payment_request_models import SupplyPaymentRequest

    buyer, api, shipment, account, _row, _approver, reviewer_api = _setup_request(world, monkeypatch)
    shipment2 = _second_shipment(world, buyer, f'deposit-batch-{resolution}')
    reserved_amount = costs.payment_summary(buyer, 'shipment', shipment.pk)['summary']['remaining_amount']
    created = write(api, 'payment-batches/', {
        'payee_account_id': account['id'], 'reason': '释放抵扣预占',
        'lines': [{'kind': 'shipment', 'source_id': shipment.pk, 'amount': reserved_amount},
                  {'kind': 'shipment', 'source_id': shipment2.pk, 'amount': '0.2500'}],
    }, f'deposit-batch-{resolution}-create')
    assert created.status_code == 201, created.data
    submitted = write(api, f'payment-batches/{created.data["data"]["id"]}/submit/', {
        'expected_version': created.data['data']['version'],
    }, f'deposit-batch-{resolution}-submit')
    assert submitted.status_code == 200, submitted.data
    batch = submitted.data['data']

    order_account = write(api, f'costs/purchase/{shipment.order_id}/payee-accounts/', {
        'nature': 'corporate', 'account_name': f'{resolution}定金账户', 'account_holder': '供应商',
        'bank_name': '测试银行', 'account_number': '6222000000005555', 'active': True,
    }, f'deposit-batch-{resolution}-account')
    assert order_account.status_code == 201, order_account.data
    deposit = write(api, f'costs/purchase/{shipment.order_id}/payments/', {
        'amount': '1.0000', 'payee_account_id': order_account.data['data']['account']['id'],
        'date': '2026-10-14', 'expected_version': 0,
    }, f'deposit-batch-{resolution}-payment')
    assert deposit.status_code == 201, deposit.data
    payment_id = deposit.data['data']['entries'][0]['id']
    state = costs.payment_summary(buyer, 'shipment', shipment.pk)

    blocked = api.post(f'/api/internal/supply-chain/v2/costs/shipment/{shipment.pk}/prepayment-applications/', {
        'payment_id': payment_id, 'amount': '1.0000', 'date': '2026-10-14',
        'expected_version': state['version'],
    }, format='json', HTTP_IDEMPOTENCY_KEY=f'deposit-batch-{resolution}-blocked-apply')
    assert blocked.status_code == 422, blocked.data
    assert PaymentApplication.objects.filter(shipment=shipment).count() == 0

    if resolution == 'rejected':
        result = reviewer_api.post(
            f'/api/internal/workflow/approvals/{batch["approval_id"]}/reject/',
            {'note': '拒绝释放预占'}, format='json')
    else:
        _grant(buyer, 'workflow.approvals.withdraw')
        result = api.post(
            f'/api/internal/workflow/approvals/{batch["approval_id"]}/withdraw/',
            {}, format='json')
    assert result.status_code == 200, result.data
    child = SupplyPaymentRequest.objects.get(batch_id=batch['id'], source_id=shipment.pk)
    assert child.status == 'submitted'
    state = costs.payment_summary(buyer, 'shipment', shipment.pk)

    applied = api.post(f'/api/internal/supply-chain/v2/costs/shipment/{shipment.pk}/prepayment-applications/', {
        'payment_id': payment_id, 'amount': '1.0000', 'date': '2026-10-14',
        'expected_version': state['version'],
    }, format='json', HTTP_IDEMPOTENCY_KEY=f'deposit-batch-{resolution}-apply')
    assert applied.status_code == 201, applied.data
    assert PaymentApplication.objects.filter(shipment=shipment).count() == 1
