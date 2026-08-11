from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError as DRFValidationError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.common.exceptions import BusinessRuleViolation, ScopedResourceNotFound, StateConflict
from apps.packing.models import PackingStandardVersion, _packing_domain_write_context
from apps.packing.services import create_packing_batch
from apps.permissions.models import DataScope, Role, UserRole
from apps.purchasing.models import (
    SupplyPurchaseOrder,
    SupplyPurchaseOrderEvent,
    SupplyPurchaseOrderLine,
    _supply_action_write_context,
)
from apps.purchasing.supply_services import perform_shipping_route_action
from apps.tenants.models import Tenant

from .test_supply_chain_f1_api import (
    create_catalog,
    create_internal_user,
    create_supplier_user,
    ensure_supply_permissions,
)


pytestmark = pytest.mark.django_db


def _request():
    return SimpleNamespace(META={})


def _completed_order(tenant, actor, supplier, sku, suffix="A"):
    order = SupplyPurchaseOrder.objects.create(
        tenant=tenant,
        supplier=supplier,
        order_no=f"ROUTE-PO-{suffix}",
        order_date=timezone.localdate(),
        created_by=actor,
    )
    SupplyPurchaseOrderLine.objects.create(
        tenant=tenant,
        order=order,
        line_no=1,
        sku=sku,
        sku_code_snapshot=sku.sku_code,
        product_name_snapshot=sku.spu.product_name,
        quantity=10,
        unit_price="1.0000",
    )
    order.status = SupplyPurchaseOrder.Status.PRODUCTION_COMPLETED
    order.completed_quantity = 10
    order.production_completed_at = timezone.now()
    with _supply_action_write_context():
        order.save(
            update_fields=[
                "status",
                "completed_quantity",
                "production_completed_at",
                "updated_at",
            ]
        )
    return order


def _route_action(order, actor, action, route, key, reason=""):
    return perform_shipping_route_action(
        order_id=order.id,
        actor=actor,
        action=action,
        idempotency_key=key,
        expected_version=order.version,
        shipping_route=route,
        reason=reason,
        request=_request(),
    )


def _install_packing_standard():
    if not PackingStandardVersion.objects.filter(code="packing-v1", version=1).exists():
        with _packing_domain_write_context():
            PackingStandardVersion.objects.create(
                code="packing-v1",
                version=1,
                title="Shipping-route packing gate test",
                rules={"exact_completion_required": True},
                is_active=True,
            )


def test_create_rejects_route_input_and_defaults_to_undecided():
    tenant = Tenant.objects.create(name="Route Create", code="route-create")
    actor = create_internal_user(tenant, "route-create-user")
    supplier, sku = create_catalog(tenant, "ROUTE-CREATE")
    client = APIClient()
    client.force_authenticate(user=actor)
    payload = {
        "order_no": "ROUTE-CREATE-001",
        "supplier_id": supplier.id,
        "order_date": "2026-08-03",
        "shipping_route": SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO,
        "lines": [
            {
                "line_no": 1,
                "sku_id": sku.id,
                "quantity": 10,
                "unit_price": "1.0000",
            }
        ],
    }

    rejected = client.post(
        "/api/internal/purchasing/supply-orders/",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="route-create-rejected",
    )

    assert rejected.status_code == 400
    assert SupplyPurchaseOrder.objects.count() == 0

    payload.pop("shipping_route")
    created = client.post(
        "/api/internal/purchasing/supply-orders/",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="route-create-valid",
    )

    assert created.status_code == 201
    assert created.json()["data"]["shipping_route"] == SupplyPurchaseOrder.ShippingRoute.UNDECIDED


