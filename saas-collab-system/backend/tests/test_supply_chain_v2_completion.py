"""Corrections preserve sources, scoped history and retry safety."""
from unittest.mock import patch

import pytest
from apps.permissions.models import DataScope
from apps.supply_chain import services, logistics
from apps.supply_chain.models import BusinessEvent, DispatchBatch, DispatchMembership, InternalStockReceipt
from tests.test_supply_chain_v2_foundation import world, internal_user, confirmed_order, po_payload, shipment_payload
from tests.test_supply_chain_v2_logistics import BASE, setup, client, write, create, arrive, generate, checked


def members(batch, rows, reason='发货安排调整'):
    for row in rows:
        row.refresh_from_db()
    return {'expected_version': batch['version'], 'shipment_ids': [r.pk for r in rows],
            'shipment_versions': [{'id': r.pk, 'version': r.version} for r in rows], 'reason': reason}


def test_change_members_release_history_reselect_and_replay(world):
    buyer, one, two, carrier, warehouse = setup(world)
    api = client(buyer)
    batch, _ = create(api, [one], carrier)
    body = members(batch, [two])
    path = f"dispatch-batches/{batch['id']}/members/"
    response = write(api, path, body, 'replace')
    assert response.status_code == 200, response.data
    updated = response.data['data']
    assert updated['shipment_ids'] == [two.pk]
    assert api.get(BASE + 'dispatch-candidates/').data['data'][0]['id'] == one.pk
    assert DispatchMembership.objects.get(batch_id=batch['id'], shipment=one).active_guard is None
    assert write(api, path, body, 'replace').data['data']['version'] == updated['version']
    assert DispatchMembership.objects.filter(active_guard=True).count() == 1
    assert write(api, path, {**body, 'reason': '不同请求'}, 'replace').status_code == 422
    old = write(api, path, members(updated, [one, two]), 'add-back')
    assert old.status_code == 200, old.data
    assert DispatchMembership.objects.filter(batch_id=batch['id'], shipment=one).count() == 2
    one.refresh_from_db(); two.refresh_from_db()
    assert len(old.data['data']['shipments']) == 2
    event = BusinessEvent.objects.get(action='members_changed', request_key='replace')
    assert event.created_by == buyer and event.payload['previous_shipment_ids'] == [one.pk]
    assert event.payload['reason'] == '发货安排调整'


def test_cancel_release_and_repeat_no_scope_leak(world):
    buyer, one, two, carrier, warehouse = setup(world, mixed_suppliers=True)
    api = client(buyer); batch, _ = create(api, [one, two], carrier)
    path = f"dispatch-batches/{batch['id']}/cancel/"
    body = {'expected_version': batch['version'], 'reason': '取消本次发运'}
    response = write(api, path, body, 'cancel')
    assert response.status_code == 200, response.data
    data = response.data['data']
    assert data['status'] == 'cancelled' and data['stage'] == 'unmarked' and data['shipment_ids'] == []
    assert not DispatchMembership.objects.filter(active_guard=True).exists()
    assert api.get(BASE + 'dispatch-candidates/').data['count'] == 2
    assert write(api, path, body, 'cancel').data['data']['version'] == data['version']
    assert write(api, f"dispatch-batches/{batch['id']}/stage/", {'expected_version': data['version'],
        'stage': 'departed', 'occurred_at': '2026-10-12T01:00:00Z'}, 'late').status_code == 422
    assert write(api, f"dispatch-batches/{batch['id']}/", {'expected_version': data['version'], 'notes': 'late'}, 'late', 'patch').status_code == 422
    assert write(api, f"dispatch-batches/{batch['id']}/members/", members(data, [one]), 'late').status_code == 422
    assert write(api, path, {'expected_version': data['version'], 'reason': '再次取消'}, 'again').status_code == 422
    limited = client(internal_user(world, 'limited', scope=DataScope.ScopeType.CUSTOM,
        config={'supplier_ids': [world['supplier'].pk]}))
    assert limited.get(BASE + 'dispatch-batches/').data['count'] == 0
    assert limited.get(BASE + f"dispatch-batches/{batch['id']}/").status_code == 404
    assert write(limited, path, body, 'cancel').status_code == 404
    one.refresh_from_db(); two.refresh_from_db()
    rebatched, _ = create(api, [one, two], carrier, key='rebatched')
    assert rebatched['id'] != batch['id'] and DispatchMembership.objects.filter(active_guard=True).count() == 2


