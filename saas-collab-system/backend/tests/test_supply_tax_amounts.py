from decimal import Decimal
import pytest
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_payments import itemized_batch
from tests.test_supply_chain_v2_costs import get, fee_body, calculate
from tests.test_supply_chain_v2_logistics import write
from apps.supply_chain.models import domain_write

@pytest.mark.django_db
def test_inclusive_ocean_tax_default_override_snapshot_and_cost_total(world):
    buyer, api, batch, carrier, profiles = itemized_batch(world)
    with domain_write():
        profiles[0].default_tax_rate=Decimal('6'); profiles[0].save()
    context=get(api,'batch',batch)
    body=fee_body(context,'156',item_breakdown=[{'fee_item_id':profiles[0].pk,'amount':'106','nature':'corporate'}, {'fee_item_id':profiles[1].pk,'amount':'50','nature':'personal'}])
    saved=write(api,f'costs/batch/{batch.pk}/fee/',body,'tax-fee','put')
    assert saved.status_code==200,saved.data
    fee=saved.data['data']['fee']; public,private=fee['item_breakdown']
    assert Decimal(public['tax_amount'])==6 and Decimal(public['net_amount'])==100
    assert Decimal(private['tax_amount'])==0
    assert Decimal(fee['amount'])==156
    assert sum(Decimal(x['amount']) for x in fee['allocations'])==156
    cost,_=calculate(api,'batch',batch)
    assert sum(Decimal(x['freight_fee']) for x in cost['entries'])==156
    with domain_write():
        profiles[0].default_tax_rate=Decimal('13');profiles[0].save()
    assert Decimal(get(api,'batch',batch)['fee']['item_breakdown'][0]['tax_rate'])==6
    body=fee_body(get(api,'batch',batch),'156',item_breakdown=[{**public,'tax_rate':'13'},private])
    changed=write(api,f'costs/batch/{batch.pk}/fee/',body,'tax-override','put')
    assert changed.status_code==200,changed.data
    assert Decimal(changed.data['data']['fee']['item_breakdown'][0]['tax_amount'])==Decimal('12.19')
    assert Decimal(changed.data['data']['fee']['amount'])==156
    assert Decimal(changed.data['data']['fee_history'][-1]['amount'])==156

@pytest.mark.django_db
@pytest.mark.parametrize('rate',['-1','101','6.1234','NaN','bad',None])
def test_invalid_or_unconfirmed_corporate_rate_rejected(world,rate):
    buyer,api,batch,carrier,profiles=itemized_batch(world)
    body=fee_body(get(api,'batch',batch),'106',item_breakdown=[{'fee_item_id':profiles[0].pk,'amount':'106','nature':'corporate','tax_rate':rate}])
    result=write(api,f'costs/batch/{batch.pk}/fee/',body,'invalid-tax','put')
    assert result.status_code in (400,422),result.data
