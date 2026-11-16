from datetime import timedelta
import uuid
from unittest.mock import patch

import pytest
from django.utils import timezone
from apps.sales_management.warehouse_order_models import OrderWarehouseLookup as Lookup
from apps.sales_management.warehouse_orders import publish_lookup, request_lookup, synchronize
from apps.sales_management.tasks import dispatch_order_warehouse
from tests.test_order_warehouse_lookup import setup_order, binding, package, response

pytestmark = pytest.mark.django_db


def pending(setup_order):
    order, actor, _ = setup_order
    return request_lookup(order.pk, actor, manual=True)


def test_one_delivery_and_stale_callback_dropped(setup_order):
    row = pending(setup_order)
    with patch('apps.sales_management.tasks.synchronize_order_warehouse.apply_async') as send:
        assert not publish_lookup(row.pk, uuid.uuid4())
        assert publish_lookup(row.pk, row.revision)
        assert not publish_lookup(row.pk, row.revision)
        assert send.call_count == 1
    row.refresh_from_db()
    assert row.status == 'pending' and row.lease and row.lease_until > timezone.now()


def test_broker_failure_releases_claim_for_retry(setup_order):
    row = pending(setup_order)
    with patch('apps.sales_management.tasks.synchronize_order_warehouse.apply_async', side_effect=RuntimeError('secret')):
        assert not publish_lookup(row.pk, row.revision)
    row.refresh_from_db()
    assert row.lease is None and row.lease_until is None and 'secret' not in row.message
    with patch('apps.sales_management.tasks.synchronize_order_warehouse.apply_async'):
        assert publish_lookup(row.pk, row.revision)


@pytest.mark.parametrize('state', ['pending', 'running'])
def test_expired_claim_or_execution_is_recoverable(setup_order, state):
    row = pending(setup_order)
    old = uuid.uuid4()
    Lookup.objects.filter(pk=row.pk).update(status=state, lease=old, lease_until=timezone.now()-timedelta(seconds=1), followup_required=True)
    with patch('apps.sales_management.tasks.synchronize_order_warehouse.apply_async'):
        assert publish_lookup(row.pk, row.revision)
    row.refresh_from_db()
    assert row.status == 'pending' and row.lease != old and row.followup_required
    assert not Lookup.objects.filter(pk=row.pk, revision=row.revision, lease=old).exists()


def test_active_execution_is_never_republished(setup_order):
    row = pending(setup_order)
    Lookup.objects.filter(pk=row.pk).update(status='running', lease=uuid.uuid4(), lease_until=timezone.now()+timedelta(minutes=10))
    with patch('apps.sales_management.tasks.synchronize_order_warehouse.apply_async') as send:
        assert not publish_lookup(row.pk, row.revision)
        send.assert_not_called()


def test_dispatch_skips_live_delivery_claim(setup_order):
    row = pending(setup_order)
    with patch('apps.sales_management.tasks.synchronize_order_warehouse.apply_async') as send:
        assert publish_lookup(row.pk, row.revision)
        assert dispatch_order_warehouse()['submitted'] == 0
        assert send.call_count == 1


def test_pending_delivery_can_execute_normal_query(setup_order):
    order, actor, warehouse = setup_order
    binding(order, actor, warehouse)
    row = pending(setup_order)
    with patch('apps.sales_management.tasks.synchronize_order_warehouse.apply_async'):
        assert publish_lookup(row.pk, row.revision)
    with patch('apps.sales_management.warehouse_orders.execute_operation', return_value=response([package(order)])):
        assert synchronize(row.pk, str(row.revision)) == 'matched'
    row.refresh_from_db()
    assert row.snapshot['packages'] and row.lease is None


def test_ambiguous_failure_does_not_clear_execution_lease(setup_order):
    row = pending(setup_order)
    execution = uuid.uuid4()
    def accepted_then_failed(**kwargs):
        Lookup.objects.filter(pk=row.pk).update(status='running', lease=execution)
        raise RuntimeError('ambiguous')
    with patch('apps.sales_management.tasks.synchronize_order_warehouse.apply_async', side_effect=accepted_then_failed):
        assert not publish_lookup(row.pk, row.revision)
    row.refresh_from_db()
    assert row.status == 'running' and row.lease == execution


def test_dispatch_permission_cache_reduces_queries_without_skipping_order_scope(setup_order):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from rest_framework.exceptions import PermissionDenied
    from apps.sales_management.warehouse_orders import require_access
    order, actor, _ = setup_order
    cache = {}
    with CaptureQueriesContext(connection) as first:
        require_access(actor, order, permission_cache=cache)
    with CaptureQueriesContext(connection) as second:
        require_access(actor, order, permission_cache=cache)
    assert len(second) < len(first)
    with patch('apps.sales_management.warehouse_orders.filter_sales_queryset') as scope:
        scope.return_value.exists.return_value = False
        with pytest.raises(PermissionDenied):
            require_access(actor, order, permission_cache=cache)
