from datetime import date
from decimal import Decimal
import hashlib
from unittest.mock import patch

from apps.permissions.models import DataScope
from apps.supply_chain.models import PaymentApplication, PaymentRecord, PaymentVoucher, domain_write
from apps.supply_chain.models import SettlementRecord, SettlementRevision
from tests.test_supply_chain_v2_costs import pilot
from tests.test_supply_chain_v2_foundation import world, internal_user, confirmed_order, po_payload, shipment_payload
from apps.supply_chain import services
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
    assert Decimal(supplier['paid_amount']) == 5
    assert Decimal(supplier['applied_amount']) == 3
    assert Decimal(supplier['remaining_amount']) == 15
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
    for view in ('parties', 'documents', 'payments'):
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
    assert result['rows'][0]['payment_status'] == 'unknown'
    assert result['document_status_counts']['unknown'] == 1


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


def test_party_totals_group_before_pagination_and_match_drilldown(world):
    actor, api, first = pilot(world); set_day(first)
    second = services.create_supplier_shipment(actor, shipment_payload(world, first.order, 'second', number='SH-SECOND'), idempotency_key='second')
    set_day(second)
    # Same display name must not collapse distinct supplier identities.
    supplier_b = world['supplier_b']; supplier_b.name = world['supplier'].name; supplier_b.save(update_fields=['name'])
    other_order = confirmed_order(world, actor, key='other', payload=po_payload(world, supplier=supplier_b, number='PO-OTHER'))
    other = services.create_supplier_shipment(actor, shipment_payload(world, other_order, 'other-sh', number='SH-OTHER'), idempotency_key='other-sh')
    set_day(other)
    cash(world, actor, first, '4', '2026-10-01', 'party-cash')
    grouped = monthly(api, view='parties', limit=1)
    assert grouped['count'] == 2 and len(grouped['rows']) == 1
    row = grouped['rows'][0]
    assert row['party_id'] == world['supplier'].pk and row['document_count'] == 2
    assert Decimal(row['opening_payable']) == 30
    assert Decimal(row['paid_amount']) == 4 and Decimal(row['remaining_amount']) == 26
    details = monthly(api, party_id=row['party_id'])
    for key in ('opening_payable', 'paid_amount', 'remaining_amount'):
        assert Decimal(row[key]) == Decimal(details['summary'][key])
    assert {r['id'] for r in details['rows']} == {first.pk, second.pk}
    assert monthly(api, view='parties', offset=1, limit=1)['rows'][0]['party_id'] == supplier_b.pk
    assert Decimal(grouped['summary']['remaining_amount']) == 36


def test_unassigned_party_drilldown_and_unknown_cash_are_not_lost(world):
    actor, api, shipment = pilot(world); set_day(shipment)
    cash(world, actor, shipment, '4', '2026-10-01', 'domestic-unknown', purpose='domestic_freight')
    grouped = monthly(api, queue='domestic', view='parties')
    row = grouped['rows'][0]
    assert row['party_id'] is None and row['unknown_documents'] == 1
    assert Decimal(row['unknown_payment_amount']) == 4
    detail = monthly(api, queue='domestic', unassigned_party=True, view='payments')
    assert detail['count'] == 1 and detail['rows'][0]['source_id'] == shipment.pk
    assert api.get(BASE + 'dashboard/monthly/', {'party_id': world['supplier'].pk, 'unassigned_party': True}).status_code == 400


def test_supplier_deposit_cash_and_reversal_use_original_purchase_voucher(world):
    actor, api, shipment = pilot(world); set_day(shipment, '2026-10-15')
    with domain_write():
        paid = PaymentRecord.objects.create(tenant=world['tenant'], created_by=actor, purchase_order=shipment.order,
            amount=Decimal('6'), date='2026-09-30', idempotency_key='supplier-deposit')
        PaymentRecord.objects.create(tenant=world['tenant'], created_by=actor, purchase_order=shipment.order,
            amount=Decimal('6'), date='2026-11-01', idempotency_key='supplier-deposit-reverse', reverses=paid, reversal_reason='test')
        voucher = PaymentVoucher.objects.create(tenant=world['tenant'], created_by=actor, payment=paid,
            file_name='deposit.png', media_type='image/png', byte_size=3, content=b'png',
            sha256=hashlib.sha256(b'png').hexdigest(), idempotency_key='deposit-voucher')
    oct = monthly(api, view='parties')['rows'][0]
    assert Decimal(oct['opening_credit']) == 6 and Decimal(oct['remaining_amount']) == 14
    november = monthly(api, month='2026-11', view='payments', party_id=shipment.order.supplier_id)
    assert Decimal(november['summary']['paid_amount']) == -6
    assert Decimal(november['summary']['remaining_amount']) == 20
    row = november['rows'][0]
    assert row['kind'] == 'purchase' and row['source_id'] == shipment.order_id
    assert row['voucher_payment_id'] == paid.pk and row['vouchers'][0]['id'] == voucher.pk


