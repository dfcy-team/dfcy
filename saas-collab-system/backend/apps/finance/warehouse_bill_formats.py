"""Server-side versioned worksheet rules, scoped to tenant warehouse access."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from itertools import islice
import re

from django.db import IntegrityError, transaction
from rest_framework.exceptions import NotFound, ValidationError

from apps.masterdata.models import WarehouseMaster
from .models import FinanceAuditLog
from .warehouse_bill_parser import BillError, BillReader, amount, decimal, text
from .warehouse_bill_contract import POLICY, audit_file
from .warehouse_fee_models import WarehouseBillFormatRule
from .warehouse_fee_services import scope_configs, values_allowed

SCHEMA = 3


def warehouses_for(user):
    configs = scope_configs(user, 'import')
    warehouses = WarehouseMaster.objects.filter(tenant=user.tenant)
    if configs is None:
        return warehouses
    ids = [w.pk for w in warehouses if values_allowed(user, 'import',
        {'warehouse_id': w.pk, 'store_id': None, 'country': w.country_code, 'currency': 'CNY'}, None)]
    return warehouses.filter(pk__in=ids)


def rules_for(user, *, include_archived=False):
    rules = WarehouseBillFormatRule.objects.filter(tenant=user.tenant)
    if not include_archived:
        rules = rules.filter(is_active=True)
    if scope_configs(user, 'import') is not None:
        rules = rules.filter(warehouse__in=warehouses_for(user))
    return rules.select_related('warehouse').order_by('name', 'pk')


def describe_rule(rule, successful_files=None):
    return dict(id=rule.pk, name=rule.name, warehouse_id=rule.warehouse_id,
        warehouse_code=rule.warehouse.code if rule.warehouse_id else '通用格式', country=rule.warehouse.country_code if rule.warehouse_id else '',
        version=rule.version, config=rule.config, created_at=rule.created_at,
        successful_files=successful_files or [])


def successful_rule_files(user, rules):
    """Rule sharing does not expose another uploader's private file names."""
    from .warehouse_fee_models import WarehouseBillUpload
    files = {str(rule.pk): [] for rule in rules}
    if scope_configs(user, 'import') is not None:
        return files
    def add(rule_id, filename):
        key = str(rule_id)
        if key in files and isinstance(filename, str) and filename and filename not in files[key]:
            files[key].append(filename)
    events = FinanceAuditLog.objects.filter(tenant=user.tenant, actor=user,
        object_type='warehouse_bill_format', object_id__in=files,
        action__in=['source_conversion', 'parse_success']).order_by('-created_at', '-id')
    for rule_id, detail in events.values_list('object_id', 'masked_detail'):
        add(rule_id, detail.get('file_name') or detail.get('source_file'))
    jobs = WarehouseBillUpload.objects.filter(tenant=user.tenant, uploaded_by=user,
        status__in=['ready','completed'], summary__applied_rule__id__in=[rule.pk for rule in rules]).order_by('-updated_at')
    for filename, summary in jobs.values_list('file_name','summary'):
        add((summary.get('applied_rule') or {}).get('id'), filename)
    return files


