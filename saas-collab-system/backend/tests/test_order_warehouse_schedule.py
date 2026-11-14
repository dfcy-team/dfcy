from datetime import timedelta
from unittest.mock import patch
import pytest
from django.utils import timezone
from apps.commerce.models import SalesOrder
from apps.sales_management.warehouse_order_models import OrderWarehouseLookup
from apps.sales_management.warehouse_orders import request_lookup, synchronize
from apps.sales_management.tasks import dispatch_order_warehouse
from tests.test_order_warehouse_lookup import setup_order, binding, package, response, run

pytestmark = pytest.mark.django_db


def test_unpaid_waits_and_payment_starts_query(setup_order):
    order, actor, _ = setup_order
    SalesOrder.objects.filter(pk=order.pk).update(raw_status='UNPAID', paid_at_utc=None)
    assert request_lookup(order.pk) is None
    assert not OrderWarehouseLookup.objects.filter(order=order).exists()
    order.refresh_from_db()
    with patch('apps.sales_management.warehouse_orders.publish_lookup'):
        order.paid_at_utc = timezone.now()
        order.save(update_fields=['paid_at_utc'])
    assert OrderWarehouseLookup.objects.get(order=order).status == 'pending'


def test_tracking_change_triggers_but_trace_description_does_not(setup_order):
    order, actor, _ = setup_order
    row = request_lookup(order.pk, actor, manual=True)
    row.status = 'matched'
    row.save(update_fields=['status'])
    old = row.revision
    with patch('apps.sales_management.warehouse_orders.publish_lookup'):
        order.source_details = {'packages': [{'package_number': 'PK1', 'tracking_number': 'TRACK1'}]}
        order.save(update_fields=['source_details'])
    row.refresh_from_db()
    assert row.revision != old
    new = row.revision
    order.source_details['packages'][0]['description'] = 'Unrelated text'
    order.save(update_fields=['source_details'])
    row.refresh_from_db()
    assert row.revision == new


def test_running_changes_coalesce_and_old_result_is_discarded(setup_order, django_capture_on_commit_callbacks):
    order, actor, warehouse = setup_order
    binding(order, actor, warehouse)
    row = request_lookup(order.pk, actor, manual=True)
    original = row.revision
    def fetch(*args):
        with django_capture_on_commit_callbacks(execute=True):
            order.raw_status = 'SHIPPED'
            order.save(update_fields=['raw_status'])
            order.raw_status = 'DELIVERED'
            order.save(update_fields=['raw_status'])
        row.refresh_from_db()
        assert row.revision == original and row.followup_required
        return [{'warehouse_order_no': 'WH1'}]
    with patch('apps.sales_management.warehouse_orders.fetch_packages', side_effect=fetch), patch('apps.sales_management.warehouse_orders.publish_lookup') as publish:
        with django_capture_on_commit_callbacks(execute=True):
            assert synchronize(row.pk, str(original)) == 'superseded'
        assert publish.call_count == 1
    row.refresh_from_db()
    assert row.status == 'pending' and row.revision != original and row.snapshot == {}


def test_not_found_backoff_is_bounded_and_keeps_old_binding(setup_order):
    order, actor, warehouse = setup_order
    SalesOrder.objects.filter(pk=order.pk).update(normalized_status='confirmed')
    binding(order, actor, warehouse)
    with patch('apps.sales_management.warehouse_orders.execute_operation', return_value=response([package(order)])):
        _, row = run(order, actor)
    snapshot = row.snapshot
    with patch('apps.sales_management.warehouse_orders.execute_operation', return_value=response([])):
        row = request_lookup(order.pk, actor, manual=True)
        for expected in (10, 30, 120, None):
            synchronize(row.pk, str(row.revision))
            row.refresh_from_db()
            assert row.snapshot == snapshot and row.warehouse_id == warehouse.pk
            if expected is None:
                assert row.next_query_at is None
            else:
                assert expected * 60 - 5 < (row.next_query_at - timezone.now()).total_seconds() <= expected * 60
                row.next_query_at = timezone.now() - timedelta(seconds=1)
                row.save(update_fields=['next_query_at'])
                row = request_lookup(order.pk, actor, scheduled=True)


def test_pending_shipment_polls_and_complete_or_terminal_stops(setup_order):
    order, actor, warehouse = setup_order
    SalesOrder.objects.filter(pk=order.pk).update(normalized_status='confirmed')
    binding(order, actor, warehouse)
    pending = package(order)
    pending.pop('shippedTime')
    with patch('apps.sales_management.warehouse_orders.execute_operation', return_value=response([pending])):
        _, row = run(order, actor)
    assert row.next_query_at and row.next_query_at > timezone.now() + timedelta(minutes=59)
    with patch('apps.sales_management.warehouse_orders.execute_operation', return_value=response([package(order)])):
        _, row = run(order, actor)
    assert row.next_query_at is None
    SalesOrder.objects.filter(pk=order.pk).update(normalized_status='completed')
    with patch('apps.sales_management.warehouse_orders.execute_operation', return_value=response([])):
        _, row = run(order, actor)
    assert row.next_query_at is None


def test_blocked_dispatcher_checks_readiness_without_queue_until_recovered(setup_order, django_capture_on_commit_callbacks):
    order, actor, _ = setup_order
    row = request_lookup(order.pk, actor, manual=True)
    row.status = 'blocked'
    row.next_query_at = timezone.now() - timedelta(seconds=1)
    row.save()
    with patch('apps.sales_management.warehouse_orders.scheduled_ready', return_value=False), patch('apps.sales_management.warehouse_orders.publish_lookup') as publish:
        assert dispatch_order_warehouse()['submitted'] == 0
        assert not publish.called
    row.refresh_from_db()
    assert row.next_query_at > timezone.now()
    row.next_query_at = timezone.now() - timedelta(seconds=1)
    row.save()
    with patch('apps.sales_management.warehouse_orders.scheduled_ready', return_value=True), patch('apps.sales_management.warehouse_orders.publish_lookup') as publish:
        with django_capture_on_commit_callbacks(execute=True):
            assert dispatch_order_warehouse()['submitted'] == 1
        assert publish.call_count == 1


def test_deadline_stops_rechecks_and_untouched_history_is_not_scanned(setup_order):
    order, actor, _ = setup_order
    row = request_lookup(order.pk, actor, manual=True)
    row.status, row.next_query_at, row.polling_until = 'not_found', timezone.now() - timedelta(seconds=1), timezone.now() - timedelta(seconds=1)
    row.save()
    with patch('apps.sales_management.warehouse_orders.publish_lookup') as publish:
        assert dispatch_order_warehouse()['submitted'] == 0
        assert not publish.called
    row.refresh_from_db()
    assert row.next_query_at is None
