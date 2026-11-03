from decimal import Decimal
from types import SimpleNamespace as Row

from apps.finance.summary_cost_classification import classify
from apps.finance.summary_database_document import render


def order(raw='completed', normalized='completed'):
    return Row(pk=1, raw_status=raw, normalized_status=normalized, delivered_at_utc=None)


def refund(status):
    return Row(pk=7, normalized_status=status)


def test_completed_and_original_returned_are_not_confused_with_pending():
    assert classify(order())['category'] == 'normal'
    returned = classify(order('returned', 'pending'))
    assert returned['category'] == 'refund'
    assert returned['evidence']['raw_status'] == 'returned'
    assert '入库' in returned['reason']
    assert classify(order('confirmed', 'confirmed'))['category'] == 'pending'


def test_successful_refund_pending_request_and_cancelled_request_are_distinct():
    assert classify(order(), refunds=[refund('refund_success')])['category'] == 'refund'
    assert classify(order(), refunds=[refund('request_cancel')])['category'] == 'normal'
    assert classify(order(), refunds=[refund('requested')])['category'] == 'pending'
    assert classify(order('confirmed', 'confirmed'), refunds=[refund('refund_success')])['category'] == 'pending'
    assert classify(order(), financial_refund=Decimal('-20'))['category'] == 'refund'


def test_cancelled_cost_needs_shipment_and_never_invents_credit():
    o = order('cancelled', 'cancelled')
    assert classify(o)['category'] == 'pending'
    result = classify(o, shipments=[Row(pk=2)])
    assert result['category'] == 'cancelled_shipped'
    assert result['evidence']['shipment_ids'] == [2]
    assert 'return_credit' not in result


def test_only_explicit_sample_link_classifies_sample_on_any_platform():
    result = classify(order(), samples=[Row(pk=3)])
    assert result['category'] == 'sample'
    assert result['evidence']['sample_ids'] == [3]
    assert classify(None)['category'] == 'pending'


def test_cancelled_refund_case_is_ignored_but_unresolved_case_stays_pending():
    case = Row(pk=9, refund_id=7, return_status='pending')
    assert classify(order(), refunds=[refund('request_cancel')], cases=[case])['category'] == 'normal'
    case.refund_id = None
    assert classify(order(), cases=[case])['category'] == 'pending'


def test_rebuild_installs_saas_classification_once_without_rewriting_original_html():
    template = '<script id="html2-sp6th-fees">function classify(f){const c=f.cost_calculation,e=c.business_evidence;return "pending";}</script>'
    source = {'read_at': '2026-11-02', 'raw': [], 'shopee_income': [], 'sku_members': [], 'cycles': {},
              'recharge': {}, 'sku_sales': {}, 'products': {}}
    first = render(template, source)
    second = render(first, source)
    assert first == second
    assert first.count('// SAAS_COST_CLASSIFICATION') == 1
    assert 'if(c.business_classification)return c.business_classification.category;' in first
    assert 'SAAS_COST_CLASSIFICATION' not in template


def tracked_order(code='1400', description='Your package has been delivered!'):
    o = order('confirmed', 'confirmed')
    o.external_order_id = 'order-1'
    o.source_details = {'platform_logistics': {'status': 'ok', 'order_sn': 'order-1',
        'collected_at_utc': '2026-11-01T00:00:00Z', 'source_operation_id': 8,
        'packages': [{'tracking_query_status': 'ok', 'events': [{'status': code,
            'description': description, 'occurred_at_utc': '2026-09-15T00:00:00Z'}]}]}}
    return o


def test_lazada_saved_delivery_proves_fulfilment_without_rewriting_order_or_cost():
    o = tracked_order()
    result = classify(o, platform='lazada')
    assert result['category'] == 'normal'
    assert result['evidence']['platform_logistics']['status'] == '1400'
    assert classify(o, platform='lazada', refunds=[refund('refund_success')])['category'] == 'refund'
    assert o.raw_status == 'confirmed'
    assert classify(o, platform='shopee')['category'] == 'pending'


def test_label_pickup_failure_and_reverse_delivery_do_not_prove_forward_shipment():
    for code, description in [('1200', 'Your package is packed and will be handed over'),
        ('100051', 'Pickup attempt is unsuccessful'), ('3350', 'Customer Return Parcel has been delivered to Seller/Warehouse'),
        ('1400', 'Unknown status')]:
        assert classify(tracked_order(code, description), platform='lazada')['category'] == 'pending'


def test_unmatched_order_failed_query_and_invalid_event_dates_are_not_evidence():
    o = tracked_order(); s = o.source_details['platform_logistics']
    s['order_sn'] = 'another-order'
    assert classify(o, platform='lazada')['category'] == 'pending'
    s['order_sn'] = o.external_order_id
    package = s['packages'][0]; package['tracking_query_status'] = 'unavailable'
    assert classify(o, platform='lazada')['category'] == 'pending'
    package['tracking_query_status'] = 'ok'
    for value in ['invalid', '2026-11-02T00:00:00Z', '2026-09-01T00:00:00']:
        package['events'][0]['occurred_at_utc'] = value
        assert classify(o, platform='lazada')['category'] == 'pending'


def test_lazada_mixed_returned_item_is_not_hidden_by_confirmed_order_or_delivery():
    result = classify(tracked_order(), platform='lazada', item_statuses=['confirmed', 'returned'])
    assert result['category'] == 'refund'
    assert result['evidence']['item_statuses'] == ['confirmed', 'returned']
    assert '部分退货' in result['reason']
    assert classify(tracked_order(), platform='lazada', item_statuses=['confirmed', 'canceled'])['category'] == 'normal'
