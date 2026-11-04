import io
import json
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import load_workbook

from apps.finance.models import FinanceAuditLog
from apps.finance.warehouse_fee_models import WarehouseFee
from apps.masterdata.models import CountrySiteMaster
from apps.permissions.models import DataScope
from tests.test_sales_management import create_scope, create_order, user_for, grant, client_for

pytestmark = pytest.mark.django_db
URL = '/api/finance/warehouse-fees/'
UPLOADS = {}


@pytest.fixture
def context():
    tenant, _, store, warehouse = create_scope('warehouse-fees')
    site = CountrySiteMaster.objects.create(tenant=tenant, code='PH', name='菲律宾', country_code='PH', currency='PHP')
    user = user_for(tenant, 'fee-registrar')
    for action in ['view', 'create', 'edit', 'register', 'void', 'import', 'export']:
        grant(user, 'finance.warehouse_fees.' + action)
    return client_for(user), user, store, warehouse, site


def payload(context, **changes):
    _, _, store, warehouse, _ = context
    return {'kind': 'order', 'country': 'PH', 'warehouse_id': warehouse.pk, 'store_id': store.pk,
            'external_order_id': 'NOT-LOCAL-YET', 'bill_number': 'WAREHOUSE-2026-09', 'bill_month': '2026-09',
            'fee_item': '订单处理费', 'amount': '2.400000', 'currency': 'CNY', 'occurred_on': '2026-09-30',
            'reference': 'WMS-001', 'note': '账单费用，不代表付款', **changes}


def create(context, **changes):
    response = context[0].post(URL, payload(context, **changes), format='json')
    assert response.status_code == 201, response.data
    return response.data['data']


def action(context, row, name, **extra):
    return context[0].post(f'{URL}{row["id"]}/{name}/', {'expected_version': row['version'], **extra}, format='json')


def local_order(context):
    order = create_order(context[1].tenant, context[2], 'fees-link')
    order.external_order_id = 'NOT-LOCAL-YET'
    order.save()
    return order


def test_draft_confirm_unmatched_and_link_never_touch_order(context):
    row = create(context)
    assert row['match_status'] == 'unmatched' and row['status'] == 'draft'
    registered = action(context, row, 'register')
    assert registered.status_code == 400, registered.data
    saved = WarehouseFee.objects.get(pk=row['id'])
    assert saved.status == 'draft' and saved.version == row['version']
    assert not FinanceAuditLog.objects.filter(action='register').exists()
    order = local_order(context)
    before = list(order.items.values())
    linked = action(context, row, 'link')
    assert linked.status_code == 200 and linked.data['data']['order_id'] == order.pk
    registered = action(context, linked.data['data'], 'register')
    assert registered.status_code == 200, registered.data
    assert registered.data['data']['status'] == 'registered'
    order.refresh_from_db()
    assert order.normalized_status == 'completed' and list(order.items.values()) == before
    assert FinanceAuditLog.objects.filter(object_type='warehouse_fee', object_id=str(row['id']), action='register').exists()


def test_correction_audit_void_and_stale_version(context):
    local_order(context)
    row = create(context)
    assert action(context, row, 'register', expected_version=999).status_code == 409
    row = action(context, row, 'register').data['data']
    assert action(context, row, 'correct', changes={'amount': '3.100000'}, reason='').status_code == 400
    result = action(context, row, 'correct', changes={'amount': '3.100000'}, reason='账单更正')
    assert result.status_code == 200, result.data
    corrected = result.data['data']
    assert Decimal(corrected['amount']) == Decimal('3.1')
    assert action(context, row, 'void', reason='过期版本').status_code == 409
    assert action(context, corrected, 'void', reason='重复计费').data['data']['status'] == 'void'
    assert WarehouseFee.objects.count() == 1
    history = context[0].get(f'{URL}{row["id"]}/').data['data']['audit']
    assert any(x['action'] == 'correct' and x['detail']['before']['amount'] == '2.400000' for x in history)


def test_business_key_idempotency_and_content_conflict(context):
    first = create(context)
    response = context[0].post(URL, payload(context), format='json')
    assert response.status_code == 200 and response.data['data']['id'] == first['id']
    assert context[0].post(URL, payload(context, amount='99'), format='json').status_code == 409
    assert WarehouseFee.objects.count() == 1


@pytest.mark.parametrize('changes', [
    {'country': 'MY'}, {'amount': '-1'}, {'amount': 'NaN'}, {'amount': '0'},
    {'bill_month': '2026-13'}, {'occurred_on': '2026/09/01'}, {'amount': '1.1234567'},
    {'original_amount': '10', 'original_currency': 'THB'},
    {'original_amount': '10', 'original_currency': 'THB', 'exchange_rate': '2'},
    {'reference': ''}, {'kind': 'other'}, {'currency': 'BOGUS'}, {'unexpected': 'x'},
])
def test_invalid_values_rejected_without_writes(context, changes):
    assert context[0].post(URL, payload(context, **changes), format='json').status_code == 400
    assert not WarehouseFee.objects.exists()