def test_members_validation_competing_batches_versions_country_and_permissions(world):
    buyer, one, two, carrier, warehouse = setup(world)
    api = client(buyer); batch, _ = create(api, [one], carrier)
    body = members(batch, [two]); two.version += 1
    from apps.supply_chain.models import domain_write
    with domain_write():
        two.save()
    path = f"dispatch-batches/{batch['id']}/members/"
    assert write(api, path, body, 'stale').status_code == 422
    body = members(batch, [two])
    assert write(api, path, {**body, 'reason': ' '}, 'empty-reason').status_code == 400
    assert write(api, path, {**body, 'shipment_ids': []}, 'empty-batch').status_code == 400
    assert write(api, path, {**body, 'shipment_ids': [two.pk, two.pk]}, 'duplicate').status_code == 422
    create(api, [two], carrier, key='competitor')
    assert write(api, path, members(batch, [two]), 'occupied').status_code == 422
    foreign_order = confirmed_order(world, buyer, key='canada', payload=po_payload(world, number='PO-CA', country=world['country_ca']))
    foreign = services.create_supplier_shipment(buyer, shipment_payload(world, foreign_order, 'ca', number='SH-CA'), idempotency_key='ca')
    assert write(api, path, members(batch, [foreign]), 'country').status_code == 422
    readonly = client(internal_user(world, 'readonly', codes=('supply.v2.view',)))
    assert write(readonly, path, body, 'readonly').status_code == 403
    departed = write(api, f"dispatch-batches/{batch['id']}/stage/", {'expected_version': batch['version'],
        'stage': 'departed', 'occurred_at': '2026-10-12T01:00:00Z'}, 'departure').data['data']
    assert write(api, path, members(departed, [one]), 'departed').status_code == 422
    assert write(api, f"dispatch-batches/{batch['id']}/cancel/", {'expected_version': departed['version'], 'reason': 'late'}, 'late').status_code == 422
    assert DispatchMembership.objects.filter(batch_id=batch['id'], active_guard=True).count() == 1


@pytest.mark.parametrize('command', ['members', 'cancel'])
def test_member_cancellation_atomic_rollback(world, command):
    buyer, one, two, carrier, warehouse = setup(world)
    api = client(buyer); batch, _ = create(api, [one], carrier)
    body = members(batch, [two]) if command == 'members' else {'expected_version': batch['version'], 'reason': '取消'}
    handler = logistics.replace_members if command == 'members' else logistics.cancel_batch
    with patch('apps.supply_chain.logistics.services._event', side_effect=RuntimeError('injected failure')):
        with pytest.raises(RuntimeError):
            handler(buyer, batch['id'], body, 'rollback')
    assert DispatchBatch.objects.get(pk=batch['id']).version == batch['version']
    assert DispatchMembership.objects.get(batch_id=batch['id']).active_guard is True
    assert not BusinessEvent.objects.filter(request_key='rollback').exists()


def test_date_correction_after_receipt_audit_projection_and_idempotence(world):
    buyer, one, two, carrier, warehouse = setup(world)
    api = client(buyer); batch, _ = create(api, [one], carrier); batch = arrive(api, batch)
    inbound, _ = checked(api, generate(api, batch, warehouse))
    assert write(api, f"inbound-orders/{inbound['id']}/confirm/", {'expected_version': inbound['version']}, 'confirm').status_code == 200
    current = api.get(BASE + f"dispatch-batches/{batch['id']}/").data['data']
    path = f"dispatch-batches/{batch['id']}/dates/"
    body = {'expected_version': current['version'], 'stage': 'arrived_port',
            'occurred_at': '2026-10-12T02:30:00+08:00', 'reason': '货代修正到港时间'}
    response = write(api, path, body, 'correct')
    assert response.status_code == 200, response.data
    changed = response.data['data']
    assert changed['stage'] == 'arrived_warehouse' and changed['inbound_id'] == inbound['id']
    assert InternalStockReceipt.objects.count() == 1
    assert write(api, path, body, 'correct').data['data']['version'] == changed['version']
    projection = api.get(BASE + f'supplier-shipments/{one.pk}/').data['data']
    assert projection['logistics_dates'] == changed['logistics_dates']
    event = BusinessEvent.objects.get(action='logistics_date_corrected')
    assert event.created_by == buyer and event.payload['previous_occurred_at']
    for timestamp in ['2026-10-12T00:00:00+08:00', '2026-10-12T04:00:00+08:00', '2026-10-12T02:00:00']:
        bad = {**body, 'expected_version': changed['version'], 'occurred_at': timestamp}
        assert write(api, path, bad, 'bad-' + timestamp).status_code in (400, 422)
    assert write(api, path, {**body, 'expected_version': changed['version'], 'reason': ' '}, 'no-reason').status_code == 400
    assert DispatchBatch.objects.get(pk=batch['id']).version == changed['version']


def test_unrecorded_dates_and_removed_member_history_scope(world):
    buyer, one, two, carrier, warehouse = setup(world, mixed_suppliers=True)
    api = client(buyer); batch, _ = create(api, [one, two], carrier)
    path = f"dispatch-batches/{batch['id']}/dates/"
    assert write(api, path, {'expected_version': batch['version'], 'stage': 'arrived_port',
        'occurred_at': '2026-10-12T02:00:00Z', 'reason': '补录'}, 'unrecorded').status_code == 422
    response = write(api, f"dispatch-batches/{batch['id']}/members/", members(batch, [one]), 'remove-other')
    assert response.status_code == 200, response.data
    limited = client(internal_user(world, 'limited-history', scope=DataScope.ScopeType.CUSTOM,
        config={'supplier_ids': [world['supplier'].pk]}))
    assert limited.get(BASE + f"dispatch-batches/{batch['id']}/").status_code == 404
    assert limited.get(BASE + 'dispatch-batches/').data['count'] == 0