def clean_config(config):
    if not isinstance(config, dict) or set(config) != {'schema_version', 'sheets'} or config.get('schema_version') != SCHEMA:
        raise BillError('格式配置版本无效；旧整表其他费用规则必须重新配置。')
    specs = config['sheets']
    if not isinstance(specs, list) or not 1 <= len(specs) <= 100:
        raise BillError('请配置1至100张工作表。')
    names = set()
    for spec in specs:
        if not isinstance(spec, dict) or set(spec) - {'name','kind','header','end','columns','expected','items','reason','start','total_source','filters','group_by','skip_zero','warehouse_column','warehouse_header','warehouse_values','month_name','settlement_auto','header_mode','optional_sheet','sheet_aliases','field_aliases'}:
            raise BillError('工作表配置包含不支持的字段。')
        name, kind = spec.get('name'), spec.get('kind')
        if 'field_aliases' in spec and (not isinstance(spec['field_aliases'],dict) or len(spec['field_aliases'])>20 or any(not isinstance(k,str) or not re.fullmatch('[A-Z]{1,3}',k) or not isinstance(v,list) or len(v)>10 or any(not isinstance(label,str) or not label.strip() or len(label)>191 for label in v) for k,v in spec['field_aliases'].items())):
            raise BillError('字段备用名称配置无效。')
        if 'sheet_aliases' in spec and (not isinstance(spec['sheet_aliases'],list) or len(spec['sheet_aliases']) > 30 or any(not isinstance(n,str) or not n.strip() or len(n)>100 for n in spec['sheet_aliases'])):
            raise BillError('工作表备用名称无效或超过30个。')
        if 'header_mode' in spec and (spec['header_mode'] not in {'exact','fields'} or kind == 'ignore'):
            raise BillError('表头识别方式无效。')
        if 'optional_sheet' in spec and (kind != 'ignore' or type(spec['optional_sheet']) is not bool):
            raise BillError('仅辅助工作表允许按已知名称缺省。')
        if 'month_name' in spec and type(spec['month_name']) is not bool:
            raise BillError('工作表月份匹配配置无效。')
        if 'settlement_auto' in spec and (kind != 'settlement' or spec['settlement_auto'] not in {'total_row','items_in_range','sequence_total'}):
            raise BillError('结算自动定位配置无效。')
        if not isinstance(name, str) or not name or len(name) > 100 or name in names:
            raise BillError('工作表名称无效或重复。')
        names.add(name)
        if not isinstance(spec.get('reason', ''), str) or len(spec.get('reason', '')) > 500:
            raise BillError('忽略或范围说明最多500字。')
        if any(k in spec for k in ['warehouse_column','warehouse_header','warehouse_values']):
            if (not isinstance(spec.get('warehouse_column'), str) or not re.fullmatch('[A-Z]{1,3}', spec['warehouse_column'])
                or type(spec.get('warehouse_header')) is not int or not 1 <= spec['warehouse_header'] <= 30
                or not isinstance(spec.get('warehouse_values'), list) or not 1 <= len(spec['warehouse_values']) <= 30
                or any(not isinstance(v,str) or not v.strip() or len(v)>191 for v in spec['warehouse_values'])):
                raise BillError('仓库核对条件须提供表头行、仓库列和允许名称。')
        if kind == 'ignore':
            if not text(spec.get('reason')):
                raise BillError(f'请填写忽略工作表“{name}”的原因。')
            continue
        if kind not in {'order', 'settlement'}:
            raise BillError(f'工作表“{name}”尚未指定用途。')
        header, end = spec.get('header'), spec.get('end')
        if type(header) is not int or not 1 <= header <= 30 or end is not None and (type(end) is not int or end <= header or end > 1500000):
            raise BillError('表头须为1至30行，结束行须在表头之后。')
        start = spec.get('start', header + 1)
        if type(start) is not int or start <= header or (end is not None and start > end):
            raise BillError('数据开始行必须在表头之后且不超过结束行。')
        total_source = spec.get('total_source', '')
        if not isinstance(total_source, str) or (total_source and (kind != 'settlement' or not re.fullmatch(r'(sum|[A-Z]{1,3}[1-9][0-9]{0,6})', total_source))):
            raise BillError('结算总额来源须为单元格地址或项目合计。')
        group_by = spec.get('group_by', '')
        if not isinstance(group_by, str) or (group_by and (kind != 'order' or not re.fullmatch('[A-Z]{1,3}', group_by))):
            raise BillError('合并列必须是订单明细的有效列。')
        if 'skip_zero' in spec and type(spec['skip_zero']) is not bool:
            raise BillError('跳过零金额配置无效。')
        filters = spec.get('filters', [])
        if not isinstance(filters, list) or len(filters) > 10 or (filters and kind != 'order'):
            raise BillError('筛选条件最多10项。')
        for condition in filters:
            if (not isinstance(condition, dict) or set(condition) - {'column', 'values', 'optional'} or not {'column','values'} <= set(condition)
                or ('optional' in condition and type(condition['optional']) is not bool)
                or not isinstance(condition['column'], str) or not re.fullmatch('[A-Z]{1,3}', condition['column'])
                or not isinstance(condition['values'], list) or not 1 <= len(condition['values']) <= 30
                or any(not isinstance(v, str) or len(v) > 191 for v in condition['values'])):
                raise BillError('筛选条件须指定列和允许值。')
        fields = {'number','amount'} if kind == 'order' else {'item','amount'}
        cols, expected = spec.get('columns'), spec.get('expected')
        if not isinstance(cols, dict) or set(cols) != fields or any(
                not isinstance(c, str) or not re.fullmatch('[A-Z]{1,3}', c) for c in cols.values()) or len(set(cols.values())) != len(fields):
            raise BillError('字段必须选择互不重合的有效列。')
        if not isinstance(expected, dict) or not expected or len(expected) > 200 or any(
                not isinstance(k, str) or not re.fullmatch('[A-Z]{1,3}', k) or not isinstance(v, str) or len(v) > 500
                for k, v in expected.items()):
            raise BillError('缺少完整的表头快照，请重新读取原表。')
        if kind == 'settlement':
            items = spec.get('items')
            if not isinstance(items, dict) or len(items) > 1000:
                raise BillError('结算项目配置无效或超过1000项。')
            for label, rule in items.items():
                if not isinstance(label, str) or not label or len(label) > 191 or not isinstance(rule, dict) or set(rule) - {'role','reason'}:
                    raise BillError('结算项目配置无效。')
                if rule.get('role') not in {'order','other','total','empty','ignore'}:
                    raise BillError('每个结算项目都须明确用途。')
                if rule['role'] == 'ignore' and not text(rule.get('reason')):
                    raise BillError('忽略结算项目必须填写原因。')
                if not isinstance(rule.get('reason',''), str) or len(rule.get('reason','')) > 500:
                    raise BillError('项目忽略说明最多500字。')
    return deepcopy(config)


