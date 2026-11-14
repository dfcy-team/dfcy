import json
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Sum

from apps.finance.warehouse_bill_parser import BillError, CNY_ORIGINAL
from apps.finance.warehouse_bill_uploads import process_job, source_path
from apps.finance.warehouse_fee_models import WarehouseBillUpload, WarehouseFee
from apps.finance.warehouse_fee_services import operate
from tests.test_sales_management import grant
from tests.test_warehouse_bill_uploads import URL, context, ph_bill, read, workbook

MODE = {'registration_mode': CNY_ORIGINAL}


def test_original_headers_can_move_and_fee_sheet_can_be_renamed(tmp_path):
    raw = workbook({
        '业务结算单': [['MY2026年10月'], [None] * 6 + [4, '一件代发订单']],
        '本月费用明细': [['说明']] * 10 + [['实际应收金额', '备注', '平台订单编号'], [4, '', 'ORDER001']],
        'HY--仓库清单': [['仓库名称', '业务单号'], ['恒置', 'PACKAGE001']],
        '仓库费用汇总': [['人民币', '计费名称'], [4, '一件代发订单'], [1, '退货入库']],
    })
    rows, summary = read(tmp_path, raw, '2026年10月马来处理费.xlsx', MODE)
    assert len(rows) == 2
    assert rows[0]['sheet'] == '本月费用明细' and rows[0]['row'] == 12
    assert rows[0]['external_order_id'] == 'ORDER001'
    assert {r['raw_warehouse'] for r in rows} == {'恒置'}
    assert {r['currency'] for r in rows} == {'CNY'}
    assert summary['settlement']['total'] == '4.000000'


def test_duplicate_amount_headers_are_rejected_instead_of_picking_one(tmp_path):
    raw = workbook({'代发费': [['平台订单号', '实际应收', '实际应收金额'], ['ORDER001', 3, 4]]})
    with pytest.raises(BillError, match='重复'):
        read(tmp_path, raw, overrides=MODE)


def test_original_ph_amount_is_not_recalculated_from_exchange_rate(tmp_path):
    raw = workbook({
        'Sheet1': [['菲律宾2026年9月'], [None]*6+[4, '代发费'], [None]*6+[552.82, '其他应收费用']],
        '代发费': [['平台订单号', '实际应收'], ['ORDER001', 4]],
        '其他应收费用': [['PHP', '数量', '单价', '汇率', 'rmb'], ['样品', 1, 5003, 9.05, 552.82]],
    })
    rows, _ = read(tmp_path, raw, overrides=MODE)
    assert rows[1]['amount'] == '552.820000' and rows[1]['currency'] == 'CNY'
    assert Decimal(rows[1]['raw_amount']).quantize(Decimal('.01')) == Decimal('552.82')


def test_shiyang_original_keeps_missing_amount_rows_and_invoice_control(tmp_path):
    raw = workbook({
        '费用账单': [['基础信息'], ['仓库', '客户编码', '客户名称', '币种', '账单总金额', '账期', '创建人', '创建时间', '账单时间范围'],
                 ['SA_01', '', '', 'MYR', 5.5, '', '', '2026-11-03', '2026-10-01 ~ 2026-10-31'],
                 [], ['费用汇总'], [], ['费用大类', '费用汇总', '单据数量', '费用汇总'],
                 ['出库', 4, 2, 4], ['入库', 1.5, 1, 1.5]],
        '出库费用': [['费用单据号', '总金额', '仓库', '平台单号'],
                  ['FEE001', 4, 'SA_01', 'ORDER001'], ['FEE002', None, 'SA_01', 'ORDER002']],
        '入库费用': [['费用单据号', '总金额', '仓库'], ['FEE003', 1.5, 'SA_01']],
    })
    rows, summary = read(tmp_path, raw, '2026年10月马来世洋仓.xlsx', MODE)
    assert len(rows) == 3 and rows[1]['amount'] is None and rows[1]['issues']
    assert summary['bill_month'] == '2026-10'
    assert summary['settlement']['total'] == '5.500000'
    assert summary['settlement']['other_total'] == '1.500000'


@pytest.mark.django_db
def test_original_upload_adjust_restore_import_and_auto_difference(context):
    client, user, store, warehouse = context
    for action in ['create', 'edit', 'register', 'view']:
        grant(user, 'finance.warehouse_fees.' + action)
    raw = ph_bill(store.code, warehouse.code, total=5)
    with patch('apps.finance.warehouse_bill_uploads.enqueue'):
        response = client.post(URL, {'file': SimpleUploadedFile('2026年9月菲律宾处理费.xlsx', raw),
                                    'options': json.dumps(MODE)}, format='multipart')
    assert response.status_code == 202, response.data
    job = WarehouseBillUpload.objects.get(pk=response.data['data']['id'])
    process_job(str(job.pk), job.version, 'parse'); job.refresh_from_db()
    assert job.status == 'ready', job.error
    assert job.rows.filter(status='valid').count() == 2
    assert job.summary['settlement_warehouse_id'] == warehouse.pk
    original_bytes = source_path(job).read_bytes()
    response = client.post(URL + str(job.pk) + '/', {'operation': 'edit', 'version': job.version,
        'rows': [{'number': 1, 'changes': {'amount': '6'}}], 'reason': '核对后调整'}, format='json')
    assert response.status_code == 200, response.data
    job.refresh_from_db(); row = job.rows.get(number=1)
    assert row.status == 'valid' and Decimal(row.data['amount']) == 6
    assert row.source['registration_original_amount'] == '4.000000'
    assert source_path(job).read_bytes() == original_bytes
    response = client.post(URL + str(job.pk) + '/', {'operation': 'edit', 'version': job.version,
        'rows': [{'number': 1, 'changes': {'currency': 'PHP'}}], 'reason': '不允许改币种'}, format='json')
    assert response.status_code == 400
    with patch('apps.finance.warehouse_bill_uploads.enqueue'):
        response = client.post(URL + str(job.pk) + '/', {'operation': 'import', 'version': job.version}, format='json')
    assert response.status_code == 202, response.data
    job.refresh_from_db(); process_job(str(job.pk), job.version, 'import'); job.refresh_from_db()
    assert job.status == 'completed', job.error
    fees = list(WarehouseFee.objects.order_by('id'))
    assert len(fees) == 2 and all(f.status == 'draft' for f in fees)
    first = operate(user, fees[0].pk, 'register', fees[0].version)
    operate(user, fees[1].pk, 'register', fees[1].version)
    assert WarehouseFee.objects.filter(status='registered').aggregate(s=Sum('amount'))['s'] == Decimal(13)
    adjustments = WarehouseFee.objects.filter(source__type='warehouse_settlement_adjustment')
    assert sum(f.amount for f in adjustments if f.status == 'registered') == Decimal(-1)
    assert all(f.warehouse_id == warehouse.pk for f in adjustments)
    count = WarehouseFee.objects.count()
    first = operate(user, first.pk, 'correct', first.version, changes={'amount': '4'}, reason='恢复原文件金额')
    assert WarehouseFee.objects.count() == count
    assert WarehouseFee.objects.filter(status='registered').aggregate(s=Sum('amount'))['s'] == Decimal(13)
    assert first.source['registration_original_amount'] == '4.000000'
    with patch('apps.finance.warehouse_bill_uploads.enqueue'):
        again = client.post(URL, {'file': SimpleUploadedFile(job.file_name, raw), 'options': json.dumps(MODE)}, format='multipart')
    assert again.data['data']['id'] == str(job.pk)
    assert WarehouseFee.objects.count() == count
