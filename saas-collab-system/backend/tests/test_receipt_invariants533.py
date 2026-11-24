from decimal import Decimal
from datetime import date, datetime, timezone

import pytest
from apps.supply_chain import costs, services, logistics
from apps.supply_chain.models import ReceiptDifferenceDecision, SettlementRecord, SettlementRevision, domain_write
from apps.supply_chain.receipt_differences import rows_for
from tests.test_supply_chain_v2_costs import received_pilot
from tests.test_supply_chain_v2_logistics import BASE, create, arrive, client
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_v2_foundation import internal_user, confirmed_order, po_payload, shipment_payload, freight


@pytest.fixture(autouse=True)
def confirmed_currency(monkeypatch):
    from apps.supply_chain import receipt_differences
    monkeypatch.setattr(receipt_differences, '_shipment_currencies', lambda actor, sources: {pk: 'CNY' for pk in sources})


@pytest.mark.django_db(transaction=True)
def test_active_decision_blocks_next_partial_receipt_until_reversal(world):
    buyer = internal_user(world)
    # Cumulative actual receipts equal the original 200 billed units.
    order = confirmed_order(world, buyer, payload=po_payload(world, lines=[{'sku_id': world['sku'].pk, 'quantity': 200, 'unit_price': '2'}]))
    shipment = services.create_supplier_shipment(buyer, shipment_payload(world, order, 'two-partial', lines=[{'sku_id': world['sku'].pk, 'quantity': 200}]), idempotency_key='two-partial')
    shipment = services.mark_collection_arrival(buyer, shipment.pk, expected_version=shipment.version, occurred_at=datetime(2026, 10, 12, tzinfo=timezone.utc), idempotency_key='collect-two-partial')
    api = client(buyer)
    batch, _ = create(api, [shipment], freight(world), key='two-partial-batch')
    batch = arrive(api, batch)
    from apps.masterdata.models import WarehouseMaster
    warehouse = WarehouseMaster.objects.create(tenant=world['tenant'], code='US-533', name='US 533', country_code='US')
    source = shipment.lines.get()
    first_inbound = services.generate_inbound_draft(buyer, batch['id'], warehouse_id=warehouse.pk, expected_version=batch['version'], idempotency_key='first-partial', lines=[{'shipment_line_id': source.pk, 'quantity': 100}])
    first_line = first_inbound.lines.get()
    logistics.update_inbound(buyer, first_inbound.pk, {'expected_version': first_inbound.version, 'lines': [{'id': first_line.pk, 'received_quantity': 112, 'difference_note': '实收112'}]}, 'first-partial-count')
    first_inbound.refresh_from_db()
    assert logistics.confirm_inbound(buyer, first_inbound.pk, {'expected_version': first_inbound.version}, 'confirm-first-partial').status == 'confirmed'
    over = next(row for row in rows_for(buyer) if row['type'] == 'over')
    assert Decimal(over['payable_increment']) == 0
    body = dict(keys=[over['key']], option='wrong_item_net_settlement', reason='确认多收', expected_versions={over['key']: over['version']})
    preview = api.post(BASE + 'receipt-differences/preview/', body, format='json')
    assert preview.status_code == 200, preview.data
    body['preview_token'] = preview.data['data']['preview_token']
    settled = api.post(BASE + 'receipt-differences/settle/', body, format='json', HTTP_IDEMPOTENCY_KEY='decision-before-second-receipt')
    assert settled.status_code == 201, settled.data

    source_id = over['shipment_line_id']
    batch_obj = services._batch(buyer, batch['id'])
    second = services.generate_inbound_draft(buyer, batch['id'], warehouse_id=warehouse.pk,
        expected_version=batch_obj.version, idempotency_key='second-partial',
        lines=[{'shipment_line_id': source_id, 'quantity': 88}], notes='second partial')
    line = second.lines.get()
    logistics.update_inbound(buyer, second.pk, {'expected_version': second.version, 'lines': [{'id': line.pk, 'received_quantity': 88, 'difference_note': '实收88'}]}, 'second-partial-count')
    second.refresh_from_db()
    confirmed = api.post(BASE + f'inbound-orders/{second.pk}/confirm/', {'expected_version': second.version}, format='json', HTTP_IDEMPOTENCY_KEY='blocked-second')
    assert confirmed.status_code == 422, confirmed.data

    decision = ReceiptDifferenceDecision.objects.get(pk=settled.data['data']['decision_ids'][0])
    reversed_result = api.post(BASE + f'receipt-differences/{decision.pk}/reverse/', {'reason': '撤销原处理'}, format='json')
    assert reversed_result.status_code == 200, reversed_result.data
    second.refresh_from_db()
    confirmed = api.post(BASE + f'inbound-orders/{second.pk}/confirm/', {'expected_version': second.version}, format='json', HTTP_IDEMPOTENCY_KEY='accepted-after-reversal')
    assert confirmed.status_code == 200, confirmed.data
    pending = next(row for row in rows_for(buyer) if row['key'] == over['key'])
    assert Decimal(pending['payable_increment']) == 0
    settlement = dict(keys=[pending['key']], option='wrong_item_net_settlement', reason='累计实收等于原发货，不得重复加价', expected_versions={pending['key']: pending['version']})
    pv = api.post(BASE + 'receipt-differences/preview/', settlement, format='json')
    assert pv.status_code == 200, pv.data
    settlement['preview_token'] = pv.data['data']['preview_token']
    done = api.post(BASE + 'receipt-differences/settle/', settlement, format='json', HTTP_IDEMPOTENCY_KEY='fresh-settlement-after-receipt')
    assert done.status_code == 201, done.data
    shipment.refresh_from_db()
    assert costs.settlement_amount('shipment', shipment) == Decimal('400')
    from apps.supply_chain.receipt_payable_adjustments import annotate_receipt_shortage
    from apps.supply_chain.models import SupplierShipment
    projected = annotate_receipt_shortage(SupplierShipment.objects.filter(pk=shipment.pk)).get()
    assert projected.inbound_shortage_amount == 0
    assert projected.receipt_decision_delta == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('first_option,replacement_option', [
    ('wrong_item_net_settlement', 'supplier_waived'),
    ('wrong_item_net_settlement', 'wrong_item_net_settlement'),
    ('supplier_waived', 'wrong_item_net_settlement'),
])
def test_history_restore_preview_matches_replacement_actual_balance(world, first_option, replacement_option):
    buyer, api, shipment, _, _ = received_pilot(world, quantities=(1, 3))
    over = next(row for row in rows_for(buyer) if row['type'] == 'over')
    with domain_write():
        record = SettlementRecord.objects.create(tenant=buyer.tenant, created_by=buyer, shipment=shipment)
        revision = SettlementRevision.objects.create(tenant=buyer.tenant, created_by=buyer, settlement=record,
            sequence=1, recorded_amount=Decimal('5'), reference_number='hist-5', date=date.today(),
            notes='HIST-PH-COUNT-20261106', reason='seed historical settlement',
            source_snapshot={'receipt_difference_allocations': {over['key']: '5'}})
        record.current_revision, = [revision]
        record.save()
    first_body = dict(keys=[over['key']], option=first_option, reason='确认错货',
        expected_versions={over['key']: over['version']}, adjust_previous=True)
    first_preview = api.post(BASE + 'receipt-differences/preview/', first_body, format='json')
    assert first_preview.status_code == 200, first_preview.data
    first_body['preview_token'] = first_preview.data['data']['preview_token']
    first = api.post(BASE + 'receipt-differences/settle/', first_body, format='json', HTTP_IDEMPOTENCY_KEY='consume-history-five')
    assert first.status_code == 201, first.data

    active = next(row for row in rows_for(buyer) if row['key'] == over['key'])
    replacement = dict(keys=[active['key']], option=replacement_option, reason='改为供应商承担',
        expected_versions={active['key']: active['version']}, adjust_previous=True)
    preview = api.post(BASE + 'receipt-differences/preview/', replacement, format='json')
    assert preview.status_code == 200, preview.data
    if first_option == 'wrong_item_net_settlement':
        assert Decimal(preview.data['data']['history_restorations'][0]['amount']) == 5
    else:
        assert preview.data['data']['history_restorations'] == []
    if replacement_option == 'wrong_item_net_settlement':
        assert Decimal(preview.data['data']['history_adjustments'][0]['reduction']) == 5
    replacement['preview_token'] = preview.data['data']['preview_token']
    result = api.post(BASE + 'receipt-differences/settle/', replacement, format='json', HTTP_IDEMPOTENCY_KEY='replace-history-decision')
    assert result.status_code == 201, result.data
    summary = costs.payment_summary(buyer, 'shipment', shipment.pk)['summary']
    balance = Decimal(summary['due_amount']) - Decimal(summary['paid_amount']) - Decimal(summary['applied_amount'])
    assert Decimal(preview.data['data']['remaining_after']) == max(balance, Decimal('0'))
    assert Decimal(preview.data['data']['prepaid_balance_after']) == max(-balance, Decimal('0'))


