from datetime import date
from decimal import Decimal
import hashlib
from unittest.mock import patch

from apps.permissions.models import DataScope
from apps.supply_chain.models import PaymentApplication, PaymentRecord, PaymentVoucher, domain_write
from apps.supply_chain.models import SettlementRecord, SettlementRevision
from tests.test_supply_chain_v2_costs import pilot
from tests.test_supply_chain_v2_foundation import world, internal_user
from tests.test_supply_chain_v2_logistics import BASE, client


def monthly(api, **params):
    response = api.get(BASE + 'dashboard/monthly/', {'month': '2026-10', 'queue': 'supplier', **params})
    assert response.status_code == 200, response.data
    return response.data['data']


def cash(world, actor, shipment, amount, day, key, **extra):
    with domain_write():
        return PaymentRecord.objects.create(tenant=world['tenant'], created_by=actor, shipment=shipment,
            amount=Decimal(amount), date=day, idempotency_key=key, **extra)


def set_day(shipment, value='2026-09-12'):
    with domain_write():
        shipment.shipment_date = date.fromisoformat(value)
        shipment.save(update_fields=['shipment_date'])


def test_month_boundaries_and_later_reversal_preserve_prior_month(world):
    actor, api, shipment = pilot(world); set_day(shipment)
    cash(world, actor, shipment, '5', '2026-09-30', 'prior')
    paid = cash(world, actor, shipment, '4', '2026-10-31', 'oct')
    cash(world, actor, shipment, '4', '2026-11-01', 'rev', reverses=paid, reversal_reason='correction')
    result = monthly(api)
    assert Decimal(result['summary']['opening_payable']) == 15
    assert Decimal(result['summary']['paid_amount']) == 4
    assert Decimal(result['summary']['remaining_amount']) == 11
    assert Decimal(result['summary']['new_payable']) == 0
    november = monthly(api, month='2026-11')['summary']
    assert Decimal(november['opening_payable']) == 11
    assert Decimal(november['paid_amount']) == -4
    assert Decimal(november['remaining_amount']) == 15


def test_purchase_source_date_and_application_are_not_double_counted_as_cash(world):
    actor, api, shipment = pilot(world); set_day(shipment)
    order = shipment.order
    with domain_write():
        order.creation_key = 'PHHIST20261103:po:monthly-test'
        order.reference_number = 'PHCG260915001'; order.order_date = date(2026, 10, 15)
        order.save(update_fields=['creation_key', 'reference_number', 'order_date'])
        prepayment = PaymentRecord.objects.create(tenant=world['tenant'], created_by=actor,
            purchase_order=order, amount=Decimal('5'), date='2026-10-02', idempotency_key='prepay')
        PaymentApplication.objects.create(tenant=world['tenant'], created_by=actor, prepayment=prepayment,
            shipment=shipment, amount=Decimal('3'), date='2026-10-03', idempotency_key='apply')
    supplier = monthly(api)['summary']; purchase = monthly(api, queue='deposit')['summary']
    assert Decimal(supplier['paid_amount']) == 0
    assert Decimal(supplier['applied_amount']) == 3
    assert Decimal(supplier['remaining_amount']) == 17
    assert Decimal(purchase['opening_payable']) == Decimal('7.5')
    assert Decimal(purchase['paid_amount']) == 5
    assert Decimal(purchase['remaining_amount']) == Decimal('2.5')


