import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import RequestFactory
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.packing.models import (
    PackingBatchLineAllocation,
    PackingBoxConsumption,
    PackingBoxConsumptionAction,
    PackingStandardVersion,
    _packing_domain_write_context,
)
from apps.packing.services import (
    add_packing_box,
    cancel_packing_batch,
    complete_packing_batch,
    commit_box_consumption,
    create_packing_batch,
    release_box_consumption,
    reserve_box_consumption,
    transfer_box_consumption,
)
from apps.common.exceptions import StateConflict
from apps.purchasing.models import (
    SupplyFulfillmentEvent,
    SupplyOrderLineFulfillment,
    SupplyPurchaseOrder,
    _ensure_order_line_fulfillment_projections,
    _converge_completed_order_line_fulfillment_projections,
    _supply_action_write_context,
)
from apps.purchasing.supply_services import perform_supply_order_action
from apps.tenants.models import Tenant

from .test_supply_chain_f2_packing_services import (
    create_completed_order,
    create_supplier,
    create_user,
)


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def frozen_standard():
    if not PackingStandardVersion.objects.filter(code="packing-v1", version=1).exists():
        with _packing_domain_write_context():
            PackingStandardVersion.objects.create(
                code="packing-v1",
                version=1,
                title="SC-F2 frozen packing standard v1",
                rules={"empty_box_forbidden": True},
                is_active=True,
            )


def test_multiple_batches_reserve_and_freeze_partial_line_quantity():
    tenant = Tenant.objects.create(name="F2 multi local", code="f2-multi-local")
    actor = create_user(tenant, "f2-multi-local-user")
    supplier = create_supplier(tenant, "F2-MULTI-LOCAL")
    order, lines = create_completed_order(tenant, supplier, actor, "F2-MULTI-LOCAL", (10,))

    first, replayed = create_packing_batch(
        order_ids=[order.id], actor=actor, idempotency_key="f2-multi-create-1"
    )
    second, replayed_second = create_packing_batch(
        order_ids=[order.id], actor=actor, idempotency_key="f2-multi-create-2"
    )
    assert replayed is False
    assert replayed_second is False

    first_box, _, _ = add_packing_box(
        batch_id=first.id,
        actor=actor,
        idempotency_key="f2-multi-add-1",
        expected_version=first.version,
        items=[{"order_line_id": lines[0].id, "quantity": 6}],
    )
    second.refresh_from_db()
    add_packing_box(
        batch_id=second.id,
        actor=actor,
        idempotency_key="f2-multi-add-2",
        expected_version=second.version,
        items=[{"order_line_id": lines[0].id, "quantity": 4}],
    )
    projection = SupplyOrderLineFulfillment.objects.get(order_line=lines[0])
    assert projection.packing_reserved_quantity == 10
    assert projection.packed_quantity == 0

    first.refresh_from_db()
    complete_packing_batch(
        batch_id=first.id,
        actor=actor,
        idempotency_key="f2-multi-complete-1",
        expected_version=first.version,
    )
    projection.refresh_from_db()
    assert projection.packing_reserved_quantity == 4
    assert projection.packed_quantity == 6
    assert SupplyFulfillmentEvent.objects.filter(
        order_line=lines[0], action=SupplyFulfillmentEvent.Action.FREEZE_PACKING
    ).count() == 1

    second.refresh_from_db()
    complete_packing_batch(
        batch_id=second.id,
        actor=actor,
        idempotency_key="f2-multi-complete-2",
        expected_version=second.version,
    )
    projection.refresh_from_db()
    assert projection.packing_reserved_quantity == 0
    assert projection.packed_quantity == 10
    assert PackingBatchLineAllocation.objects.filter(
        batch=first, state=PackingBatchLineAllocation.State.FROZEN
    ).count() == 1