def test_internal_api_assigns_and_idempotently_replays_shipping_route():
    tenant = Tenant.objects.create(name="Route Assign", code="route-assign")
    actor = create_internal_user(tenant, "route-assign-user")
    supplier, sku = create_catalog(tenant, "ROUTE-ASSIGN")
    order = _completed_order(tenant, actor, supplier, sku)
    client = APIClient()
    client.force_authenticate(user=actor)
    payload = {
        "expected_version": order.version,
        "shipping_route": SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO,
        "reason": "Purchasing confirmed loose cargo.",
    }
    url = f"/api/internal/purchasing/supply-orders/{order.id}/actions/assign-shipping-route/"

    first = client.post(url, payload, format="json", HTTP_IDEMPOTENCY_KEY="route-assign-1")
    replay = client.post(url, payload, format="json", HTTP_IDEMPOTENCY_KEY="route-assign-1")

    assert first.status_code == 200
    assert first.json()["data"]["replayed"] is False
    assert replay.status_code == 200
    assert replay.json()["data"]["replayed"] is True
    assert replay.json()["data"]["order"] == first.json()["data"]["order"]
    order.refresh_from_db()
    assert order.shipping_route == SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO
    assert order.shipping_route_decided_by_id == actor.id
    assert order.shipping_route_decided_at is not None
    assert order.version == 2
    event = SupplyPurchaseOrderEvent.objects.get(
        order=order,
        action=SupplyPurchaseOrderEvent.Action.ASSIGN_SHIPPING_ROUTE,
    )
    assert event.before_shipping_route == SupplyPurchaseOrder.ShippingRoute.UNDECIDED
    assert event.after_shipping_route == SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO
    assert OperationLog.objects.filter(
        object_id=str(order.id),
        action="purchase_order.assign_shipping_route",
    ).count() == 1


