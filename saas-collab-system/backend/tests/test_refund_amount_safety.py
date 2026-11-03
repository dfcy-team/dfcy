from types import SimpleNamespace
from decimal import Decimal

import pytest

from apps.integrations.adapters import MarketplaceRefundAdapter
from apps.sales_management.aftersales import track_source, refresh_case
from apps.sales_management.aftersales_models import AftersalesCase
from apps.sales_management.serializers import SalesOrderSerializer
from apps.sales_management.services import upsert_normalized_refund
from tests.test_sales_management import NOW, create_scope, create_order, create_run


def refund_payload(store, order, status='accepted'):
    return {'store_id': store.id, 'external_order_id': order.external_order_id,
        'external_return_id': 'RETURN', 'requested_at_utc': NOW.isoformat(),
        'updated_at_utc': NOW.isoformat(), 'currency': 'PHP', 'raw_status': status.upper(),
        'normalized_status': status, 'requires_physical_return': True, 'refund_amount': '10',
        'items': [{'external_return_item_id': 'LINE', 'seller_sku': 'SKU', 'quantity': 1}]}


def test_order_summary_separates_completed_accepted_and_cancelled_amounts():
    rows = [SimpleNamespace(id=i, updated_at_utc=NOW, normalized_status=status,
        refund_amount=Decimal(amount), is_partial_quantity_return=False, is_refund_amount_adjusted=False)
        for i, (status, amount) in enumerate([('completed', '20'), ('accepted', '30'), ('cancelled', '40'), ('pending', '50')])]
    summary = SalesOrderSerializer().get_refund_summary(SimpleNamespace(refund_returns=SimpleNamespace(all=lambda: rows)))
    assert summary['refund_amount'] == '20.0000'
    assert summary['accepted_amount'] == '30.0000'
    assert summary['cancelled_amount'] == '40.0000'
    assert summary['case_count'] == 4


@pytest.mark.django_db
def test_cancelled_refund_does_not_create_a_pending_warehouse_return():
    tenant, _, store, _ = create_scope('cancelled-refund-safe')
    order = create_order(tenant, store, 'cancelled-refund-safe')
    run = create_run(tenant, 'refund_return', 'cancelled-refund-safe')
    refund = upsert_normalized_refund(tenant=tenant, source_run=run, payload=refund_payload(store, order, 'cancelled'))
    assert not AftersalesCase.objects.filter(refund=refund).exists()
    assert track_source(refund) is None


@pytest.mark.django_db
def test_later_cancellation_closes_tracking_without_deleting_warehouse_evidence():
    from apps.sales_management.aftersales import ingest_receipt, allocate_line
    from apps.sales_management.aftersales_models import ReturnAllocation
    from tests.test_sales_management import user_for, grant
    tenant, _, store, warehouse = create_scope('later-cancelled-refund')
    order = create_order(tenant, store, 'later-cancelled-refund')
    run = create_run(tenant, 'refund_return', 'later-cancelled-refund')
    payload = refund_payload(store, order)
    refund = upsert_normalized_refund(tenant=tenant, source_run=run, payload=payload)
    case = AftersalesCase.objects.get(refund=refund)
    case.expectation_reviewed = True
    case.save(update_fields=['expectation_reviewed'])
    expected = dict(case.expected_skus)
    user = user_for(tenant, 'cancelled-evidence-user')
    grant(user, 'sales_management.returns.view')
    grant(user, 'sales_management.aftersales.manage')
    receipt, _ = ingest_receipt(user, warehouse, {'return_no': 'ACTUAL-RECEIPT',
        'received_at': NOW.isoformat(), 'lines': [{'sku': 'SKU', 'received_quantity': 1}]}, auto_match=False)
    allocation = allocate_line(user, receipt.lines.get().id, case, 'SKU', 1,
        reason='Synthetic verified receipt', expected_version=receipt.version)
    payload.update(normalized_status='cancelled', raw_status='CANCELLED')
    upsert_normalized_refund(tenant=tenant, source_run=run, payload=payload)
    case.refresh_from_db()
    assert case.return_status == 'cancelled' and case.expected_skus == expected
    refresh_case(case)
    assert case.return_status == 'cancelled'
    assert ReturnAllocation.objects.get(pk=allocation.pk).quantity == 1
    receipt.refresh_from_db()
    assert receipt.received_at == NOW