def inspect_file(path, spec=None, *, progress=None):
    reader = BillReader(path, progress=progress)
    try:
        if spec is not None:
            spec = deepcopy(spec)
            if spec.get('settlement_auto') in {'sequence_total','total_row'}:
                from .warehouse_bill_rule_resolution import resolve_fields, resolve_sequence_total
                rows = dict(reader.rows(spec['name']))
                spec['expected'] = spec.get('expected') or {k:text(v) for k,v in rows.get(spec['header'],{}).items() if text(v)}
                if spec.get('header_mode') == 'fields': resolve_fields(spec, rows)
                if spec['settlement_auto'] == 'sequence_total':
                    resolve_sequence_total(spec, rows)
                else:
                    item, money = spec.get('columns',{}).get('item'), spec.get('columns',{}).get('amount')
                    if not item or not money: raise BillError('请先选择项目和金额字段。')
                    from .warehouse_bill_rule_resolution import labelled_total_rows
                    totals = labelled_total_rows(rows, spec['header'], money)
                    if not totals: raise BillError('未找到有效的合计标签及金额，请核对总额定位方式。')
                    if len(totals) > 1: raise BillError('找到多个合计金额行，请明确总额位置。')
                    spec.update(start=spec['header']+1,end=totals[0]-1,total_source=f'{money}{totals[0]}')
                return {'items':settlement_items(reader,spec), 'range':{k:spec[k] for k in ('header','start','end','total_source','columns','expected')}}
            return {'items': settlement_items(reader, spec)}
        return {'sheets': [{'name': name, 'sample': [{'row': n, 'cells': cells}
            for n, cells in islice(reader.rows(name), 40)]} for name in reader.sheets]}
    finally:
        reader.close()


def resolution_samples(path, config, *, progress=None):
    from .warehouse_bill_rule_resolution import month_name
    reader = BillReader(path, progress=progress)
    try:
        settlements = [s for s in config['sheets'] if s['kind'] == 'settlement']
        return [{'name':name,'sample':[{'row':n,'cells':cells} for n,cells in
            (reader.rows(name) if any(any(month_name(name)==month_name(alias) if s.get('month_name') else name==alias
                for alias in [s['name'],*s.get('sheet_aliases',[])]) for s in settlements)
             else islice(reader.rows(name),40))]} for name in reader.sheets]
    finally:
        reader.close()


