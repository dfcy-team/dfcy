from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch
import pytest
from apps.supply_chain.models import PaymentRecord, domain_write
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_v2_costs import pilot, received_pilot
from tests.test_supply_chain_v2_logistics import BASE, write


def adjust(api,kind,pk,due,days=None,key='terms'):
    response=write(api,f'costs/{kind}/{pk}/payment-terms/',{'expected_version':0,'days':days,
        'start':'reconciliation_date','reminder_days':7,'reconciliation_date':'2026-10-01',
        'due_date_override':due,'reason':'双方确认'},key,'put')
    assert response.status_code==200,response.data
    return response


@pytest.mark.django_db(transaction=True)
def test_reminder_due_boundaries_live_payment_and_reversal(world):
    buyer,api,shipment=pilot(world)
    with patch('apps.supply_chain.payment_reminders.business_date',return_value=date(2026,10,30)):
        adjust(api,'shipment',shipment.pk,None,days=29)
        endpoint=BASE+'payment-reminders/?kind=shipment&status='
        today=api.get(endpoint+'due_soon')
        assert today.status_code==200,today.data
        assert today.data['count']==1
        assert str(today.data['data'][0]['due_date'])=='2026-10-30'
        assert api.get(endpoint+'overdue').data['count']==0
        with domain_write():
            payment=PaymentRecord.objects.create(tenant=world['tenant'],created_by=buyer,shipment=shipment,
                amount=Decimal('20'),date='2026-10-30',idempotency_key='reminder-paid')
        assert api.get(endpoint+'all').data['count']==0
        with domain_write():
            PaymentRecord.objects.create(tenant=world['tenant'],created_by=buyer,shipment=shipment,
                amount=payment.amount,date='2026-10-30',reverses=payment,idempotency_key='reminder-reversed')
        assert api.get(endpoint+'due_soon').data['count']==1


@pytest.mark.django_db(transaction=True)
def test_reminder_unknown_history_and_clearance_date_override(world):
    buyer,api,shipment,batch_id,inbound_id=received_pilot(world)
    with patch('apps.supply_chain.payment_reminders.business_date',return_value=date(2026,10,30)):
        unknown=api.get(BASE+'payment-reminders/?kind=batch&status=unknown')
        assert unknown.status_code==200,unknown.data
        assert unknown.data['count']==1
        adjust(api,'inbound',inbound_id,'2026-10-29',key='clearance-terms')
        overdue=api.get(BASE+'payment-reminders/?kind=inbound&status=overdue&limit=1')
        assert overdue.status_code==200,overdue.data
        assert overdue.data['count']==1
        assert overdue.data['data'][0]['href'].endswith(f'kind=inbound&id={inbound_id}')
        assert Decimal(overdue.data['data'][0]['remaining_amount'])==7
        assert api.get(BASE+'payment-reminders/?kind=purchase').status_code==400
        assert api.get(BASE+'payment-reminders/?country_id=999999').status_code==404


@pytest.mark.django_db(transaction=True)
def test_frozen_warehouse_anchor_uses_business_timezone_and_missing_event_is_unknown(world):
    from apps.supply_chain.models import DispatchBatch
    buyer,api,shipment,batch_id,_=received_pilot(world)
    order=shipment.order
    batch=DispatchBatch.objects.get(pk=batch_id)
    with domain_write():
        order.supplier_terms_snapshot={'days':0,'start':'warehouse_arrival','reminder_days':7}
        order.save(update_fields=['supplier_terms_snapshot'])
        batch.arrived_warehouse_at=datetime(2026,10,29,16,30,tzinfo=timezone.utc)
        batch.save(update_fields=['arrived_warehouse_at'])
    with patch('apps.supply_chain.payment_reminders.business_date',return_value=date(2026,10,30)):
        endpoint=BASE+'payment-reminders/?kind=shipment&status='
        response=api.get(endpoint+'due_soon')
        assert response.status_code==200,response.data
        assert response.data['count']==1
        assert str(response.data['data'][0]['due_date'])=='2026-10-30'
        with domain_write():
            batch.arrived_warehouse_at=None
            batch.save(update_fields=['arrived_warehouse_at'])
        assert api.get(endpoint+'due_soon').data['count']==0
        assert api.get(endpoint+'unknown').data['count']==1
