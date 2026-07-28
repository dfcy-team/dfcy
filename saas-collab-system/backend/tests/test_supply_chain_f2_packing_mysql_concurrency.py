from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import close_old_connections, connection

from apps.common.exceptions import StateConflict
from apps.packing.models import (
    PackingBatch,
    PackingBox,
    PackingBoxItem,
    PackingEvent,
    PackingStandardVersion,
)
from apps.packing.services import (
    add_packing_box,
    approve_packing_change,
    create_packing_batch,
    submit_packing_change,
)
from apps.tenants.models import Tenant

from .test_supply_chain_f2_packing_services import (
    add_exact_box,
    complete_batch,
    create_batch,
    create_completed_order,
    create_supplier,
    create_user,
)


pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "mysql",
        reason="SC-F2 concurrency verification requires MySQL row locks and unique-key semantics.",
    ),
]


@pytest.fixture(autouse=True)
def frozen_standard():
    PackingStandardVersion.objects.get_or_create(
        code="packing-v1",
        version=1,
        defaults={
            "title": "SC-F2 frozen packing standard v1",
            "rules": {"exact_completion_required": True},
            "is_active": True,
        },
    )


def _thread_create(order_id, actor, key, barrier):
    close_old_connections()
    try:
        barrier.wait(timeout=10)
        batch, replayed = create_packing_batch(
            order_ids=[order_id],
            actor=actor,
            idempotency_key=key,
        )
        return "ok", batch.id, replayed
    except StateConflict as exc:
        return "conflict", str(exc.detail), None
    finally:
        close_old_connections()


def _thread_add(batch_id, line_id, actor, key, barrier):
    close_old_connections()
    try:
        barrier.wait(timeout=10)
        box, _, replayed = add_packing_box(
            batch_id=batch_id,
            actor=actor,
            idempotency_key=key,
            expected_version=1,
            items=[{"order_line_id": line_id, "quantity": 10}],
        )
        return "ok", box.id, replayed
    except StateConflict as exc:
        return "conflict", str(exc.detail), None
    finally:
        close_old_connections()


def _thread_approve(change_request_id, reviewer, key, barrier):
    close_old_connections()
    try:
        barrier.wait(timeout=10)
        change, _, replayed = approve_packing_change(
            change_request_id=change_request_id,
            reviewer=reviewer,
            idempotency_key=key,
            review_note="Concurrent MySQL approval",
        )
        return "ok", change.id, replayed
    except StateConflict as exc:
        return "conflict", str(exc.detail), None
    finally:
        close_old_connections()


def test_mysql_concurrent_create_same_key_replays_one_batch():
    tenant = Tenant.objects.create(name="SC-F2 MySQL create", code="sc-f2-mysql-create")
    actor = create_user(tenant, "sc-f2-mysql-create-user")
    supplier = create_supplier(tenant, "MYSQL-CREATE")
    order, _ = create_completed_order(tenant, supplier, actor, "MYSQL-CREATE", (10,))
    barrier = Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=20)
            for future in [
                executor.submit(
                    _thread_create,
                    order.id,
                    actor,
                    "mysql-same-create",
                    barrier,
                )
                for _ in range(2)
            ]
        ]

    assert [result[0] for result in results] == ["ok", "ok"], results
    assert len({result[1] for result in results}) == 1
    assert sorted(result[2] for result in results) == [False, True]
    assert PackingBatch.objects.filter(
        tenant=tenant,
        creation_idempotency_key="mysql-same-create",
    ).count() == 1


def test_mysql_concurrent_create_different_keys_allows_one_active_batch():
    tenant = Tenant.objects.create(name="SC-F2 MySQL active", code="sc-f2-mysql-active")
    actor = create_user(tenant, "sc-f2-mysql-active-user")
    supplier = create_supplier(tenant, "MYSQL-ACTIVE")
    order, _ = create_completed_order(tenant, supplier, actor, "MYSQL-ACTIVE", (10,))
    barrier = Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=20)
            for future in [
                executor.submit(
                    _thread_create,
                    order.id,
                    actor,
                    key,
                    barrier,
                )
                for key in ("mysql-active-a", "mysql-active-b")
            ]
        ]

    assert sorted(result[0] for result in results) == ["conflict", "ok"]
    assert PackingBatch.objects.filter(tenant=tenant).count() == 1