def test_cancel_releases_only_reservation_and_keeps_history():
    tenant = Tenant.objects.create(name="F2 cancel local", code="f2-cancel-local")
    actor = create_user(tenant, "f2-cancel-local-user")
    supplier = create_supplier(tenant, "F2-CANCEL-LOCAL")
    order, lines = create_completed_order(tenant, supplier, actor, "F2-CANCEL-LOCAL", (5,))
    batch, _ = create_packing_batch(
        order_ids=[order.id], actor=actor, idempotency_key="f2-cancel-create"
    )
    add_packing_box(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="f2-cancel-add",
        expected_version=batch.version,
        items=[{"order_line_id": lines[0].id, "quantity": 5}],
    )
    batch.refresh_from_db()
    cancel_packing_batch(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="f2-cancel-action",
        expected_version=batch.version,
    )
    projection = SupplyOrderLineFulfillment.objects.get(order_line=lines[0])
    allocation = PackingBatchLineAllocation.objects.get(batch=batch, order_line=lines[0])
    assert projection.packing_reserved_quantity == 0
    assert allocation.state == PackingBatchLineAllocation.State.RELEASED
    assert batch.batch_orders.get().active_guard is None


def test_box_consumer_slot_and_transfer_are_atomic():
    tenant = Tenant.objects.create(name="F2 consumer local", code="f2-consumer-local")
    actor = create_user(tenant, "f2-consumer-local-user")
    supplier = create_supplier(tenant, "F2-CONSUMER-LOCAL")
    order, lines = create_completed_order(tenant, supplier, actor, "F2-CONSUMER-LOCAL", (2,))
    batch, _ = create_packing_batch(
        order_ids=[order.id], actor=actor, idempotency_key="f2-consume-create"
    )
    add_packing_box(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="f2-consume-add",
        expected_version=batch.version,
        items=[{"order_line_id": lines[0].id, "quantity": 2}],
    )
    batch.refresh_from_db()
    complete_packing_batch(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="f2-consume-complete",
        expected_version=batch.version,
    )
    box = batch.boxes.get()
    source, replayed = reserve_box_consumption(
        box_id=box.id,
        consumer_type=PackingBoxConsumption.ConsumerType.CONSOLIDATION,
        consumer_id=101,
        actor=actor,
        idempotency_key="f2-consume-reserve",
    )
    assert replayed is False
    with pytest.raises(Exception):
        reserve_box_consumption(
            box_id=box.id,
            consumer_type=PackingBoxConsumption.ConsumerType.SHIPMENT,
            consumer_id=202,
            actor=actor,
            idempotency_key="f2-consume-conflict",
        )
    target, replayed = transfer_box_consumption(
        consumption_id=source.id,
        target_consumer_type=PackingBoxConsumption.ConsumerType.SHIPMENT,
        target_consumer_id=202,
        actor=actor,
        idempotency_key="f2-consume-transfer",
    )
    assert replayed is False
    source.refresh_from_db()
    assert source.active_guard is None
    assert target.active_guard is True
    assert target.transferred_from_id == source.id
    assert PackingBoxConsumption.objects.filter(box=box, active_guard=True).count() == 1


def test_multi_line_box_emits_distinct_line_action_fulfillment_keys():
    tenant = Tenant.objects.create(name="F2 event keys", code="f2-event-keys")
    actor = create_user(tenant, "f2-event-keys-user")
    supplier = create_supplier(tenant, "F2-EVENT-KEYS")
    order, lines = create_completed_order(
        tenant, supplier, actor, "F2-EVENT-KEYS", quantities=(2, 3)
    )
    batch, _ = create_packing_batch(
        order_ids=[order.id], actor=actor, idempotency_key="f2-event-keys-create"
    )
    add_packing_box(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="f2-event-keys-add",
        expected_version=batch.version,
        items=[
            {"order_line_id": lines[0].id, "quantity": 2},
            {"order_line_id": lines[1].id, "quantity": 3},
        ],
    )
    batch.refresh_from_db()
    complete_packing_batch(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="f2-event-keys-complete",
        expected_version=batch.version,
    )
    events = list(
        SupplyFulfillmentEvent.objects.filter(
            order_line__in=lines,
            source_type="packing_batch",
            action=SupplyFulfillmentEvent.Action.FREEZE_PACKING,
        ).order_by("order_line_id")
    )
    assert [event.order_line_id for event in events] == [lines[0].id, lines[1].id]
    assert len({event.idempotency_key for event in events}) == 2
    assert all(
        ":line:" in event.idempotency_key and ":action:freeze_packing" in event.idempotency_key
        for event in events
    )


