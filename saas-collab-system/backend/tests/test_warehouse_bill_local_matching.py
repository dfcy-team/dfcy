import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.finance.warehouse_bill_matching import LocalOrderLookup
from apps.integrations.models import SyncRawEnvelope
from apps.integrations.raw_services import payload_digest
from tests.test_sales_management import create_order, create_scope, user_for
from tests.test_warehouse_bill_uploads import context, uploaded, workbook, URL
from apps.finance.warehouse_bill_parser import parse_bill
from apps.finance.warehouse_bill_uploads import process_job, source_path
from apps.finance.warehouse_fee_models import WarehouseFee
from unittest.mock import patch


pytestmark = pytest.mark.django_db


def setup_order(code='local-fee'):
    tenant, _, store, _ = create_scope(code)
    user = user_for(tenant, code)
    order = create_order(tenant, store, code)
    return user, store, order


def source(original, tracking=(), shops=()):
    return {'original_order_id': original, 'tracking_numbers': list(tracking),
            'raw_stores': list(shops), 'raw_platform': 'Shopee'}


def match(user, original, tracking=(), shops=(), **changes):
    data = {'kind': 'order', 'country': 'PH', 'external_order_id': original, **changes}
    row_source = source(original, tracking, shops)
    lookup = LocalOrderLookup(user, [(data, row_source)])
    return lookup.resolve(data, row_source)


def archive(order, tracking, *, valid=True, booking=None):
    payload = {'responses': [{'payload': {'response': {'order_list': [
        {'order_sn': order.external_order_id, 'booking_sn': booking, 'package_list': [{'tracking_number': tracking}]}
    ]}}}]}
    return SyncRawEnvelope.objects.create(tenant=order.tenant, sync_run=order.source_run,
        store=order.store, platform='shopee', endpoint='/api/v2/order/get_order_detail',
        sequence=1, payload=payload, payload_hash=payload_digest(payload) if valid else '0' * 64)


def test_order_supplies_store_without_bill_shop_alias():
    user, store, order = setup_order()
    result = match(user, order.external_order_id, shops=['过时的账单店铺名'])
    assert result['status'] == 'matched'
    assert result['store_id'] == store.pk and result['order_id'] == order.pk


def test_reservation_uses_local_archive_tracking_without_month_filter():
    user, store, order = setup_order()
    archive(order, 'TRACK0001')
    result = match(user, '260831AASP4PQIW2JDM', ['TRACK0001'])
    assert result['status'] == 'reservation_matched'
    assert result['external_order_id'] == order.external_order_id
    assert result['original_order_id'] == '260831AASP4PQIW2JDM'


def test_formal_order_id_is_not_used_as_a_reservation_number_field():
    user, store, order = setup_order()
    order.external_order_id = '260831AASP4PQIW2JDM'; order.save()
    result = match(user, order.external_order_id)
    assert result['status'] == 'missing_tracking'
    assert 'order_id' not in result


def test_booking_sn_links_to_formal_order_sn_without_tracking():
    user, store, order = setup_order()
    archive(order, '', booking='260831AASP4PQIW2JDM')
    with CaptureQueriesContext(connection) as queries:
        result = match(user, '260831AASP4PQIW2JDM')
    raw_queries = [q['sql'] for q in queries if 'integrations_syncrawenvelope' in q['sql']]
    assert raw_queries and all('ORDER BY' not in q for q in raw_queries)
    assert result['status'] == 'booking_matched'
    assert result['external_order_id'] == order.external_order_id
    assert result['order_id'] == order.pk and result['store_id'] == store.pk


def test_booking_ref_with_missing_formal_order_is_not_a_success():
    user, _, order = setup_order()
    archive(order, '', booking='260831AASP4PQIW2JDM')
    order.external_order_id = 'CHANGED001'; order.save()
    assert match(user, '260831AASP4PQIW2JDM')['status'] == 'booking_order_missing'


def test_tracking_ambiguity_is_not_resolved_by_bill_shop():
    user, store, order = setup_order()
    other = create_order(user.tenant, store, 'other-local-fee')
    archive(order, 'TRACK0001'); archive(other, 'TRACK0001')
    assert match(user, '260831AASP4PQIW2JDM', ['TRACK0001'])['status'] == 'ambiguous'


def test_foreign_tenant_tracking_is_never_a_match():
    user, _, _ = setup_order()
    _, _, foreign_order = setup_order('foreign-local-fee')
    archive(foreign_order, 'TRACK0001')
    assert match(user, '260831AASP4PQIW2JDM', ['TRACK0001'])['status'] == 'tracking_unmatched'


