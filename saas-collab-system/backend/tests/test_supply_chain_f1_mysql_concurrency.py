from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import close_old_connections, connection
from rest_framework.test import APIClient

from apps.audit.models import OperationLog
from apps.permissions.models import Permission
from apps.purchasing.models import (
    SupplyProductionProgress,
    SupplyPurchaseOrder,
    SupplyPurchaseOrderEvent,
    SupplyPurchaseOrderLine,
)
from apps.purchasing.supply_serializers import SupplyPurchaseOrderCreateSerializer
from apps.purchasing import views_supply

from .test_supply_chain_f1_api import (
    SUPPLY_PERMISSION_CODES,
    create_catalog,
    create_internal_user,
    create_order,
    internal_client,
)
from apps.tenants.models import Tenant


pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "mysql",
        reason="SC-F1 concurrency verification requires MySQL row locks and unique-key semantics.",
    ),
]


@pytest.fixture(autouse=True)
def supply_permission_fixture():
    for code in SUPPLY_PERMISSION_CODES:
        Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": code,
                "module": "supply",
                "action": code.rsplit(".", 1)[-1],
                "description": "SC-F1 MySQL concurrency test permission.",
            },
        )


def _create_payload(supplier, sku, order_no):
    return {
        "order_no": order_no,
        "supplier_id": supplier.id,
        "order_date": "2026-07-25",
        "expected_delivery_date": "2026-08-25",
        "currency": "CNY",
        "notes": "MySQL concurrency verification",
        "lines": [
            {
                "line_no": 1,
                "sku_id": sku.id,
                "quantity": 100,
                "unit_price": "12.5000",
                "expected_delivery_date": "2026-08-25",
            }
        ],
    }


def _thread_post(user, path, payload, idempotency_key):
    close_old_connections()
    try:
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(
            path,
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )
        return response.status_code, response.json()
    finally:
        close_old_connections()


def test_mysql_concurrent_create_replays_unique_idempotency_result(monkeypatch):
    tenant = Tenant.objects.create(name="SC-F1 MySQL Create", code="sc-f1-mysql-create")
    user = create_internal_user(tenant, "sc-f1-mysql-create-user")
    supplier, sku = create_catalog(tenant, "MYSQL-CREATE")
    payload = _create_payload(supplier, sku, "SC-MYSQL-CONCURRENT-CREATE")
    path = "/api/internal/purchasing/supply-orders/"
    barrier = Barrier(2)
    original_create = SupplyPurchaseOrderCreateSerializer.create

    def synchronized_create(serializer, validated_data):
        barrier.wait(timeout=10)
        return original_create(serializer, validated_data)

    monkeypatch.setattr(SupplyPurchaseOrderCreateSerializer, "create", synchronized_create)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                _thread_post,
                user,
                path,
                payload,
                "mysql-concurrent-create-key",
            )
            for _ in range(2)
        ]
        responses = [future.result(timeout=20) for future in futures]

    assert sorted(status for status, _ in responses) == [200, 201]
    order_ids = {body["data"]["id"] for _, body in responses}
    assert len(order_ids) == 1
    assert SupplyPurchaseOrder.objects.filter(
        tenant=tenant,
        creation_idempotency_key="mysql-concurrent-create-key",
    ).count() == 1
    assert OperationLog.objects.filter(
        tenant=tenant,
        module="supply_chain",
        action="purchase_order.create",
    ).count() == 1


def test_mysql_concurrent_action_serializes_and_replays_original_result(monkeypatch):
    tenant = Tenant.objects.create(name="SC-F1 MySQL Action", code="sc-f1-mysql-action")
    user = create_internal_user(tenant, "sc-f1-mysql-action-user")
    supplier, sku = create_catalog(tenant, "MYSQL-ACTION")
    order_id = create_order(
        internal_client(user),
        supplier,
        sku,
        "SC-MYSQL-CONCURRENT-ACTION",
    ).json()["data"]["id"]
    path = f"/api/internal/purchasing/supply-orders/{order_id}/actions/accept/"
    barrier = Barrier(2)
    original_perform = views_supply.perform_supply_order_action

    def synchronized_perform(**kwargs):
        barrier.wait(timeout=10)
        return original_perform(**kwargs)

    monkeypatch.setattr(views_supply, "perform_supply_order_action", synchronized_perform)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                _thread_post,
                user,
                path,
                {},
                "mysql-concurrent-accept-key",
            )
            for _ in range(2)
        ]
        responses = [future.result(timeout=20) for future in futures]

    assert [status for status, _ in responses] == [200, 200]
    response_orders = [body["data"]["order"] for _, body in responses]
    assert response_orders[0] == response_orders[1]
    assert sorted(body["data"]["replayed"] for _, body in responses) == [False, True]
    order = SupplyPurchaseOrder.objects.get(pk=order_id)
    assert order.status == SupplyPurchaseOrder.Status.ACCEPTED
    assert order.version == 2
    assert SupplyPurchaseOrderEvent.objects.filter(
        order=order,
        idempotency_key="mysql-concurrent-accept-key",
    ).count() == 1
    assert OperationLog.objects.filter(
        tenant=tenant,
        module="supply_chain",
        action="purchase_order.accept",
        object_id=str(order_id),
    ).count() == 1


def test_mysql_orm_bulk_paths_cannot_mutate_accepted_or_audit_records():
    tenant = Tenant.objects.create(name="SC-F1 MySQL ORM", code="sc-f1-mysql-orm")
    user = create_internal_user(tenant, "sc-f1-mysql-orm-user")
    supplier, sku = create_catalog(tenant, "MYSQL-ORM")
    order_id = create_order(
        internal_client(user),
        supplier,
        sku,
        "SC-MYSQL-ORM-GUARD",
    ).json()["data"]["id"]
    accepted = internal_client(user).post(
        f"/api/internal/purchasing/supply-orders/{order_id}/actions/accept/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="mysql-orm-accept",
    )
    assert accepted.status_code == 200

    order = SupplyPurchaseOrder.objects.get(pk=order_id)
    line = order.lines.get()
    event = order.events.get()
    progress = SupplyProductionProgress.objects.create(
        tenant=tenant,
        order=order,
        completed_quantity=0,
        progress_percent="0.00",
        note="MySQL append-only check",
        actor=user,
        request_id="mysql-orm-progress",
    )

    with pytest.raises(DjangoValidationError):
        SupplyPurchaseOrderLine.objects.create(
            tenant=tenant,
            order=order,
            line_no=2,
            sku=sku,
            sku_code_snapshot=sku.sku_code,
            product_name_snapshot=sku.spu.product_name,
            quantity=1,
            unit_price="1.0000",
        )
    with pytest.raises(DjangoValidationError):
        SupplyPurchaseOrderLine.objects.filter(pk=line.pk).update(quantity=999)
    with pytest.raises(DjangoValidationError):
        SupplyPurchaseOrderLine.objects.filter(pk=line.pk).delete()
    with pytest.raises(DjangoValidationError):
        SupplyPurchaseOrderEvent.objects.filter(pk=event.pk).update(payload={"tampered": True})
    with pytest.raises(DjangoValidationError):
        SupplyPurchaseOrderEvent.objects.filter(pk=event.pk).delete()
    with pytest.raises(DjangoValidationError):
        SupplyProductionProgress.objects.filter(pk=progress.pk).update(note="tampered")
    with pytest.raises(DjangoValidationError):
        SupplyProductionProgress.objects.filter(pk=progress.pk).delete()
    with pytest.raises(DjangoValidationError):
        SupplyPurchaseOrder.objects.filter(pk=order.pk).delete()
