import io

from openpyxl import Workbook

from .warehouse_fee_import import fields_for, import_fees


def fields_for_simple(kind):
    fields_for(kind)
    return [('country', '国家'), ('warehouse_code', '仓库编码'),
            ('external_order_id', '订单号／预约单号／包裹号') if kind == 'order' else ('fee_item', '费用名称'),
            ('amount', '金额（CNY）'), ('bill_month', '来源月份')]


def template_bytes(kind):
    wb = Workbook()
    ws = wb.active
    ws.title = '登记'
    ws.append([label for _, label in fields_for_simple(kind)])
    for column in 'ABCDE':
        ws.column_dimensions[column].width = 30
    # Preserve long identifiers and leading zeros when users paste values.
    for row in ws.iter_rows(min_row=2, max_row=1001, max_col=5):
        for cell in row:
            cell.number_format = '@'
    ws.freeze_panes = 'A2'
    stream = io.BytesIO()
    wb.save(stream)
    wb.close()
    return stream.getvalue()


def import_simple(user, kind, uploaded, **kwargs):
    return import_fees(user, kind, uploaded, simple=True, **kwargs)
