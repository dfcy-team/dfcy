"""Read original warehouse XLSX bills, never execute formulas or update business data."""
import posixpath
import re
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from itertools import islice
from zipfile import BadZipFile, ZipFile

from defusedxml import ElementTree as XML

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
SIX = Decimal('.000001')
CNY_ORIGINAL = 'cny_original_v1'


def header_label(value):
    label = re.sub(r'\s+', '', text(value)).replace('（', '(').replace('）', ')')
    return {'平台单号': '平台订单号', '平台订单编号': '平台订单号',
            '实际应收金额': '实际应收', '仓库名': '仓库名称'}.get(label, label)


class BillError(ValueError):
    pass


def text(value):
    return '' if value is None else str(value).strip()


def decimal(value):
    try:
        result = Decimal(text(value).replace(',', ''))
        return result if result.is_finite() and abs(result) < Decimal('1e14') else None
    except InvalidOperation:
        return None


def amount(value):
    number = decimal(value)
    if number is None:
        return None
    rounded = number.quantize(SIX, rounding=ROUND_HALF_UP)
    return str(abs(rounded) if rounded == 0 else rounded)


def day(value):
    raw = text(value)
    if re.fullmatch(r'\d{5}(\.\d+)?', raw):
        return (datetime(1899, 12, 30) + timedelta(days=float(raw))).date().isoformat()
    for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%m/%d/%Y']:
        try:
            return datetime.strptime(raw[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return None


class BillReader:
    """Stream actual rows, ignoring inflated dimension tags and embedded pictures."""
    def __init__(self, path, progress=None):
        self.progress = progress
        self.archive = ZipFile(path)
        try:
            entries = self.archive.infolist()
            names = [e.filename for e in entries]
            if len(entries) > 5000 or len(names) != len(set(names)) or sum(e.file_size for e in entries) > 2 * 1024**3:
                raise BillError('账单解压内容过大或包含重复条目。')
            if any(e.flag_bits & 1 or e.file_size > 512 * 1024**2 for e in entries):
                raise BillError('不支持加密账单或超大工作表。')
            if any('vbaproject' in n.lower() for n in names):
                raise BillError('不支持含宏的账单。')
            if any(self.archive.getinfo(n).file_size > 2 * 1024**2 for n in ['xl/workbook.xml', 'xl/_rels/workbook.xml.rels']):
                raise BillError('工作簿索引内容异常。')
            book = XML.fromstring(self.archive.read('xl/workbook.xml'))
            if book.find(NS + 'workbookPr') is not None and book.find(NS + 'workbookPr').get('date1904') in {'1', 'true'}:
                raise BillError('暂不支持1904日期系统，请另存为标准日期账单。')
            rels = XML.fromstring(self.archive.read('xl/_rels/workbook.xml.rels'))
            targets = {}
            for rel in rels:
                if rel.get('TargetMode') == 'External':
                    continue
                target = rel.get('Target', '')
                target = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
                if target.startswith('xl/worksheets/') and target in names:
                    targets[rel.get('Id')] = target
            self.sheets = {s.get('name'): targets[s.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')]
                           for s in book.find(NS + 'sheets') if s.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id') in targets}
            self.strings = []
            if 'xl/sharedStrings.xml' in names:
                if self.archive.getinfo('xl/sharedStrings.xml').file_size > 256 * 1024**2:
                    raise BillError('共享文本过大，无法安全解析。')
                with self.archive.open('xl/sharedStrings.xml') as stream:
                    root = None
                    for event, node in XML.iterparse(stream, events=('start', 'end')):
                        if root is None:
                            root = node
                        if event == 'end' and node.tag == NS + 'si':
                            self.strings.append(''.join(t.text or '' for t in node.iter(NS + 't')))
                            root.remove(node)
                            if len(self.strings) > 1500000:
                                raise BillError('共享文本条数超过安全限制。')
        except Exception:
            self.archive.close()
            raise

    def close(self):
        self.archive.close()

    def rows(self, sheet, columns=None, *, with_types=False, with_formulas=False):
        if self.progress:
            self.progress(sheet, 0)
        with self.archive.open(self.sheets[sheet]) as stream:
            parent = None
            count = 0
            for event, node in XML.iterparse(stream, events=('start', 'end')):
                if event == 'start' and node.tag == NS + 'sheetData':
                    parent = node
                if event != 'end' or node.tag != NS + 'row':
                    continue
                count += 1
                if self.progress and count % 10000 == 0:
                    self.progress(sheet, count)
                if count > 1500000:
                    raise BillError('工作表实际行数超过安全限制。')
                values, cell_types, formulas = {}, {}, {}
                for cell in node.findall(NS + 'c'):
                    col = re.sub(r'\d', '', cell.get('r', ''))
                    if columns is not None and col not in columns:
                        continue
                    formula = cell.find(NS + 'f')
                    if with_formulas and formula is not None:
                        formulas[col] = formula.text or ''
                    value = cell.find(NS + 'v')
                    raw = value.text if value is not None else None
                    if cell.get('t') == 's' and raw is not None:
                        raw = self.strings[int(raw)]
                    elif cell.get('t') == 'inlineStr':
                        raw = ''.join(t.text or '' for t in cell.iter(NS + 't'))
                    if raw is not None:
                        values[col] = raw
                        if with_types:
                            cell_types[col] = cell.get('t', 'n')
                number = int(node.get('r', count))
                if parent is not None:
                    parent.remove(node)
                node.clear()
                if values:
                    result = (number, values)
                    if with_types:
                        result += (cell_types,)
                    if with_formulas:
                        result += (formulas,)
                    yield result

    def header(self, sheet, required):
        automatic = getattr(self, 'cny_original', False)
        for row, cells in islice(self.rows(sheet), 30 if automatic else 8):
            label = header_label if automatic else text
            mapping = {label(v): col for col, v in cells.items()}
            if all(key in mapping for key in required):
                if automatic and any(sum(label(v) == key for v in cells.values()) > 1
                                     for key in required if key != '平台订单号'):
                    raise BillError(f'工作表“{sheet}”存在重复金额或标识表头，请核对后再解析。')
                return row, mapping
        raise BillError(f'工作表“{sheet}”缺少表头：' + '、'.join(required))


def parse_bill(path, file_name, overrides=None, *, progress=None):
    overrides = overrides or {}
    try:
        reader = BillReader(path, progress=progress)
    except (BadZipFile, KeyError, ValueError) as exc:
        raise BillError('无法读取xlsx账单，请检查文件是否完整、未加密。') from exc
    try:
        return _parse(reader, file_name, overrides)
    finally:
        reader.close()


def _parse(reader, file_name, overrides):
    cny_original = overrides.get('registration_mode') == CNY_ORIGINAL
    reader.cny_original = cny_original
    fee_sheet = '代发费' if '代发费' in reader.sheets else None
    if cny_original and not fee_sheet:
        candidates = []
        for sheet in reader.sheets:
            try:
                reader.header(sheet, ['平台订单号', '实际应收'])
                candidates.append(sheet)
            except BillError as exc:
                if '重复' in str(exc):
                    raise
        if len(candidates) > 1:
            raise BillError('多个工作表包含订单应收金额，无法确定费用主表，请核对原文件。')
        fee_sheet = next(iter(candidates), None)
    shiyang = cny_original and {'费用账单', '出库费用', '入库费用'} <= set(reader.sheets)
    fus = '账单汇总' in reader.sheets
    summary_sheet = '费用账单' if shiyang else '账单汇总' if fus else next((s for s in reader.sheets if '业务结算单' in s), 'Sheet1')
    summary_rows = list(islice(reader.rows(summary_sheet, with_formulas=True), 40)) if summary_sheet in reader.sheets else []
    summary = [(n, cells) for n, cells, _ in summary_rows]
    summary_formulas = {n: formulas for n, _, formulas in summary_rows}
    clues = file_name + ' ' + ' '.join(text(v) for _, row in summary[:5] for v in row.values())
    if shiyang:
        h, columns = reader.header(summary_sheet, ['账单时间范围', '账单总金额'])
        clues = file_name + ' ' + ' '.join(text(r.get(columns['账单时间范围']))
            for n, r in summary if n > h and r.get(columns['账单时间范围']))
    countries = {code for word, code in [('马来', 'MY'), ('泰国', 'TH'), ('菲律宾', 'PH')] if word in clues}
    countries.update(re.findall(r'(?<![A-Z])(MY|TH|PH)(?![A-Z])', clues.upper()))
    country = next(iter(countries)) if len(countries) == 1 else ''
    months = set()
    for year, month in re.findall(r'(20\d{2})[年/.-](\d{1,2})(?:月|[/.\-])', clues):
        if 1 <= int(month) <= 12:
            months.add(f'{year}-{int(month):02}')
    # FUS settlement periods also use MM/DD/YYYY.
    for month, _, year in re.findall(r'(\d{2})/(\d{2})/(20\d{2})', clues):
        if 1 <= int(month) <= 12:
            months.add(f'{year}-{int(month):02}')
    month = next(iter(months)) if len(months) == 1 else ''
    for key, detected in [('country', country), ('bill_month', month)]:
        if overrides.get(key) and detected and overrides[key] != detected:
            raise BillError('补充信息与原账单识别的国家或月份矛盾，请核对原文件。')
    country = overrides.get('country') or country
    month = overrides.get('bill_month') or month
    if country not in {'MY', 'TH', 'PH'} or not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])', month):
        raise BillError('无法唯一识别国家或账单月份，请补充后重新解析。')
    facts, warnings = [], []
    bill_number = file_name.rsplit('.', 1)[0][:191]
    total = Decimal(0)
    expected = None
    currency = ''
    if fus and any(text(v) in {'CNY', 'RMB', '人民币'} for _, r in summary[:5] for v in r.values()):
        currency = 'CNY'
    if not fus and ('代发费' in reader.sheets):
        # These formats explicitly settle in the RMB column / RMB invoice.
        check_sheets = [s for s in reader.sheets if '仓库费用汇总' in s or s == '其他应收费用']
        if any(any(text(v) in {'人民币', 'RMB', 'CNY'} for _, r in islice(reader.rows(s), 3) for v in r.values()) for s in check_sheets):
            currency = 'CNY'
    if overrides.get('currency') and currency and overrides['currency'] != currency:
        raise BillError('补充币种与账单明确标注的结算币种矛盾。')
    currency = currency or overrides.get('currency', '')
    if cny_original:
        currency = 'CNY'

    def emit(kind, sheet, row, item, value, *, order='', shop='', warehouse='', platform='', date=None, reference='', error='', settled=None, source_rows=None, raw_stores=None, raw_warehouses=None, tracking_numbers=None):
        nonlocal total
        number = decimal(value)
        if number == 0:
            return
        issues = [e for e in [error, '' if number is not None and number > 0 else '金额缺失、公式无缓存或非正数', '' if settled or currency else '账单未注明结算币种，请补充确认'] if e]
        if kind == 'order' and number is not None:
            total += number
        facts.append({'kind': kind, 'country': country, 'bill_month': month, 'bill_number': bill_number,
                      'fee_item': item, 'reference': reference or f'{sheet}!{row}', 'external_order_id': order,
                      'amount': amount(value), 'currency': 'CNY' if cny_original else settled or currency, 'occurred_on': date,
                      'raw_store': shop, 'raw_warehouse': warehouse, 'raw_platform': platform,
                      'raw_stores': raw_stores or [shop], 'raw_warehouses': raw_warehouses or [warehouse],
                      'sheet': sheet, 'row': row, 'source_rows': source_rows or [row], 'raw_amount': text(value),
                      'tracking_numbers': sorted(set(tracking_numbers or [])), 'issues': issues})
        if len(facts) > 300000:
            raise BillError('单账单费用超过30万条，请拆分账单。')

    if shiyang:
        for sheet, kind in [('出库费用', 'order'), ('入库费用', 'other')]:
            h, columns = reader.header(sheet, ['费用单据号', '总金额', '仓库'])
            for n, r in reader.rows(sheet, set(columns.values())):
                identifier = text(r.get(columns['费用单据号']))
                if n <= h or not identifier or any(word in identifier for word in ['合计', '总计']):
                    continue
                order = next((text(r.get(columns.get(k))) for k in ['平台订单号', '外部单号', '运单号']
                              if text(r.get(columns.get(k)))), '') if kind == 'order' else ''
                emit(kind, sheet, n, '出库处理费' if kind == 'order' else '入库费用', r.get(columns['总金额']),
                     order=order, warehouse=text(r.get(columns['仓库'])),
                     date=day(r.get(columns.get('完成时间'))), reference=f'{sheet}:{identifier}',
                     tracking_numbers=[text(r.get(columns.get('运单号')))] if kind == 'order' else [])
        # The overview is the control total; detail rows remain the source amounts.
        for n, r in summary:
            if text(r.get('A')) == '出库':
                expected = decimal(r.get('D'))
    elif fus:
        h, columns = reader.header('出库订单', ['WMS单号', '参考号', '店铺编码'])
        outbound = defaultdict(lambda: {'info': set(), 'amount': set()})
        for n, r in reader.rows('出库订单', set(columns.values())):
            if n <= h or not text(r.get(columns['WMS单号'])):
                continue
            key = text(r.get(columns['WMS单号']))
            outbound[key]['info'].add(tuple(text(r.get(columns.get(k, ''))) for k in ['参考号', '店铺编码', '仓库']) + (day(r.get(columns.get('交易日期'))),))
            value = decimal(r.get(columns.get('操作费', columns.get('总费用'))))
            if value is not None:
                outbound[key]['amount'].add(value)
        h, columns = reader.header('库内操作费', ['交易单号', '金额', '类型', '参考号', '店铺编码', '仓库'])
        charges = defaultdict(lambda: {'amount': Decimal(0), 'rows': [], 'info': set(), 'invalid': False})
        for n, r in reader.rows('库内操作费', set(columns.values())):
            if n <= h or text(r.get(columns['类型'])).lower() != 'outbound' or text(r.get(columns.get('计费项类型'))) not in {'', '出库费用'}:
                continue
            key = text(r.get(columns['交易单号']))
            value = decimal(r.get(columns['金额']))
            if value == 0:
                continue
            if not key:
                emit('order', '库内操作费', n, '出库处理费', r.get(columns['金额']),
                     order=text(r.get(columns['参考号'])), shop=text(r.get(columns['店铺编码'])),
                     warehouse=text(r.get(columns['仓库'])), reference=f'库内操作费!{n}',
                     error='交易单号缺失，需核对原账单')
                continue
            charge = charges[key]
            charge['invalid'] |= value is None
            charge['amount'] += value or Decimal(0)
            charge['rows'].append(n)
            charge['info'].add(tuple(text(r.get(columns.get(k, ''))) for k in ['参考号', '店铺编码', '仓库']) + (day(r.get(columns.get('交易日期'))),))
        for key, charge in charges.items():
            previous = outbound.get(key)
            info = charge['info'] | (previous['info'] if previous else set())
            identities = {(entry[0], entry[2]) for entry in info}
            dates = {entry[3] for entry in info if entry[3]}
            error = '同一WMS单号的订单或仓库不一致' if len(identities) != 1 else ''
            order, warehouse = sorted(identities)[0]
            shops = sorted({entry[1] for entry in info if entry[1]})
            shop = shops[0] if len(shops) == 1 else ' / '.join(shops)
            date = next(iter(dates)) if len(dates) == 1 else None
            if previous and (len(previous['amount']) != 1 or abs(next(iter(previous['amount'])) - charge['amount']) > SIX):
                error = error or '出库订单操作费与计费明细不一致'
            emit('order', '库内操作费', charge['rows'][0], '出库处理费', None if charge['invalid'] else charge['amount'], order=order,
                 shop=shop, warehouse=warehouse, date=date, reference='WMS:' + key, error=error, source_rows=charge['rows'], raw_stores=shops)
        for n, r in summary:
            item, value = text(r.get('A')), decimal(r.get('C'))
            if item == '出库费用':
                expected = value
            elif item and (text(r.get('C')) or 'C' in summary_formulas[n]) and value is None and item != '计费项类型' and text(r.get('C')) not in {'金额', '汇总'}:
                emit('other', summary_sheet, n, item, r.get('C'),
                     error='账单汇总费用金额异常，需核对原账单')
            elif item and value is not None and value != 0 and not any(t in item for t in ['合计', '总计', '总费用', '汇总']):
                warehouses = {x['raw_warehouse'] for x in facts if x['raw_warehouse']}
                emit('other', summary_sheet, n, item, value, warehouse=next(iter(warehouses)) if len(warehouses) == 1 else '')
    elif fee_sheet:
        metadata = defaultdict(set)
        names = [s for s in reader.sheets if s in {'订单', '聚灵订单', '极风订单', '一件代发出库费用'}]
        extra_warehouses = set()
        if cny_original:
            for sheet in reader.sheets:
                if '仓库清单' not in sheet:
                    continue
                h, columns = reader.header(sheet, ['仓库名称'])
                if '平台订单号' in columns:
                    names.append(sheet)
                else:
                    extra_warehouses.update(text(r.get(columns['仓库名称'])) for n, r in reader.rows(sheet, {columns['仓库名称']})
                                            if n > h and text(r.get(columns['仓库名称'])))
        if '订单' in names and '聚灵订单' in names and '极风订单' in names:
            names.remove('订单')
        for sheet in names:
            h, columns = reader.header(sheet, ['平台订单号'])
            header_cells = next(cells for n, cells in islice(reader.rows(sheet), 30) if n == h)
            order_cols = {col for col, label in header_cells.items() if (header_label(label) if cny_original else text(label)) == '平台订单号'}
            tracking_cols = {col for col, label in header_cells.items() if text(label) in {'运单号', '物流单号', '物流号', '物流追踪号', '快递单号'}}
            select = lambda *keys: next((columns[k] for k in keys if k in columns), '')
            shop_col = select('店铺名称', '店铺名', '店铺')
            wh_col = select('仓库名称', '仓库')
            date_col = select('出库时间', '发货时间', '计费时间')
            for n, r in reader.rows(sheet, {*order_cols, *tracking_cols, shop_col, wh_col, date_col, columns.get('平台')}):
                if n <= h:
                    continue
                tracking = tuple(sorted({text(r.get(col)) for col in tracking_cols if text(r.get(col))}))
                for order in {text(r.get(col)) for col in order_cols} - {''}:
                    metadata[order].add((text(r.get(shop_col)), text(r.get(wh_col)), text(r.get(columns.get('平台'))), day(r.get(date_col)), tracking))
        file_warehouses = extra_warehouses | {info[1] for values in metadata.values() for info in values if info[1]}
        h, columns = reader.header(fee_sheet, ['平台订单号', '实际应收'])
        for n, r, cell_types, formulas in reader.rows(fee_sheet, set(columns.values()), with_types=True, with_formulas=True):
            order = text(r.get(columns['平台订单号']))
            if n <= h or any(word in order for word in ['合计', '总计']):
                continue
            if not order and (any(text(v) in {'合计', '总计', '小计'} for v in r.values())
                              or re.match(r'^(SUM|SUBTOTAL|AGGREGATE)\s*\(', formulas.get(columns['实际应收'], ''), re.I)):
                continue
            if not order and decimal(r.get(columns['实际应收'])) is None and not text(r.get(columns['实际应收'])):
                continue
            values = metadata.get(order, set())
            shops = {v[0] for v in values if v[0]}
            whs = {v[1] for v in values if v[1]}
            platforms = {v[2] for v in values if v[2]}
            dates = {v[3] for v in values if v[3]}
            direct = text(r.get(columns.get('店铺')))
            if direct:
                shops.add(direct)
            if not whs and len(file_warehouses) == 1:
                whs = file_warehouses
            error = ''  # Names are compared after resolving tenant archive IDs.
            # Text IDs may legitimately contain E (e.g. Shopee order numbers).
            # Reject numeric exponent cells or explicit signed exponents, not
            # ordinary alphanumeric text that happens to resemble a number.
            numeric_exponent = re.fullmatch(r'\d+(?:\.\d+)?[Ee][+\-]?\d+', order) and cell_types.get(columns['平台订单号']) not in {'s', 'inlineStr', 'str'}
            signed_exponent = re.fullmatch(r'\d+[Ee][+\-]\d+', order)
            if not re.fullmatch(r'[A-Za-z0-9_-]{6,80}', order) or numeric_exponent or signed_exponent:
                error = '平台订单号格式异常或已使用科学计数法'
            emit('order', fee_sheet, n, '出库处理费', r.get(columns['实际应收']), order=order,
                 shop=next(iter(shops)) if len(shops) == 1 else '', warehouse=next(iter(whs)) if len(whs) == 1 else '',
                 platform=next(iter(platforms)) if len(platforms) == 1 else '', date=day(r.get(columns.get('出库日期'))) or (next(iter(dates)) if len(dates) == 1 else None),
                 reference='ORDER:' + order, error=error, raw_stores=sorted(shops), raw_warehouses=sorted(whs),
                 tracking_numbers={number for value in values for number in value[4]})
        warehouse = next(iter(file_warehouses)) if len(file_warehouses) == 1 else ''
        if country == 'PH' and '其他应收费用' in reader.sheets:
            other_start = len(facts)
            block_currency = ''
            converted = False
            for n, r, formulas in reader.rows('其他应收费用', {'A', 'B', 'C', 'D', 'E'}, with_formulas=True):
                item = text(r.get('A'))
                if item in {'RMB', '人民币', 'CNY', '比索', 'PHP'}:
                    block_currency = 'CNY' if item in {'RMB', '人民币', 'CNY'} else 'PHP'
                    converted = text(r.get('D')) == '汇率' and 'rmb' in text(r.get('E')).lower()
                    continue
                if any(t in item for t in ['合计', '总计']):
                    continue
                amount_col = 'E' if converted else 'D'
                value = r.get(amount_col)
                if decimal(value) == 0 or (not item and decimal(value) is None):
                    continue
                if not text(value) and amount_col not in formulas and not text(r.get('B')):
                    continue
                settled = 'CNY' if converted else block_currency
                error = '' if settled or cny_original else '费用未明确标注币种，需核对原账单'
                if not item:
                    error = '费用项目为空，需核对原账单'
                quantity, price = decimal(r.get('B')), decimal(r.get('C'))
                if converted and quantity is not None and price is not None and not cny_original:
                    original = quantity * price
                    before = len(facts)
                    emit('other', '其他应收费用', n, item, original, warehouse=warehouse, settled=block_currency, error=error)
                    if len(facts) > before:
                        facts[-1]['settlement_evidence'] = {
                            'original_amount': amount(original), 'original_currency': block_currency,
                            'original_sheet': '其他应收费用', 'original_row': n,
                            'settlement_amount': amount(value), 'settlement_currency': 'CNY',
                            'settlement_sheet': '其他应收费用', 'settlement_row': n,
                            'quoted_rate': text(r.get('D')), 'included_in_other_subtotal': True,
                        }
                else:
                    emit('other', '其他应收费用', n, item, value, warehouse=warehouse, settled=settled, error=error)
            invoice_other = None
            for n, r in summary:
                label = text(r.get('H'))
                if label == '代发费':
                    expected = decimal(r.get('G'))
                elif label == '其他应收费用':
                    invoice_other = decimal(r.get('G'))
                elif label and decimal(r.get('G')) not in {None, Decimal(0)} and label not in {'备注', '总计', '合计'}:
                    candidates = [fact for fact in facts[other_start:]
                                  if fact['sheet'] == '其他应收费用' and fact['fee_item'] == label
                                  and (fact['currency'] != 'CNY' or cny_original)]
                    if (currency == 'CNY' and len(candidates) == 1 and not candidates[0]['issues']
                            and (cny_original or decimal(candidates[0]['amount']) == decimal(r.get('E')))
                            and sum(text(entry.get('H')) == label for _, entry in summary) == 1):
                        fact = candidates[0]
                        fact['settlement_evidence'] = {
                            'original_amount': fact['amount'], 'original_currency': fact['currency'],
                            'original_sheet': fact['sheet'], 'original_row': fact['row'],
                            'settlement_amount': amount(r.get('G')), 'settlement_currency': 'CNY',
                            'settlement_sheet': summary_sheet, 'settlement_row': n,
                            'quoted_rate': text(r.get('F')), 'included_in_other_subtotal': False,
                        }
                        continue
                    for fact in candidates:
                        fact['issues'].append('原币费用与人民币结算汇总存在同名项目，需确认是否同一笔，不能重复登记')
                    emit('other', summary_sheet, n, label, r.get('G'), warehouse=warehouse,
                         error='额外结算项目需确认分类及是否与明细重复')
            settled_sum = Decimal(0)
            for fact in facts[other_start:]:
                if fact['sheet'] != '其他应收费用':
                    continue
                evidence = fact.get('settlement_evidence')
                if evidence:
                    if evidence.get('included_in_other_subtotal') and evidence['settlement_amount']:
                        settled_sum += Decimal(evidence['settlement_amount'])
                elif fact['currency'] == 'CNY' and fact['amount']:
                    settled_sum += Decimal(fact['amount'])
            if invoice_other is not None and abs(settled_sum - invoice_other) > SIX:
                warnings.append(f'其他费用明细与账单汇总差额{amount(settled_sum - invoice_other)} CNY')
                for fact in facts[other_start:]:
                    fact['issues'].append(f'其他费用明细与账单汇总差额{amount(settled_sum - invoice_other)} CNY')
                if len(facts) == other_start:
                    invoice_row = next(n for n, r in summary if text(r.get('H')) == '其他应收费用')
                    emit('other', summary_sheet, invoice_row, '其他应收费用', invoice_other, warehouse=warehouse,
                         error='账单其他费用汇总缺少可解析明细，需核对原账单')
        else:
            sheet = next((s for s in reader.sheets if '仓库费用汇总' in s), None)
            if not sheet:
                raise BillError('缺少仓库费用汇总表，无法确认结算金额。')
            item_col, money_col = 'B', 'I'
            if cny_original:
                _, summary_columns = reader.header(sheet, ['计费名称', '人民币'])
                item_col, money_col = summary_columns['计费名称'], summary_columns['人民币']
            for n, r, formulas in reader.rows(sheet, {item_col, money_col}, with_formulas=True):
                item, value = text(r.get(item_col)), decimal(r.get(money_col))
                if item == '一件代发订单':
                    expected = value
                elif item and (text(r.get(money_col)) or money_col in formulas) and value is None and item != '计费名称':
                    emit('other', sheet, n, item, r.get(money_col), warehouse=warehouse,
                         error='账单汇总费用金额异常，需核对原账单')
                elif item and value is not None and value != 0 and not any(t in item for t in ['合计', '总计', '汇总']):
                    emit('other', sheet, n, item, value, warehouse=warehouse)
            if country == 'TH':
                for n, r in summary:
                    item = text(r.get('H'))
                    if item and decimal(r.get('G')) not in {None, Decimal(0)} and item not in {'备注', '仓库费用', '一件代发订单', '合计', '总计'}:
                        emit('other', summary_sheet, n, item, r.get('G'), warehouse=warehouse)
    else:
        raise BillError('暂不识别此原始账单结构；支持FUS及极风/聚灵的原始结算账单。')
    duplicates = defaultdict(list)
    for fact in facts:
        if fact['kind'] == 'order':
            duplicates[fact['reference']].append(fact)
    for group in duplicates.values():
        if len(group) > 1:
            for fact in group:
                fact['issues'].append('原账单订单计费重复，需核对，未自动合并')
    difference = amount(total - expected) if expected is not None else None
    if expected is None:
        warnings.append('账单订单汇总缺失或公式缓存不可用；订单费用暂不能通过对账。')
    if expected is None or abs(total - expected) > SIX:
        for fact in facts:
            if fact['kind'] == 'order':
                fact['issues'].append('订单费用汇总不可核对' if expected is None else f'订单明细与账单汇总差额{difference} {currency}')
    if not facts:
        raise BillError('账单没有可解析的费用行。')
    result = {'country': country, 'bill_month': month, 'bill_number': bill_number, 'currency': currency,
              'format': '世洋' if shiyang else 'FUS' if fus else '极风/聚灵', 'order_detail_sum': amount(total),
              'order_bill_total': amount(expected), 'order_difference': difference, 'warnings': warnings}
    from .warehouse_bill_settlement import invoice_plan
    result['settlement'] = invoice_plan(reader, result)
    if cny_original:
        result['registration_mode'] = CNY_ORIGINAL
    return facts, result
