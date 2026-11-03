import io
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from apps.finance.models import FinanceAuditLog
from apps.commerce.models import SalesOrder
from apps.finance.warehouse_bill_parser import BillError, parse_bill
from apps.finance.warehouse_bill_uploads import process_job, source_path
from apps.finance.warehouse_fee_models import WarehouseBillUpload, WarehouseFee
from apps.masterdata.models import CountrySiteMaster
from apps.permissions.models import DataScope
from tests.test_sales_management import create_scope, create_order, user_for, grant, client_for

URL = '/api/finance/warehouse-fees/original-bills/'


def workbook(sheets):
    book = Workbook(); book.remove(book.active)
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    stream = io.BytesIO(); book.save(stream)
    return stream.getvalue()


def ph_bill(shop='SHOP-PH', warehouse='OLD-PH', total=4, duplicate=False, missing=False, order='ORDER001'):
    return workbook({
        'Sheet1': [['菲律宾2026年9月结算'], [None]*6 + [total, '代发费'], [None]*6 + [8, '其他应收费用']],
        '订单': [['平台订单号', '店铺名称', '仓库', '出库时间'], [order, shop, warehouse, '2026-09-10']],
        '代发费': [['平台订单号', '实际应收'], [order, '=2+2' if missing else 4], *([[order, 4]] if duplicate else [])],
        '其他应收费用': [['RMB', '数量', '单价', '金额', '备注'], ['仓储费', 1, 8, 8], ['合计', None, None, 8]],
    })


def read(tmp_path, raw, name='2026年9月菲律宾处理费.xlsx', overrides=None):
    target = tmp_path / 'bill.xlsx'; target.write_bytes(raw)
    return parse_bill(target, name, overrides)


def test_ph_original_separates_fees_and_never_counts_invoice_twice(tmp_path):
    rows, summary = read(tmp_path, ph_bill())
    assert len(rows) == 2
    assert [r['kind'] for r in rows] == ['order', 'other']
    assert [r['amount'] for r in rows] == ['4.000000', '8.000000']
    assert rows[0]['raw_warehouse'] == 'OLD-PH' and rows[0]['occurred_on'] == '2026-09-10'
    assert all(not r['issues'] for r in rows)
    assert summary['order_difference'] == '0.000000'


@pytest.mark.parametrize('order', [
    '260103240E4365', '260104590E7903', '260115470125E2', '260126363E7371', '26012756339E83',
])
def test_shopee_text_order_ids_containing_e_are_not_scientific_numbers(tmp_path, order):
    rows, _ = read(tmp_path, ph_bill(order=order))
    assert rows[0]['external_order_id'] == order
    assert not rows[0]['issues']


@pytest.mark.parametrize('order', ['2.601032404365E+12', '260103240E+4365', '260103240E-4365'])
def test_explicit_scientific_notation_order_ids_remain_held(tmp_path, order):
    rows, _ = read(tmp_path, ph_bill(order=order))
    assert any('科学计数法' in issue for issue in rows[0]['issues'])


def test_numeric_exponent_cell_is_not_accepted_as_a_text_order_id(tmp_path):
    from zipfile import ZipFile
    from xml.etree import ElementTree as XML
    from apps.finance.warehouse_bill_parser import NS
    source = io.BytesIO(ph_bill(order='260103240E4365'))
    target = io.BytesIO()
    with ZipFile(source) as original, ZipFile(target, 'w') as updated:
        for entry in original.infolist():
            raw = original.read(entry.filename)
            if entry.filename == 'xl/worksheets/sheet3.xml':
                root = XML.fromstring(raw)
                cell = root.find(f'.//{NS}c[@r="A2"]')
                cell.clear(); cell.set('r', 'A2'); cell.set('t', 'n')
                XML.SubElement(cell, NS + 'v').text = '260103240E4365'
                raw = XML.tostring(root)
            updated.writestr(entry, raw)
    rows, _ = read(tmp_path, target.getvalue())
    assert any('科学计数法' in issue for issue in rows[0]['issues'])