def test_other_fee_has_country_not_a_fake_order(context):
    row = create(context, kind='other', store_id=None, external_order_id='', fee_item='仓储费', occurred_on=None)
    assert row['match_status'] == 'not_applicable' and row['order_id'] is None
    assert action(context, row, 'register').status_code == 200
    assert action(context, row, 'link').status_code == 409


def test_store_scope_cannot_read_or_write_country_costs(context):
    client, user, store, _, _ = context
    own = create(context)
    other = create(context, kind='other', store_id=None, external_order_id='', reference='OTHER-1', fee_item='仓租')
    narrow = user_for(user.tenant, 'store-only')
    for operation in ['view', 'create', 'register', 'import']:
        grant(narrow, 'finance.warehouse_fees.' + operation, DataScope.ScopeType.CUSTOM, {'store_ids': [store.pk]})
    limited = client_for(narrow)
    assert [r['id'] for r in limited.get(URL).data['data']['results']] == [own['id']]
    assert limited.get(f'{URL}{other["id"]}/').status_code == 404
    assert limited.post(URL, payload(context, kind='other', store_id=None, external_order_id=''), format='json').status_code == 403
    assert limited.post(f'{URL}{other["id"]}/register/', {'expected_version': other['version']}, format='json').status_code == 404


def test_country_scope_and_cross_tenant_protection(context):
    client, user, store, warehouse, site = context
    row = create(context)
    narrow = user_for(user.tenant, 'country-only')
    grant(narrow, 'finance.warehouse_fees.view', DataScope.ScopeType.CUSTOM, {'site_ids': [site.pk]})
    assert client_for(narrow).get(f'{URL}{row["id"]}/').status_code == 200
    tenant2, _, store2, warehouse2 = create_scope('fees-outside')
    assert client.post(URL, payload(context, warehouse_id=warehouse2.pk), format='json').status_code == 400
    assert client.post(URL, payload(context, store_id=store2.pk), format='json').status_code == 400
    denied = user_for(tenant2, 'no-fee-permission')
    assert client_for(denied).get(URL).status_code == 403


def test_currency_scope_totals_export_and_no_permission_escalation(context):
    local_order(context)
    client, user, store, _, _ = context
    cny = create(context)
    php = create(context, reference='PHP-1', currency='PHP')
    action(context, cny, 'register'); action(context, php, 'register')
    totals = client.get(URL).data['data']['registered_totals']
    assert {r['currency']: Decimal(r['amount']) for r in totals} == {'CNY': Decimal('2.4'), 'PHP': Decimal('2.4')}
    limited = user_for(user.tenant, 'cny-store')
    for permission in ['view', 'create', 'export']:
        grant(limited, 'finance.warehouse_fees.' + permission, DataScope.ScopeType.CUSTOM,
              {'store_ids': [store.pk], 'currencies': ['CNY']})
    narrow = client_for(limited)
    assert len(narrow.get(URL).data['data']['results']) == 1
    assert narrow.post(URL, payload(context, reference='DENIED', currency='PHP'), format='json').status_code == 403
    assert narrow.post(f'{URL}{cny["id"]}/void/', {'expected_version': 2, 'reason': 'denied'}, format='json').status_code == 403
    exported = narrow.get(URL + 'export/').content.decode('utf-8-sig')
    assert 'CNY' in exported and 'PHP-1' not in exported


def test_batch_confirmation_rolls_back_on_any_version_conflict(context):
    local_order(context)
    first = create(context)
    second = create(context, reference='WMS-002')
    response = context[0].post(URL + 'batch-register/', {'targets': [
        {'id': first['id'], 'version': 1}, {'id': second['id'], 'version': 99}]}, format='json')
    assert response.status_code == 409
    assert WarehouseFee.objects.filter(status='registered').count() == 0
    assert not FinanceAuditLog.objects.filter(action='register', object_type='warehouse_fee').exists()


def test_registration_rechecks_a_previously_matched_draft(context):
    order = local_order(context)
    row = create(context)
    assert row['match_status'] == 'matched'
    order.external_order_id = 'ORDER-CHANGED'
    order.save()
    assert action(context, row, 'register').status_code == 400
    saved = WarehouseFee.objects.get(pk=row['id'])
    assert saved.status == 'draft' and saved.version == row['version']
    assert not FinanceAuditLog.objects.filter(action='register').exists()


def test_batch_registration_rolls_back_when_any_order_is_unmatched(context):
    local_order(context)
    first = create(context)
    second = create(context, reference='WMS-002', external_order_id='MISSING')
    response = context[0].post(URL + 'batch-register/', {'targets': [
        {'id': first['id'], 'version': 1}, {'id': second['id'], 'version': 1}]}, format='json')
    assert response.status_code == 400
    assert WarehouseFee.objects.filter(status='registered').count() == 0
    assert not FinanceAuditLog.objects.filter(action='register').exists()


def test_large_invalid_fx_is_validation_error_not_server_error(context):
    response = context[0].post(URL, payload(context, original_amount='99999999999999.000000',
        original_currency='THB', exchange_rate='99999999999999.0000000000', rate_date='2026-09-01', rate_source='账单'), format='json')
    assert response.status_code == 400


