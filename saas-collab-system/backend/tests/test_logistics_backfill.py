import pytest
from rest_framework.exceptions import ValidationError

from apps.audit.models import OperationLog
from apps.sales_management.logistics_backfill import business_hash, save_snapshot
from tests.test_sales_management import create_scope, create_order, user_for


def batch_fixture():
    tenant, _, store, _ = create_scope('logistics-only')
    actor = user_for(tenant, 'logistics-actor')
    actor.is_superuser = True
    actor.save(update_fields=['is_superuser'])
    order = create_order(tenant, store, 'logistics-only')
    batch = OperationLog.objects.create(tenant=tenant, user=actor, module='sales_management',
        action='logistics_backfill_started', object_type='SalesOrderLogisticsBackfill',
        after_data={'store_id': store.id, 'orders': [{'id': order.id,
            'external_order_id': order.external_order_id, 'business_hash': business_hash(order)}]})
    facts = {'status': 'ok', 'order_sn': order.external_order_id, 'collected_at_utc': '2026-10-26T00:00:00Z',
             'packages': [{'package_number': 'SYNTHETIC', 'tracking_number': 'SYNTHETIC-TRACK'}],
             'collection_pin_code': 'PRIVATE-PIN'}
    return actor, order, batch, facts


@pytest.mark.django_db
def test_only_logistics_metadata_is_saved_and_prior_snapshot_is_backed_up():
    actor, order, batch, facts = batch_fixture()
    order.source_details['unrelated_metadata'] = 'keep'
    order.source_details['platform_logistics'] = {'status': 'previous'}
    order.save(update_fields=['source_details'])
    before = business_hash(order)
    assert save_snapshot(actor, batch, order.external_order_id, facts) == 'saved'
    order.refresh_from_db()
    assert business_hash(order) == before
    assert order.source_details['unrelated_metadata'] == 'keep'
    assert 'PRIVATE-PIN' not in str(order.source_details)
    audit = OperationLog.objects.get(pk=order.source_details['platform_logistics']['source_operation_id'])
    assert audit.before_data['snapshot'] == {'status': 'previous'}
    assert save_snapshot(actor, batch, order.external_order_id, facts) == 'already_saved'
    assert OperationLog.objects.filter(action='logistics_snapshot_saved').count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize('failure', ['out_of_scope', 'wrong_identity', 'partial', 'business_changed'])
def test_out_of_scope_incomplete_or_changed_orders_are_not_written(failure):
    actor, order, batch, facts = batch_fixture()
    external_id = order.external_order_id
    if failure == 'out_of_scope': external_id = 'NOT-IN-MANIFEST'
    if failure == 'wrong_identity': facts['order_sn'] = 'WRONG'
    if failure == 'partial': facts['status'] = 'partial'
    if failure == 'business_changed':
        order.order_total_amount += 1
        order.save(update_fields=['order_total_amount'])
    with pytest.raises(ValidationError):
        save_snapshot(actor, batch, external_id, facts)
    order.refresh_from_db()
    assert 'platform_logistics' not in order.source_details
    assert not OperationLog.objects.filter(action='logistics_snapshot_saved').exists()


@pytest.mark.django_db
def test_return_snapshot_is_separate_and_idempotent():
    actor, order, batch, facts = batch_fixture()
    facts.update(return_sn='SYNTHETIC-RETURN', buyer_return={'tracking_number': 'RETURN-TRACK'})
    assert save_snapshot(actor, batch, order.external_order_id, facts, return_id='SYNTHETIC-RETURN') == 'saved'
    order.refresh_from_db()
    assert 'platform_logistics' not in order.source_details
    assert order.source_details['platform_return_logistics']['SYNTHETIC-RETURN']['buyer_return']['tracking_number'] == 'RETURN-TRACK'
    from apps.sales_management.serializers import SalesOrderDetailSerializer
    data = SalesOrderDetailSerializer(order).data
    assert data['refund_returns'] == []
    assert data['order_observations']['return_logistics_snapshots'][0]['return_sn'] == 'SYNTHETIC-RETURN'
    assert save_snapshot(actor, batch, order.external_order_id, facts, return_id='SYNTHETIC-RETURN') == 'already_saved'
