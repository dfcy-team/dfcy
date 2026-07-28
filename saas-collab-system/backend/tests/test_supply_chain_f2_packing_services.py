import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import CustomUser, ExternalUserProfile
from apps.audit.models import OperationLog
from apps.common.exceptions import BusinessRuleViolation, ScopedResourceNotFound, StateConflict
from apps.masterdata.models import StatusChoices, SupplierMaster
from apps.packing.models import (
    PackingBatch,
    PackingBatchOrder,
    PackingBox,
    PackingBoxItem,
    PackingChangeRequest,
    PackingEvent,
    PackingStandardVersion,
    PackingSupplierCapability,
)
from apps.packing.services import (
    add_packing_box,
    approve_packing_change,
    cancel_packing_batch,
    complete_packing_batch,
    create_packing_batch,
    reject_packing_change,
    remove_packing_box,
    replace_packing_box,
    set_supplier_packing_capability,
    submit_packing_change,
)
from apps.products.models import ProductSKU, ProductSPU
from apps.purchasing.models import SupplyPurchaseOrder, SupplyPurchaseOrderLine
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def frozen_standard():
    PackingStandardVersion.objects.get_or_create(
        code="packing-v1",
        version=1,
        defaults={
            "title": "SC-F2 frozen packing standard v1",
            "rules": {
                "empty_box_forbidden": True,
                "exact_completion_required": True,
                "mixed_box_label_items_required": True,
                "single_order_single_sku_recommended": True,
            },
            "is_active": True,
        },
    )


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=user_type,
    )


def create_supplier_user(tenant, supplier, username):
    user = create_user(tenant, username, CustomUser.UserType.EXTERNAL)
    ExternalUserProfile.objects.create(
        user=user,
        tenant=tenant,
        supplier_id=supplier.id,
        company_name=supplier.name,
    )
    return user


def create_supplier(tenant, suffix):
    return SupplierMaster.objects.create(
        tenant=tenant,
        code=f"pack-supplier-{suffix.lower()}",
        name=f"Packing Supplier {suffix}",
    )


def create_completed_order(tenant, supplier, actor, suffix, quantities=(10,)):
    order = SupplyPurchaseOrder.objects.create(
        tenant=tenant,
        supplier=supplier,
        order_no=f"PACK-PO-{suffix}",
        order_date=timezone.localdate(),
        status=SupplyPurchaseOrder.Status.PENDING,
        created_by=actor,
    )
    lines = []
    for index, quantity in enumerate(quantities, start=1):
        spu = ProductSPU.objects.create(
            tenant=tenant,
            spu_code=f"PACK-SPU-{suffix}-{index}",
            product_name=f"Packing product {suffix} {index}",
        )
        sku = ProductSKU.objects.create(
            tenant=tenant,
            spu=spu,
            sku_code=f"PACK-SKU-{suffix}-{index}",
        )
        lines.append(
            SupplyPurchaseOrderLine.objects.create(
                tenant=tenant,
                order=order,
                line_no=index,
                sku=sku,
                sku_code_snapshot=sku.sku_code,
                product_name_snapshot=spu.product_name,
                quantity=quantity,
                unit_price="1.0000",
            )
        )
    order.status = SupplyPurchaseOrder.Status.PRODUCTION_COMPLETED
    order.completed_quantity = sum(quantities)
    order.production_completed_at = timezone.now()
    order._action_service_write = True
    order.save(
        update_fields=[
            "status",
            "completed_quantity",
            "production_completed_at",
            "updated_at",
        ]
    )
    return order, lines


def create_batch(order, actor, key="create-pack"):
    batch, replayed = create_packing_batch(
        order_ids=[order.id],
        actor=actor,
        idempotency_key=key,
        note="SC-F2 local test",
    )
    assert replayed is False
    return batch


