"""SC-SHIPMENT-1 typed loose-cargo shipment domain tests."""

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError

from apps.common.exceptions import IdempotencyConflict, StateConflict
from apps.consolidation.models import ConsolidationBoxAllocation, LooseCargoConsolidation
from apps.consolidation.services import (
    allocate_consolidation_boxes,
    receive_consolidation_box,
    ready_consolidation,
    release_consolidation,
)
from apps.packing.models import PackingBoxConsumption, PackingStandardVersion, _packing_domain_write_context
from apps.shipping.models import LooseCargoShipment, ShipmentBoxAllocation, ShipmentEvent
from apps.shipping.services import (
    allocate_shipment_boxes,
    cancel_shipment,
    create_shipment,
    customs_declare_shipment,
    dispatch_shipment,
)
from apps.tenants.models import Tenant
from tests.test_sc_consolidation_1_local import actor, completed_box, site_and_consolidation


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def packing_standard():
    if not PackingStandardVersion.objects.filter(code="packing-v1", version=1).exists():
        with _packing_domain_write_context():
            PackingStandardVersion.objects.create(
                code="packing-v1", version=1, title="Packing v1", rules={
                    "empty_box_forbidden": True,
                    "exact_completion_required": True,
                    "mixed_box_label_items_required": True,
                },
            )


def ready_consolidation_with_boxes(tenant, user, suffix, count=1):
    boxes = [completed_box(tenant, user, f"{suffix}{index}") for index in range(count)]
    _, consolidation = site_and_consolidation(tenant, user, suffix)
    consolidation, _, _ = allocate_consolidation_boxes(
        consolidation_id=consolidation.id, box_ids=[box.id for box in boxes], actor=user,
        expected_version=consolidation.version, idempotency_key=f"allocate-{suffix}",
    )
    consolidation, _, _ = release_consolidation(
        consolidation_id=consolidation.id, actor=user, expected_version=consolidation.version,
        idempotency_key=f"release-{suffix}",
    )
    for allocation in list(consolidation.allocations.order_by("id")):
        consolidation.refresh_from_db()
        _, _, _ = receive_consolidation_box(
            consolidation_id=consolidation.id, allocation_id=allocation.id, actor=user,
            expected_version=consolidation.version, idempotency_key=f"receive-{suffix}-{allocation.id}",
        )
    consolidation.refresh_from_db()
    consolidation, _, _ = ready_consolidation(
        consolidation_id=consolidation.id, actor=user, expected_version=consolidation.version,
        idempotency_key=f"ready-{suffix}",
    )
    return consolidation, boxes


def test_partial_transfers_support_multiple_shipments_and_preserve_source_projection():
    tenant = Tenant.objects.create(name="Shipment local", code="ship-local")
    user = actor(tenant, "shipment-local-actor")
    consolidation, boxes = ready_consolidation_with_boxes(tenant, user, "PART", count=2)
    first, _, replayed = create_shipment(
        actor=user, shipment_no="SHP-PART-1", region_code=consolidation.region_code,
        idempotency_key="ship-create-1",
    )
    assert replayed is False
    first, _, _ = allocate_shipment_boxes(
        shipment_id=first.id, consolidation_id=consolidation.id,
        allocation_ids=[consolidation.allocations.order_by("id").first().id], actor=user,
        expected_version=first.version, idempotency_key="ship-allocate-1",
    )
    consolidation.refresh_from_db()
    assert consolidation.status == LooseCargoConsolidation.Status.READY_FOR_SHIPMENT
    assert consolidation.allocations.filter(state=ConsolidationBoxAllocation.State.TRANSFERRED).count() == 1
    assert consolidation.allocations.filter(state=ConsolidationBoxAllocation.State.RECEIVED).count() == 1
    assert PackingBoxConsumption.objects.filter(
        tenant=tenant, box__in=boxes, consumer_type=PackingBoxConsumption.ConsumerType.SHIPMENT,
        active_guard=True,
    ).count() == 1

    second, _, _ = create_shipment(
        actor=user, shipment_no="SHP-PART-2", region_code=consolidation.region_code,
        idempotency_key="ship-create-2",
    )
    second, _, _ = allocate_shipment_boxes(
        shipment_id=second.id, consolidation_id=consolidation.id,
        allocation_ids=[consolidation.allocations.filter(state=ConsolidationBoxAllocation.State.RECEIVED).first().id],
        actor=user, expected_version=second.version, idempotency_key="ship-allocate-2",
    )
    consolidation.refresh_from_db()
    assert consolidation.status == LooseCargoConsolidation.Status.TRANSFERRED
    assert ShipmentBoxAllocation.objects.filter(tenant=tenant).count() == 2
    assert not PackingBoxConsumption.objects.filter(
        tenant=tenant, consumer_type=PackingBoxConsumption.ConsumerType.SHIPMENT,
        state=PackingBoxConsumption.State.COMMITTED,
    ).exists()