def test_voucher_metadata_links_to_original_bytes_and_reversal_reuses_original(world):
    actor, api, shipment = pilot(world); set_day(shipment)
    paid = cash(world, actor, shipment, '4', '2026-10-01', 'proof')
    cash(world, actor, shipment, '1', '2026-10-02', 'no-proof')
    reverse = cash(world, actor, shipment, '4', '2026-11-01', 'proof-rev', reverses=paid, reversal_reason='correction')
    body = b'%PDF-1.4\noriginal transfer evidence\n%%EOF'
    with domain_write():
        voucher = PaymentVoucher.objects.create(tenant=world['tenant'], created_by=actor, payment=paid,
            file_name='transfer.pdf', media_type='application/pdf', byte_size=len(body),
            sha256=hashlib.sha256(body).hexdigest(), content=body, idempotency_key='file')
    rows = monthly(api, view='payments')['rows']
    proof = next(r for r in rows if r['id'] == paid.pk)
    assert proof['vouchers'][0]['id'] == voucher.pk
    assert proof['voucher_payment_id'] == paid.pk
    assert next(r for r in rows if r['id'] != paid.pk)['vouchers'] == []
    response = api.get(BASE + f'costs/shipment/{shipment.pk}/payments/{paid.pk}/vouchers/{voucher.pk}/download/')
    assert response.status_code == 200
    assert b''.join(response.streaming_content) == body
    reversal = monthly(api, view='payments', month='2026-11')['rows'][0]
    assert reversal['id'] == reverse.pk and reversal['voucher_payment_id'] == paid.pk
    assert reversal['vouchers'][0]['id'] == voucher.pk


def test_scope_and_invalid_month_are_enforced_for_documents_and_vouchers(world):
    actor, api, shipment = pilot(world); set_day(shipment)
    cash(world, actor, shipment, '4', '2026-10-01', 'private')
    restricted = internal_user(world, 'monthly-restricted', scope=DataScope.ScopeType.CUSTOM,
        config={'supplier_ids': [world['supplier_b'].pk]})
    for view in ('documents', 'payments'):
        result = monthly(client(restricted), view=view, party_id=shipment.order.supplier_id)
        assert result['rows'] == [] and result['count'] == 0
        assert Decimal(result['summary']['paid_amount']) == 0
    assert api.get(BASE + 'dashboard/monthly/', {'month': '2026-13'}).status_code == 400
    assert api.get(BASE + 'dashboard/monthly/', {'month': '0000-01'}).status_code == 400
    assert api.get(BASE + 'dashboard/monthly/', {'country_id': world['country_ca'].pk}).status_code == 404


def test_undated_obligation_does_not_invent_balance_but_payment_is_visible(world):
    actor, api, shipment = pilot(world)
    cash(world, actor, shipment, '4', '2026-10-01', 'undated-owner')
    with patch('apps.supply_chain.monthly_payables.document_time', return_value=None):
        result = monthly(api)
    assert result['summary']['undated_documents'] == 1
    assert Decimal(result['summary']['paid_amount']) == 4
    assert Decimal(result['summary']['unknown_payment_amount']) == 4
    assert result['rows'][0]['remaining_amount'] is None


def test_current_month_new_obligation_and_prepayment_credit_are_separate(world):
    actor, api, shipment = pilot(world); set_day(shipment, '2026-10-15')
    cash(world, actor, shipment, '5', '2026-09-30', 'early')
    september = monthly(api, month='2026-09')['summary']
    assert Decimal(september['remaining_amount']) == 0
    assert Decimal(september['credit_balance']) == 5
    october = monthly(api)['summary']
    assert Decimal(october['opening_payable']) == 0
    assert Decimal(october['opening_credit']) == 5
    assert Decimal(october['new_payable']) == 20
    assert Decimal(october['remaining_amount']) == 15


def test_historical_registration_uses_only_current_revision_and_is_not_cash(world):
    actor, api, shipment = pilot(world); set_day(shipment)
    with domain_write():
        record = SettlementRecord.objects.create(tenant=world['tenant'], created_by=actor, shipment=shipment)
        for sequence, amount, day in [(1, '4', '2026-09-01'), (2, '8', '2026-10-01')]:
            revision = SettlementRevision.objects.create(tenant=world['tenant'], created_by=actor,
                settlement=record, sequence=sequence, recorded_amount=amount, reference_number='legacy',
                date=day, reason='correct cumulative legacy amount', source_snapshot={'shipment_id': shipment.pk})
        record.current_revision = revision
        record.save(update_fields=['current_revision'])
    result = monthly(api)
    assert Decimal(result['summary']['opening_payable']) == 20
    assert Decimal(result['summary']['historical_paid_amount']) == 8
    assert Decimal(result['summary']['paid_amount']) == 0
    assert Decimal(result['summary']['remaining_amount']) == 12
    assert '2026-10' in result['available_months']
