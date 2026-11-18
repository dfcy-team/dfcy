"""API coverage for explicit, repeatable partial inbound receipts."""
import pytest
from rest_framework.test import APIClient

from apps.supply_chain.models import (InboundOrder, InboundShortageTermination, InternalStockReceipt,
    FeeRecord, PaymentRecord, PaymentTermsRecord, CostVersion)
from tests.test_supply_chain_v2_logistics import BASE, setup, create, arrive, write, client, generate
from tests.test_supply_chain_v2_foundation import internal_user, world, confirmed_order, shipment_payload, po_payload
from apps.supply_chain import services


def create_partial(api, batch, warehouse, source_line, quantity, key):
    return write(api, f"dispatch-batches/{batch['id']}/inbound/", {
        'expected_version': batch['version'], 'warehouse_id': warehouse.pk,
        'lines': [{'shipment_line_id': source_line.pk, 'quantity': quantity}],
    }, key)


def test_explicit_lines_create_multiple_inbounds_and_reserve_until_cancel(world):
    buyer, shipment, _, carrier, warehouse = setup(world)
    api = client(buyer)
    batch, _ = create(api, [shipment], carrier)
    batch = arrive(api, batch)
    source = shipment.lines.get()

    first = create_partial(api, batch, warehouse, source, 2, 'partial-one')
    assert first.status_code == 200, first.data
    first_doc = first.data['data']
    assert first_doc['receipt_mode'] == 'manual_partial'
    assert first_doc['lines'][0]['expected_quantity'] == 2
    progress = api.get(BASE + f"dispatch-batches/{batch['id']}/")
    assert progress.status_code == 200, progress.data
    candidate = progress.data['data']['inbound_candidates'][0]
    assert candidate['reserved_quantity'] == 2 and candidate['available_quantity'] == 2

    over_reservation = create_partial(api, batch, warehouse, source, 3, 'partial-over-reserved')
    assert over_reservation.status_code == 422, over_reservation.data
    latest_batch = api.get(BASE + f"dispatch-batches/{batch['id']}/").data['data']
    second = create_partial(api, latest_batch, warehouse, source, 2, 'partial-two')
    assert second.status_code == 200, second.data
    second_doc = second.data['data']
    assert second_doc['id'] != first_doc['id']
    assert InboundOrder.objects.filter(batch_id=batch['id']).count() == 2

    cancelled = write(api, f"inbound-orders/{first_doc['id']}/cancel/",
        {'expected_version': first_doc['version'], 'reason': '更正分批安排'}, 'cancel-partial')
    assert cancelled.status_code == 200, cancelled.data
    latest_batch = api.get(BASE + f"dispatch-batches/{batch['id']}/").data['data']
    replacement = create_partial(api, latest_batch, warehouse, source, 2, 'partial-after-cancel')
    assert replacement.status_code == 200, replacement.data


def test_short_receipt_stays_open_then_re_receipt_and_final_shortage_are_idempotent(world):
    buyer, shipment, _, carrier, warehouse = setup(world)
    api = client(buyer)
    batch, _ = create(api, [shipment], carrier)
    batch = arrive(api, batch)
    source = shipment.lines.get()
    draft = create_partial(api, batch, warehouse, source, 4, 'partial-short-receipt')
    assert draft.status_code == 200, draft.data
    inbound = draft.data['data']
    checked_body = {'expected_version': inbound['version'], 'notes': '短收核对', 'lines': [
        {'id': inbound['lines'][0]['id'], 'received_quantity': 2, 'difference_note': '外箱短少'}]}
    checked = write(api, f"inbound-orders/{inbound['id']}/", checked_body, 'check-short', 'patch')
    assert checked.status_code == 200, checked.data
    confirmation = {'expected_version': checked.data['data']['version']}
    confirmed = write(api, f"inbound-orders/{inbound['id']}/confirm/", confirmation, 'confirm-short')
    assert confirmed.status_code == 200, confirmed.data
    assert confirmed.data['data']['status'] == 'confirmed'

    progress = api.get(BASE + f"dispatch-batches/{batch['id']}/").data['data']
    candidate = progress['inbound_candidates'][0]
    assert candidate['received_quantity'] == 2
    assert candidate['fulfilled_quantity'] == 2
    assert candidate['remaining_quantity'] == 2 and candidate['available_quantity'] == 2
    latest_batch = api.get(BASE + f"dispatch-batches/{batch['id']}/").data['data']
    next_draft = create_partial(api, latest_batch, warehouse, source, 2, 'partial-receipt-two')
    assert next_draft.status_code == 200, next_draft.data
    next_inbound = next_draft.data['data']
    checked_next = write(api, f"inbound-orders/{next_inbound['id']}/", {
        'expected_version': next_inbound['version'], 'notes': '', 'lines': [
            {'id': next_inbound['lines'][0]['id'], 'received_quantity': 2, 'difference_note': ''}],
    }, 'check-receipt-two', 'patch')
    assert checked_next.status_code == 200, checked_next.data
    assert write(api, f"inbound-orders/{next_inbound['id']}/confirm/",
        {'expected_version': checked_next.data['data']['version']}, 'confirm-receipt-two').status_code == 200

    order = shipment.order
    shortage_path = BASE + f"purchase-orders/{order.pk}/terminate-remainder/"
    preview = api.get(shortage_path, {'scope': 'inbound_shortage'})
    assert preview.status_code == 200, preview.data
    assert preview.data['data']['scope'] == 'inbound_shortage'
    assert preview.data['data']['rows'] == []

    # A separate shipment leaves a real, explicit final shortage to terminate.
    short_order = confirmed_order(world, buyer, key='final-shortage-order',
        payload=po_payload(world, number='PO-FINAL-SHORTAGE'))
    short_shipment = services.create_supplier_shipment(buyer,
        shipment_payload(world, short_order, 'final-shortage-shipment', number='SH-FINAL-SHORTAGE'),
        idempotency_key='final-shortage-shipment')
    batch2, _ = create(api, [short_shipment], carrier, key='shortage-batch')
    batch2 = arrive(api, batch2)
    source2 = short_shipment.lines.get()
    draft2 = create_partial(api, batch2, warehouse, source2, 4, 'shortage-short-receipt')
    assert draft2.status_code == 200, draft2.data
    inbound2 = draft2.data['data']
    checked2 = write(api, f"inbound-orders/{inbound2['id']}/", {
        'expected_version': inbound2['version'], 'notes': '', 'lines': [
            {'id': inbound2['lines'][0]['id'], 'received_quantity': 2, 'difference_note': '短收'}],
    }, 'shortage-check', 'patch').data['data']
    write(api, f"inbound-orders/{inbound2['id']}/confirm/",
        {'expected_version': checked2['version']}, 'shortage-confirm')
    order2 = short_shipment.order
    path2 = f"purchase-orders/{order2.pk}/terminate-remainder/"
    preview2 = api.get(BASE + path2, {'scope': 'inbound_shortage'}).data['data']
    row = preview2['rows'][0]
    body = {'scope': 'inbound_shortage', 'expected_version': preview2['version'],
        'preview_token': preview2['preview_token'], 'reason': '供应商确认余量无法交付',
        'lines': [{'batch_id': row['batch_id'], 'shipment_line_id': row['shipment_line_id'], 'quantity': 2}]}
    done = write(api, path2, body, 'final-shortage')
    assert done.status_code == 200, done.data
    assert write(api, path2, body, 'final-shortage').status_code == 200
    assert InboundShortageTermination.objects.filter(batch_id=row['batch_id'], origin='final_shortage').count() == 1
    progress2 = api.get(BASE + f"dispatch-batches/{batch2['id']}/").data['data']
    assert progress2['inbound_progress']['closed'] is True
    assert progress2['inbound_progress']['shortage_terminated_quantity'] == 2


