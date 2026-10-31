import pytest
from tests.test_supply_chain_v2_costs import pilot
from tests.test_supply_chain_v2_foundation import world


@pytest.mark.django_db
def test_payment_request_create_list_and_idempotent_payload(world, monkeypatch):
    from apps.supply_chain import costs
    from tests.test_supply_chain_v2_logistics import write
    buyer, api, shipment = pilot(world)
    account = write(api, f'costs/shipment/{shipment.pk}/payee-accounts/', {
        'nature':'corporate','account_name':'测试户','account_holder':'供应商','bank_name':'测试银行',
        'account_number':'6222000000001111','active':True}, 'request-account').data['data']['account']
    endpoint=f'costs/shipment/{shipment.pk}/payment-requests/'
    payload={'amount':'1.0000','payee_account_id':account['id'],'reason':'测试付款申请'}
    first=write(api,endpoint,payload,'payment-request-create')
    assert first.status_code==201, first.data
    replay=write(api,endpoint,payload,'payment-request-create')
    assert replay.status_code==200 and replay.data['data']['id']==first.data['data']['id']
    def should_not_recheck(*args, **kwargs):
        raise AssertionError('idempotent replay must not revalidate mutable balance')
    monkeypatch.setattr(costs, 'payment_summary', should_not_recheck)
    replay_after_balance_change=write(api,endpoint,payload,'payment-request-create')
    assert replay_after_balance_change.status_code==200
    listed=api.get('/api/internal/supply-chain/v2/'+endpoint)
    assert listed.status_code==200 and listed.data['count']==1
    assert listed.data['data'][0]['account_snapshot']['account_number'].endswith('1111')
    assert '*' in listed.data['data'][0]['account_snapshot']['account_number']