def test_missing_tracking_is_distinct_from_missing_order():
    user, _, _ = setup_order()
    assert match(user, '260831AASP4PQIW2JDM')['status'] == 'missing_tracking'
    assert match(user, '260513A2YJ9AAS')['status'] == 'missing_order'
    assert match(user, 'PO-160-00033285980793928')['status'] == 'temu_unintegrated'
    assert match(user, 'OD16WCY010380')['status'] == 'manual_pending'


def test_bf_candidate_requires_confirmation_and_preserves_original():
    user, _, order = setup_order()
    order.external_order_id = '260808SBP468K9'; order.save()
    result = match(user, '260808SBP468K9BF')
    assert result['status'] == 'bf_candidate'
    assert result['candidates'][0]['external_order_id'] == order.external_order_id
    assert 'order_id' not in result


def test_damaged_archive_and_masked_tracking_are_not_used():
    user, _, order = setup_order()
    archive(order, 'TRACK0001', valid=False)
    assert match(user, '260831AASP4PQIW2JDM', ['TRACK0001'])['status'] == 'tracking_unmatched'
    assert match(user, '260831AASP4PQIW2JDM', ['TRACK****'])['status'] == 'missing_tracking'


def bill(context, original, *, shop='过时店铺名', tracking='TRACK0001'):
    return workbook({
        'Sheet1': [['菲律宾2026年9月'], [None] * 6 + [4, '代发费'], [None] * 6 + [8, '其他应收费用']],
        '订单': [['平台订单号', '仓库', '平台订单号', '运单号', '店铺名', '平台'],
                 [original, context[3].code, 'OTHER-REFERENCE', tracking, shop, 'Shopee']],
        '代发费': [['平台订单号', '实际应收'], [original, 4]],
        '其他应收费用': [['RMB', '数量', '单价', '金额'], ['仓储费', 1, 8, 8]],
    })


def parsed(context, original, **kwargs):
    job = uploaded(context, bill(context, original, **kwargs))
    process_job(str(job.pk), job.version, 'parse'); job.refresh_from_db()
    assert job.status == 'ready', job.error
    return job


def test_parser_keeps_tracking_and_all_duplicate_order_columns(context):
    job = uploaded(context, bill(context, '260831AASP4PQIW2JDM'))
    facts, _ = parse_bill(source_path(job), job.file_name)
    assert facts[0]['tracking_numbers'] == ['TRACK0001']
    assert facts[0]['raw_warehouse'] == context[3].code


def test_reservation_preview_and_import_keep_original_and_actual_ids(context):
    from apps.commerce.models import SalesOrder
    order = SalesOrder.objects.get(tenant=context[1].tenant, external_order_id='ORDER001')
    archive(order, 'TRACK0001')
    job = parsed(context, '260831AASP4PQIW2JDM')
    row = job.rows.get(number=1)
    assert row.status == 'valid' and row.data['external_order_id'] == 'ORDER001'
    assert row.source['original_order_id'] == '260831AASP4PQIW2JDM'
    assert row.source['matching']['status'] == 'reservation_matched'
    with patch('apps.finance.warehouse_bill_uploads.enqueue'):
        response = context[0].post(URL + str(job.pk) + '/', {'operation': 'import', 'version': job.version}, format='json')
    assert response.status_code == 202
    job.refresh_from_db(); process_job(str(job.pk), job.version, 'import')
    fee = WarehouseFee.objects.get(kind='order')
    assert fee.order_id == order.pk and fee.source['original_order_id'] == '260831AASP4PQIW2JDM'


@pytest.mark.parametrize('original,shop,status,valid', [
    ('11', 'Manual Orders', 'manual_confirmed', False),
    ('OD16WCY010380', '', 'manual_pending', False),
    ('MISSING001', '', 'missing_order', False),
])
def test_store_edit_cannot_turn_missing_order_into_a_match(context, original, shop, status, valid):
    job = parsed(context, original, shop=shop)
    response = context[0].post(URL + str(job.pk) + '/', {'operation': 'edit', 'version': job.version,
        'rows': [{'number': 1, 'changes': {'store_id': context[2].pk}}], 'reason': '人工核对归属'}, format='json')
    assert response.status_code == 200, response.data
    row = job.rows.get(number=1)
    assert row.source['matching']['status'] == status
    assert (row.status == 'valid') is valid
    assert not WarehouseFee.objects.exists()
