import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import load_workbook

from apps.finance.warehouse_fee_models import WarehouseFee
from apps.finance.warehouse_fee_simple_import import template_bytes
from tests.test_warehouse_fees import context, local_order, action, URL
from tests.test_sales_management import create_order
from tests.test_warehouse_bill_local_matching import archive
from apps.integrations.raw_services import payload_digest

pytestmark = pytest.mark.django_db


def simple(context, **changes):
    data = {'registration_mode': 'cny_simple', 'kind': 'order', 'country': 'PH',
            'warehouse_id': context[3].pk, 'external_order_id': 'NOT-LOCAL-YET',
            'amount': '120.5', 'bill_month': '2026-10', 'reference': 'MANUAL:stable-id', **changes}
    return context[0].post(URL, data, format='json')


def test_minimal_cny_amount_and_immutable_adjustment_history(context):
    local_order(context)
    response = simple(context)
    assert response.status_code == 201, response.data
    row = response.data['data']
    assert row['currency'] == 'CNY' and row['store_id'] == context[2].pk
    assert row['original_amount'] is None and row['exchange_rate'] is None
    assert simple(context).status_code == 200
    assert action(context, row, 'edit', changes={'amount': '100'}).status_code == 400
    response = action(context, row, 'edit', changes={'amount': '100'}, reason='账单核对')
    assert response.status_code == 200, response.data
    row = response.data['data']
    assert Decimal(row['source']['registration_original_amount']) == Decimal('120.5')
    assert action(context, row, 'edit', changes={'currency': 'PHP'}, reason='改币种').status_code == 400
    row = action(context, row, 'register').data['data']
    restored = action(context, row, 'correct', changes={'amount': row['source']['registration_original_amount']}, reason='恢复原金额')
    assert restored.status_code == 200, restored.data
    history = context[0].get(f'{URL}{row["id"]}/').data['data']['audit']
    assert [e['action'] for e in history] == ['create', 'edit', 'register', 'correct']


def test_unmatched_draft_can_relink_and_retry_without_duplicate(context):
    row = simple(context).data['data']
    assert row['store_id'] is None and row['match_status'] == 'unmatched'
    assert action(context, row, 'register').status_code == 400
    order = local_order(context)
    response = action(context, row, 'link')
    assert response.status_code == 200, response.data
    row = response.data['data']
    assert row['order_id'] == order.pk
    assert simple(context).status_code == 200
    assert WarehouseFee.objects.count() == 1
    assert action(context, row, 'register').status_code == 200


def test_other_only_needs_five_fields_and_fixed_currency(context):
    response = simple(context, kind='other', external_order_id='', fee_item='卸货费')
    assert response.status_code == 201, response.data
    row = response.data['data']
    assert row['currency'] == 'CNY' and row['match_status'] == 'not_applicable'
    assert simple(context, currency='PHP').status_code == 400
    assert simple(context, amount='0').status_code == 400
    assert simple(context, external_order_id=123).status_code == 400


def test_simple_template_pending_import_and_idempotency(context):
    wb = load_workbook(io.BytesIO(template_bytes('order')))
    ws = wb['登记']
    for col, value in enumerate(['PH', context[3].code, 'NOT-LOCAL-YET', '99.25', '2026-10'], 1):
        ws.cell(2, col, value)
    stream = io.BytesIO()
    wb.save(stream)
    raw = stream.getvalue()
    def upload(**extra):
        return context[0].post(URL + 'import/', {'kind': 'order', 'registration_mode': 'cny_simple',
            'file': SimpleUploadedFile('费用.xlsx', raw), **extra}, format='multipart')
    preview = upload()
    assert preview.status_code == 200, preview.data
    result = preview.data['data']
    assert result['errors'] == 0 and result['results'][0]['match_status'] == 'unmatched'
    assert WarehouseFee.objects.count() == 0
    saved = upload(confirm='true', sha256=result['sha256'])
    assert saved.status_code == 200, saved.data
    assert saved.data['data']['created'] == 1
    assert upload(confirm='true', sha256=result['sha256']).data['data']['created'] == 0
    row = WarehouseFee.objects.get()
    assert row.amount == Decimal('99.25') and row.currency == 'CNY' and row.status == 'draft'


@pytest.mark.parametrize('number_type', ['tracking', 'package', 'booking'])
def test_local_reference_matches_formal_order(context, number_type):
    order = local_order(context)
    number = '260831AASP4PQIW2JDM' if number_type == 'booking' else 'FULLNUMBER001'
    envelope = archive(order, number if number_type == 'tracking' else '',
                       booking=number if number_type == 'booking' else None)
    if number_type == 'package':
        envelope.payload['responses'][0]['payload']['response']['order_list'][0]['package_list'] = [{'package_number': number}]
        type(envelope).objects.create(tenant=order.tenant, sync_run=order.source_run,
            store=order.store, platform='shopee', endpoint='/api/v2/order/get_order_detail',
            sequence=2, payload=envelope.payload, payload_hash=payload_digest(envelope.payload))
    response = simple(context, external_order_id=number)
    assert response.status_code == 201, response.data
    row = response.data['data']
    assert row['order_id'] == order.pk and row['external_order_id'] == order.external_order_id
    assert row['source']['original_order_id'] == number


def test_multiple_orders_for_reference_stay_pending(context):
    order = local_order(context)
    other = create_order(context[1].tenant, context[2], 'other-fee-simple')
    archive(order, 'SHARED-TRACK'); archive(other, 'SHARED-TRACK')
    response = simple(context, external_order_id='SHARED-TRACK')
    assert response.status_code == 201, response.data
    row = response.data['data']
    assert row['match_status'] == 'ambiguous' and row['order_id'] is None
    assert action(context, row, 'register').status_code == 400