def test_fus_aggregates_wms_fee_not_repeated_sku_order_total(tmp_path):
    raw = workbook({
        '账单汇总': [['马来2026年9月', 'CNY'], ['出库费用', None, 6], ['仓储费', None, 10], ['总费用', None, 16]],
        '出库订单': [['WMS单号', '参考号', '店铺编码', '仓库', '交易日期', '操作费'],
                 ['WMS001', 'ORDER001', 'SHOP-MY', 'MY-A1', '2026-09-02', 6], ['WMS001', 'ORDER001', 'SHOP-MY', 'MY-A1', '2026-09-02', 6]],
        '库内操作费': [['交易单号', '金额', '类型', '参考号', '店铺编码', '仓库', '交易日期', '计费项类型'],
                   ['WMS001', 2, 'OutBound', 'ORDER001', 'SHOP-MY', 'MY-A1', '2026-09-02', '出库费用'],
                   ['WMS001', 4, 'OutBound', 'ORDER001', 'SHOP-MY', 'MY-A1', '2026-09-02', '出库费用']],
    })
    rows, summary = read(tmp_path, raw, '2026年9月马来处理费.xlsx')
    assert [r['amount'] for r in rows] == ['6.000000', '10.000000']
    assert rows[0]['reference'] == 'WMS:WMS001'
    assert not rows[0]['issues'] and summary['order_difference'] == '0.000000'


def test_new_my_bill_uses_settlement_column_and_order_detail(tmp_path):
    raw = workbook({
        '业务结算单': [['马来2026年9月']],
        '一件代发出库费用': [['平台订单号', '店铺名', '仓库名称', '平台'], ['ORDER001', 'SHOP-MY', '恒置', 'Shopee']],
        '代发费': [['平台订单号', '实际应收'], ['ORDER001', 2.4]],
        '仓库费用汇总表': [[None, '计费名称', None, None, None, None, None, None, '人民币'],
                       [None, '一件代发订单', None, None, None, None, None, None, 2.4],
                       [None, '仓租账单', None, None, None, None, None, None, 8]],
    })
    rows, summary = read(tmp_path, raw, '2026年9月马来处理费.xlsx')
    assert [r['currency'] for r in rows] == ['CNY', 'CNY']
    assert not rows[0]['issues'] and summary['order_difference'] == '0.000000'


@pytest.mark.parametrize('raw, fragment', [(ph_bill(total=4.01), '差额'), (ph_bill(duplicate=True, total=8), '重复'), (ph_bill(missing=True), '金额缺失')])
def test_bad_totals_duplicate_orders_and_uncached_formulas_are_held(tmp_path, raw, fragment):
    rows, _ = read(tmp_path, raw)
    assert any(fragment in issue for r in rows if r['kind'] == 'order' for issue in r['issues'])


def test_ph_peso_block_does_not_use_fx_rate_as_settlement_amount(tmp_path):
    raw = workbook({
        'Sheet1': [['菲律宾2026年9月'], [None]*6+[4, '代发费'], [None]*6+[12, '其他应收费用']],
        '订单': [['平台订单号', '店铺名称', '仓库'], ['ORDER001', 'SHOP-PH', 'OLD-PH']],
        '代发费': [['平台订单号', '实际应收'], ['ORDER001', 4]],
        '其他应收费用': [['RMB', '数量', '单价', '金额'], ['仓储费', 1, 8, 8], ['比索', '数量', '单价', '汇率', 'rmb'], ['样品', None, 40, 10, 4], ['PHP', '数量', '单价', '金额'], ['加工费', None, None, 100]],
    })
    rows, _ = read(tmp_path, raw)
    assert [(r['amount'], r['currency']) for r in rows[1:]] == [('8.000000', 'CNY'), ('4.000000', 'CNY'), ('100.000000', 'PHP')]
    assert not rows[-1]['issues']


def test_local_currency_fee_is_held_if_same_item_has_a_cny_invoice_candidate(tmp_path):
    raw = workbook({
        'Sheet1': [['菲律宾2026年9月结算'], [None]*6 + [4, '代发费'],
                   [None]*6 + [0, '其他应收费用'], [None]*4 + [None, 10, 10, '加工费']],
        '代发费': [['平台订单号', '实际应收'], ['ORDER001', 4]],
        '其他应收费用': [['RMB', '数量', '单价', '金额'], ['PHP', '数量', '单价', '金额'], ['加工费', 1, 100, 100]],
    })
    rows, _ = read(tmp_path, raw)
    others = [row for row in rows if row['kind'] == 'other']
    assert {(row['amount'], row['currency']) for row in others} == {('100.000000', 'PHP'), ('10.000000', 'CNY')}
    assert all(row['issues'] for row in others)


