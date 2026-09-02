from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, connection, transaction
from django.db import close_old_connections

from apps.common.exceptions import StateConflict
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
    commit_box_consumption,
    complete_packing_batch,
    create_packing_batch,
    reserve_box_consumption,
    transfer_box_consumption,
)
from apps.purchasing.models import (
    SupplyFulfillmentEvent,
    SupplyOrderLineFulfillment,
    _supply_action_write_context,
)
from apps.tenants.models import Tenant

from .test_supply_chain_f2_packing_services import (
    create_completed_order,
    create_supplier,
    create_user,
)


pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "mysql",
        reason="SC-F2-MULTI-1 MySQL gate requires MySQL row locks and checks.",
    ),
]


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


def _thread_call(barrier, callback):
    close_old_connections()
    try:
        barrier.wait(timeout=15)
        return ("ok", callback())
    except Exception as exc:  # keep both DB conflict forms observable
        return ("error", exc)
    finally:
        close_old_connections()


def _add_quantity(batch_id, line_id, quantity, actor, key, barrier):
    return _thread_call(
        barrier,
        lambda: add_packing_box(
            batch_id=batch_id,
            actor=actor,
            idempotency_key=key,
            expected_version=1,
            items=[{"order_line_id": line_id, "quantity": quantity}],
        ),
    )


def test_mysql_same_line_six_plus_four_and_overage_competition_is_conserved():
    tenant = Tenant.objects.create(name="SC-F2 MySQL line race", code="sc-f2-mysql-line-race")
    actor = create_user(tenant, "sc-f2-mysql-line-race-user")
    supplier = create_supplier(tenant, "MYSQL-LINE-RACE")
    order, lines = create_completed_order(tenant, supplier, actor, "MYSQL-LINE-RACE", (10,))
    batches = [
        create_packing_batch(
            order_ids=[order.id],
            actor=actor,
            idempotency_key=f"mysql-line-batch-{index}",
        )[0]
        for index in range(1, 5)
    ]

    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first_wave = [
            future.result(timeout=30)
            for future in (
                executor.submit(_add_quantity, batches[0].id, lines[0].id, 6, actor, "mysql-line-6", barrier),
                executor.submit(_add_quantity, batches[1].id, lines[0].id, 4, actor, "mysql-line-4", barrier),
            )
        ]
    assert [result[0] for result in first_wave] == ["ok", "ok"], first_wave

    # Once 6+4 is reserved, two concurrent overage attempts cannot create any
    # additional allocation and the projection remains exactly at the line
    # quantity.
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        overage = [
            future.result(timeout=30)
            for future in (
                executor.submit(_add_quantity, batches[2].id, lines[0].id, 1, actor, "mysql-line-over-1", barrier),
                executor.submit(_add_quantity, batches[3].id, lines[0].id, 1, actor, "mysql-line-over-2", barrier),
            )
        ]
    assert all(result[0] == "error" for result in overage), overage
    projection = SupplyOrderLineFulfillment.objects.get(order_line=lines[0])
    assert projection.packing_reserved_quantity == 10
    assert projection.packed_quantity == 0
    assert PackingBatchLineAllocation.objects.filter(
        order_line=lines[0], state=PackingBatchLineAllocation.State.RESERVED
    ).aggregate(total=__import__("django.db.models").db.models.Sum("quantity"))["total"] == 10


def test_mysql_complete_cancel_race_has_one_terminal_batch_state():
    tenant = Tenant.objects.create(name="SC-F2 MySQL terminal race", code="sc-f2-mysql-terminal")
    actor = create_user(tenant, "sc-f2-mysql-terminal-user")
    supplier = create_supplier(tenant, "MYSQL-TERMINAL-RACE")
    order, lines = create_completed_order(tenant, supplier, actor, "MYSQL-TERMINAL-RACE", (10,))
    batch, _ = create_packing_batch(
        order_ids=[order.id], actor=actor, idempotency_key="mysql-terminal-batch"
    )
    add_packing_box(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="mysql-terminal-add",
        expected_version=1,
        items=[{"order_line_id": lines[0].id, "quantity": 10}],
    )
    batch.refresh_from_db()
    barrier = Barrier(2)

    def complete():
        return complete_packing_batch(
            batch_id=batch.id,
            actor=actor,
            idempotency_key="mysql-terminal-complete",
            expected_version=2,
        )

    def cancel():
        return cancel_packing_batch(
            batch_id=batch.id,
            actor=actor,
            idempotency_key="mysql-terminal-cancel",
            expected_version=2,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=30)
            for future in (executor.submit(_thread_call, barrier, complete), executor.submit(_thread_call, barrier, cancel))
        ]
    assert sorted(result[0] for result in results) == ["error", "ok"], results
    batch.refresh_from_db()
    assert batch.status in {batch.Status.COMPLETED, batch.Status.CANCELLED}
    assert PackingBatchLineAllocation.objects.filter(batch=batch).count() == 1
    projection = SupplyOrderLineFulfillment.objects.get(order_line=lines[0])
    if batch.status == batch.Status.COMPLETED:
        assert projection.packed_quantity == 10
        assert projection.packing_reserved_quantity == 0
    else:
        assert projection.packed_quantity == 0
        assert projection.packing_reserved_quantity == 0


