"""Bounded offline warehouse receipts. Preview never creates or links records."""
import csv
import hashlib
from io import BytesIO, StringIO
from zipfile import BadZipFile, ZipFile

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from apps.masterdata.models import WarehouseMaster
from .aftersales import _quantity, _text, ingest_receipt, require_full_scope

HEADERS = ('仓库编码', '仓库退货单号', '平台订单号', '运单号', 'SKU', '实收数量', '实际入库时间')
MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000


def read_rows(uploaded):
    if not uploaded or uploaded.size > MAX_BYTES:
        raise ValidationError('请选择不超过5MB的 CSV 或 XLSX 文件。')
    raw = uploaded.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValidationError('文件超过5MB。')
    suffix = uploaded.name.lower().rsplit('.', 1)[-1]
    try:
        if suffix == 'csv':
            rows = []
            for row in csv.reader(StringIO(raw.decode('utf-8-sig'))):
                rows.append(row)
                if len(rows) > MAX_ROWS + 1:
                    raise ValidationError('每次最多5000行，请拆分文件。')
        elif suffix == 'xlsx':
            with ZipFile(BytesIO(raw)) as archive:
                if len(archive.infolist()) > 2000 or sum(item.file_size for item in archive.infolist()) > 50 * 1024 * 1024:
                    raise ValidationError('工作簿解压后过大。')
            from openpyxl import load_workbook
            book = load_workbook(BytesIO(raw), read_only=True, data_only=False, keep_links=False)
            try:
                rows = []
                for cells in book.active.iter_rows():
                    if any(cell.data_type == 'f' for cell in cells):
                        raise ValidationError('导入不接受公式，请使用已核对的原始值。')
                    rows.append([cell.value for cell in cells])
                    if len(rows) > MAX_ROWS + 1:
                        raise ValidationError('每次最多5000行，请拆分文件。')
            finally:
                book.close()
        else:
            raise ValidationError('仅支持 CSV 和 XLSX。')
    except (UnicodeError, BadZipFile, csv.Error, ValueError, KeyError) as exc:
        raise ValidationError('文件损坏或编码不支持；CSV 请保存为 UTF-8。') from exc
    if not rows or tuple(rows[0][:len(HEADERS)]) != HEADERS:
        raise ValidationError('列名或列顺序与模板不一致，请先按模板整理仓库导出文件。')
    if not 1 <= len(rows) - 1 <= MAX_ROWS:
        raise ValidationError('文件需包含1至5000行商品记录。')
    return rows[1:], hashlib.sha256(raw).hexdigest()


def prepare_import(user, uploaded):
    require_full_scope(user)
    rows, digest = read_rows(uploaded)
    warehouses = {item.code: item for item in WarehouseMaster.objects.filter(tenant=user.tenant)}
    groups, seen, samples = {}, set(), []
    count = 0
    for number, cells in enumerate(rows, 2):
        if all(value in (None, '') for value in cells):
            continue
        if len(cells) < len(HEADERS):
            raise ValidationError(f'第{number}行字段不完整。')
        values = dict(zip(HEADERS, cells))
        try:
            code = _text(values['仓库编码'], required=True)
            warehouse = warehouses.get(code)
            if warehouse is None:
                raise ValidationError('仓库编码不存在于当前租户；不按名称猜测归属。')
            return_no = _text(values['仓库退货单号'], required=True)
            order_no, tracking = (_text(values[key] if values[key] is not None else '') for key in ('平台订单号', '运单号'))
            sku = _text(values['SKU'], required=True)
            quantity = values['实收数量']
            if type(quantity) is float and quantity.is_integer():
                quantity = int(quantity)
            quantity = _quantity(quantity)
            if not quantity:
                raise ValidationError('导出补充仅接受正数实收数量。')
            raw_time = values['实际入库时间']
            received_at = parse_datetime(raw_time) if isinstance(raw_time, str) else raw_time
            if not received_at or timezone.is_naive(received_at) or received_at > timezone.now():
                raise ValidationError('实际入库时间须包含时区且不能晚于当前时间；Excel 时间请按文本填写。')
            key = (code, return_no)
            if (*key, sku) in seen:
                raise ValidationError('同一退货单 SKU 重复，请核对实收数量，不自动累加。')
            seen.add((*key, sku))
            item = groups.setdefault(key, {'warehouse': warehouse, 'value': {'return_no': return_no,
                'platform_order_no': order_no, 'tracking_no': tracking, 'received_at': received_at.isoformat(), 'lines': []}})
            if any(item['value'][field] != val for field, val in (('platform_order_no', order_no), ('tracking_no', tracking), ('received_at', received_at.isoformat()))):
                raise ValidationError('同一退货单的订单号、运单号或实收时间不一致。')
            item['value']['lines'].append({'sku': sku, 'received_quantity': quantity})
            count += 1
            if len(samples) < 20:
                samples.append({'row': number, 'warehouse_code': code, 'return_no': return_no, 'platform_order_no': order_no,
                                'sku': sku, 'received_quantity': quantity})
        except (ValidationError, ValueError, TypeError, AttributeError) as exc:
            message = exc.detail if isinstance(exc, ValidationError) else '时间或数量格式无效。'
            raise ValidationError({'row': number, 'detail': message}) from exc
    if not count:
        raise ValidationError('文件没有商品记录。')
    return list(groups.values()), {'sha256': digest, 'documents': len(groups), 'lines': count, 'preview': samples}


@transaction.atomic
def commit_import(user, prepared):
    created = existing = 0
    for item in prepared:
        _, added = ingest_receipt(user, item['warehouse'], item['value'], source='file')
        created += int(added)
        existing += int(not added)
    return {'created_documents': created, 'existing_documents': existing, 'inventory_changed': False}