def test_unique_invoice_original_amount_links_local_fee_without_double_counting(tmp_path):
    raw = workbook({
        'Sheet1': [['菲律宾2026年8月结算'], [None]*6 + [4, '代发费'],
                   [None]*6 + [8, '其他应收费用'], [None]*4 + [30765, 9.35, 3290, '瑜伽垫加工费']],
        '代发费': [['平台订单号', '实际应收'], ['ORDER001', 4]],
        '其他应收费用': [['RMB', '数量', '单价', '金额'], ['仓储费', 1, 8, 8],
                       ['PHP', '数量', '单价', '金额'], ['瑜伽垫加工费', 10255, 3, 30765]],
    })
    rows, summary = read(tmp_path, raw, '2026年8月菲律宾处理费.xlsx')
    matched = [row for row in rows if row['fee_item'] == '瑜伽垫加工费']
    assert len(rows) == 3 and len(matched) == 1
    fact = matched[0]
    assert fact['amount'] == '30765.000000' and fact['currency'] == 'PHP'
    assert not fact['issues'] and not summary['warnings']
    assert fact['settlement_evidence'] == {
        'original_amount': '30765.000000', 'original_currency': 'PHP',
        'original_sheet': '其他应收费用', 'original_row': 4,
        'settlement_amount': '3290.000000', 'settlement_currency': 'CNY',
        'settlement_sheet': 'Sheet1', 'settlement_row': 4, 'quoted_rate': '9.35', 'included_in_other_subtotal': False,
    }


def test_converted_peso_block_keeps_original_currency_and_uses_cny_only_for_reconciliation(tmp_path):
    raw = workbook({
        'Sheet1': [['菲律宾2026年4月结算'], [None]*6 + [4, '代发费'],
                   [None]*6 + [552.817679558011, '其他应收费用']],
        '代发费': [['平台订单号', '实际应收'], ['ORDER001', 4]],
        '其他应收费用': [['RMB', '数量', '单价', '金额'], ['比索', '数量', '单价', '汇率', 'rmb'],
                       ['样品', 1, 5003, 9.05, 552.817679558011]],
    })
    rows, summary = read(tmp_path, raw, '2026年4月菲律宾处理费.xlsx')
    fact = rows[1]
    assert fact['amount'] == '5003.000000' and fact['currency'] == 'PHP'
    assert fact['settlement_evidence']['settlement_amount'] == '552.817680'
    assert not fact['issues'] and not summary['warnings']


def test_conflicting_override_is_not_silently_applied(tmp_path):
    with pytest.raises(BillError, match='矛盾'):
        read(tmp_path, ph_bill(), overrides={'country': 'TH'})


def test_missing_currency_does_not_default_to_cny_and_can_be_confirmed(tmp_path):
    raw = workbook({
        '账单汇总': [['泰国2026年2月'], ['出库费用', None, 4]],
        '出库订单': [['WMS单号', '参考号', '店铺编码', '仓库', '操作费'], ['WMS001', 'ORDER001', 'SHOP', 'THA-A1', 4]],
        '库内操作费': [['交易单号', '金额', '类型', '参考号', '店铺编码', '仓库'], ['WMS001', 4, 'OutBound', 'ORDER001', 'SHOP', 'THA-A1']],
    })
    rows, _ = read(tmp_path, raw, '2026年2月泰国处理费.xlsx')
    assert rows[0]['currency'] == '' and any('币种' in e for e in rows[0]['issues'])
    rows, _ = read(tmp_path, raw, '2026年2月泰国处理费.xlsx', {'currency': 'CNY'})
    assert rows[0]['currency'] == 'CNY' and not rows[0]['issues']


def test_yearless_bill_requires_confirmation_instead_of_guessing_year(tmp_path):
    raw = workbook({'代发费': [['平台订单号', '实际应收'], ['ORDER001', 4]], '其他应收费用': [['RMB'], ['仓储费', None, None, 8]],
                    '订单': [['平台订单号', '店铺名称', '仓库'], ['ORDER001', 'SHOP', 'OLD']]})
    with pytest.raises(BillError, match='月份'):
        read(tmp_path, raw, '12月菲律宾处理费.xlsx')


def test_invalid_workbook_is_rejected(tmp_path):
    with pytest.raises(BillError):
        read(tmp_path, b'not an xlsx')


def test_charge_without_order_number_is_retained_for_review(tmp_path):
    raw = workbook({
        'Sheet1': [['菲律宾2026年9月结算'], [None]*6 + [4, '代发费'], [None]*6 + [8, '其他应收费用']],
        '代发费': [['平台订单号', '实际应收'], [None, 4]],
        '其他应收费用': [['RMB', '数量', '单价', '金额'], ['仓储费', 1, 8, 8]],
    })
    rows, summary = read(tmp_path, raw)
    orders = [row for row in rows if row['kind'] == 'order']
    assert len(orders) == 1
    assert orders[0]['amount'] == '4.000000' and orders[0]['issues']
    assert orders[0]['source_rows'] == [2]
    assert summary['order_difference'] == '0.000000'


