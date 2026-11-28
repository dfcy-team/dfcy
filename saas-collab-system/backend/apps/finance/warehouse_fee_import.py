import hashlib
import io
from datetime import date, datetime
from pathlib import Path

from django.db import transaction
from openpyxl import load_workbook
from rest_framework.exceptions import APIException, ValidationError

from apps.masterdata.models import StoreMaster, WarehouseMaster
from apps.sales_management.registration_import import safe_zip
from .warehouse_fee_models import WarehouseFeeImportBatch
from .warehouse_fee_services import create_fee, require, validate_input

SCHEMA = [('country', '国家'), ('warehouse_code', '仓库编码'), ('bill_number', '账单编号'), ('bill_month', '账单月份'),
          ('store_code', '店铺编码'), ('external_order_id', '平台订单号'), ('fee_item', '费用项目'), ('reference', '来源费用编号'),
          ('amount', '结算金额'), ('currency', '结算币种'), ('occurred_on', '发生日期'), ('original_amount', '原币金额'),
          ('original_currency', '原币币种'), ('exchange_rate', '兑换汇率'), ('rate_date', '汇率日期'),
          ('rate_source', '汇率来源'), ('note', '备注')]


def fields_for(kind):
    if kind not in {'order', 'other'}:
        raise ValidationError('请选择订单处理费或仓库其他处理费。')
    return [pair for pair in SCHEMA if kind == 'order' or pair[0] not in {'store_code', 'external_order_id'}]


def read_upload(user, kind, uploaded, *, simple=False):
    fields = fields_for(kind)
    if simple:
        from .warehouse_fee_simple_import import fields_for_simple
        fields = fields_for_simple(kind)
    if not uploaded or not uploaded.name.lower().endswith('.xlsx'):
        raise ValidationError('请选择标准xlsx登记模板；原始仓库大账单不使用此入口。')
    raw = uploaded.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        raise ValidationError('标准模板不能超过5MB，请分批上传。')
    archive = safe_zip(raw, spreadsheet=True)
    archive.close()
    try:
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=False, keep_links=False)
        if '登记' not in wb.sheetnames:
            raise ValidationError('缺少登记工作表。')
        ws = wb['登记']
        if (ws.max_row is not None and ws.max_row > 1001) or (ws.max_column is not None and ws.max_column != len(fields)):
            raise ValidationError('请使用当前标准模板，每批最多1000条。')
        # Declared dimensions are optional in XLSX. Read actual rows with the
        # same limits, also catching files whose declared dimensions undercount.
        ws.reset_dimensions()
        cells = []
        for row in ws.iter_rows():
            if len(cells) >= 1001 or len(row) > len(fields):
                raise ValidationError('请使用当前标准模板，每批最多1000条。')
            cells.append(row)
        if [c.value for c in cells[0]] != [label for _, label in fields]:
            raise ValidationError('模板表头不匹配，请重新下载对应类型模板。')
    except APIException:
        raise
    except Exception as exc:
        raise ValidationError('无法读取标准模板，请检查文件是否完整。') from exc
    finally:
        if 'wb' in locals():
            wb.close()
    inputs = []
    for number, cells_row in enumerate(cells[1:], 2):
        if not any(c.value is not None for c in cells_row):
            continue
        data, error = {}, ''
        for (key, label), cell in zip(fields, cells_row):
            value = cell.value
            if cell.data_type == 'f':
                error = f'{label}不允许公式，请粘贴核对后的数值。'
            if key in {'warehouse_code', 'store_code', 'external_order_id', 'reference', 'bill_number'} and value is not None and not isinstance(value, str):
                error = f'{label}必须为文本，不能丢失前导零或长编号精度。'
            if isinstance(value, datetime):
                value = value.date().isoformat()
            elif isinstance(value, date):
                value = value.isoformat()
            if simple and isinstance(value, str):
                value = value.strip()
            data[key] = value
        for key in ([] if simple else ['occurred_on', 'original_amount', 'exchange_rate', 'rate_date']):
            if data.get(key) in (None, ''):
                data[key] = None
        for key in ([] if simple else ['original_currency', 'rate_source', 'note']):
            data[key] = data.get(key) or ''
        store_code = data.pop('store_code', '') or ''
        warehouse_code = data.pop('warehouse_code', '') or ''
        warehouse = WarehouseMaster.objects.filter(tenant=user.tenant, code=warehouse_code).first()
        store = StoreMaster.objects.filter(tenant=user.tenant, code=store_code).first() if store_code else None
        if not warehouse or (not simple and kind == 'order' and not store):
            error = '仓库或店铺编码不存在于当前租户，请使用系统标准编码。'
        data.update(kind=kind, warehouse_id=warehouse.pk if warehouse else None, store_id=store.pk if store else None)
        if simple:
            data.pop('store_id')
            data['reference'] = f"FILE:{hashlib.sha256(raw).hexdigest()}:{number}"
        inputs.append((number, data, error))
    if not inputs:
        raise ValidationError('模板没有登记数据。')
    return raw, inputs


def import_fees(user, kind, uploaded, *, confirm=False, expected_hash='', valid_only=False, simple=False):
    require(user, 'import')
    raw, inputs = read_upload(user, kind, uploaded, simple=simple)
    file_hash = hashlib.sha256(raw).hexdigest()
    if confirm and expected_hash != file_hash:
        raise ValidationError('文件与预览不一致，请重新预览。')
    results, valid, seen = [], [], set()
    lookup = None
    if simple:
        from .warehouse_bill_matching import LocalOrderLookup
        from .warehouse_fee_registration import prepare_registration
        lookup = LocalOrderLookup(user, [(data, {'lookup_numbers': True}) for _, data, error in inputs
                                         if not error and isinstance(data.get('external_order_id', ''), str)])
    for number, data, error in inputs:
        record = {'row': number, 'reference': data.get('reference'), 'order_number': data.get('external_order_id', '')}
        try:
            if error:
                raise ValidationError(error)
            source = {'type': 'xlsx', 'file_name': Path(uploaded.name).name, 'sha256': file_hash, 'row': number}
            if simple:
                data, source = prepare_registration(user, data, source, lookup)
            _, key = validate_input(user, data, 'import', allow_unmatched=simple)
            if key in seen:
                raise ValidationError('文件内同一费用重复，请先核对来源费用编号。')
            seen.add(key)
            row, created = create_fee(user, data, action='import', preview=True, source=source)
            results.append({**record, 'status': 'valid' if created else 'existing', 'id': row.pk,
                            'match_status': row.match_status, 'amount': str(row.amount), 'currency': row.currency, 'error': ''})
            valid.append((len(results) - 1, data, source))
        except APIException as exc:
            results.append({**record, 'status': 'error', 'error': str(exc.detail)})
    if confirm:
        if any(r['status'] == 'error' for r in results) and not valid_only:
            raise ValidationError('存在错误记录；请修正或明确选择仅导入有效记录。')
        with transaction.atomic():
            for index, data, source in valid:
                row, created = create_fee(user, data, action='import', source=source)
                results[index].update(id=row.pk, status='created' if created else 'existing')
            batch, _ = WarehouseFeeImportBatch.objects.update_or_create(tenant=user.tenant, imported_by=user,
                kind=kind, file_hash=file_hash, defaults={'file_name': Path(uploaded.name).name[:191], 'results': results})
    return {'sha256': file_hash, 'confirmed': confirm, 'batch_id': batch.pk if confirm else None, 'results': results,
            'created': sum(r['status'] == 'created' for r in results), 'errors': sum(r['status'] == 'error' for r in results)}
