from decimal import Decimal
import pytest
from apps.supply_chain import costs
from apps.supply_chain.receipt_differences import rows_for
from apps.supply_chain.models import SupplierShipment
from apps.supply_chain.receipt_payable_adjustments import annotate_receipt_shortage
from tests.test_supply_chain_v2_costs import received_pilot
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_v2_logistics import BASE

@pytest.fixture(autouse=True)
def confirmed_currency(monkeypatch):
    from apps.supply_chain import receipt_differences
    monkeypatch.setattr(receipt_differences,'_shipment_currencies',lambda actor,sources:{pk:'CNY' for pk in sources})


@pytest.mark.django_db(transaction=True)
def test_difference_sku_and_document_search(world):
    buyer,api,shipment,_,_=received_pilot(world,quantities=(1,3))
    rows=rows_for(buyer)
    assert all('new_sku' in row and 'old_sku' in row and 'sku' in row for row in rows)
    for query in [shipment.number,shipment.order.number,rows[0]['inbound_number']]:
        response=api.get(BASE+'receipt-differences/',{'query':query})
        assert response.status_code==200
        assert response.data['data']['rows']
    response=api.get(BASE+'receipt-differences/',{'query':'definitely-no-document-match'})
    assert response.data['data']=={'rows':[],'suppliers':[]}
    from apps.supply_chain.models import domain_write
    secondary=shipment.order
    with domain_write():
        secondary.pk=None
        secondary.number='SECONDARY-SKU-SEARCH'
        secondary.creation_key='secondary-search'
        secondary.notes='secondary-remark-only'
        secondary.save()
        line=shipment.lines.filter(purchase_line__isnull=False).first()
        purchase_line=line.purchase_line
        purchase_line.pk=None
        purchase_line.order=secondary
        purchase_line.save()
        line.purchase_line=purchase_line
        line.save()
    response=api.get(BASE+'receipt-differences/',{'query':'secondary-remark-only'})
    assert response.status_code==200,response.data
    assert response.data['data']['rows']


@pytest.mark.django_db(transaction=True)
def test_manual_net_settlement_and_reverse(world):
    buyer,api,shipment,_,_=received_pilot(world,quantities=(1,3))
    before=costs.settlement_amount('shipment',shipment)
    rows=rows_for(buyer)
    assert {r['type'] for r in rows}=={'short','over'}
    body=dict(keys=[r['key'] for r in rows],option='wrong_item_net_settlement',reason='verified wrong item',expected_versions={r['key']:r['version'] for r in rows})
    response=api.post(BASE+'receipt-differences/preview/',body,format='json')
    assert response.status_code==200,response.data
    assert Decimal(response.data['data']['incremental_adjustment'])==5
    body['preview_token']=response.data['data']['preview_token']
    response=api.post(BASE+'receipt-differences/settle/',body,format='json',HTTP_IDEMPOTENCY_KEY='net-one')
    assert response.status_code==201,response.data
    assert costs.settlement_amount('shipment',shipment)==before+5
    row=annotate_receipt_shortage(SupplierShipment.objects.filter(pk=shipment.pk)).get()
    assert row.receipt_decision_delta==5
    assert api.post(BASE+'receipt-differences/settle/',body,format='json',HTTP_IDEMPOTENCY_KEY='net-one').status_code==200
    for pk in response.data['data']['decision_ids']:
        reversal=api.post(BASE+f'receipt-differences/{pk}/reverse/',{'reason':'correction'},format='json')
        assert reversal.status_code==200,reversal.data
    assert costs.settlement_amount('shipment',shipment)==before


@pytest.mark.django_db(transaction=True)
def test_stale_and_read_only_guards(world):
    buyer,api,shipment,_,_=received_pilot(world,quantities=(1,3))
    rows=rows_for(buyer)
    body=dict(keys=[r['key'] for r in rows],option='supplier_waived',reason='waived',expected_versions={r['key']:999 for r in rows})
    response=api.post(BASE+'receipt-differences/settle/',body,format='json',HTTP_IDEMPOTENCY_KEY='stale')
    assert response.status_code==400,response.data