def add_exact_box(batch, line, actor, key="add-exact"):
    box, event, replayed = add_packing_box(
        batch_id=batch.id,
        actor=actor,
        idempotency_key=key,
        expected_version=batch.version,
        items=[{"order_line_id": line.id, "quantity": line.quantity}],
        weight="2.500",
        volume="0.125000",
    )
    assert replayed is False
    return box, event


def complete_batch(batch, actor, key="complete-pack"):
    batch.refresh_from_db()
    completed, event, replayed = complete_packing_batch(
        batch_id=batch.id,
        actor=actor,
        idempotency_key=key,
        expected_version=batch.version,
    )
    assert replayed is False
    return completed, event


def test_frozen_standard_and_supplier_capabilities_fail_closed():
    tenant = Tenant.objects.create(name="Packing capability", code="pack-cap")
    supplier = create_supplier(tenant, "CAP")
    internal = create_user(tenant, "pack-cap-internal")
    external = create_supplier_user(tenant, supplier, "pack-cap-external")
    order, _ = create_completed_order(tenant, supplier, internal, "CAP")

    standard = PackingStandardVersion.objects.get(code="packing-v1", version=1)
    assert standard.rules["exact_completion_required"] is True

    with pytest.raises(PermissionDenied):
        create_packing_batch(
            order_ids=[order.id],
            actor=external,
            idempotency_key="cap-denied",
        )

    capability = set_supplier_packing_capability(
        supplier_id=supplier.id,
        actor=internal,
        can_self_pack=True,
    )
    assert capability.can_self_pack is True
    assert capability.can_mix_order_packing is False

    batch, replayed = create_packing_batch(
        order_ids=[order.id],
        actor=external,
        idempotency_key="cap-allowed",
    )
    assert replayed is False
    assert batch.supplier_id == supplier.id


def test_create_batch_is_idempotent_and_rejects_payload_or_supplier_conflicts():
    tenant = Tenant.objects.create(name="Packing create", code="pack-create")
    actor = create_user(tenant, "pack-create-user")
    supplier_a = create_supplier(tenant, "CREATE-A")
    supplier_b = create_supplier(tenant, "CREATE-B")
    order_a, _ = create_completed_order(tenant, supplier_a, actor, "CREATE-A")
    order_b, _ = create_completed_order(tenant, supplier_b, actor, "CREATE-B")

    batch, replayed = create_packing_batch(
        order_ids=[order_a.id],
        actor=actor,
        idempotency_key="create-idem",
    )
    replay, was_replayed = create_packing_batch(
        order_ids=[order_a.id],
        actor=actor,
        idempotency_key="create-idem",
    )

    assert replayed is False
    assert was_replayed is True
    assert replay.id == batch.id
    assert PackingBatch.objects.count() == 1
    assert PackingEvent.objects.filter(action=PackingEvent.Action.CREATE_BATCH).count() == 1

    with pytest.raises(StateConflict):
        create_packing_batch(
            order_ids=[order_b.id],
            actor=actor,
            idempotency_key="create-idem",
        )
    with pytest.raises(BusinessRuleViolation):
        create_packing_batch(
            order_ids=[order_a.id, order_b.id],
            actor=actor,
            idempotency_key="mixed-suppliers",
        )
    with pytest.raises(StateConflict):
        create_packing_batch(
            order_ids=[order_a.id],
            actor=actor,
            idempotency_key="second-active-batch",
        )