def test_consumption_actions_replay_independently_and_shipment_counts_once():
    tenant = Tenant.objects.create(name="F2 action ledger", code="f2-action-ledger")
    actor = create_user(tenant, "f2-action-ledger-user")
    supplier = create_supplier(tenant, "F2-ACTION-LEDGER")
    order, lines = create_completed_order(
        tenant, supplier, actor, "F2-ACTION-LEDGER", quantities=(2, 2)
    )
    batch, _ = create_packing_batch(
        order_ids=[order.id], actor=actor, idempotency_key="f2-action-ledger-create"
    )
    add_packing_box(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="f2-action-ledger-add",
        expected_version=batch.version,
        items=[{"order_line_id": lines[0].id, "quantity": 2}],
    )
    batch.refresh_from_db()
    add_packing_box(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="f2-action-ledger-add-2",
        expected_version=batch.version,
        items=[{"order_line_id": lines[1].id, "quantity": 2}],
    )
    batch.refresh_from_db()
    complete_packing_batch(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="f2-action-ledger-complete",
        expected_version=batch.version,
    )
    boxes = list(batch.boxes.order_by("sequence"))
    source, _ = reserve_box_consumption(
        box_id=boxes[0].id,
        consumer_type=PackingBoxConsumption.ConsumerType.CONSOLIDATION,
        consumer_id=301,
        actor=actor,
        idempotency_key="f2-action-ledger-reserve-source",
    )
    committed, replayed = commit_box_consumption(
        consumption_id=source.id,
        actor=actor,
        idempotency_key="f2-action-ledger-commit-source",
    )
    assert replayed is False
    replayed_commit, replayed = commit_box_consumption(
        consumption_id=source.id,
        actor=actor,
        idempotency_key="f2-action-ledger-commit-source",
    )
    assert replayed is True
    assert replayed_commit.id == committed.id
    assert PackingBoxConsumptionAction.objects.filter(
        consumption=source, action=PackingBoxConsumptionAction.Action.COMMIT
    ).count() == 1
    with pytest.raises(StateConflict):
        commit_box_consumption(
            consumption_id=source.id,
            actor=actor,
            idempotency_key="f2-action-ledger-commit-source",
            reason="different payload",
        )

    target, replayed = transfer_box_consumption(
        consumption_id=source.id,
        target_consumer_type=PackingBoxConsumption.ConsumerType.SHIPMENT,
        target_consumer_id=401,
        actor=actor,
        idempotency_key="f2-action-ledger-transfer",
    )
    assert replayed is False
    target_replay, replayed = transfer_box_consumption(
        consumption_id=source.id,
        target_consumer_type=PackingBoxConsumption.ConsumerType.SHIPMENT,
        target_consumer_id=401,
        actor=actor,
        idempotency_key="f2-action-ledger-transfer",
    )
    assert replayed is True
    assert target_replay.id == target.id
    projection = SupplyOrderLineFulfillment.objects.get(order_line=lines[0])
    assert projection.shipped_quantity == 0
    shipment, replayed = commit_box_consumption(
        consumption_id=target.id,
        actor=actor,
        idempotency_key="f2-action-ledger-commit-shipment",
    )
    assert replayed is False
    _, replayed = commit_box_consumption(
        consumption_id=target.id,
        actor=actor,
        idempotency_key="f2-action-ledger-commit-shipment",
    )
    assert replayed is True
    projection.refresh_from_db()
    assert projection.shipped_quantity == 2
    assert SupplyFulfillmentEvent.objects.filter(
        order_line=lines[0], action=SupplyFulfillmentEvent.Action.SHIP
    ).count() == 1

    release_source, _ = reserve_box_consumption(
        box_id=boxes[1].id,
        consumer_type=PackingBoxConsumption.ConsumerType.CONSOLIDATION,
        consumer_id=302,
        actor=actor,
        idempotency_key="f2-action-ledger-reserve-release",
    )
    released, replayed = release_box_consumption(
        consumption_id=release_source.id,
        actor=actor,
        idempotency_key="f2-action-ledger-release",
    )
    assert replayed is False
    release_replay, replayed = release_box_consumption(
        consumption_id=release_source.id,
        actor=actor,
        idempotency_key="f2-action-ledger-release",
    )
    assert replayed is True
    assert release_replay.id == released.id
    assert PackingBoxConsumptionAction.objects.filter(
        consumption=release_source, action=PackingBoxConsumptionAction.Action.RELEASE
    ).count() == 1


