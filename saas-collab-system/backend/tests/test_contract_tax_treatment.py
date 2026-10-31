from decimal import Decimal
import pytest
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_purchase_contracts import submitted_shipment
from tests.test_supply_chain_v2_numbering import config
from tests.test_supply_chain_v2_costs import calculate
from apps.supply_chain import costs, dashboard
from apps.supply_chain.models import SupplierShipment
BASE='/api/internal/supply-chain/v2/'

@pytest.mark.parametrize('treatment,cost_tax',[('refund',Decimal('0')),('exempt',Decimal('0.60'))])
def test_contract_tax_adds_payable_with_selected_cost_treatment(submitted_shipment,world,treatment,cost_tax):
    user,api,data=submitted_shipment
    shipment=SupplierShipment.objects.get(pk=data['id'])
    base=BASE+f'supplier-shipments/{shipment.pk}/purchase-contract/'
    source=api.get(base).data['data']['defaults']
    source.update(tax_treatment=treatment,contract_date='2026-10-30')
    source['buyer']['name']='buyer'
    source['lines'][0]['tax_rate']='6'
    before=costs.payment_summary(user,'shipment',shipment.pk)['summary']
    saved=api.put(base,{'expected_version':0,'expected_source_version':shipment.version,'nature':'corporate','payload':source},format='json')
    assert saved.status_code==200,saved.data
    assert costs.payment_summary(user,'shipment',shipment.pk)['summary']['due_amount']==before['due_amount']
    config(world,user,kind='corporate_contract',prefix='CC')
    body={'expected_version':saved.data['data']['contract']['version'],'expected_source_version':shipment.version,'confirmed':True}
    issued=api.post(base+'issue/',body,format='json')
    assert issued.status_code==200,issued.data
    api.post(base+'issue/',body,format='json')
    summary=costs.payment_summary(user,'shipment',shipment.pk)['summary']
    assert Decimal(summary['due_amount'])==Decimal(before['due_amount'])+Decimal('.60')
    assert Decimal(summary['contract_tax_amount'])==Decimal('.60')
    assert Decimal(summary['contract_cost_tax_amount'])==cost_tax
    query=dashboard._money_targets('supplier',dashboard.scope(user))
    assert query.get(pk=shipment.pk).due==Decimal(summary['due_amount'])
    costs.prepare_target_financials('shipment',[shipment])
    assert Decimal(shipment._payment_projection['due_amount'])==Decimal(summary['due_amount'])
    result,_=calculate(api,'shipment',shipment)
    assert sum(Decimal(x['goods_tax_amount']) for x in result['entries'])==cost_tax
    assert sum(Decimal(x['goods_amount']) for x in result['entries'])==Decimal(before['due_amount'])+cost_tax
    assert shipment.lines.get().unit_price==Decimal('2.5')


def test_new_corporate_contract_requires_treatment(submitted_shipment):
    user,api,data=submitted_shipment
    base=BASE+f"supplier-shipments/{data['id']}/purchase-contract/"
    source=api.get(base).data['data']['defaults'];source['lines'][0]['tax_rate']='6'
    saved=api.put(base,{'expected_version':0,'expected_source_version':data['version'],'nature':'corporate','payload':source},format='json')
    assert saved.status_code==400


@pytest.mark.parametrize('mutation', ['missing','outside','duplicate','quantity','price'])
def test_net_contract_issue_requires_exact_shipment_line_snapshot(submitted_shipment, mutation):
    from apps.supply_chain.models import PurchaseContract, domain_write
    user,api,data=submitted_shipment
    shipment=SupplierShipment.objects.get(pk=data['id'])
    base=BASE+f'supplier-shipments/{shipment.pk}/purchase-contract/'
    payload=api.get(base).data['data']['defaults']
    payload.update(tax_treatment='exempt', contract_date='2026-10-30')
    payload['buyer']['name']='buyer'
    payload['lines'][0]['tax_rate']='6'
    saved=api.put(base,{'expected_version':0,'expected_source_version':shipment.version,'nature':'corporate','payload':payload},format='json')
    assert saved.status_code==200,saved.data
    contract=PurchaseContract.objects.get(shipment=shipment)
    with domain_write():
        rows=contract.payload['lines']
        if mutation=='missing': rows[0]['source_line_id']=None
        elif mutation=='outside': rows[0]['source_line_id']=999999
        elif mutation=='duplicate': rows.append(dict(rows[0]))
        elif mutation=='quantity': rows[0]['quantity']=str(Decimal(rows[0]['quantity'])+1)
        elif mutation=='price': rows[0]['unit_price']=str(Decimal(rows[0]['unit_price'])+1)
        contract.save(update_fields=['payload'])
    response=api.post(base+'issue/',{'expected_version':contract.version,'expected_source_version':shipment.version,'confirmed':True},format='json')
    assert response.status_code==400,response.data
    contract.refresh_from_db()
    assert contract.status=='draft' and not contract.number


