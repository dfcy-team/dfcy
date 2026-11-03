from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connection

from apps.common.exceptions import StateConflict
from apps.sales_management.registration_models import OrderRegistration, PendingOrderDetail
from apps.sales_management.registration_services import create_registration, registration_action, set_registration_deleted
from apps.workflows.models import WorkflowAuditEvent
from tests.test_order_registrations import context, exchange

pytestmark = pytest.mark.django_db(transaction=True)


def simultaneous(operation):
    barrier = Barrier(2)
    def invoke():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return operation()
        except StateConflict:
            return "conflict"
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(lambda _: invoke(), range(2)))


def test_mysql_same_exchange_request_is_concurrently_idempotent(context):
    if connection.vendor != "mysql":
        pytest.skip("Requires actual MySQL row locks, not SQLite emulation.")
    creator, _, store, order, sku = context
    payload = {"reason": "并发增加同款", "changes": [{"action": "add", "new_sku_id": sku.pk, "add_quantity": 1}]}
    results = simultaneous(lambda: create_registration(creator, "exchange", store.pk, order.pk, payload, "concurrent-key")[1])
    assert sorted(results) == [False, True]
    assert OrderRegistration.objects.count() == 1


def test_mysql_duplicate_approval_updates_detail_once(context):
    if connection.vendor != "mysql":
        pytest.skip("Requires actual MySQL row locks, not SQLite emulation.")
    creator, reviewer, _, order, _ = context
    row = registration_action(creator, "exchange", exchange(context).pk, "submit")
    results = simultaneous(lambda: registration_action(reviewer, "exchange", row.pk, "approve", expected_version=row.version).status)
    assert sorted(results) == ["completed", "conflict"]
    detail = PendingOrderDetail.objects.get(order=order)
    assert detail.version == 2 and detail.lines[0]["quantity"] == 3
    assert WorkflowAuditEvent.objects.filter(resource_type="order_registration", resource_id=str(row.pk), action="approve").count() == 1


@pytest.mark.parametrize("restore", [False, True])
def test_mysql_concurrent_soft_delete_or_restore_applies_only_once(context, restore):
    if connection.vendor != "mysql":
        pytest.skip("Requires actual MySQL row locks, not SQLite emulation.")
    user = context[0]
    row = exchange(context)
    if restore:
        row = set_registration_deleted(user, "exchange", row.pk, row.version, "先删除")
    results = simultaneous(lambda: set_registration_deleted(user, "exchange", row.pk, row.version, "并发校验", restore=restore).status)
    assert sorted(results) == ["conflict", "draft"]
    saved = OrderRegistration.objects.get(pk=row.pk)
    assert bool(saved.deleted_at) is not restore
    assert WorkflowAuditEvent.objects.filter(resource_type="order_registration", resource_id=str(row.pk), action="restore" if restore else "delete").count() == 1