def test_create_requires_production_completed_and_current_tenant():
    tenant_a = Tenant.objects.create(name="Packing tenant A", code="pack-tenant-a")
    tenant_b = Tenant.objects.create(name="Packing tenant B", code="pack-tenant-b")
    actor_a = create_user(tenant_a, "pack-tenant-user-a")
    actor_b = create_user(tenant_b, "pack-tenant-user-b")
    supplier_a = create_supplier(tenant_a, "TENANT-A")
    supplier_b = create_supplier(tenant_b, "TENANT-B")
    pending, _ = create_completed_order(tenant_a, supplier_a, actor_a, "PENDING")
    pending.status = SupplyPurchaseOrder.Status.IN_PRODUCTION
    pending._action_service_write = True
    pending.save(update_fields=["status", "updated_at"])
    foreign, _ = create_completed_order(tenant_b, supplier_b, actor_b, "FOREIGN")

    with pytest.raises(StateConflict):
        create_packing_batch(
            order_ids=[pending.id],
            actor=actor_a,
            idempotency_key="pending-order",
        )
    with pytest.raises(ScopedResourceNotFound):
        create_packing_batch(
            order_ids=[foreign.id],
            actor=actor_a,
            idempotency_key="foreign-order",
        )

    completed, _ = create_completed_order(
        tenant_a,
        supplier_a,
        actor_a,
        "INACTIVE-SUPPLIER",
    )
    supplier_a.status = StatusChoices.INACTIVE
    supplier_a.save(update_fields=["status"])
    with pytest.raises(StateConflict):
        create_packing_batch(
            order_ids=[completed.id],
            actor=actor_a,
            idempotency_key="inactive-supplier",
        )


def test_add_box_merges_duplicate_lines_snapshots_and_replays():
    tenant = Tenant.objects.create(name="Packing add", code="pack-add")
    actor = create_user(tenant, "pack-add-user")
    supplier = create_supplier(tenant, "ADD")
    order, lines = create_completed_order(tenant, supplier, actor, "ADD", (10,))
    batch = create_batch(order, actor, "create-add")

    box, event, replayed = add_packing_box(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="add-box-idem",
        expected_version=1,
        items=[
            {"order_line_id": lines[0].id, "quantity": 4},
            {"order_line_id": lines[0].id, "quantity": 6},
        ],
        weight="2.500",
        volume="0.125",
    )
    replay_box, replay_event, was_replayed = add_packing_box(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="add-box-idem",
        expected_version=1,
        items=[
            {"order_line_id": lines[0].id, "quantity": 4},
            {"order_line_id": lines[0].id, "quantity": 6},
        ],
        weight="2.500",
        volume="0.125",
    )

    batch.refresh_from_db()
    item = box.items.get()
    assert replayed is False
    assert was_replayed is True
    assert replay_box.id == box.id
    assert replay_event.id == event.id
    assert item.quantity == 10
    assert item.order_no_snapshot == order.order_no
    assert item.sku_code_snapshot == lines[0].sku_code_snapshot
    assert batch.status == PackingBatch.Status.IN_PROGRESS
    assert batch.version == 2
    assert box.box_no.endswith("-B001")
    assert PackingBox.objects.count() == 1
    assert OperationLog.objects.filter(action="packing.add_box").count() == 1


def test_add_box_rejects_overpack_and_stale_version():
    tenant = Tenant.objects.create(name="Packing quantity", code="pack-quantity")
    actor = create_user(tenant, "pack-quantity-user")
    supplier = create_supplier(tenant, "QUANTITY")
    order, lines = create_completed_order(tenant, supplier, actor, "QUANTITY", (10,))
    batch = create_batch(order, actor, "create-quantity")

    with pytest.raises(StateConflict):
        add_packing_box(
            batch_id=batch.id,
            actor=actor,
            idempotency_key="overpack",
            expected_version=1,
            items=[{"order_line_id": lines[0].id, "quantity": 11}],
        )

    add_packing_box(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="valid-partial",
        expected_version=1,
        items=[{"order_line_id": lines[0].id, "quantity": 5}],
    )
    with pytest.raises(StateConflict):
        add_packing_box(
            batch_id=batch.id,
            actor=actor,
            idempotency_key="stale-version",
            expected_version=1,
            items=[{"order_line_id": lines[0].id, "quantity": 5}],
        )