@pytest.mark.django_db(transaction=True)
def test_precise_history_adjustment_and_restore(world):
    from datetime import date
    from apps.supply_chain.models import SettlementRecord,SettlementRevision,PaymentRecord,domain_write
    buyer,api,shipment,_,_=received_pilot(world,quantities=(1,3))
    rows=rows_for(buyer);over=next(r for r in rows if r['type']=='over')
    with domain_write():
        record=SettlementRecord.objects.create(tenant=buyer.tenant,created_by=buyer,shipment=shipment)
        revision=SettlementRevision.objects.create(tenant=buyer.tenant,created_by=buyer,settlement=record,sequence=1,recorded_amount=Decimal('8'),reference_number='history',date=date.today(),notes='HIST-PH-COUNT-20261106',reason='test precise history',source_snapshot={'amount':str(costs.settlement_amount('shipment',shipment)),'receipt_difference_allocations':{'other':'3'}})
        record.current_revision=revision;record.save()
    body=dict(keys=[r['key'] for r in rows],option='wrong_item_net_settlement',reason='verified swap',expected_versions={r['key']:r['version'] for r in rows},adjust_previous=True)
    assert api.post(BASE+'receipt-differences/preview/',body,format='json').status_code==400
    bound=api.post(BASE+'receipt-differences/history-bind/',dict(key=over['key'],revision_id=revision.pk,amount='5',reason='verified original attribution'),format='json',HTTP_IDEMPOTENCY_KEY='bind-history')
    assert bound.status_code==200,bound.data
    body['preview_token']=api.post(BASE+'receipt-differences/preview/',body,format='json').data['data']['preview_token']
    before_cash=PaymentRecord.objects.count()
    response=api.post(BASE+'receipt-differences/settle/',body,format='json',HTTP_IDEMPOTENCY_KEY='history-net')
    assert response.status_code==201,response.data
    record.refresh_from_db();assert record.current_revision.recorded_amount==3
    assert record.current_revision.source_snapshot['receipt_difference_allocations']=={'other':'3'}
    new=next(r for r in rows_for(buyer) if r['key']==over['key'])
    response=api.post(BASE+f"receipt-differences/{new['decision_id']}/reverse/",{'reason':'undo swap'},format='json')
    assert response.status_code==200,response.data
    record.refresh_from_db();assert record.current_revision.recorded_amount==8
    assert PaymentRecord.objects.count()==before_cash


@pytest.mark.django_db(transaction=True)
def test_unconfirmed_currency_is_blocked(world,monkeypatch):
    buyer,api,shipment,_,_=received_pilot(world,quantities=(1,3))
    from apps.supply_chain import receipt_differences
    monkeypatch.setattr(receipt_differences,'_shipment_currencies',lambda actor,sources:{pk:None for pk in sources})
    rows=rows_for(buyer)
    body=dict(keys=[r['key'] for r in rows],option='supplier_waived',reason='verified',expected_versions={r['key']:r['version'] for r in rows})
    response=api.post(BASE+'receipt-differences/preview/',body,format='json')
    assert response.status_code==400,response.data


@pytest.mark.django_db(transaction=True)
def test_waived_does_not_consume_history(world,monkeypatch):
    from apps.supply_chain import receipt_difference_history as h
    buyer,api,shipment,_,_=received_pilot(world,quantities=(1,3))
    monkeypatch.setattr(h,'preview_history',lambda *a: (_ for _ in ()).throw(AssertionError('history must not be consumed')))
    monkeypatch.setattr(h,'confirm_history',lambda *a: (_ for _ in ()).throw(AssertionError('history must not be consumed')))
    rows=rows_for(buyer)
    body=dict(keys=[r['key'] for r in rows],option='supplier_waived',reason='waived',expected_versions={r['key']:r['version'] for r in rows},adjust_previous=True)
    view=api.post(BASE+'receipt-differences/preview/',body,format='json');assert view.status_code==200,view.data
    body['preview_token']=view.data['data']['preview_token']
    result=api.post(BASE+'receipt-differences/settle/',body,format='json',HTTP_IDEMPOTENCY_KEY='waived-safe')
    assert result.status_code==201,result.data

@pytest.mark.django_db(transaction=True)
def test_preview_fingerprint_rejects_changed_amount(world):
    from apps.supply_chain.models import InboundLine,domain_write
    buyer,api,shipment,_,_=received_pilot(world,quantities=(1,3))
    rows=rows_for(buyer)
    body=dict(keys=[r['key'] for r in rows],option='wrong_item_net_settlement',reason='net',expected_versions={r['key']:r['version'] for r in rows})
    view=api.post(BASE+'receipt-differences/preview/',body,format='json');assert view.status_code==200,view.data
    body['preview_token']=view.data['data']['preview_token']
    line=InboundLine.objects.get(pk=int(rows[0]['key'].split(':')[1]))
    with domain_write():
        line.received_quantity+=1;line.save()
    result=api.post(BASE+'receipt-differences/settle/',body,format='json',HTTP_IDEMPOTENCY_KEY='stale-amount')
    assert result.status_code==400,result.data