def settlement_items(reader, spec):
    if not isinstance(spec, dict):
        raise BillError('请指定结算表范围。')
    header, end, cols = spec.get('header'), spec.get('end'), spec.get('columns', {})
    if (spec.get('name') not in reader.sheets or type(header) is not int or not 1 <= header <= 30
        or end is not None and (type(end) is not int or end <= header)
        or any(not isinstance(cols.get(k), str) or not re.fullmatch('[A-Z]{1,3}', cols[k]) for k in ['item','amount'])
        or cols['item'] == cols['amount']):
        raise BillError('请指定结算表、范围及不同的项目和金额列。')
    result, seen = [], set()
    for n, cells in reader.rows(spec['name']):
        if n < spec.get('start', header + 1) or end is not None and n > end:
            continue
        item, raw = text(cells.get(cols['item'])), text(cells.get(cols['amount']))
        if not item and not raw:
            continue
        if not item or item in seen:
            raise BillError(f'结算表第{n}行项目缺失或重复，请限定单个结算范围。')
        seen.add(item)
        result.append(dict(item=item, raw=raw, amount=amount(raw), row=n))
        if len(result) > 1000:
            raise BillError('结算项目超过1000项，请缩小范围。')
    return result


def check_warehouse(spec, row, cells):
    if spec.get('warehouse_column') and row > spec['warehouse_header']:
        value = text(cells.get(spec['warehouse_column']))
        if value and value not in spec['warehouse_values']:
            raise BillError(f'工作表“{spec["name"]}”包含规则范围外的仓库，请核对混仓账单，不能整单归入同一仓库。')