def test_replace_remove_and_cancel_release_active_order():
    tenant = Tenant.objects.create(name="Packing mutation", code="pack-mutation")
    actor = create_user(tenant, "pack-mutation-user")
    supplier = create_supplier(tenant, "MUTATION")
    order, lines = create_completed_order(tenant, supplier, actor, "MUTATION", (10,))
    batch = create_batch(order, actor, "create-mutation")
    box, _, _ = add_packing_box(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="add-mutation",
        expected_version=1,
        items=[{"order_line_id": lines[0].id, "quantity": 4}],
    )
    batch.refresh_from_db()

    replace_packing_box(
        batch_id=batch.id,
        box_id=box.id,
        actor=actor,
        idempotency_key="replace-mutation",
        expected_version=batch.version,
        items=[{"order_line_id": lines[0].id, "quantity": 6}],
        note="replacement",
    )
    box.refresh_from_db()
    batch.refresh_from_db()
    assert box.items.get().quantity == 6
    assert box.note == "replacement"

    remove_packing_box(
        batch_id=batch.id,
        box_id=box.id,
        actor=actor,
        idempotency_key="remove-mutation",
        expected_version=batch.version,
    )
    batch.refresh_from_db()
    assert batch.status == PackingBatch.Status.DRAFT
    assert batch.boxes.count() == 0

    cancel_packing_batch(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="cancel-mutation",
        expected_version=batch.version,
    )
    batch.refresh_from_db()
    assert batch.status == PackingBatch.Status.CANCELLED
    assert batch.batch_orders.get().active_guard is None

    replacement, replayed = create_packing_batch(
        order_ids=[order.id],
        actor=actor,
        idempotency_key="create-after-cancel",
    )
    assert replayed is False
    assert replacement.id != batch.id


def test_completion_requires_exact_layout_and_does_not_advance_purchase_order():
    tenant = Tenant.objects.create(name="Packing completion", code="pack-complete")
    actor = create_user(tenant, "pack-complete-user")
    supplier = create_supplier(tenant, "COMPLETE")
    order, lines = create_completed_order(tenant, supplier, actor, "COMPLETE", (10, 5))
    batch = create_batch(order, actor, "create-complete")
    add_packing_box(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="add-partial-complete",
        expected_version=1,
        items=[{"order_line_id": lines[0].id, "quantity": 10}],
    )
    batch.refresh_from_db()

    with pytest.raises(BusinessRuleViolation):
        complete_packing_batch(
            batch_id=batch.id,
            actor=actor,
            idempotency_key="inexact-complete",
            expected_version=batch.version,
        )

    add_packing_box(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="add-final-complete",
        expected_version=batch.version,
        items=[{"order_line_id": lines[1].id, "quantity": 5}],
    )
    completed, event = complete_batch(batch, actor)
    order.refresh_from_db()
    replayed_batch, replayed_event, replayed = complete_packing_batch(
        batch_id=batch.id,
        actor=actor,
        idempotency_key="complete-pack",
        expected_version=completed.version - 1,
    )

    assert completed.status == PackingBatch.Status.COMPLETED
    assert completed.completed_at is not None
    assert event.after_status == PackingBatch.Status.COMPLETED
    assert replayed is True
    assert replayed_batch.id == completed.id
    assert replayed_event.id == event.id
    assert order.status == SupplyPurchaseOrder.Status.PRODUCTION_COMPLETED

    with pytest.raises(StateConflict):
        add_packing_box(
            batch_id=batch.id,
            actor=actor,
            idempotency_key="add-after-complete",
            expected_version=completed.version,
            items=[{"order_line_id": lines[0].id, "quantity": 1}],
        )