def test_completed_production_converges_manual_lines_only_without_packing_history():
    tenant = Tenant.objects.create(name="F2 converge", code="f2-converge")
    actor = create_user(tenant, "f2-converge-user")
    supplier = create_supplier(tenant, "F2-CONVERGE")
    order, lines = create_completed_order(
        tenant, supplier, actor, "F2-CONVERGE", quantities=(2, 3)
    )
    order.status = SupplyPurchaseOrder.Status.IN_PRODUCTION
    order.completed_quantity = 1
    with _supply_action_write_context():
        order.save(update_fields=["status", "completed_quantity", "updated_at"])
    _ensure_order_line_fulfillment_projections(order)
    for line in lines:
        projection = SupplyOrderLineFulfillment.objects.get(order_line=line)
        projection.production_completed_quantity = 0
        projection.migration_classification = SupplyOrderLineFulfillment.MigrationClassification.LEGACY_PARTIAL_MANUAL
        projection.needs_manual_allocation = True
        with _supply_action_write_context():
            projection.save(update_fields=["production_completed_quantity", "migration_classification", "needs_manual_allocation", "updated_at"])

    request = RequestFactory().post("/internal/supply/orders/action")
    request.META["REMOTE_ADDR"] = "127.0.0.1"
    perform_supply_order_action(
        order_id=order.id,
        actor=actor,
        action="update_progress",
        idempotency_key="f2-converge-progress",
        request=request,
        completed_quantity=5,
    )
    perform_supply_order_action(
        order_id=order.id,
        actor=actor,
        action="complete_production",
        idempotency_key="f2-converge-complete",
        request=request,
    )
    for line in lines:
        projection = SupplyOrderLineFulfillment.objects.get(order_line=line)
        assert projection.production_completed_quantity == line.quantity
        assert projection.needs_manual_allocation is False
        assert projection.migration_classification == SupplyOrderLineFulfillment.MigrationClassification.LEGACY_FULL_ORDER
        assert SupplyFulfillmentEvent.objects.filter(
            order_line=line,
            stage=SupplyFulfillmentEvent.Stage.PRODUCTION,
            action=SupplyFulfillmentEvent.Action.PRODUCTION_COMPLETE,
        ).count() == 1


def test_completed_production_does_not_overwrite_manual_projection_with_packing_activity():
    tenant = Tenant.objects.create(name="F2 converge guard", code="f2-converge-guard")
    actor = create_user(tenant, "f2-converge-guard-user")
    supplier = create_supplier(tenant, "F2-CONVERGE-GUARD")
    order, lines = create_completed_order(
        tenant, supplier, actor, "F2-CONVERGE-GUARD", quantities=(2,)
    )
    _ensure_order_line_fulfillment_projections(order)
    projection = SupplyOrderLineFulfillment.objects.get(order_line=lines[0])
    projection.production_completed_quantity = 0
    projection.packed_quantity = 0
    projection.packing_reserved_quantity = 0
    projection.migration_classification = SupplyOrderLineFulfillment.MigrationClassification.LEGACY_PARTIAL_MANUAL
    projection.needs_manual_allocation = True
    with _supply_action_write_context():
        projection.save(update_fields=["production_completed_quantity", "migration_classification", "needs_manual_allocation", "updated_at"])
    with _supply_action_write_context():
        SupplyFulfillmentEvent.objects.create(
            tenant=tenant,
            order=order,
            order_line=lines[0],
            stage=SupplyFulfillmentEvent.Stage.PACKING,
            delta_quantity=1,
            source_type="packing_batch",
            source_id="historical-guard",
            source_version=1,
            action=SupplyFulfillmentEvent.Action.RESERVE_PACKING,
            actor=actor,
            idempotency_key="f2-converge-guard-event",
            before_snapshot={"packing_reserved_quantity": 0},
            after_snapshot={"packing_reserved_quantity": 1},
            occurred_at=timezone.now(),
        )
    order.completed_quantity = 2
    with pytest.raises(DjangoValidationError):
        _converge_completed_order_line_fulfillment_projections(
            order, actor=actor, idempotency_key="f2-converge-guard"
        )


def test_new_projection_and_consumption_orm_paths_are_protected():
    with pytest.raises(DjangoValidationError):
        SupplyOrderLineFulfillment.objects.update(version=2)
    with pytest.raises(DjangoValidationError):
        PackingBatchLineAllocation.objects.update(quantity=2)
    with pytest.raises(DjangoValidationError):
        PackingBoxConsumption.objects.update(state=PackingBoxConsumption.State.COMMITTED)