def test_mysql_same_box_dual_consumption_has_one_active_slot():
    tenant = Tenant.objects.create(name="SC-F2 MySQL box race", code="sc-f2-mysql-box-race")
    actor = create_user(tenant, "sc-f2-mysql-box-race-user")
    supplier = create_supplier(tenant, "MYSQL-BOX-RACE")
    order, lines = create_completed_order(tenant, supplier, actor, "MYSQL-BOX-RACE", (2,))
    batch, _ = create_packing_batch(
        order_ids=[order.id], actor=actor, idempotency_key="mysql-box-race-batch"
    )
    add_packing_box(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="mysql-box-race-add",
        expected_version=1,
        items=[{"order_line_id": lines[0].id, "quantity": 2}],
    )
    batch.refresh_from_db()
    complete_packing_batch(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="mysql-box-race-complete",
        expected_version=2,
    )
    box = batch.boxes.get()
    barrier = Barrier(2)

    def reserve(consumer_type, consumer_id, key):
        return reserve_box_consumption(
            box_id=box.id,
            consumer_type=consumer_type,
            consumer_id=consumer_id,
            actor=actor,
            idempotency_key=key,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=30)
            for future in (
                executor.submit(_thread_call, barrier, lambda: reserve(PackingBoxConsumption.ConsumerType.CONSOLIDATION, 101, "mysql-box-consolidation")),
                executor.submit(_thread_call, barrier, lambda: reserve(PackingBoxConsumption.ConsumerType.SHIPMENT, 202, "mysql-box-shipment")),
            )
        ]
    assert sorted(result[0] for result in results) == ["error", "ok"], results
    assert PackingBoxConsumption.objects.filter(box=box, active_guard=True).count() == 1


def test_mysql_transfer_and_repeated_shipment_commit_count_once():
    tenant = Tenant.objects.create(name="SC-F2 MySQL transfer", code="sc-f2-mysql-transfer")
    actor = create_user(tenant, "sc-f2-mysql-transfer-user")
    supplier = create_supplier(tenant, "MYSQL-TRANSFER")
    order, lines = create_completed_order(tenant, supplier, actor, "MYSQL-TRANSFER", (2,))
    batch, _ = create_packing_batch(
        order_ids=[order.id], actor=actor, idempotency_key="mysql-transfer-batch"
    )
    add_packing_box(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="mysql-transfer-add",
        expected_version=1,
        items=[{"order_line_id": lines[0].id, "quantity": 2}],
    )
    batch.refresh_from_db()
    complete_packing_batch(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="mysql-transfer-complete",
        expected_version=2,
    )
    box = batch.boxes.get()
    source, _ = reserve_box_consumption(
        box_id=box.id,
        consumer_type=PackingBoxConsumption.ConsumerType.CONSOLIDATION,
        consumer_id=301,
        actor=actor,
        idempotency_key="mysql-transfer-reserve",
    )
    commit_box_consumption(
        consumption_id=source.id,
        actor=actor,
        idempotency_key="mysql-transfer-commit-source",
    )
    target, replayed = transfer_box_consumption(
        consumption_id=source.id,
        target_consumer_type=PackingBoxConsumption.ConsumerType.SHIPMENT,
        target_consumer_id=401,
        actor=actor,
        idempotency_key="mysql-transfer-action",
    )
    assert replayed is False
    replay_target, replayed = transfer_box_consumption(
        consumption_id=source.id,
        target_consumer_type=PackingBoxConsumption.ConsumerType.SHIPMENT,
        target_consumer_id=401,
        actor=actor,
        idempotency_key="mysql-transfer-action",
    )
    assert replayed is True
    assert replay_target.id == target.id
    commit_box_consumption(
        consumption_id=target.id,
        actor=actor,
        idempotency_key="mysql-transfer-commit-shipment",
    )
    _, replayed = commit_box_consumption(
        consumption_id=target.id,
        actor=actor,
        idempotency_key="mysql-transfer-commit-shipment",
    )
    assert replayed is True
    projection = SupplyOrderLineFulfillment.objects.get(order_line=lines[0])
    assert projection.shipped_quantity == 2
    assert SupplyFulfillmentEvent.objects.filter(
        order_line=lines[0], action=SupplyFulfillmentEvent.Action.SHIP
    ).count() == 1
    assert PackingBoxConsumptionAction.objects.filter(
        action=PackingBoxConsumptionAction.Action.TRANSFER,
        idempotency_key="mysql-transfer-action",
    ).count() == 1


def test_mysql_orm_bypass_and_fulfillment_check_constraint_are_closed():
    tenant = Tenant.objects.create(name="SC-F2 MySQL constraints", code="sc-f2-mysql-constraints")
    actor = create_user(tenant, "sc-f2-mysql-constraints-user")
    supplier = create_supplier(tenant, "MYSQL-CONSTRAINTS")
    order, lines = create_completed_order(tenant, supplier, actor, "MYSQL-CONSTRAINTS", (2,))
    projection = SupplyOrderLineFulfillment.objects.get(order_line=lines[0])
    with pytest.raises(DjangoValidationError):
        SupplyOrderLineFulfillment.objects.update(version=projection.version + 1)
    with pytest.raises(DjangoValidationError):
        SupplyOrderLineFulfillment.objects.bulk_update([projection], ["version"])

    # Bypass the service gate at SQL level only to prove MySQL enforces the
    # projection's reserved+packed <= production check constraint.
    table = projection._meta.db_table
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE `{table}` SET packing_reserved_quantity = 1, "
                    "packed_quantity = 2, production_completed_quantity = 2 WHERE id = %s",
                    [projection.id],
                )

    with pytest.raises(DjangoValidationError):
        PackingBoxConsumptionAction.objects.update(action=PackingBoxConsumptionAction.Action.RELEASE)