@pytest.mark.parametrize('value', ['=1+7', '#REF!', '金额待确认'])
def test_invalid_other_fee_amount_is_retained_for_review(tmp_path, value):
    raw = workbook({
        'Sheet1': [['菲律宾2026年9月结算'], [None]*6 + [4, '代发费'], [None]*6 + [8, '其他应收费用']],
        '代发费': [['平台订单号', '实际应收'], ['ORDER001', 4]],
        '其他应收费用': [['RMB', '数量', '单价', '金额'], ['仓储费', 1, 8, value]],
    })
    rows, _ = read(tmp_path, raw)
    others = [row for row in rows if row['kind'] == 'other']
    assert len(others) == 1
    assert others[0]['amount'] is None and others[0]['issues']
    assert others[0]['sheet'] == '其他应收费用' and others[0]['row'] == 2


def test_fus_charge_without_transaction_number_is_retained_for_review(tmp_path):
    raw = workbook({
        '账单汇总': [['马来2026年9月', 'CNY'], ['出库费用', None, 4]],
        '出库订单': [['WMS单号', '参考号', '店铺编码']],
        '库内操作费': [['交易单号', '金额', '类型', '参考号', '店铺编码', '仓库'],
                   [None, 4, 'OutBound', 'ORDER001', 'SHOP', 'MY-A1']],
    })
    rows, summary = read(tmp_path, raw, '2026年9月马来处理费.xlsx')
    assert len(rows) == 1 and rows[0]['amount'] == '4.000000'
    assert any('交易单号' in issue for issue in rows[0]['issues'])
    assert summary['order_difference'] == '0.000000'


def test_blank_unused_other_fee_template_is_not_a_missing_charge(tmp_path):
    raw = workbook({
        'Sheet1': [['菲律宾2026年9月结算'], [None]*6 + [4, '代发费'], [None]*6 + [0, '其他应收费用']],
        '代发费': [['平台订单号', '实际应收'], ['ORDER001', 4]],
        '其他应收费用': [['RMB', '数量', '单价', '金额'], ['装车费'], ['仓租', None, 10000, 0]],
    })
    rows, _ = read(tmp_path, raw)
    assert len(rows) == 1 and rows[0]['kind'] == 'order'


def test_unlabelled_cached_sum_footer_is_not_registered_twice(tmp_path):
    from zipfile import ZipFile
    from xml.etree import ElementTree as XML
    from apps.finance.warehouse_bill_parser import NS
    original = io.BytesIO(workbook({
        'Sheet1': [['菲律宾2026年9月结算'], [None]*6 + [4, '代发费'], [None]*6 + [0, '其他应收费用']],
        '代发费': [['平台订单号', '实际应收'], ['ORDER001', 4], [None, '=SUM(B2:B2)']],
        '其他应收费用': [['RMB', '数量', '单价', '金额']],
    }))
    stream = io.BytesIO()
    with ZipFile(original) as source, ZipFile(stream, 'w') as target:
        for entry in source.infolist():
            raw = source.read(entry.filename)
            if entry.filename == 'xl/worksheets/sheet2.xml':
                root = XML.fromstring(raw)
                root.find(f'.//{NS}c[@r="B3"]/{NS}v').text = '4'
                raw = XML.tostring(root)
            target.writestr(entry, raw)
    rows, summary = read(tmp_path, stream.getvalue())
    assert len(rows) == 1 and not rows[0]['issues']
    assert summary['order_detail_sum'] == '4.000000'


def test_other_invoice_with_no_detail_is_retained_as_an_unresolved_charge(tmp_path):
    raw = workbook({
        'Sheet1': [['菲律宾2026年9月结算'], [None]*6 + [4, '代发费'], [None]*6 + [8, '其他应收费用']],
        '代发费': [['平台订单号', '实际应收'], ['ORDER001', 4]],
        '其他应收费用': [['RMB', '数量', '单价', '金额']],
    })
    rows, summary = read(tmp_path, raw)
    assert len(rows) == 2
    assert rows[1]['amount'] == '8.000000' and rows[1]['issues']
    assert rows[1]['sheet'] == 'Sheet1' and rows[1]['row'] == 3
    assert summary['warnings']


@pytest.mark.parametrize('country', ['MY', 'TH'])
@pytest.mark.parametrize('value', ['#REF!', '=1+7'])
def test_non_numeric_warehouse_summary_fee_is_not_dropped(tmp_path, country, value):
    raw = workbook({
        '业务结算单': [[f'{country}2026年9月']],
        '代发费': [['平台订单号', '实际应收'], ['ORDER001', 4]],
        '仓库费用汇总表': [[None, '计费名称', None, None, None, None, None, None, '人民币'],
                       [None, '一件代发订单', None, None, None, None, None, None, 4],
                       [None, '仓租账单', None, None, None, None, None, None, value]],
    })
    rows, _ = read(tmp_path, raw, f'{country}2026年9月处理费.xlsx')
    assert len(rows) == 2 and rows[1]['fee_item'] == '仓租账单'
    assert rows[1]['amount'] is None and rows[1]['issues']