def test_route_requires_completed_order_permission_scope_and_internal_actor():
    tenant = Tenant.objects.create(name="Route Scope", code="route-scope")
    actor = create_internal_user(tenant, "route-owner")
    supplier, sku = create_catalog(tenant, "ROUTE-SCOPE")
    order = _completed_order(tenant, actor, supplier, sku)
    pending = SupplyPurchaseOrder.objects.create(
        tenant=tenant,
        supplier=supplier,
        order_no="ROUTE-PENDING",
        order_date=timezone.localdate(),
        created_by=actor,
    )
    client = APIClient()
    client.force_authenticate(user=actor)
    pending_response = client.post(
        f"/api/internal/purchasing/supply-orders/{pending.id}/actions/assign-shipping-route/",
        {"expected_version": pending.version, "shipping_route": "loose_cargo"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="route-pending",
    )
    assert pending_response.status_code == 409

    scoped_actor = create_internal_user(
        tenant,
        "route-scoped-out",
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"supply_purchase_order_ids": []},
    )
    scoped_client = APIClient()
    scoped_client.force_authenticate(user=scoped_actor)
    scoped_response = scoped_client.post(
        f"/api/internal/purchasing/supply-orders/{order.id}/actions/assign-shipping-route/",
        {"expected_version": order.version, "shipping_route": "loose_cargo"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="route-scoped",
    )
    assert scoped_response.status_code == 404

    supplier_user = create_supplier_user(tenant, supplier, "route-supplier")
    supplier_client = APIClient()
    supplier_client.force_authenticate(user=supplier_user)
    supplier_response = supplier_client.post(
        f"/api/external/supplier/purchase-orders/{order.id}/actions/assign-shipping-route/",
        {"expected_version": order.version, "shipping_route": "loose_cargo"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="route-supplier",
    )
    assert supplier_response.status_code == 404


def test_route_same_key_different_payload_and_stale_version_conflict():
    tenant = Tenant.objects.create(name="Route Conflict", code="route-conflict")
    actor = create_internal_user(tenant, "route-conflict-user")
    supplier, sku = create_catalog(tenant, "ROUTE-CONFLICT")
    order = _completed_order(tenant, actor, supplier, sku)
    client = APIClient()
    client.force_authenticate(user=actor)
    url = f"/api/internal/purchasing/supply-orders/{order.id}/actions/assign-shipping-route/"
    first_payload = {"expected_version": order.version, "shipping_route": "loose_cargo"}

    assert client.post(
        url,
        first_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="route-conflict-key",
    ).status_code == 200
    assert client.post(
        url,
        {"expected_version": order.version, "shipping_route": "container_cargo"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="route-conflict-key",
    ).status_code == 409
    assert client.post(
        url,
        {"expected_version": 1, "shipping_route": "container_cargo"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="route-stale-key",
    ).status_code == 409


def test_route_can_change_before_but_not_after_active_packing():
    tenant = Tenant.objects.create(name="Route Change", code="route-change")
    actor = create_internal_user(tenant, "route-change-user")
    supplier, sku = create_catalog(tenant, "ROUTE-CHANGE")
    order = _completed_order(tenant, actor, supplier, sku)

    order, _, _ = _route_action(
        order,
        actor,
        SupplyPurchaseOrderEvent.Action.ASSIGN_SHIPPING_ROUTE,
        SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO,
        "route-initial",
    )
    order, _, _ = _route_action(
        order,
        actor,
        SupplyPurchaseOrderEvent.Action.CHANGE_SHIPPING_ROUTE,
        SupplyPurchaseOrder.ShippingRoute.CONTAINER_CARGO,
        "route-change",
        reason="Purchasing corrected the route before packing.",
    )
    assert order.shipping_route == SupplyPurchaseOrder.ShippingRoute.CONTAINER_CARGO

    _install_packing_standard()
    create_packing_batch(
        order_ids=[order.id],
        actor=actor,
        idempotency_key="route-pack",
    )
    with pytest.raises(StateConflict, match="cannot change"):
        _route_action(
            order,
            actor,
            SupplyPurchaseOrderEvent.Action.CHANGE_SHIPPING_ROUTE,
            SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO,
            "route-change-after-pack",
            reason="This must be blocked.",
        )


def test_packing_rejects_undecided_and_mixed_routes():
    tenant = Tenant.objects.create(name="Route Packing", code="route-packing")
    actor = create_internal_user(tenant, "route-packing-user")
    supplier, sku = create_catalog(tenant, "ROUTE-PACKING")
    undecided = _completed_order(tenant, actor, supplier, sku, "UNDECIDED")
    _install_packing_standard()

    with pytest.raises(StateConflict, match="shipping-route decision"):
        create_packing_batch(
            order_ids=[undecided.id],
            actor=actor,
            idempotency_key="route-pack-undecided",
        )

    loose = _completed_order(tenant, actor, supplier, sku, "LOOSE")
    container = _completed_order(tenant, actor, supplier, sku, "CONTAINER")
    loose, _, _ = _route_action(
        loose,
        actor,
        SupplyPurchaseOrderEvent.Action.ASSIGN_SHIPPING_ROUTE,
        SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO,
        "route-loose",
    )
    container, _, _ = _route_action(
        container,
        actor,
        SupplyPurchaseOrderEvent.Action.ASSIGN_SHIPPING_ROUTE,
        SupplyPurchaseOrder.ShippingRoute.CONTAINER_CARGO,
        "route-container",
    )

    with pytest.raises(BusinessRuleViolation, match="cannot mix"):
        create_packing_batch(
            order_ids=[loose.id, container.id],
            actor=actor,
            idempotency_key="route-pack-mixed",
        )


def test_route_fields_cannot_be_bypassed_through_orm_mutations():
    tenant = Tenant.objects.create(name="Route ORM", code="route-orm")
    actor = create_internal_user(tenant, "route-orm-user")
    supplier, sku = create_catalog(tenant, "ROUTE-ORM")
    order = _completed_order(tenant, actor, supplier, sku)

    order.shipping_route = SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO
    order.shipping_route_decided_at = timezone.now()
    order.shipping_route_decided_by = actor
    order._action_service_write = True
    with pytest.raises(DjangoValidationError, match="audited action service"):
        order.save()
    order.refresh_from_db()

    with pytest.raises(DjangoValidationError, match="audited action service"):
        SupplyPurchaseOrder.objects.filter(pk=order.pk).update(
            shipping_route=SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO
        )

    order.shipping_route = SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO
    with pytest.raises(DjangoValidationError, match="audited action service"):
        SupplyPurchaseOrder.objects.bulk_update([order], ["shipping_route"])

    with pytest.raises(DjangoValidationError, match="audited action service"):
        SupplyPurchaseOrder.objects.create(
            tenant=tenant,
            supplier=supplier,
            order_no="ROUTE-ORM-DIRECT",
            order_date=timezone.localdate(),
            created_by=actor,
            shipping_route=SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO,
            shipping_route_decided_at=timezone.now(),
            shipping_route_decided_by=actor,
        )

    forged_event = SupplyPurchaseOrderEvent(
        tenant=tenant,
        order=order,
        action=SupplyPurchaseOrderEvent.Action.ASSIGN_SHIPPING_ROUTE,
        idempotency_key="forged-route-event",
        actor=actor,
        actor_type=SupplyPurchaseOrderEvent.ActorType.INTERNAL,
        before_status=order.status,
        after_status=order.status,
    )
    forged_event._action_service_write = True
    with pytest.raises(DjangoValidationError, match="audited action service"):
        forged_event.save()


@pytest.mark.parametrize(
    ("controlled_values", "order_suffix"),
    [
        ({"status": SupplyPurchaseOrder.Status.PRODUCTION_COMPLETED}, "STATUS"),
        ({"completed_quantity": 10}, "QUANTITY"),
        ({"production_completed_at": timezone.now()}, "TIMESTAMP"),
        ({"version": 2}, "VERSION"),
    ],
)
def test_new_order_rejects_noncanonical_controlled_state(controlled_values, order_suffix):
    tenant = Tenant.objects.create(
        name=f"Route Initial {order_suffix}",
        code=f"route-initial-{order_suffix.lower()}",
    )
    actor = create_internal_user(tenant, f"route-initial-{order_suffix.lower()}-user")
    supplier, _ = create_catalog(tenant, f"ROUTE-INITIAL-{order_suffix}")

    with pytest.raises(DjangoValidationError, match="canonical defaults"):
        SupplyPurchaseOrder.objects.create(
            tenant=tenant,
            supplier=supplier,
            order_no=f"ROUTE-INITIAL-{order_suffix}",
            order_date=timezone.localdate(),
            created_by=actor,
            **controlled_values,
        )


def test_direct_route_service_enforces_permission_before_idempotency_replay():
    tenant = Tenant.objects.create(name="Route Service Permission", code="route-service-perm")
    owner = create_internal_user(tenant, "route-service-owner")
    supplier, sku = create_catalog(tenant, "ROUTE-SERVICE-PERM")
    order = _completed_order(tenant, owner, supplier, sku)
    order, _, _ = _route_action(
        order,
        owner,
        SupplyPurchaseOrderEvent.Action.ASSIGN_SHIPPING_ROUTE,
        SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO,
        "route-service-existing-key",
    )
    unauthorized = CustomUser.objects.create_user(
        username="route-service-no-permission",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    no_permission = CustomUser.objects.create_user(
        username="route-service-no-permission-role",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    no_permission_role = Role.objects.create(
        tenant=tenant,
        code="route-service-no-permission-role",
        name="No route permission",
    )
    UserRole.objects.create(tenant=tenant, user=no_permission, role=no_permission_role)
    DataScope.objects.create(
        tenant=tenant,
        role=no_permission_role,
        scope_type=DataScope.ScopeType.ALL,
    )
    no_scope = CustomUser.objects.create_user(
        username="route-service-no-scope",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    no_scope_role = Role.objects.create(
        tenant=tenant,
        code="route-service-no-scope-role",
        name="No route scope",
    )
    no_scope_role.permissions.add(*ensure_supply_permissions())
    UserRole.objects.create(tenant=tenant, user=no_scope, role=no_scope_role)

    for denied_actor in (unauthorized, no_permission, no_scope):
        with pytest.raises(PermissionDenied, match="permission"):
            perform_shipping_route_action(
                order_id=order.id,
                actor=denied_actor,
                action=SupplyPurchaseOrderEvent.Action.ASSIGN_SHIPPING_ROUTE,
                idempotency_key="route-service-existing-key",
                expected_version=1,
                shipping_route=SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO,
                reason="",
                request=_request(),
            )


def test_direct_route_service_enforces_datascope():
    tenant = Tenant.objects.create(name="Route Service Scope", code="route-service-scope")
    owner = create_internal_user(tenant, "route-service-scope-owner")
    supplier, sku = create_catalog(tenant, "ROUTE-SERVICE-SCOPE")
    order = _completed_order(tenant, owner, supplier, sku)
    scoped_out = create_internal_user(
        tenant,
        "route-service-scoped-out",
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"supply_purchase_order_ids": []},
    )

    with pytest.raises(ScopedResourceNotFound, match="authorized scope"):
        _route_action(
            order,
            scoped_out,
            SupplyPurchaseOrderEvent.Action.ASSIGN_SHIPPING_ROUTE,
            SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO,
            "route-service-scoped-key",
        )


def test_direct_route_service_supports_own_and_custom_scopes_and_hides_cross_tenant():
    tenant = Tenant.objects.create(name="Route Scope Matrix", code="route-scope-matrix")
    own_actor = create_internal_user(
        tenant,
        "route-own-actor",
        scope_type=DataScope.ScopeType.OWN,
    )
    supplier, sku = create_catalog(tenant, "ROUTE-SCOPE-MATRIX")
    own_order = _completed_order(tenant, own_actor, supplier, sku, "OWN")
    own_result, _, _ = _route_action(
        own_order,
        own_actor,
        SupplyPurchaseOrderEvent.Action.ASSIGN_SHIPPING_ROUTE,
        SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO,
        "route-own-key",
    )
    assert own_result.shipping_route == SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO

    owner = create_internal_user(tenant, "route-custom-owner")
    supplier_order = _completed_order(tenant, owner, supplier, sku, "CUSTOM-SUPPLIER")
    supplier_scoped = create_internal_user(
        tenant,
        "route-custom-supplier",
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"supplier_ids": [supplier.id]},
    )
    supplier_result, _, _ = _route_action(
        supplier_order,
        supplier_scoped,
        SupplyPurchaseOrderEvent.Action.ASSIGN_SHIPPING_ROUTE,
        SupplyPurchaseOrder.ShippingRoute.CONTAINER_CARGO,
        "route-custom-supplier-key",
    )
    assert supplier_result.shipping_route == SupplyPurchaseOrder.ShippingRoute.CONTAINER_CARGO

    order_scoped_order = _completed_order(tenant, owner, supplier, sku, "CUSTOM-ORDER")
    order_scoped = create_internal_user(
        tenant,
        "route-custom-order",
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"supply_purchase_order_ids": [order_scoped_order.id]},
    )
    order_result, _, _ = _route_action(
        order_scoped_order,
        order_scoped,
        SupplyPurchaseOrderEvent.Action.ASSIGN_SHIPPING_ROUTE,
        SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO,
        "route-custom-order-key",
    )
    assert order_result.shipping_route == SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO

    other_tenant = Tenant.objects.create(name="Route Other Tenant", code="route-other-tenant")
    cross_tenant_actor = create_internal_user(other_tenant, "route-cross-tenant")
    hidden_order = _completed_order(tenant, owner, supplier, sku, "CROSS-TENANT")
    with pytest.raises(ScopedResourceNotFound, match="authorized scope"):
        _route_action(
            hidden_order,
            cross_tenant_actor,
            SupplyPurchaseOrderEvent.Action.ASSIGN_SHIPPING_ROUTE,
            SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO,
            "route-cross-tenant-key",
        )


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"idempotency_key": 123}, "idempotency_key"),
        ({"expected_version": True}, "expected_version"),
        ({"expected_version": 0}, "expected_version"),
        ({"reason": {"not": "text"}}, "reason"),
        ({"reason": "x" * 2001}, "reason"),
    ],
)
def test_direct_route_service_validates_contract_types_and_lengths(overrides, field):
    tenant = Tenant.objects.create(name=f"Route Contract {field}", code=f"route-contract-{field}")
    actor = create_internal_user(tenant, f"route-contract-{field}-user")
    supplier, sku = create_catalog(tenant, f"ROUTE-CONTRACT-{field}")
    order = _completed_order(tenant, actor, supplier, sku)
    arguments = {
        "order_id": order.id,
        "actor": actor,
        "action": SupplyPurchaseOrderEvent.Action.ASSIGN_SHIPPING_ROUTE,
        "idempotency_key": f"route-contract-{field}",
        "expected_version": order.version,
        "shipping_route": SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO,
        "reason": "",
        "request": _request(),
    }
    arguments.update(overrides)

    with pytest.raises(DRFValidationError) as exc_info:
        perform_shipping_route_action(**arguments)
    assert field in exc_info.value.detail
