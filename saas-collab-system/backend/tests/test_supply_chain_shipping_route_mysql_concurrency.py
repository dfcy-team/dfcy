from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest
from django.db import close_old_connections, connection

from apps.audit.models import OperationLog
from apps.common.exceptions import StateConflict
from apps.purchasing.models import SupplyPurchaseOrder, SupplyPurchaseOrderEvent
from apps.purchasing.supply_services import perform_shipping_route_action
from apps.tenants.models import Tenant

from .test_supply_chain_f1_api import create_catalog, create_internal_user
from .test_supply_chain_shipping_route import _completed_order


pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "mysql",
        reason="Shipping-route concurrency verification requires MySQL row-lock semantics.",
    ),
]


def _assign_route(order_id, actor, route, key, barrier):
    close_old_connections()
    try:
        barrier.wait(timeout=10)
        order, _, replayed = perform_shipping_route_action(
            order_id=order_id,
            actor=actor,
            action=SupplyPurchaseOrderEvent.Action.ASSIGN_SHIPPING_ROUTE,
            idempotency_key=key,
            expected_version=1,
            shipping_route=route,
            reason="Concurrent purchasing route decision.",
            request=SimpleNamespace(META={}),
        )
        return "ok", order.shipping_route, replayed
    except StateConflict as exc:
        return "conflict", str(exc.detail), None
    finally:
        close_old_connections()


def test_mysql_competing_route_assignments_commit_one_decision_and_one_audit():
    tenant = Tenant.objects.create(name="Route MySQL", code="route-mysql")
    actor = create_internal_user(tenant, "route-mysql-user")
    supplier, sku = create_catalog(tenant, "ROUTE-MYSQL")
    order = _completed_order(tenant, actor, supplier, sku, "MYSQL")
    barrier = Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=30)
            for future in (
                executor.submit(
                    _assign_route,
                    order.id,
                    actor,
                    SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO,
                    "route-mysql-loose",
                    barrier,
                ),
                executor.submit(
                    _assign_route,
                    order.id,
                    actor,
                    SupplyPurchaseOrder.ShippingRoute.CONTAINER_CARGO,
                    "route-mysql-container",
                    barrier,
                ),
            )
        ]

    assert sorted(result[0] for result in results) == ["conflict", "ok"]
    order.refresh_from_db()
    assert order.shipping_route in {
        SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO,
        SupplyPurchaseOrder.ShippingRoute.CONTAINER_CARGO,
    }
    assert order.version == 2
    assert SupplyPurchaseOrderEvent.objects.filter(
        order=order,
        action=SupplyPurchaseOrderEvent.Action.ASSIGN_SHIPPING_ROUTE,
    ).count() == 1
    assert OperationLog.objects.filter(
        object_type="SupplyPurchaseOrder",
        object_id=str(order.id),
        action="purchase_order.assign_shipping_route",
    ).count() == 1