@pytest.mark.parametrize('label,heading', [('计费项类型', '金额'), ('计费项类型', '汇总'), ('部门', '汇总')])
def test_fus_summary_header_is_not_misread_as_an_invalid_fee(tmp_path, label, heading):
    raw = workbook({
        '账单汇总': [['马来2026年9月', 'CNY'], [label, '编码：MY-A1', heading],
                 ['出库费用', 4, 4], ['仓储费', 8, '=4+4']],
        '出库订单': [['WMS单号', '参考号', '店铺编码', '仓库', '操作费'],
                 ['WMS001', 'ORDER001', 'SHOP', 'MY-A1', 4]],
        '库内操作费': [['交易单号', '金额', '类型', '参考号', '店铺编码', '仓库'],
                   ['WMS001', 4, 'OutBound', 'ORDER001', 'SHOP', 'MY-A1']],
    })
    rows, _ = read(tmp_path, raw, '2026年9月马来处理费.xlsx')
    assert len(rows) == 2 and rows[1]['fee_item'] == '仓储费'
    assert rows[1]['amount'] is None and rows[1]['issues']


@pytest.fixture
def context(settings, tmp_path):
    settings.BASE_DIR = tmp_path
    tenant, _, store, warehouse = create_scope('original-fees')
    CountrySiteMaster.objects.create(tenant=tenant, code='PH', name='菲律宾', country_code='PH', currency='PHP')
    user = user_for(tenant, 'original-fee-importer')
    grant(user, 'finance.warehouse_fees.import')
    order = create_order(tenant, store, 'bill-local-order')
    order.external_order_id = 'ORDER001'; order.save()
    return client_for(user), user, store, warehouse


def uploaded(context, raw=None):
    client, _, store, warehouse = context
    raw = raw or ph_bill(store.code, warehouse.code)
    with patch('apps.finance.warehouse_bill_uploads.enqueue'):
        response = client.post(URL, {'file': SimpleUploadedFile('2026年9月菲律宾处理费.xlsx', raw)}, format='multipart')
    assert response.status_code == 202, response.data
    return WarehouseBillUpload.objects.get(pk=response.data['data']['id'])


@pytest.mark.django_db
def test_invoice_currency_is_registered_and_original_currency_stays_as_evidence(context):
    client, user, store, warehouse = context
    raw = workbook({
        'Sheet1': [['菲律宾2026年9月结算'], [None]*6 + [4, '代发费'],
                   [None]*6 + [0, '其他应收费用'], [None]*4 + [30765, 9.35, 3290, '瑜伽垫加工费']],
        '订单': [['平台订单号', '店铺名称', '仓库'], ['ORDER001', store.code, warehouse.code]],
        '代发费': [['平台订单号', '实际应收'], ['ORDER001', 4]],
        '其他应收费用': [['RMB', '数量', '单价', '金额'], ['PHP', '数量', '单价', '金额'],
                       ['瑜伽垫加工费', 10255, 3, 30765]],
    })
    job = uploaded(context, raw)
    process_job(job.pk, job.version, 'parse'); job.refresh_from_db()
    assert job.status == 'ready' and job.rows.filter(status='valid').count() == 2
    assert {item['currency']: item['amount'] for item in job.summary['totals']} == {'CNY': '3294.000000'}
    with patch('apps.finance.warehouse_bill_uploads.enqueue'):
        response = client.post(URL + str(job.pk) + '/', {'operation': 'import', 'version': job.version}, format='json')
    assert response.status_code == 202, response.data
    job.refresh_from_db(); process_job(job.pk, job.version, 'import')
    assert WarehouseFee.objects.count() == 2
    fee = WarehouseFee.objects.get(kind='other')
    assert str(fee.amount) == '3290.000000' and fee.currency == 'CNY'
    assert fee.source['settlement_evidence']['original_amount'] == '30765.000000'
    assert fee.source['settlement_evidence']['settlement_amount'] == '3290.000000'
    assert fee.source['settlement_evidence']['quoted_rate'] == '9.35'
    assert not WarehouseFee.objects.filter(currency='PHP').exists()
    process_job(job.pk, job.version, 'import')
    assert WarehouseFee.objects.count() == 2
    from apps.finance.warehouse_fee_services import operate
    for action in ['register', 'view']:
        grant(user, 'finance.warehouse_fees.' + action)
    for row in WarehouseFee.objects.all():
        operate(user, row.pk, 'register', row.version)
    totals = client.get('/api/finance/warehouse-fees/').data['data']['registered_totals']
    assert {row['currency']: row['amount'] for row in totals} == {'CNY': '3294'}