def workbook_upload(client, rows):
    key = json.dumps(rows)
    if key in UPLOADS:
        return SimpleUploadedFile('fees.xlsx', UPLOADS[key])
    template = client.get(URL + 'template/?kind=order')
    assert template.status_code == 200
    wb = load_workbook(io.BytesIO(template.content))
    for row_number, row in enumerate(rows, 2):
        for column, value in enumerate(row, 1):
            wb['登记'].cell(row_number, column, value)
    stream = io.BytesIO(); wb.save(stream); wb.close()
    UPLOADS[key] = stream.getvalue()
    return SimpleUploadedFile('fees.xlsx', UPLOADS[key])


def test_template_preview_partial_import_and_replay(context):
    local_order(context)
    client, _, store, warehouse, _ = context
    # Template order: country, warehouse, bill, month, store, order, item, reference,
    # amount, currency, date, original amount/currency/rate/date/source, note.
    valid = ['PH', warehouse.code, 'BILL-1', '2026-09', store.code, 'NOT-LOCAL-YET', '订单处理费', 'LINE-1',
             '2.40', 'CNY', '2026-09-30', '', '', '', '', '', '来源账单']
    invalid = [*valid]; invalid[7] = 'LINE-2'; invalid[8] = '-3'
    response = client.post(URL + 'import/', {'file': workbook_upload(client, [valid, invalid]), 'kind': 'order'}, format='multipart')
    assert response.status_code == 200, response.data
    preview = response.data['data']
    assert [r['status'] for r in preview['results']] == ['valid', 'error']
    assert not WarehouseFee.objects.exists() and not FinanceAuditLog.objects.exists()
    bad = client.post(URL + 'import/', {'file': workbook_upload(client, [valid, invalid]), 'kind': 'order', 'confirm': 'true',
        'sha256': 'changed', 'valid_only': 'true'}, format='multipart')
    assert bad.status_code == 400 and not WarehouseFee.objects.exists()
    data = {'kind': 'order', 'confirm': 'true', 'sha256': preview['sha256'], 'valid_only': 'true'}
    confirmed = client.post(URL + 'import/', {**data, 'file': workbook_upload(client, [valid, invalid])}, format='multipart')
    assert confirmed.status_code == 200, confirmed.data
    assert WarehouseFee.objects.count() == 1 and WarehouseFee.objects.get().status == 'draft'
    replay = client.post(URL + 'import/', {**data, 'file': workbook_upload(client, [valid, invalid])}, format='multipart')
    assert replay.status_code == 200 and WarehouseFee.objects.count() == 1
    assert client.get(URL + 'imports/').data['data']['results']


def test_unmatched_template_order_is_pending_and_cannot_be_imported(context):
    client, _, store, warehouse, _ = context
    row = ['PH', warehouse.code, 'BILL-PENDING', '2026-09', store.code, 'MISSING', '订单处理费', 'LINE-1',
           '2.40', 'CNY', '2026-09-30', '', '', '', '', '', '']
    response = client.post(URL + 'import/', {'file': workbook_upload(client, [row]), 'kind': 'order'}, format='multipart')
    preview = response.data['data']
    assert preview['results'][0]['status'] == 'error'
    assert '待核对' in preview['results'][0]['error']
    response = client.post(URL + 'import/', {'file': workbook_upload(client, [row]), 'kind': 'order',
        'confirm': 'true', 'sha256': preview['sha256']}, format='multipart')
    assert response.status_code == 400 and not WarehouseFee.objects.exists()


@pytest.mark.parametrize('row_count,expected_status', [(1, 200), (1001, 400)])
def test_xlsx_without_declared_dimensions_is_read_with_existing_limits(context, row_count, expected_status):
    from zipfile import ZIP_DEFLATED, ZipFile
    import xml.etree.ElementTree as ET

    client, _, store, warehouse, _ = context
    local_order(context)
    row = ['PH', warehouse.code, 'NO-DIM', '2026-09', store.code, 'NOT-LOCAL-YET', '订单处理费', 'LINE-1',
           '2.40', 'CNY', '2026-09-30', '', '', '', '', '', '来源账单']
    upload = workbook_upload(client, [row] * row_count)
    result = io.BytesIO()
    with ZipFile(upload) as source, ZipFile(result, 'w', ZIP_DEFLATED) as target:
        for member in source.infolist():
            raw = source.read(member.filename)
            if member.filename == 'xl/worksheets/sheet1.xml':
                root = ET.fromstring(raw)
                dimension = root.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}dimension')
                root.remove(dimension)
                raw = ET.tostring(root, encoding='utf-8', xml_declaration=True)
            target.writestr(member, raw)
    response = client.post(URL + 'import/', {'file': SimpleUploadedFile('no-dimension.xlsx', result.getvalue()),
        'kind': 'order'}, format='multipart')
    assert response.status_code == expected_status, response.data
    assert not WarehouseFee.objects.exists()
    if expected_status == 200:
        assert response.data['data']['results'][0]['status'] == 'valid'
