"""SC-SHIPMENT-1 MySQL-only concurrency and constraint gate."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import close_old_connections, connection

from apps.accounts.models import CustomUser
from apps.common.exceptions import IdempotencyConflict, StateConflict
from apps.consolidation.models import ConsolidationBoxAllocation
from apps.shipping.models import LooseCargoShipment, ShipmentBoxAllocation, ShipmentEvent
from apps.shipping.services import allocate_shipment_boxes, create_shipment
from apps.tenants.models import Tenant
from tests.test_sc_shipment_1_local import (
    actor,
    packing_standard,
    ready_consolidation_with_boxes,
)


pytestmark = pytest.mark.django_db(transaction=True)


def _mysql_only():
    if connection.vendor != "mysql":
        pytest.skip("SC-SHIPMENT-1 MySQL gate test")


def _threaded(callable_):
    close_old_connections()
    try:
        return callable_()
    finally:
        close_old_connections()


def test_mysql_concurrent_create_same_key_replays_stably(packing_standard):
    _mysql_only()
    tenant = Tenant.objects.create(name="Shipment MySQL create", code="ship-mysql-create")
    user = actor(tenant, "ship-mysql-create-actor")

    def create_once():
        worker = CustomUser.objects.get(pk=user.id)
        return create_shipment(
            actor=worker,
            shipment_no="SHP-MYSQL-RACE",
            region_code="CN-SOUTH",
            idempotency_key="ship-mysql-race",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _threaded(create_once), (1, 2)))
    assert sorted(bool(result[2]) for result in results) == [False, True]
    assert len({result[0].id for result in results}) == 1
    assert ShipmentEvent.objects.filter(tenant=tenant, idempotency_key="ship-mysql-race").count() == 1
    with pytest.raises(IdempotencyConflict):
        create_shipment(
            actor=user,
            shipment_no="SHP-MYSQL-RACE",
            region_code="CN-NORTH",
            idempotency_key="ship-mysql-race",
        )


def test_mysql_concurrent_box_transfer_has_one_active_slot_and_batch_rollback(packing_standard):
    _mysql_only()
    tenant = Tenant.objects.create(name="Shipment MySQL transfer", code="ship-mysql-transfer")
    user = actor(tenant, "ship-mysql-transfer-actor")
    consolidation, boxes = ready_consolidation_with_boxes(tenant, user, "MTR", count=2)
    first, _, _ = create_shipment(
        actor=user, shipment_no="SHP-MYSQL-1", region_code=consolidation.region_code,
        idempotency_key="ship-mysql-one-create",
    )
    second, _, _ = create_shipment(
        actor=user, shipment_no="SHP-MYSQL-2", region_code=consolidation.region_code,
        idempotency_key="ship-mysql-two-create",
    )
    allocation_id = consolidation.allocations.order_by("id").first().id

    def allocate_once(shipment_id, key):
        worker = CustomUser.objects.get(pk=user.id)
        shipment = LooseCargoShipment.objects.get(pk=shipment_id)
        try:
            result = allocate_shipment_boxes(
                shipment_id=shipment.id,
                consolidation_id=consolidation.id,
                allocation_ids=[allocation_id],
                actor=worker,
                expected_version=shipment.version,
                idempotency_key=key,
            )
            return "ok", result[0].id
        except (StateConflict, IdempotencyConflict):
            return "conflict", None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda args: _threaded(lambda: allocate_once(*args)),
            ((first.id, "ship-mysql-allocate-a"), (second.id, "ship-mysql-allocate-b")),
        ))
    assert [kind for kind, _ in results].count("ok") == 1
    assert ShipmentBoxAllocation.objects.filter(tenant=tenant, box_id=boxes[0].id).count() == 1
    assert ConsolidationBoxAllocation.objects.filter(
        tenant=tenant, id=allocation_id,
    ).exclude(state=ConsolidationBoxAllocation.State.RECEIVED).count() == 1

    # A mixed valid/missing batch is rejected before any source is transferred.
    winner_id = next(value for kind, value in results if kind == "ok")
    loser_id = second.id if winner_id == first.id else first.id
    loser = LooseCargoShipment.objects.get(pk=loser_id)
    remaining_id = consolidation.allocations.order_by("id").last().id
    with pytest.raises(Exception):
        allocate_shipment_boxes(
            shipment_id=loser.id,
            consolidation_id=consolidation.id,
            allocation_ids=[remaining_id, 999999],
            actor=user,
            expected_version=loser.version,
            idempotency_key="ship-mysql-batch-invalid",
        )
    assert not ShipmentBoxAllocation.objects.filter(shipment=loser).exists()


def test_mysql_shipping_models_reject_orm_shortcuts(packing_standard):
    _mysql_only()
    tenant = Tenant.objects.create(name="Shipment MySQL guard", code="ship-mysql-guard")
    user = actor(tenant, "ship-mysql-guard-actor")
    shipment, event, _ = create_shipment(
        actor=user, shipment_no="SHP-MYSQL-GUARD", region_code="CN-SOUTH",
        idempotency_key="ship-mysql-guard-create",
    )
    with pytest.raises(DjangoValidationError):
        LooseCargoShipment.objects.filter(pk=shipment.id).update(note="bypass")
    with pytest.raises(DjangoValidationError):
        ShipmentEvent.objects.bulk_create([])
    with pytest.raises(DjangoValidationError):
        event.delete()