@pytest.mark.django_db
def test_adding_year_to_failed_bill_name_recovers_month_detection(context, django_capture_on_commit_callbacks):
    client, _, store, warehouse = context
    raw = workbook({
        '代发费': [['平台订单号', '实际应收'], ['ORDER001', 4]],
        '其他应收费用': [['RMB', '数量', '单价', '金额'], ['仓储费', 1, 8, 8]],
        '订单': [['平台订单号', '店铺名称', '仓库'], ['ORDER001', store.code, warehouse.code]],
    })
    with patch('apps.finance.warehouse_bill_uploads.enqueue'):
        response = client.post(URL, {'file': SimpleUploadedFile('11月菲律宾处理费.xlsx', raw)}, format='multipart')
    job = WarehouseBillUpload.objects.get(pk=response.data['data']['id'])
    process_job(str(job.pk), job.version, 'parse'); job.refresh_from_db()
    assert job.status == 'failed' and '月份' in job.error
    with patch('apps.finance.warehouse_bill_uploads.enqueue') as enqueue:
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(URL, {'file': SimpleUploadedFile('2025年11月菲律宾处理费.xlsx', raw)}, format='multipart')
        enqueue.assert_called_once()
    assert response.status_code == 202 and response.data['data']['id'] == str(job.pk)
    job.refresh_from_db()
    process_job(str(job.pk), job.version, 'parse'); job.refresh_from_db()
    assert job.status == 'ready' and job.rows.count() == 2
    assert all(row.data['bill_month'] == '2025-11' for row in job.rows.all())
    assert not WarehouseFee.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize('status, renamed', [('failed', True), ('failed', False), ('ready', True)])
def test_reupload_retries_unimported_bill_and_preserves_mapping(context, django_capture_on_commit_callbacks, status, renamed):
    client, _, store, warehouse = context
    raw = ph_bill(store.code, warehouse.code)
    job = uploaded(context, raw)
    saved_options = {'stores': {'SHOP-PH': store.pk}, 'warehouses': {'OLD-PH': warehouse.pk}, 'currency': 'CNY'}
    job.status, job.error, job.processed, job.summary = status, '旧失败结果', 2, {'old': True}
    job.overrides = saved_options
    job.save()
    original_source = source_path(job).read_bytes()
    name = '2026年9月菲律宾订单处理费.xlsx' if renamed else job.file_name
    version = job.version
    with patch('apps.finance.warehouse_bill_uploads.enqueue') as enqueue:
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(URL, {'file': SimpleUploadedFile(name, raw), 'options': '{}'}, format='multipart')
            enqueue.assert_not_called()
        enqueue.assert_called_once()
    assert response.status_code == 202, response.data
    job.refresh_from_db()
    assert response.data['data']['id'] == str(job.pk) and WarehouseBillUpload.objects.count() == 1
    assert job.status == 'queued' and job.version == version + 1
    assert job.file_name == name and job.overrides == saved_options
    assert job.error == '' and job.processed == 0 and job.summary == {}
    assert source_path(job).read_bytes() == original_source
    process_job(str(job.pk), version, 'parse')
    job.refresh_from_db()
    assert job.status == 'queued' and not job.rows.exists()
    process_job(str(job.pk), job.version, 'parse')
    job.refresh_from_db()
    assert job.status == 'ready' and job.rows.filter(status='valid').count() == 2
    assert not WarehouseFee.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize('status', ['queued', 'parsing', 'import_queued', 'importing', 'completed'])
def test_reupload_does_not_reset_running_or_completed_bill(context, django_capture_on_commit_callbacks, status):
    client, _, store, warehouse = context
    raw = ph_bill(store.code, warehouse.code)
    job = uploaded(context, raw)
    job.status = status
    job.save()
    before = (job.file_name, job.version, job.overrides)
    with patch('apps.finance.warehouse_bill_uploads.enqueue') as enqueue:
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(URL, {'file': SimpleUploadedFile('改名2026年9月菲律宾.xlsx', raw)}, format='multipart')
        enqueue.assert_not_called()
    assert response.status_code == 202, response.data
    job.refresh_from_db()
    assert (job.file_name, job.version, job.overrides) == before and job.status == status
    assert WarehouseBillUpload.objects.count() == 1