def test_completed_change_requires_different_reviewer_and_applies_one_version():
    tenant = Tenant.objects.create(name="Packing change", code="pack-change")
    submitter = create_user(tenant, "pack-change-submitter")
    reviewer = create_user(tenant, "pack-change-reviewer")
    supplier = create_supplier(tenant, "CHANGE")
    order, lines = create_completed_order(tenant, supplier, submitter, "CHANGE", (10,))
    batch = create_batch(order, submitter, "create-change")
    add_exact_box(batch, lines[0], submitter, "add-change")
    complete_batch(batch, submitter, "complete-change")
    batch.refresh_from_db()

    proposed = [
        {
            "weight": "1.500",
            "volume": "0.100000",
            "items": [{"order_line_id": lines[0].id, "quantity": 4}],
        },
        {
            "weight": "2.000",
            "volume": "0.150000",
            "items": [{"order_line_id": lines[0].id, "quantity": 6}],
        },
    ]
    change, _, _ = submit_packing_change(
        batch_id=batch.id,
        actor=submitter,
        idempotency_key="submit-change",
        expected_version=batch.version,
        reason="Split the completed carton",
        proposed_boxes=proposed,
    )

    with pytest.raises(PermissionDenied):
        approve_packing_change(
            change_request_id=change.id,
            reviewer=submitter,
            idempotency_key="self-approve",
        )

    approved, event, replayed = approve_packing_change(
        change_request_id=change.id,
        reviewer=reviewer,
        idempotency_key="approve-change",
        review_note="Validated locally",
    )
    replay, replay_event, was_replayed = approve_packing_change(
        change_request_id=change.id,
        reviewer=reviewer,
        idempotency_key="approve-change",
        review_note="Validated locally",
    )
    batch.refresh_from_db()

    assert replayed is False
    assert was_replayed is True
    assert replay.id == approved.id
    assert replay_event.id == event.id
    assert approved.status == PackingChangeRequest.Status.APPROVED
    assert approved.applied_version == batch.version
    assert batch.status == PackingBatch.Status.COMPLETED
    assert batch.boxes.count() == 2
    assert sum(
        PackingBoxItem.objects.filter(box__batch=batch)
        .values_list("quantity", flat=True)
    ) == 10
    assert PackingEvent.objects.filter(
        batch=batch,
        action=PackingEvent.Action.APPLY_CHANGE,
    ).count() == 1


def test_change_reject_and_stale_approval_preserve_completed_layout():
    tenant = Tenant.objects.create(name="Packing rejection", code="pack-reject")
    submitter = create_user(tenant, "pack-reject-submitter")
    reviewer = create_user(tenant, "pack-reject-reviewer")
    supplier = create_supplier(tenant, "REJECT")
    order, lines = create_completed_order(tenant, supplier, submitter, "REJECT", (10,))
    batch = create_batch(order, submitter, "create-reject")
    add_exact_box(batch, lines[0], submitter, "add-reject")
    complete_batch(batch, submitter, "complete-reject")
    batch.refresh_from_db()
    original_box_id = batch.boxes.get().id
    proposed = [
        {"items": [{"order_line_id": lines[0].id, "quantity": 10}]}
    ]

    change, _, _ = submit_packing_change(
        batch_id=batch.id,
        actor=submitter,
        idempotency_key="submit-reject",
        expected_version=batch.version,
        reason="Rejected local proposal",
        proposed_boxes=proposed,
    )
    rejected, _, _ = reject_packing_change(
        change_request_id=change.id,
        reviewer=reviewer,
        idempotency_key="reject-change",
        review_note="Insufficient reason",
    )
    assert rejected.status == PackingChangeRequest.Status.REJECTED
    assert PackingBox.objects.filter(pk=original_box_id).exists()

    second, _, _ = submit_packing_change(
        batch_id=batch.id,
        actor=submitter,
        idempotency_key="submit-stale",
        expected_version=batch.version,
        reason="Stale local proposal",
        proposed_boxes=proposed,
    )
    batch.version += 1
    batch._domain_service_write = True
    batch.save(update_fields=["version", "updated_at"])
    with pytest.raises(StateConflict):
        approve_packing_change(
            change_request_id=second.id,
            reviewer=reviewer,
            idempotency_key="approve-stale",
        )
    second.refresh_from_db()
    assert second.status == PackingChangeRequest.Status.PENDING