def normalize(items, total):
    adapter = MarketplaceRefundAdapter(SimpleNamespace(platform='shopee', platform_config={}))
    adapter.authorization = SimpleNamespace(store=SimpleNamespace(id=1, currency='PHP'), region='PH')
    return adapter.normalize_record({'return_sn': 'RETURN', 'order_sn': 'ORDER',
        'status': 'ACCEPTED', 'return_solution': 0, 'create_time': int(NOW.timestamp()),
        'update_time': int(NOW.timestamp()), 'refund_amount': total, 'item': items})


@pytest.mark.parametrize('field', ['refund_amount', 'item_price'])
def test_multi_quantity_amount_is_only_extended_when_it_reconciles_to_header(field):
    payload = normalize([{'item_id': 1, 'model_id': 2, 'amount': 2, field: 524}], 1048)
    item = payload['items'][0]
    assert item['refund_amount'] == '1048'
    assert item['amount_observations']['refund_amount_basis'] == 'unit_times_quantity'
    assert item['amount_observations']['reported_' + field] == '524'


def test_already_extended_line_amount_is_not_multiplied_twice():
    payload = normalize([{'item_id': 1, 'model_id': 2, 'amount': 2, 'refund_amount': 1048}], 1048)
    assert payload['items'][0]['refund_amount'] == '1048'
    assert payload['items'][0]['amount_observations']['refund_amount_basis'] == 'line_total'


def test_unexplained_amount_difference_is_flagged_not_plugged():
    payload = normalize([{'item_id': 1, 'model_id': 2, 'amount': 2, 'refund_amount': 524}], 999)
    assert payload['refund_amount'] == '999'
    assert payload['items'][0]['amount_observations']['refund_amount_basis'] == 'unverified'
    assert payload['items'][0]['amount_observations']['reported_refund_amount'] == '524'


@pytest.mark.django_db
def test_unverified_line_preserves_original_value_and_quantity_but_not_a_false_net_amount():
    from apps.commerce.models import SalesOrder, RefundReturn
    from apps.sales_management.serializers import RefundReturnItemSerializer
    from apps.sales_management.views import _sku_rows
    tenant, _, store, _ = create_scope('unverified-line')
    order = create_order(tenant, store, 'unverified-line')
    run = create_run(tenant, 'refund_return', 'unverified-line')
    payload = refund_payload(store, order, 'completed')
    payload['items'][0].update(refund_amount='524', amount_observations={
        'refund_amount_basis': 'unverified', 'reported_refund_amount': '524', 'reported_quantity': 1})
    refund = upsert_normalized_refund(tenant=tenant, source_run=run, payload=payload)
    item = refund.items.get()
    assert item.refund_amount == 524
    data = RefundReturnItemSerializer(item).data
    assert data['refund_amount'] is None
    assert data['amount_observations']['reported_refund_amount'] == '524'
    rows = _sku_rows(SalesOrder.objects.filter(pk=order.pk), RefundReturn.objects.filter(pk=refund.pk))
    row = next(row for row in rows if row['sku'] == 'SKU')
    assert row['refund_units'] == 1
    assert row['refund_amount'] is None and row['net_sales'] is None
    assert row['unverified_refund_lines'] == 1


@pytest.mark.django_db
def test_cancelled_source_is_visible_as_cancelled_not_an_unknown_return_task():
    from tests.test_sales_management import user_for, grant, client_for
    tenant, _, store, _ = create_scope('cancelled-read')
    order = create_order(tenant, store, 'cancelled-read')
    run = create_run(tenant, 'refund_return', 'cancelled-read')
    refund = upsert_normalized_refund(tenant=tenant, source_run=run, payload=refund_payload(store, order, 'cancelled'))
    user = user_for(tenant, 'cancelled-viewer')
    grant(user, 'sales_management.returns.view')
    client = client_for(user)
    result = client.get('/api/internal/commerce/aftersales/?return_status=cancelled')
    assert result.status_code == 200
    assert result.json()['data']['results'][0]['external_return_id'] == refund.external_return_id
    assert result.json()['data']['results'][0]['return_status'] == 'cancelled'
    assert client.get('/api/internal/commerce/aftersales/?return_status=unknown').json()['data']['count'] == 0
    assert not AftersalesCase.objects.filter(refund=refund).exists()