@pytest.mark.django_db
def test_reupload_unchanged_ready_bill_does_not_queue_again(context, django_capture_on_commit_callbacks):
    client, _, store, warehouse = context
    raw = ph_bill(store.code, warehouse.code)
    job = uploaded(context, raw)
    process_job(str(job.pk), job.version, 'parse'); job.refresh_from_db()
    with patch('apps.finance.warehouse_bill_uploads.enqueue') as enqueue:
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(URL, {'file': SimpleUploadedFile(job.file_name, raw), 'options': '{}'}, format='multipart')
        enqueue.assert_not_called()
    assert response.status_code == 202, response.data
    job.refresh_from_db()
    assert job.status == 'ready' and job.version == 1 and job.rows.count() == 2


@pytest.mark.django_db
def test_reupload_preserves_partially_imported_failed_bill(context, django_capture_on_commit_callbacks):
    client, _, store, warehouse = context
    raw = ph_bill(store.code, warehouse.code)
    job = uploaded(context, raw)
    process_job(str(job.pk), job.version, 'parse'); job.refresh_from_db()
    job.rows.filter(number=1).update(status='existing')
    job.status = 'failed'; job.save()
    with patch('apps.finance.warehouse_bill_uploads.enqueue') as enqueue:
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(URL, {'file': SimpleUploadedFile('改名2026年9月菲律宾.xlsx', raw)}, format='multipart')
        enqueue.assert_not_called()
    assert response.status_code == 202, response.data
    job.refresh_from_db()
    assert job.status == 'failed' and job.version == 1
    assert job.file_name == '2026年9月菲律宾处理费.xlsx'
    assert job.rows.get(number=1).status == 'existing'


@pytest.mark.django_db
def test_reupload_changed_options_merges_only_explicit_fields(context, django_capture_on_commit_callbacks):
    client, _, store, warehouse = context
    raw = ph_bill()
    job = uploaded(context, raw)
    job.status = 'ready'
    job.overrides = {'stores': {'SHOP-PH': store.pk}, 'warehouses': {'OLD-PH': warehouse.pk}}
    job.save()
    with patch('apps.finance.warehouse_bill_uploads.enqueue') as enqueue:
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(URL, {'file': SimpleUploadedFile(job.file_name, raw), 'options': '{"currency":"CNY"}'}, format='multipart')
        enqueue.assert_called_once()
    assert response.status_code == 202, response.data
    job.refresh_from_db()
    assert job.version == 2 and job.overrides == {
        'stores': {'SHOP-PH': store.pk}, 'warehouses': {'OLD-PH': warehouse.pk}, 'currency': 'CNY'}


@pytest.mark.django_db
def test_upload_parse_confirm_drafts_is_idempotent_and_never_modifies_orders(context):
    client, user, store, warehouse = context
    order = SalesOrder.objects.get(tenant=user.tenant, store=store, external_order_id='ORDER001')
    before = list(order.items.values())
    raw = ph_bill(store.code, warehouse.code)
    job = uploaded(context, raw)
    assert not WarehouseFee.objects.exists() and source_path(job).is_file()
    process_job(str(job.pk), job.version, 'parse')
    job.refresh_from_db()
    assert job.status == 'ready', job.error
    assert job.rows.filter(status='valid').count() == 2
    assert not WarehouseFee.objects.exists() and not FinanceAuditLog.objects.filter(object_type='warehouse_fee').exists()
    preview = client.get(URL + str(job.pk) + '/').data['data']
    assert preview['count'] == 2 and preview['counts'] == {'valid': 2}
    assert uploaded(context, raw).pk == job.pk
    with patch('apps.finance.warehouse_bill_uploads.enqueue'):
        reply = client.post(URL + str(job.pk) + '/', {'operation': 'import', 'version': job.version, 'valid_only': False}, format='json')
    assert reply.status_code == 202, reply.data
    job.refresh_from_db(); process_job(str(job.pk), job.version, 'import')
    job.refresh_from_db()
    assert job.status == 'completed', job.error
    assert WarehouseFee.objects.count() == 2
    assert set(WarehouseFee.objects.values_list('status', flat=True)) == {'draft'}
    assert WarehouseFee.objects.get(kind='order').order_id == order.pk
    process_job(str(job.pk), job.version, 'import')
    assert WarehouseFee.objects.count() == 2
    order.refresh_from_db(); assert list(order.items.values()) == before
    assert WarehouseFee.objects.get(kind='order').source['sha256'] == job.file_hash
    assert client.post(URL + str(job.pk) + '/', {'operation': 'parse', 'version': job.version}, format='json').status_code == 400