def parse_mapped(path, file_name, config, warehouse, month, *, progress=None, manual_context=False):
    config = clean_config(config)
    if not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])', month or ''):
        raise BillError('请确认当前文件来源月份，规则不保存旧月份。')
    match = re.search(r'(20\d{2})[年.-](\d{1,2})(?:月|[.-])', file_name)
    if not manual_context and match and month != f'{match[1]}-{int(match[2]):02}':
        raise BillError('来源月份与当前原文件名称不一致。')
    if any(s.get('month_name') or s.get('settlement_auto') or s.get('header_mode') == 'fields' or s.get('optional_sheet') or s.get('sheet_aliases') for s in config['sheets']):
        from .warehouse_bill_rule_resolution import resolve_config
        config = resolve_config(config, resolution_samples(path, config, progress=progress))
    reader = BillReader(path, progress=progress)
    try:
        if {s['name'] for s in config['sheets']} != set(reader.sheets):
            raise BillError('工作表集合已变化，请重新配置，不能遗漏工作表。')
        facts, coverage, lines, totals, controls = [], [], [], [], []
        bill = file_name.rsplit('.', 1)[0][:191]
        for spec in config['sheets']:
            name, kind = spec['name'], spec['kind']
            if kind == 'ignore':
                count = 0
                for n, cells in reader.rows(name):
                    check_warehouse(spec,n,cells)
                    count += bool(any(text(v) for v in cells.values()))
                coverage.append(dict(sheet=name, kind=kind, count=0, skipped=count, outside=0, reason=spec['reason']))
                continue
            head = dict(islice(reader.rows(name), 30)).get(spec['header'], {})
            if {k:text(v) for k,v in head.items() if text(v)} != {k:text(v) for k,v in spec['expected'].items() if text(v)}:
                raise BillError(f'工作表“{name}”表头或列已变化，请重新配置。')
            columns, rules = spec['columns'], spec.get('items', {})
            if kind == 'settlement':
                items = settlement_items(reader, spec)
                if set(rules) != {i['item'] for i in items}:
                    raise BillError('结算项目已变化，请逐项重新确认用途。')
                for item in items:
                    role, value = rules[item['item']]['role'], decimal(item['raw'])
                    if role == 'empty' and item['raw'] and value != 0:
                        raise BillError('跳过项目出现非零金额，必须重新核对。')
                    lines.append({**item,'kind':role,'sheet':name,'column':columns['amount'],
                                  'reason':rules[item['item']].get('reason','')})
                    if role == 'total': totals.append(value)
                    if role == 'order': controls.append(value)
            total_source = spec.get('total_source')
            if total_source:
                if total_source == 'sum':
                    values = [decimal(i['raw']) for i in items if rules[i['item']]['role'] != 'empty']
                    totals.append(sum(values, Decimal(0)) if all(v is not None for v in values) else None)
                else:
                    col, row = re.fullmatch(r'([A-Z]+)([0-9]+)', total_source).groups()
                    cells = next((c for n, c in reader.rows(name) if n == int(row)), {})
                    totals.append(decimal(cells.get(col)))
            count = skipped = outside = 0
            grouped = {}
            for n, cells, cell_types, formulas in reader.rows(name, with_types=True, with_formulas=True):
                check_warehouse(spec,n,cells)
                if n <= spec['header'] or not any(text(v) for v in cells.values()): continue
                if n < spec.get('start', spec['header'] + 1):
                    outside += 1
                    continue
                if any(text(cells.get(c['column'])) not in c['values'] for c in spec.get('filters', [])):
                    skipped += 1
                    continue
                if spec.get('end') and n > spec['end']:
                    outside += 1
                    continue
                if kind == 'order' and any(text(v) in {'合计','总计','小计','总费用','总金额'} for v in cells.values()):
                    skipped += 1
                    continue
                item = text(cells.get(columns['item'])) if kind == 'settlement' else '仓库处理费'
                if kind == 'settlement' and (not item or rules[item]['role'] != 'other'):
                    skipped += 1
                    continue
                number = text(cells.get(columns['number'])) if kind == 'order' else ''
                raw = cells.get(columns['amount'])
                if kind == 'order' and not number and (re.match(r'^(SUM|SUBTOTAL|AGGREGATE)\s*\(', formulas.get(columns['amount'], ''), re.I) or not text(raw)):
                    skipped += 1
                    continue
                if spec.get('skip_zero') and decimal(raw) == 0:
                    skipped += 1
                    continue
                issues = []
                if kind == 'order' and re.fullmatch(r'\d+(?:\.\d+)?[Ee][+-]?\d+', number) and cell_types.get(columns['number']) not in {'s','str','inlineStr'}:
                    issues.append('原单号使用科学计数法，不能猜补。')
                fact = dict(kind='order' if kind == 'order' else 'other', country=warehouse.country_code,
                    bill_month=month, bill_number=bill, fee_item=item, reference=f'{name}!{n}', external_order_id=number,
                    amount=amount(raw), currency='CNY', occurred_on=None, raw_store='', raw_warehouse=warehouse.code,
                    raw_platform='', raw_stores=[], raw_warehouses=[warehouse.code], sheet=name, row=n,
                    source_rows=[n], raw_amount=text(raw), tracking_numbers=[], issues=issues)
                key = text(cells.get(spec.get('group_by'))) if spec.get('group_by') else ''
                if spec.get('group_by') and not key:
                    fact['issues'].append('合并依据缺失，需核对原账单')
                if key and key in grouped:
                    previous = grouped[key]
                    if previous['external_order_id'] != number:
                        previous['issues'].append('同一合并依据的订单号不一致')
                    a, b = decimal(previous['raw_amount']), decimal(fact['raw_amount'])
                    combined = a + b if a is not None and b is not None else None
                    previous['amount'] = amount(combined)
                    previous['raw_amount'] = str(combined) if combined is not None else ''
                    previous['source_rows'].append(n)
                    previous['issues'].extend(issues)
                else:
                    facts.append(fact)
                    if key: grouped[key] = fact
                count += 1
                if len(facts) > 300000: raise BillError('费用超过30万行，请拆分文件。')
            if outside and not text(spec.get('reason')):
                raise BillError(f'工作表“{name}”范围外仍有{outside}行，须说明未纳入原因。')
            coverage.append(dict(sheet=name,kind=kind,count=count,skipped=skipped,outside=outside,reason=spec.get('reason','')))
        if len(totals) != 1:
            raise BillError('结算总额必须且只能指定一项。')
        order = sum(controls, Decimal(0)) if controls and all(x is not None for x in controls) else None
        included = [decimal(l['amount']) for l in lines if l['kind'] in {'order','other','ignore'}]
        line_total = sum(included, Decimal(0)) if all(v is not None for v in included) else None
        total = totals[0]
        summary = dict(country=warehouse.country_code,bill_month=month,bill_number=bill,currency='CNY',
            format='已配置格式',coverage=coverage, warnings=[],order_bill_total=amount(order),
            order_detail_sum=amount(sum((decimal(f['amount']) or Decimal(0) for f in facts if f['kind']=='order'))),
            settlement=dict(policy=POLICY,valid=total is not None and order is not None, total=amount(total),
                order_total=amount(order), lines=lines, currency='CNY',
                line_difference=amount(total-line_total) if total is not None and line_total is not None else None))
        return audit_file(facts, summary)
    finally:
        reader.close()