def test_exempt_tax_split_batches_conserve_total(world):
    from tests.test_supply_chain_v2_split_dispatch import setup,create_part
    from apps.supply_chain.models import PurchaseContract,domain_write
    from tests.test_supply_chain_v2_logistics import arrive
    buyer,api,shipment,carrier=setup(world)
    with domain_write():
        source=shipment.lines.get(is_active=True)
        PurchaseContract.objects.create(tenant=world['tenant'],created_by=buyer,shipment=shipment,nature='corporate',status='issued',number='EXEMPT',source_version=shipment.version,payload={'tax_treatment':'exempt','pricing_basis':'net_plus_tax','lines':[{'source_line_id':source.pk,'tax_amount':'0.01'}]},settlement_tax_amount=Decimal('.01'),cost_tax_amount=Decimal('.01'))
    first=create_part(api,shipment,carrier,60,'tax-first').data['data']
    second=create_part(api,shipment,carrier,40,'tax-second').data['data']
    result=[]
    for batch in (first,second):
        batch=arrive(api,batch)
        calculated,_=calculate(api,'batch',batch['id'])
        result.extend(calculated['entries'])
    assert sum(Decimal(x['goods_tax_amount']) for x in result)==Decimal('.01')
    assert sum(Decimal(x['goods_amount']) for x in result)==Decimal('250.01')


def test_exempt_tax_allocation_preserves_two_sku_rates(submitted_shipment, world):
    from apps.supply_chain.models import PurchaseContract, ShipmentLine, domain_write
    from apps.supply_chain.tax_calculation import contract_cost_allocations
    user,api,data=submitted_shipment
    shipment=SupplierShipment.objects.get(pk=data['id'])
    with domain_write():
        first=shipment.lines.get(is_active=True)
        second=ShipmentLine.objects.create(tenant=world['tenant'],created_by=user,shipment=shipment,
            line_number=first.line_number+1,sku=world['sku_b'],sku_code_snapshot=world['sku_b'].sku_code,
            product_name_snapshot='Second SKU',quantity=2,unit_price=Decimal('50.0000'))
        PurchaseContract.objects.create(tenant=world['tenant'],created_by=user,shipment=shipment,
            nature='corporate',status='issued',number='TWO-SKU',source_version=shipment.version,
            payload={'tax_treatment':'exempt','pricing_basis':'net_plus_tax','lines':[
                {'source_line_id':first.pk,'tax_rate':'6.000','tax_amount':'0.01'},
                {'source_line_id':second.pk,'tax_rate':'13.000','tax_amount':'0.02'}]},
            settlement_tax_amount=Decimal('.03'),cost_tax_amount=Decimal('.03'))
    allocation=contract_cost_allocations([shipment.pk])[0]
    assert [(row['shipment_line_id'],row['amount']) for row in allocation['allocations']]==[
        (first.pk,'0.01'),(second.pk,'0.02')]
    assert sum(Decimal(row['amount']) for row in allocation['allocations'])==Decimal('.03')

def test_supplier_default_override_and_legacy_contract_preservation(submitted_shipment,world):
    from apps.supply_chain.models import PurchaseContract,domain_write
    from copy import deepcopy
    user,api,data=submitted_shipment
    shipment=SupplierShipment.objects.select_related('order__supplier').get(pk=data['id'])
    supplier=shipment.order.supplier;supplier.default_tax_rate=Decimal('6');supplier.save()
    base=BASE+f'supplier-shipments/{shipment.pk}/purchase-contract/'
    source=api.get(base).data['data']['defaults'];assert Decimal(source['lines'][0]['tax_rate'])==6
    legacy=deepcopy(source);legacy.pop('pricing_basis');legacy.pop('tax_treatment');legacy['buyer']['name']='buyer';legacy['contract_date']='2026-10-30'
    legacy['lines'][0].update(unit_price='26.5000',tax_rate='6.000',line_total='106.00',net_total='100.00',tax_amount='6.00')
    with domain_write():
        old=PurchaseContract.objects.create(tenant=user.tenant,created_by=user,shipment=shipment,nature='corporate',payload=legacy,source_version=shipment.version)
    body={'expected_version':old.version,'expected_source_version':shipment.version,'nature':'corporate','payload':legacy}
    assert api.put(base,body,format='json').status_code==400
    assert api.post(base+'issue/',{'expected_version':old.version,'expected_source_version':shipment.version,'confirmed':True},format='json').status_code==400
    legacy['pricing_basis']='gross_inclusive'
    saved=api.put(base,body,format='json');assert saved.status_code==200,saved.data
    assert saved.data['data']['contract']['payload']['lines'][0]['line_total']=='106.00'
    config(world,user,kind='corporate_contract',prefix='CC')
    issued=api.post(base+'issue/',{'expected_version':saved.data['data']['contract']['version'],'expected_source_version':shipment.version,'confirmed':True},format='json')
    assert issued.status_code==200,issued.data
    assert Decimal(issued.data['data']['contract']['settlement_tax_amount'])==0
    supplier.default_tax_rate=Decimal('13');supplier.save()
    reread=api.get(base).data['data']
    assert Decimal(reread['defaults']['lines'][0]['tax_rate'])==13
    assert Decimal(reread['contract']['payload']['lines'][0]['tax_rate'])==6
    from openpyxl import load_workbook
    from io import BytesIO
    sheet=load_workbook(BytesIO(api.get(base+'download/').content)).active
    assert sheet['G11'].value=='26.5000'
    assert sheet['J11'].value=='106.00'


def test_new_contract_cannot_use_legacy_gross_basis(submitted_shipment):
    user,api,data=submitted_shipment
    base=BASE+f"supplier-shipments/{data['id']}/purchase-contract/"
    source=api.get(base).data['data']['defaults']
    source.update(pricing_basis='gross_inclusive',tax_treatment=None)
    source['lines'][0]['tax_rate']='6'
    response=api.put(base,{'expected_version':0,'expected_source_version':data['version'],'nature':'corporate','payload':source},format='json')
    assert response.status_code==400