@pytest.mark.django_db(transaction=True)
def test_preview_refuses_history_with_existing_account_allocation(world):
    buyer, api, shipment, _, _ = received_pilot(world, quantities=(1, 3))
    over = next(row for row in rows_for(buyer) if row['type'] == 'over')
    with domain_write():
        record = SettlementRecord.objects.create(tenant=buyer.tenant, created_by=buyer, shipment=shipment)
        revision = SettlementRevision.objects.create(tenant=buyer.tenant, created_by=buyer,
            settlement=record, sequence=1, recorded_amount=Decimal('5'), date=date.today(),
            reference_number='allocated-history', notes='HIST-PH-COUNT-20261106', reason='synthetic allocation',
            source_snapshot={'receipt_difference_allocations': {over['key']: '5'}},
            payee_allocations=[{'amount': '5', 'reference': 'synthetic-account-allocation'}])
        record.current_revision = revision
        record.save()
    response = api.post(BASE + 'receipt-differences/preview/', dict(keys=[over['key']],
        option='wrong_item_net_settlement', reason='verify original allocation',
        expected_versions={over['key']: over['version']}, adjust_previous=True), format='json')
    assert response.status_code == 400, response.data
    assert 'preview_token' not in str(response.data)
    record.refresh_from_db()
    assert record.current_revision_id == revision.pk
    assert record.current_revision.recorded_amount == 5
