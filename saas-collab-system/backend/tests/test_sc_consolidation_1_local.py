import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import CustomUser
from apps.common.exceptions import BusinessRuleViolation, IdempotencyConflict, StateConflict
from apps.consolidation.models import (
    ConsolidationBoxAllocation,
    ConsolidationEvent,
    ConsolidationSite,
    LooseCargoConsolidation,
    _consolidation_domain_write_context,
)
from apps.consolidation.services import (
    allocate_consolidation_boxes,
    cancel_consolidation,
    create_consolidation_site,
    create_loose_cargo_consolidation,
    mark_consolidation_exception,
    receive_consolidation_box,
    ready_consolidation,
    release_consolidation,
)
from apps.masterdata.models import SupplierMaster
from apps.packing.models import (
    PackingBatch,
    PackingBox,
    PackingBoxItem,
    PackingStandardVersion,
    _packing_domain_write_context,
)
from apps.packing.services import add_packing_box, complete_packing_batch, create_packing_batch
from apps.products.models import ProductSKU, ProductSPU
from apps.purchasing.models import SupplyPurchaseOrder, SupplyPurchaseOrderLine, _supply_action_write_context
from apps.tenants.models import Tenant


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


def actor(tenant, username="consolidation-actor"):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)


def completed_box(tenant, user, suffix="A", *, route=SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO):
    supplier = SupplierMaster.objects.create(tenant=tenant, code=f"con-supplier-{suffix.lower()}", name=f"Supplier {suffix}")
    order = SupplyPurchaseOrder.objects.create(
        tenant=tenant, supplier=supplier, order_no=f"CON-PO-{suffix}", order_date=timezone.localdate(), created_by=user,
    )
    spu = ProductSPU.objects.create(tenant=tenant, spu_code=f"CON-SPU-{suffix}", product_name=f"Product {suffix}")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code=f"CON-SKU-{suffix}")
    line = SupplyPurchaseOrderLine.objects.create(
        tenant=tenant, order=order, line_no=1, sku=sku, sku_code_snapshot=sku.sku_code,
        product_name_snapshot=spu.product_name, quantity=4, unit_price="1.0000",
    )
    order.status = SupplyPurchaseOrder.Status.PRODUCTION_COMPLETED
    order.completed_quantity = 4
    order.production_completed_at = timezone.now()
    order.shipping_route = route
    order.shipping_route_decided_at = timezone.now()
    order.shipping_route_decided_by = user
    with _supply_action_write_context():
        order.save(update_fields=["status", "completed_quantity", "production_completed_at", "shipping_route",
                                  "shipping_route_decided_at", "shipping_route_decided_by", "updated_at"])
    batch, _ = create_packing_batch(order_ids=[order.id], actor=user, idempotency_key=f"create-{suffix}")
    box, _, _ = add_packing_box(
        batch_id=batch.id, actor=user, idempotency_key=f"box-{suffix}", expected_version=batch.version,
        items=[{"order_line_id": line.id, "quantity": 4}], weight="2.000", volume="0.100000",
    )
    complete_packing_batch(batch_id=batch.id, actor=user, idempotency_key=f"complete-{suffix}", expected_version=batch.version + 1)
    return box


def site_and_consolidation(tenant, user, suffix="A"):
    site, _, replayed = create_consolidation_site(
        actor=user, site_code=f"SITE-{suffix}", name=f"Site {suffix}", region_code="CN-SOUTH",
        idempotency_key=f"site-{suffix}", address_line="One road", contact_phone="13900000000",
    )
    assert replayed is False
    consolidation, _, replayed = create_loose_cargo_consolidation(
        actor=user, site_id=site.id, consolidation_no=f"LC-{suffix}", idempotency_key=f"con-{suffix}",
    )
    assert replayed is False
    return site, consolidation


def test_lifecycle_freezes_snapshot_and_receive_does_not_ship():
    tenant = Tenant.objects.create(name="Consolidation", code="con-local")
    user = actor(tenant)
    box = completed_box(tenant, user)
    site, consolidation = site_and_consolidation(tenant, user)
    consolidation, _, replayed = allocate_consolidation_boxes(
        consolidation_id=consolidation.id, box_ids=[box.id], actor=user, expected_version=consolidation.version,
        idempotency_key="allocate-A",
    )
    assert replayed is False
    consolidation, _, _ = release_consolidation(
        consolidation_id=consolidation.id, actor=user, expected_version=consolidation.version,
        idempotency_key="release-A",
    )
    frozen = consolidation.release_site_snapshot
    site.name = "Changed after release"
    with pytest.raises(DjangoValidationError):
        site.save()
    allocation = consolidation.allocations.get()
    allocation, _, _ = receive_consolidation_box(
        consolidation_id=consolidation.id, allocation_id=allocation.id, actor=user,
        expected_version=consolidation.version, idempotency_key="receive-A",
    )
    consolidation.refresh_from_db()
    assert consolidation.status == LooseCargoConsolidation.Status.RECEIVING
    assert frozen["name"] == "Site A"
    assert allocation.state == ConsolidationBoxAllocation.State.RECEIVED
    assert not allocation.packing_box_consumption.box.items.filter(pk=-1).exists()
    assert not hasattr(box, "shipped_quantity")
    consolidation, _, _ = ready_consolidation(
        consolidation_id=consolidation.id, actor=user, expected_version=consolidation.version,
        idempotency_key="ready-A",
    )
    assert consolidation.status == LooseCargoConsolidation.Status.READY_FOR_SHIPMENT
    assert consolidation.events.filter(action=ConsolidationEvent.Action.RECEIVE).exists()