@pytest.mark.django_db
def test_unknown_store_and_warehouse_can_only_be_mapped_within_tenant(context):
    client, user, store, warehouse = context
    job = uploaded(context, ph_bill())
    process_job(str(job.pk), job.version, 'parse'); job.refresh_from_db()
    assert job.rows.filter(status='error').count() == 2
    assert job.summary['unresolved']['stores'] == []  # Actual local order supplies the store, not the bill alias.
    with patch('apps.finance.warehouse_bill_uploads.enqueue'):
        response = client.post(URL + str(job.pk) + '/', {'operation': 'parse', 'version': job.version,
            'options': {'stores': {'SHOP-PH': store.pk}, 'warehouses': {'OLD-PH': warehouse.pk}}}, format='json')
    assert response.status_code == 202, response.data
    job.refresh_from_db(); process_job(str(job.pk), job.version, 'parse'); job.refresh_from_db()
    assert job.rows.filter(status='valid').count() == 2
    assert not WarehouseFee.objects.exists()


@pytest.mark.django_db
def test_jobs_are_private_and_scoped_accounts_cannot_read_unclassified_data(context):
    client, user, store, _ = context
    job = uploaded(context)
    other = user_for(user.tenant, 'another-importer'); grant(other, 'finance.warehouse_fees.import')
    assert client_for(other).get(URL + str(job.pk) + '/').status_code == 404
    assert client_for(other).get(URL).data['data']['results'] == []
    narrow = user_for(user.tenant, 'partial-fee-importer')
    grant(narrow, 'finance.warehouse_fees.import', DataScope.ScopeType.CUSTOM, {'store_ids': [store.pk]})
    assert client_for(narrow).get(URL).status_code == 403
    assert client_for(narrow).post(URL, {'file': SimpleUploadedFile('test.xlsx', b'x')}).status_code == 403


@pytest.mark.django_db
def test_permission_revoked_before_worker_prevents_import(context):
    _, user, _, _ = context
    job = uploaded(context)
    user.is_active = False; user.save()
    process_job(str(job.pk), job.version, 'parse'); job.refresh_from_db()
    assert job.status == 'failed' and not WarehouseFee.objects.exists()


@pytest.mark.django_db
def test_stale_version_and_error_only_import_require_explicit_selection(context):
    client, _, store, warehouse = context
    job = uploaded(context, ph_bill(store.code, warehouse.code, missing=True))
    process_job(str(job.pk), job.version, 'parse'); job.refresh_from_db()
    assert job.rows.filter(status='error').count() == 1
    assert client.post(URL + str(job.pk) + '/', {'operation': 'import', 'version': job.version-1}, format='json').status_code == 400
    assert client.post(URL + str(job.pk) + '/', {'operation': 'import', 'version': job.version}, format='json').status_code == 400
    with patch('apps.finance.warehouse_bill_uploads.enqueue'):
        result = client.post(URL + str(job.pk) + '/', {'operation': 'import', 'version': job.version, 'valid_only': True}, format='json')
    assert result.status_code == 202
    job.refresh_from_db(); process_job(str(job.pk), job.version, 'import')
    assert WarehouseFee.objects.count() == 1 and WarehouseFee.objects.get().kind == 'other'


@pytest.mark.django_db
def test_mapping_to_another_tenant_is_not_valid(context):
    client, _, _, _ = context
    _, _, foreign_store, foreign_warehouse = create_scope('foreign-original')
    job = uploaded(context, ph_bill())
    process_job(str(job.pk), job.version, 'parse'); job.refresh_from_db()
    with patch('apps.finance.warehouse_bill_uploads.enqueue'):
        client.post(URL + str(job.pk) + '/', {'operation': 'parse', 'version': job.version,
            'options': {'stores': {'SHOP-PH': foreign_store.pk}, 'warehouses': {'OLD-PH': foreign_warehouse.pk}}}, format='json')
    job.refresh_from_db(); process_job(str(job.pk), job.version, 'parse'); job.refresh_from_db()
    assert not job.rows.filter(status='valid').exists()
    assert not WarehouseFee.objects.exists()


@pytest.mark.django_db
def test_same_store_aliases_resolve_to_one_archive_not_false_conflict(context):
    _, user, store, warehouse = context
    from apps.finance.warehouse_bill_uploads import normalize_rows
    from apps.finance.warehouse_bill_parser import parse_bill
    job = uploaded(context)
    facts, _ = parse_bill(source_path(job), job.file_name)
    facts[0]['raw_stores'] = [store.code, store.name]
    facts[0]['raw_platform'] = 'Shopee'
    rows = list(normalize_rows(user, facts, {}, job.file_name, job.file_hash))
    assert rows[0].status == 'valid' and rows[0].data['store_id'] == store.pk