def test_dispatch_commits_only_selected_boxes_and_is_idempotent():
    tenant = Tenant.objects.create(name="Shipment dispatch", code="ship-dispatch")
    user = actor(tenant, "shipment-dispatch-actor")
    consolidation, _ = ready_consolidation_with_boxes(tenant, user, "DISP", count=2)
    shipment, _, _ = create_shipment(
        actor=user, shipment_no="SHP-DISP", region_code=consolidation.region_code,
        idempotency_key="ship-dispatch-create",
    )
    shipment, _, _ = allocate_shipment_boxes(
        shipment_id=shipment.id, consolidation_id=consolidation.id,
        allocation_ids=list(consolidation.allocations.values_list("id", flat=True)), actor=user,
        expected_version=shipment.version, idempotency_key="ship-dispatch-allocate",
    )
    shipment, _, _ = customs_declare_shipment(
        shipment_id=shipment.id, actor=user, expected_version=shipment.version,
        idempotency_key="ship-customs", customs_reference="CUS-1",
    )
    first_id = shipment.box_allocations.order_by("id").first().id
    shipment, event, replayed = dispatch_shipment(
        shipment_id=shipment.id, actor=user, expected_version=shipment.version,
        allocation_ids=[first_id], idempotency_key="ship-dispatch-one",
    )
    assert replayed is False
    assert event.action == ShipmentEvent.Action.DISPATCH
    first = ShipmentBoxAllocation.objects.get(pk=first_id)
    assert first.state == ShipmentBoxAllocation.State.DISPATCHED
    assert shipment.box_allocations.exclude(pk=first_id).get().state == ShipmentBoxAllocation.State.TRANSFERRED
    target = first.packing_box_consumption
    target.refresh_from_db()
    assert target.state == PackingBoxConsumption.State.COMMITTED
    shipped_before = shipment.box_allocations.filter(state=ShipmentBoxAllocation.State.DISPATCHED).count()
    replay, replay_event, replayed = dispatch_shipment(
        shipment_id=shipment.id, actor=user, expected_version=shipment.version - 1,
        allocation_ids=[first_id], idempotency_key="ship-dispatch-one",
    )
    assert replayed is True
    assert replay_event.id == event.id
    assert replay.box_allocations.filter(state=ShipmentBoxAllocation.State.DISPATCHED).count() == shipped_before
    with pytest.raises(StateConflict):
        dispatch_shipment(
            shipment_id=shipment.id, actor=user, expected_version=shipment.version,
            allocation_ids=[first_id], idempotency_key="ship-dispatch-conflict",
        )


def test_shipment_batch_transfer_rolls_back_when_any_source_is_missing():
    tenant = Tenant.objects.create(name="Shipment rollback", code="ship-rollback")
    user = actor(tenant, "shipment-rollback-actor")
    consolidation, boxes = ready_consolidation_with_boxes(tenant, user, "ROLL", count=2)
    shipment, _, _ = create_shipment(
        actor=user, shipment_no="SHP-ROLL", region_code=consolidation.region_code,
        idempotency_key="ship-rollback-create",
    )
    allocation_ids = list(consolidation.allocations.values_list("id", flat=True))
    with pytest.raises(Exception):
        allocate_shipment_boxes(
            shipment_id=shipment.id, consolidation_id=consolidation.id,
            allocation_ids=allocation_ids + [999999], actor=user,
            expected_version=shipment.version, idempotency_key="ship-rollback-allocate",
        )
    assert not shipment.box_allocations.exists()
    assert consolidation.allocations.filter(state=ConsolidationBoxAllocation.State.RECEIVED).count() == 2
    assert not PackingBoxConsumption.objects.filter(
        tenant=tenant, consumer_type=PackingBoxConsumption.ConsumerType.SHIPMENT,
        active_guard=True,
    ).exists()


def test_shipping_model_and_event_are_protected_from_orm_bypass_and_create_replay():
    tenant = Tenant.objects.create(name="Shipment guard", code="ship-guard")
    user = actor(tenant, "shipment-guard-actor")
    shipment, event, replayed = create_shipment(
        actor=user, shipment_no="SHP-GUARD", region_code="CN-SOUTH", idempotency_key="ship-guard-create",
    )
    assert replayed is False
    replay, replay_event, replayed = create_shipment(
        actor=user, shipment_no="SHP-GUARD", region_code="CN-SOUTH", idempotency_key="ship-guard-create",
    )
    assert replay.id == shipment.id and replay_event.id == event.id and replayed is True
    with pytest.raises(IdempotencyConflict):
        create_shipment(
            actor=user, shipment_no="SHP-GUARD", region_code="CN-NORTH", idempotency_key="ship-guard-create",
        )
    with pytest.raises(DjangoValidationError):
        LooseCargoShipment.objects.filter(pk=shipment.id).update(note="bypass")
    with pytest.raises(DjangoValidationError):
        ShipmentEvent.objects.filter(pk=event.id).update(reason="bypass")
    with pytest.raises(DjangoValidationError):
        shipment.save()
    with pytest.raises(DjangoValidationError):
        event.delete()


def test_cancel_is_only_allowed_for_empty_draft():
    tenant = Tenant.objects.create(name="Shipment cancel", code="ship-cancel")
    user = actor(tenant, "shipment-cancel-actor")
    shipment, _, _ = create_shipment(
        actor=user, shipment_no="SHP-CANCEL", region_code="CN-SOUTH", idempotency_key="ship-cancel-create",
    )
    shipment, event, replayed = cancel_shipment(
        shipment_id=shipment.id, actor=user, expected_version=shipment.version,
        idempotency_key="ship-cancel", reason="No cargo",
    )
    assert replayed is False
    assert shipment.status == LooseCargoShipment.Status.CANCELLED
    assert event.action == ShipmentEvent.Action.CANCEL
    with pytest.raises(StateConflict):
        cancel_shipment(
            shipment_id=shipment.id, actor=user, expected_version=shipment.version,
            idempotency_key="ship-cancel-other", reason="Again",
        )