def test_manual_inbound_and_shortage_are_tenant_and_manage_scoped(world):
    buyer, shipment, _, carrier, warehouse = setup(world)
    api = client(buyer)
    batch, _ = create(api, [shipment], carrier)
    batch = arrive(api, batch)
    source = shipment.lines.get()
    denied = client(internal_user(world, 'inbound-own-scope', scope='own'))
    assert create_partial(denied, batch, warehouse, source, 1, 'denied-manual-inbound').status_code == 404
    progress_path = BASE + f"dispatch-batches/{batch['id']}/"
    assert denied.get(progress_path).status_code == 404

    from apps.tenants.models import Tenant
    tenant_b = Tenant.objects.create(name='foreign inbound tenant', code='foreign-inbound')
    foreign = client(internal_user({**world, 'tenant': tenant_b}, 'foreign-inbound-user'))
    assert foreign.get(progress_path).status_code == 404
    shortage_path = BASE + f"purchase-orders/{shipment.order_id}/terminate-remainder/"
    assert foreign.get(shortage_path, {'scope': 'inbound_shortage'}).status_code == 404


def test_cancelled_two_shipment_draft_can_be_restored_and_split_idempotently(world):
    from apps.supply_chain.inbound_repartition import restore_and_split_by_shipment

    buyer, one, two, carrier, warehouse = setup(world, mixed_suppliers=True)
    api = client(buyer)
    batch, _ = create(api, [one, two], carrier, key='repartition-batch')
    batch = arrive(api, batch)
    original = generate(api, batch, warehouse)
    assert original['status'] == 'draft'
    original_ids = {line['id'] for line in original['lines']}
    original_number = original['number']
    cancelled = write(api, f"inbound-orders/{original['id']}/cancel/",
        {'expected_version': original['version'], 'reason': '拆分到货记录'}, 'repartition-cancel')
    assert cancelled.status_code == 200, cancelled.data
    assert cancelled.data['data']['status'] == 'cancelled'

    split = restore_and_split_by_shipment(buyer, original['id'], expected_version=2,
        reason='按两个发货单分开登记', key='restore-and-split')
    assert len(split) == 2
    restored, new_doc = split
    restored.refresh_from_db(); new_doc.refresh_from_db()
    assert restored.number == original_number and restored.status == 'draft'
    assert {line.pk for line in restored.lines.all()} | {line.pk for line in new_doc.lines.all()} == original_ids
    first_shipments = set(restored.lines.values_list('shipment_line__shipment_id', flat=True))
    second_shipments = set(new_doc.lines.values_list('shipment_line__shipment_id', flat=True))
    assert not first_shipments & second_shipments
    assert first_shipments | second_shipments == {one.pk, two.pk}
    assert not InternalStockReceipt.objects.filter(inbound__in=[restored, new_doc]).exists()
    assert not FeeRecord.objects.filter(inbound__in=[restored, new_doc]).exists()
    assert not PaymentRecord.objects.filter(inbound__in=[restored, new_doc]).exists()
    assert not PaymentTermsRecord.objects.filter(inbound__in=[restored, new_doc]).exists()
    assert not CostVersion.objects.filter(batch_id=batch['id']).exists()
    replay = restore_and_split_by_shipment(buyer, original['id'], expected_version=2,
        reason='按两个发货单分开登记', key='restore-and-split')
    assert [doc.pk for doc in replay] == [doc.pk for doc in split]