def test_mysql_concurrent_box_actions_cannot_overpack_or_reuse_version():
    tenant = Tenant.objects.create(name="SC-F2 MySQL box", code="sc-f2-mysql-box")
    actor = create_user(tenant, "sc-f2-mysql-box-user")
    supplier = create_supplier(tenant, "MYSQL-BOX")
    order, lines = create_completed_order(tenant, supplier, actor, "MYSQL-BOX", (10,))
    batch = create_batch(order, actor, "mysql-create-box")
    barrier = Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=20)
            for future in [
                executor.submit(
                    _thread_add,
                    batch.id,
                    lines[0].id,
                    actor,
                    key,
                    barrier,
                )
                for key in ("mysql-add-a", "mysql-add-b")
            ]
        ]

    assert sorted(result[0] for result in results) == ["conflict", "ok"]
    assert PackingBox.objects.filter(batch=batch).count() == 1
    assert PackingBoxItem.objects.filter(box__batch=batch).get().quantity == 10


def test_mysql_concurrent_same_box_action_replays_original_result():
    tenant = Tenant.objects.create(name="SC-F2 MySQL replay", code="sc-f2-mysql-replay")
    actor = create_user(tenant, "sc-f2-mysql-replay-user")
    supplier = create_supplier(tenant, "MYSQL-REPLAY")
    order, lines = create_completed_order(tenant, supplier, actor, "MYSQL-REPLAY", (10,))
    batch = create_batch(order, actor, "mysql-create-replay")
    barrier = Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=20)
            for future in [
                executor.submit(
                    _thread_add,
                    batch.id,
                    lines[0].id,
                    actor,
                    "mysql-add-replay",
                    barrier,
                )
                for _ in range(2)
            ]
        ]

    assert [result[0] for result in results] == ["ok", "ok"], results
    assert len({result[1] for result in results}) == 1
    assert sorted(result[2] for result in results) == [False, True]
    assert PackingBox.objects.filter(batch=batch).count() == 1


def test_mysql_concurrent_change_approval_applies_once():
    tenant = Tenant.objects.create(name="SC-F2 MySQL approval", code="sc-f2-mysql-approval")
    submitter = create_user(tenant, "sc-f2-mysql-approval-submitter")
    reviewer = create_user(tenant, "sc-f2-mysql-approval-reviewer")
    supplier = create_supplier(tenant, "MYSQL-APPROVAL")
    order, lines = create_completed_order(
        tenant,
        supplier,
        submitter,
        "MYSQL-APPROVAL",
        (10,),
    )
    batch = create_batch(order, submitter, "mysql-create-approval")
    add_exact_box(batch, lines[0], submitter, "mysql-add-approval")
    complete_batch(batch, submitter, "mysql-complete-approval")
    batch.refresh_from_db()
    change, _, _ = submit_packing_change(
        batch_id=batch.id,
        actor=submitter,
        idempotency_key="mysql-submit-approval",
        expected_version=batch.version,
        reason="Concurrent approval verification",
        proposed_boxes=[
            {"items": [{"order_line_id": lines[0].id, "quantity": 10}]}
        ],
    )
    barrier = Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=20)
            for future in [
                executor.submit(
                    _thread_approve,
                    change.id,
                    reviewer,
                    key,
                    barrier,
                )
                for key in ("mysql-approve-a", "mysql-approve-b")
            ]
        ]

    assert sorted(result[0] for result in results) == ["conflict", "ok"]
    assert PackingEvent.objects.filter(
        batch=batch,
        action=PackingEvent.Action.APPLY_CHANGE,
    ).count() == 1


def test_mysql_packing_orm_bulk_paths_remain_closed():
    tenant = Tenant.objects.create(name="SC-F2 MySQL ORM", code="sc-f2-mysql-orm")
    actor = create_user(tenant, "sc-f2-mysql-orm-user")
    supplier = create_supplier(tenant, "MYSQL-ORM")
    order, lines = create_completed_order(tenant, supplier, actor, "MYSQL-ORM", (10,))
    batch = create_batch(order, actor, "mysql-create-orm")
    box, _, _ = add_packing_box(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="mysql-add-orm",
        expected_version=1,
        items=[{"order_line_id": lines[0].id, "quantity": 10}],
    )
    item = box.items.get()
    event = PackingEvent.objects.filter(batch=batch).first()

    with pytest.raises(DjangoValidationError):
        PackingBatch.objects.filter(pk=batch.pk).update(status=PackingBatch.Status.COMPLETED)
    with pytest.raises(DjangoValidationError):
        PackingBox.objects.filter(pk=box.pk).delete()
    with pytest.raises(DjangoValidationError):
        PackingBoxItem.objects.bulk_update([item], ["quantity"])
    with pytest.raises(DjangoValidationError):
        PackingEvent.objects.filter(pk=event.pk).update(payload={"tampered": True})