def test_multi_box_allocation_rolls_back_if_any_box_is_invalid():
    tenant = Tenant.objects.create(name="Consolidation rollback", code="con-rollback")
    user = actor(tenant, "con-rollback-actor")
    good = completed_box(tenant, user, "GOOD")
    bad = completed_box(tenant, user, "BAD", route=SupplyPurchaseOrder.ShippingRoute.CONTAINER_CARGO)
    _, consolidation = site_and_consolidation(tenant, user, "RB")
    with pytest.raises(BusinessRuleViolation):
        allocate_consolidation_boxes(
            consolidation_id=consolidation.id, box_ids=[good.id, bad.id], actor=user,
            expected_version=consolidation.version, idempotency_key="allocate-rb",
        )
    assert not consolidation.allocations.exists()
    assert not good.consumptions.filter(active_guard=True).exists()


def test_cancel_requires_allocated_boxes_and_releases_consumption():
    tenant = Tenant.objects.create(name="Consolidation cancel", code="con-cancel")
    user = actor(tenant, "con-cancel-actor")
    box = completed_box(tenant, user, "CANCEL")
    _, consolidation = site_and_consolidation(tenant, user, "CA")
    consolidation, _, _ = allocate_consolidation_boxes(
        consolidation_id=consolidation.id, box_ids=[box.id], actor=user, expected_version=consolidation.version,
        idempotency_key="allocate-ca",
    )
    cancel_version = consolidation.version
    consolidation, _, replayed = cancel_consolidation(
        consolidation_id=consolidation.id, actor=user, expected_version=cancel_version,
        idempotency_key="cancel-ca", reason="No longer needed",
    )
    assert replayed is False
    assert consolidation.status == LooseCargoConsolidation.Status.CANCELLED
    assert consolidation.allocations.get().state == ConsolidationBoxAllocation.State.RELEASED
    assert not box.consumptions.filter(active_guard=True).exists()
    replay, _, replayed = cancel_consolidation(
        consolidation_id=consolidation.id, actor=user, expected_version=cancel_version,
        idempotency_key="cancel-ca", reason="No longer needed",
    )
    assert replay.status == LooseCargoConsolidation.Status.CANCELLED
    assert replayed is True


def test_exception_can_be_ready_but_received_cannot_be_cancelled():
    tenant = Tenant.objects.create(name="Consolidation exception", code="con-exception")
    user = actor(tenant, "con-exception-actor")
    box = completed_box(tenant, user, "EX")
    _, consolidation = site_and_consolidation(tenant, user, "EX")
    consolidation, _, _ = allocate_consolidation_boxes(
        consolidation_id=consolidation.id, box_ids=[box.id], actor=user, expected_version=consolidation.version,
        idempotency_key="allocate-ex",
    )
    consolidation, _, _ = release_consolidation(
        consolidation_id=consolidation.id, actor=user, expected_version=consolidation.version,
        idempotency_key="release-ex",
    )
    allocation = consolidation.allocations.get()
    allocation, _, _ = mark_consolidation_exception(
        consolidation_id=consolidation.id, allocation_id=allocation.id, actor=user,
        expected_version=consolidation.version, idempotency_key="exception-ex", reason="Box held for inspection",
        exception_code="HOLD",
    )
    consolidation.refresh_from_db()
    with pytest.raises(StateConflict):
        ready_consolidation(
            consolidation_id=consolidation.id,
            actor=user,
            expected_version=consolidation.version,
            idempotency_key="ready-ex-before-receive",
        )
    allocation, _, _ = receive_consolidation_box(
        consolidation_id=consolidation.id,
        allocation_id=allocation.id,
        actor=user,
        expected_version=consolidation.version,
        idempotency_key="receive-exception-ex",
    )
    consolidation.refresh_from_db()
    consolidation, _, _ = ready_consolidation(
        consolidation_id=consolidation.id, actor=user, expected_version=consolidation.version,
        idempotency_key="ready-ex",
    )
    assert consolidation.status == LooseCargoConsolidation.Status.READY_FOR_SHIPMENT
    with pytest.raises(StateConflict):
        cancel_consolidation(consolidation_id=consolidation.id, actor=user,
                             expected_version=consolidation.version, idempotency_key="cancel-ex",
                             reason="Too late")


def test_model_and_queryset_bypass_are_blocked_and_idempotency_conflict_is_deterministic():
    tenant = Tenant.objects.create(name="Consolidation guards", code="con-guards")
    user = actor(tenant, "con-guards-actor")
    site, _, _ = create_consolidation_site(actor=user, site_code="SITE-G", name="Guard site",
                                            region_code="CN-SOUTH", idempotency_key="site-g")
    with pytest.raises(DjangoValidationError):
        ConsolidationSite.objects.filter(pk=site.id).update(name="raw")
    with pytest.raises(DjangoValidationError):
        site.save()
    with pytest.raises(DjangoValidationError):
        ConsolidationEvent.objects.filter(pk=-1).delete()
    with pytest.raises(IdempotencyConflict):
        create_consolidation_site(actor=user, site_code="SITE-G-OTHER", name="Other",
                                  region_code="CN-SOUTH", idempotency_key="site-g")