def save_rule(user, supplied):
    if not isinstance(supplied, dict) or set(supplied) not in ({'name','warehouse_id','config'}, {'id','version','name','warehouse_id','config'}):
        raise ValidationError('请提供规则名称、仓库和配置。')
    name = supplied['name']
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ValidationError('规则名称须为1至100字。')
    from rest_framework.serializers import IntegerField
    warehouse_id = IntegerField(min_value=1, allow_null=True).run_validation(supplied['warehouse_id'])
    warehouse = warehouses_for(user).filter(pk=warehouse_id).first()
    if warehouse_id and not warehouse: raise NotFound('仓库不存在或不在授权范围。')
    if warehouse_id is None and scope_configs(user, 'import') is not None:
        raise ValidationError('通用格式需要全部数据范围的处理费导入权限。')
    config = clean_config(supplied['config'])
    try:
        with transaction.atomic():
            if warehouse is None:
                type(user.tenant).objects.select_for_update().get(pk=user.tenant_id)
                if WarehouseBillFormatRule.objects.filter(tenant=user.tenant, warehouse__isnull=True, name=name.strip()).exclude(pk=supplied.get('id')).exists():
                    raise ValidationError('已有同名通用格式，请使用不同名称。')
            if 'id' in supplied:
                rule = rules_for(user).select_for_update().filter(pk=IntegerField(min_value=1).run_validation(supplied['id'])).first()
                if not rule:
                    raise NotFound('格式规则不存在或不在授权范围。')
                if type(supplied['version']) is not int or supplied['version'] != rule.version:
                    raise ValidationError('规则已被修改，请重新选择规则后再保存。')
                rule.name, rule.warehouse, rule.config = name.strip(), warehouse, config
                rule.version += 1
                rule.save(update_fields=['name', 'warehouse', 'config', 'version'])
            else:
                rule = WarehouseBillFormatRule.objects.create(tenant=user.tenant, warehouse=warehouse,
                    name=name.strip(), config=config, created_by=user)
            FinanceAuditLog.objects.create(tenant=user.tenant,actor=user,object_type='warehouse_bill_format',
                object_id=str(rule.pk), action='update' if 'id' in supplied else 'create',masked_detail={'name':rule.name,'warehouse_id':warehouse.pk if warehouse else None,'config':config})
    except IntegrityError:
        raise ValidationError('该仓库已有同名规则，请使用不同名称或选择修改原规则。') from None
    return rule