def test_orm_bypass_paths_and_completed_instances_are_rejected():
    tenant = Tenant.objects.create(name="Packing ORM", code="pack-orm")
    actor = create_user(tenant, "pack-orm-user")
    supplier = create_supplier(tenant, "ORM")
    order, lines = create_completed_order(tenant, supplier, actor, "ORM", (10,))
    batch = create_batch(order, actor, "create-orm")
    box, _ = add_exact_box(batch, lines[0], actor, "add-orm")
    complete_batch(batch, actor, "complete-orm")
    batch.refresh_from_db()
    item = box.items.get()
    event = batch.events.first()
    link = batch.batch_orders.get()

    with pytest.raises(DjangoValidationError):
        PackingBatch.objects.filter(pk=batch.pk).update(note="tampered")
    with pytest.raises(DjangoValidationError):
        PackingBox.objects.filter(pk=box.pk).update(weight="99.000")
    with pytest.raises(DjangoValidationError):
        PackingBoxItem.objects.bulk_update([item], ["quantity"])
    with pytest.raises(DjangoValidationError):
        PackingEvent.objects.bulk_create([])
    with pytest.raises(DjangoValidationError):
        PackingEvent.objects.filter(pk=event.pk).delete()
    with pytest.raises(DjangoValidationError):
        PackingBatchOrder.objects.filter(pk=link.pk).delete()

    batch.note = "tampered"
    with pytest.raises(DjangoValidationError):
        batch.save()
    item.quantity = 1
    with pytest.raises(DjangoValidationError):
        item.save()


def test_cross_tenant_box_action_is_hidden():
    tenant_a = Tenant.objects.create(name="Packing hidden A", code="pack-hidden-a")
    tenant_b = Tenant.objects.create(name="Packing hidden B", code="pack-hidden-b")
    actor_a = create_user(tenant_a, "pack-hidden-user-a")
    actor_b = create_user(tenant_b, "pack-hidden-user-b")
    supplier = create_supplier(tenant_a, "HIDDEN")
    order, lines = create_completed_order(tenant_a, supplier, actor_a, "HIDDEN", (10,))
    batch = create_batch(order, actor_a, "create-hidden")

    with pytest.raises(ScopedResourceNotFound):
        add_packing_box(
            batch_id=batch.id,
            actor=actor_b,
            idempotency_key="cross-tenant-box",
            expected_version=batch.version,
            items=[{"order_line_id": lines[0].id, "quantity": 10}],
        )


def test_external_supplier_cannot_mix_orders_without_capability():
    tenant = Tenant.objects.create(name="Packing mixed", code="pack-mixed")
    internal = create_user(tenant, "pack-mixed-internal")
    supplier = create_supplier(tenant, "MIXED")
    external = create_supplier_user(tenant, supplier, "pack-mixed-external")
    order_a, _ = create_completed_order(tenant, supplier, internal, "MIXED-A")
    order_b, _ = create_completed_order(tenant, supplier, internal, "MIXED-B")
    set_supplier_packing_capability(
        supplier_id=supplier.id,
        actor=internal,
        can_self_pack=True,
        can_mix_order_packing=False,
    )

    with pytest.raises(PermissionDenied):
        create_packing_batch(
            order_ids=[order_a.id, order_b.id],
            actor=external,
            idempotency_key="mixed-disabled",
        )

    set_supplier_packing_capability(
        supplier_id=supplier.id,
        actor=internal,
        can_self_pack=True,
        can_mix_order_packing=True,
    )
    batch, replayed = create_packing_batch(
        order_ids=[order_a.id, order_b.id],
        actor=external,
        idempotency_key="mixed-enabled",
    )
    assert replayed is False
    assert PackingBatchOrder.objects.filter(batch=batch, active_guard=True).count() == 2
    assert PackingSupplierCapability.objects.get(supplier=supplier).can_mix_order_packing is True