def test_purchase_only_supplier_keeps_advance_separate_and_respects_scope(world):
    actor, api, shipment = pilot(world); set_day(shipment)
    order = confirmed_order(world, actor, key='advance-only',
        payload=po_payload(world, supplier=world['supplier_b'], number='PO-ADVANCE'))
    with domain_write():
        payment = PaymentRecord.objects.create(tenant=world['tenant'], created_by=actor, purchase_order=order,
            amount=Decimal('6'), date='2026-10-01', idempotency_key='advance-only-cash')
        voucher = PaymentVoucher.objects.create(tenant=world['tenant'], created_by=actor, payment=payment,
            file_name='private.png', media_type='image/png', byte_size=3, content=b'png',
            sha256=hashlib.sha256(b'png').hexdigest(), idempotency_key='advance-only-voucher')
    result = monthly(api, view='parties')
    advance = next(r for r in result['rows'] if r['party_id'] == order.supplier_id)
    assert advance['document_count'] == 0 and Decimal(advance['credit_balance']) == 6
    assert Decimal(result['summary']['remaining_amount']) == 20
    groups = api.get(BASE + 'dashboard/?section=costs').data['data']['groups']
    assert Decimal(groups['supplier']['payable_amount']) == 20
    assert Decimal(groups['supplier']['advance_balance']) == 6
    restricted = client(internal_user(world, 'po-private', scope=DataScope.ScopeType.CUSTOM,
        config={'supplier_ids': [world['supplier'].pk]}))
    assert monthly(restricted, party_id=order.supplier_id, view='payments')['rows'] == []
    assert monthly(restricted, party_id=order.supplier_id, view='parties')['rows'] == []
    assert restricted.get(BASE + f'costs/purchase/{order.pk}/payments/{payment.pk}/vouchers/{voucher.pk}/download/').status_code in (403, 404)


def test_unknown_shipment_cash_is_visible_but_not_used_to_invent_known_balance(world):
    actor, api, shipment = pilot(world); set_day(shipment)
    unknown = services.create_supplier_shipment(actor,
        shipment_payload(world, shipment.order, 'unknown', number='SH-UNKNOWN'), idempotency_key='unknown')
    set_day(unknown)
    with domain_write():
        line = unknown.lines.filter(is_active=True).first()
        line.unit_price = None
        line.save(update_fields=['unit_price'])
    cash(world, actor, unknown, '5', '2026-10-01', 'unknown-cash')
    row = monthly(api, view='parties')['rows'][0]
    assert Decimal(row['paid_amount']) == 5 and Decimal(row['unknown_payment_amount']) == 5
    assert Decimal(row['remaining_amount']) == 20 and row['unknown_documents'] == 1
    supplier = api.get(BASE + 'dashboard/?section=costs').data['data']['groups']['supplier']
    assert Decimal(supplier['cash_paid_amount']) == 5
    assert Decimal(supplier['unknown_payment_amount']) == 5
    assert Decimal(supplier['payable_amount']) == 20


def test_document_payment_status_filter_includes_partial_and_keeps_summary(world):
    actor, api, shipment = pilot(world); set_day(shipment)
    cash(world, actor, shipment, '4', '2026-10-01', 'partial-status')
    all_rows = monthly(api)
    assert all_rows['rows'][0]['payment_status'] == 'partial'
    assert all_rows['document_status_counts'] == {'all': 1, 'unpaid': 1, 'paid': 0, 'unknown': 0}
    unpaid = monthly(api, payment_status='unpaid')
    assert unpaid['count'] == 1 and unpaid['rows'][0]['id'] == shipment.pk
    assert unpaid['summary'] == all_rows['summary']
    assert monthly(api, payment_status='paid')['count'] == 0


def test_document_status_counts_precede_pagination_and_invalid_status_is_rejected(world):
    actor, api, shipment = pilot(world); set_day(shipment)
    second = services.create_supplier_shipment(actor,
        shipment_payload(world, shipment.order, 'second', number='SH-SECOND'), idempotency_key='second-status')
    set_day(second)
    cash(world, actor, shipment, '20', '2026-10-01', 'paid-status')
    page = monthly(api, limit=1, payment_status='all')
    assert page['count'] == 2 and page['document_status_counts'] == {'all': 2, 'unpaid': 1, 'paid': 1, 'unknown': 0}
    paid = monthly(api, limit=1, payment_status='paid')
    assert paid['count'] == 1 and paid['rows'][0]['id'] == shipment.pk
    assert monthly(api, offset=1, limit=1, payment_status='paid')['rows'] == []
    assert paid['summary'] == page['summary']
    assert api.get(BASE + 'dashboard/monthly/', {'month': '2026-10', 'payment_status': 'invalid'}).status_code == 400


def test_payment_status_filter_is_supported_for_all_five_document_queues(world):
    _, api, _ = pilot(world)
    for queue in ('supplier', 'domestic', 'carrier', 'clearance', 'deposit'):
        response = api.get(BASE + 'dashboard/monthly/', {'month': '2026-10', 'queue': queue,
            'view': 'documents', 'payment_status': 'paid'})
        assert response.status_code == 200, (queue, response.data)
        data = response.data['data']
        assert set(data['document_status_counts']) == {'all', 'unpaid', 'paid', 'unknown'}
        assert data['count'] == sum(row['payment_status'] == 'paid' for row in data['rows'])


def test_payment_status_keeps_four_decimal_balance_and_reversal_month(world):
    actor, api, shipment = pilot(world); set_day(shipment)
    cash(world, actor, shipment, '19.9999', '2026-09-30', 'almost-paid')
    assert monthly(api, month='2026-09', payment_status='unpaid')['rows'][0]['payment_status'] == 'partial'
    final = cash(world, actor, shipment, '0.0001', '2026-10-01', 'final-fraction')
    cash(world, actor, shipment, '0.0001', '2026-11-01', 'reverse-fraction', reverses=final, reversal_reason='correction')
    assert monthly(api, payment_status='paid')['rows'][0]['payment_status'] == 'paid'
    november = monthly(api, month='2026-11', payment_status='unpaid')['rows'][0]
    assert november['payment_status'] == 'partial' and Decimal(november['remaining_amount']) == Decimal('0.0001')