def parse_new_bill(user, path, file_name, options, *, progress=None):
    from .warehouse_bill_parser import CNY_ORIGINAL, parse_bill
    from .warehouse_bill_contract import settlement_facts
    manual_context = options.get('order_warehouse', False)
    if manual_context and (not options.get('country') or not options.get('bill_month')):
        raise BillError('请人工选择国家和账单月份后解析。')
    month = options.get('bill_month')
    match = re.search(r'(20\d{2})[年.-](\d{1,2})(?:月|[.-])', file_name)
    month = month or (f'{match[1]}-{int(match[2]):02}' if match else '')
    country = options.get('country') or next((v for k,v in [('菲律宾','PH'),('泰国','TH'),('马来','MY')] if k in file_name), '')
    available = rules_for(user, include_archived=bool(options.get('format_rule_id')))
    if country and not manual_context: available = available.filter(warehouse__country_code=country)
    if options.get('warehouse_id') and not manual_context: available = available.filter(warehouse_id=options['warehouse_id'])
    chosen, config, warehouse = None, options.get('format_config'), None
    if config:
        warehouse = warehouses_for(user).filter(pk=options.get('warehouse_id')).first()
        if not warehouse and not manual_context: raise BillError('配置原文件格式前请选择有权限的仓库。')
    elif options.get('format_rule_id'):
        chosen = available.filter(pk=options['format_rule_id']).first()
        if not chosen: raise BillError('所选格式规则不存在或不在授权范围。')
        if options.get('format_rule_version') is not None and chosen.version != options['format_rule_version']:
            raise BillError('格式规则已更新，请重新选择规则后解析。')
    else:
        sample = inspect_file(path, progress=progress)
        actual = {s['name']: {r['row']:r['cells'] for r in s['sample']} for s in sample['sheets']}
        relevant, matches = [], []
        for rule in available:
            specs = rule.config.get('sheets', []) if isinstance(rule.config, dict) else []
            from .warehouse_bill_rule_resolution import month_name
            if not any(s.get('kind') != 'ignore' and (s.get('name') in actual or s.get('month_name') and month_name(s.get('name','')) in {month_name(n) for n in actual}) for s in specs): continue
            relevant.append(rule)
            if rule.config.get('schema_version') != SCHEMA: continue
            from .warehouse_bill_rule_resolution import resolve_config
            try:
                resolve_config(rule.config, resolution_samples(path, rule.config, progress=progress))
            except BillError:
                continue
            matches.append(rule)
        if len(matches) > 1:
            raise BillError('多个格式规则匹配，请明确选择：' + '、'.join(f'{r.name}（{r.warehouse.code if r.warehouse_id else "通用格式"}）' for r in matches)[:350])
        if matches: chosen = matches[0]
        elif relevant: raise BillError('已有相关规则发生工作表或表头漂移，请重新配置，不自动回退内置解析。')
    if chosen:
        config, warehouse = chosen.config, chosen.warehouse
    if config:
        if manual_context:
            selected = warehouses_for(user).filter(pk=options.get('warehouse_id'), country_code=country).first()
            if options.get('warehouse_id') and not selected:
                raise BillError('其他费用仓库不存在或国家不一致。')
            warehouse = SimpleNamespace(pk=selected.pk if selected else None, code=selected.code if selected else '', country_code=country)
            config = deepcopy(config)
            for spec in config['sheets']:
                for key in ['warehouse_column', 'warehouse_header', 'warehouse_values']:
                    spec.pop(key, None)
        if not warehouse:
            raise BillError('通用格式需要人工选择国家和月份。')
        if country and country != warehouse.country_code:
            raise BillError('文件国家与所选仓库不一致，请核对归属。')
        facts, summary = parse_mapped(path, file_name, config, warehouse, month, progress=progress, manual_context=manual_context)
        summary['applied_rule'] = {'id':chosen.pk if chosen else None,'name':chosen.name if chosen else '本批配置',
            'record_version':chosen.version if chosen else None,'config':deepcopy(config),'warehouse_id':warehouse.pk}
        return facts, summary
    if options.get('saved_rules_only'):
        raise BillError('暂未识别此账单格式，请增加新格式或选择已保存格式调整。')
    facts, summary = parse_bill(path, file_name, {**options, 'registration_mode':CNY_ORIGINAL}, progress=progress)
    facts = settlement_facts(facts, summary)
    facts, summary = audit_file(facts, summary)
    reader = BillReader(path, progress=progress)
    try:
        sources = {f['sheet'] for f in facts}
        settlement_sheets = {l['sheet'] for l in summary['settlement']['lines']}
        supports = {'费用账单', '入库费用', '出库费用', '账单汇总', '收货订单', '出库订单',
            '库内操作费', '快递运输单', 'TMS运输单', '每日仓库费', '增值服务', '其他应收费用',
            '卸货费', 'lalamove', '极风订单', '聚灵订单', '订单', '一件代发出库费用', '其他费用', '数据汇总', '极风数据汇总'}
        coverage = []
        for name in reader.sheets:
            total = sum(1 for _, cells in reader.rows(name) if any(text(v) for v in cells.values()))
            extracted = sum(len(f.get('source_rows', [f['row']])) for f in facts if f['sheet'] == name)
            kind = 'settlement' if name in settlement_sheets else 'order' if name in sources else 'ignore'
            if kind == 'ignore' and name not in supports and not any(token in name for token in ['业务结算单', '仓库费用汇总', '仓库清单', '其他收费明细']):
                raise BillError(f'工作表“{name}”尚未明确用途，请配置格式，不能静默忽略。')
            coverage.append(dict(sheet=name,kind=kind,count=extracted,skipped=max(0,total-extracted),outside=0,
                reason='内置格式结算依据' if kind=='settlement' else '内置格式订单明细' if kind=='order' else '内置格式支持明细，不重复生成费用'))
        summary['coverage'] = coverage
    finally:
        reader.close()
    summary['applied_rule'] = {'id':None,'name':'内置格式：'+summary['format'],'config':None}
    return facts, summary
