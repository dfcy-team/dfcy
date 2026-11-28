"""Server-side immutable worksheet rules, scoped to tenant warehouse access."""
from copy import deepcopy
from decimal import Decimal
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


def rules_for(user):
    return WarehouseBillFormatRule.objects.filter(tenant=user.tenant,
        warehouse__in=warehouses_for(user)).select_related('warehouse').order_by('name', 'pk')


def describe_rule(rule):
    return dict(id=rule.pk, name=rule.name, warehouse_id=rule.warehouse_id,
        warehouse_code=rule.warehouse.code, country=rule.warehouse.country_code,
        version=rule.version, config=rule.config, created_at=rule.created_at)


def clean_config(config):
    if not isinstance(config, dict) or set(config) != {'schema_version', 'sheets'} or config.get('schema_version') != SCHEMA:
        raise BillError('格式配置版本无效；旧整表其他费用规则必须重新配置。')
    specs = config['sheets']
    if not isinstance(specs, list) or not 1 <= len(specs) <= 100:
        raise BillError('请配置1至100张工作表。')
    names = set()
    for spec in specs:
        if not isinstance(spec, dict) or set(spec) - {'name','kind','header','end','columns','expected','items','reason'}:
            raise BillError('工作表配置包含不支持的字段。')
        name, kind = spec.get('name'), spec.get('kind')
        if not isinstance(name, str) or not name or len(name) > 100 or name in names:
            raise BillError('工作表名称无效或重复。')
        names.add(name)
        if not isinstance(spec.get('reason', ''), str) or len(spec.get('reason', '')) > 500:
            raise BillError('忽略或范围说明最多500字。')
        if kind == 'ignore':
            if not text(spec.get('reason')):
                raise BillError(f'请填写忽略工作表“{name}”的原因。')
            continue
        if kind not in {'order', 'settlement'}:
            raise BillError(f'工作表“{name}”尚未指定用途。')
        header, end = spec.get('header'), spec.get('end')
        if type(header) is not int or not 1 <= header <= 30 or end is not None and (type(end) is not int or end <= header or end > 1500000):
            raise BillError('表头须为1至30行，结束行须在表头之后。')
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
            return {'items': settlement_items(reader, spec)}
        return {'sheets': [{'name': name, 'sample': [{'row': n, 'cells': cells}
            for n, cells in islice(reader.rows(name), 30)]} for name in reader.sheets]}
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
        if n <= header or end is not None and n > end:
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


def parse_mapped(path, file_name, config, warehouse, month, *, progress=None):
    config = clean_config(config)
    if not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])', month or ''):
        raise BillError('请确认当前文件来源月份，规则不保存旧月份。')
    match = re.search(r'(20\d{2})[年.-](\d{1,2})(?:月|[.-])', file_name)
    if match and month != f'{match[1]}-{int(match[2]):02}':
        raise BillError('来源月份与当前原文件名称不一致。')
    reader = BillReader(path, progress=progress)
    try:
        if {s['name'] for s in config['sheets']} != set(reader.sheets):
            raise BillError('工作表集合已变化，请重新配置，不能遗漏工作表。')
        facts, coverage, lines, totals, controls = [], [], [], [], []
        bill = file_name.rsplit('.', 1)[0][:191]
        for spec in config['sheets']:
            name, kind = spec['name'], spec['kind']
            if kind == 'ignore':
                count = sum(1 for _, cells in reader.rows(name) if any(text(v) for v in cells.values()))
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
            count = skipped = outside = 0
            for n, cells, cell_types in reader.rows(name, with_types=True):
                if n <= spec['header'] or not any(text(v) for v in cells.values()): continue
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
                issues = []
                if kind == 'order' and re.fullmatch(r'\d+(?:\.\d+)?[Ee][+-]?\d+', number) and cell_types.get(columns['number']) not in {'s','str','inlineStr'}:
                    issues.append('原单号使用科学计数法，不能猜补。')
                facts.append(dict(kind='order' if kind == 'order' else 'other', country=warehouse.country_code,
                    bill_month=month, bill_number=bill, fee_item=item, reference=f'{name}!{n}', external_order_id=number,
                    amount=amount(raw), currency='CNY', occurred_on=None, raw_store='', raw_warehouse=warehouse.code,
                    raw_platform='', raw_stores=[], raw_warehouses=[warehouse.code], sheet=name, row=n,
                    source_rows=[n], raw_amount=text(raw), tracking_numbers=[], issues=issues))
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
    if not isinstance(supplied, dict) or set(supplied) != {'name','warehouse_id','config'}:
        raise ValidationError('请提供规则名称、仓库和配置。')
    name = supplied['name']
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ValidationError('规则名称须为1至100字。')
    from rest_framework.serializers import IntegerField
    warehouse_id = IntegerField(min_value=1).run_validation(supplied['warehouse_id'])
    warehouse = warehouses_for(user).filter(pk=warehouse_id).first()
    if not warehouse: raise NotFound('仓库不存在或不在授权范围。')
    config = clean_config(supplied['config'])
    try:
        with transaction.atomic():
            rule = WarehouseBillFormatRule.objects.create(tenant=user.tenant, warehouse=warehouse,
                name=name.strip(), config=config, created_by=user)
            FinanceAuditLog.objects.create(tenant=user.tenant,actor=user,object_type='warehouse_bill_format',
                object_id=str(rule.pk), action='create',masked_detail={'name':rule.name,'warehouse_id':warehouse.pk,'config':config})
    except IntegrityError:
        raise ValidationError('该仓库已有同名规则；修订请使用新名称，旧规则不会覆盖。') from None
    return rule


def parse_new_bill(user, path, file_name, options, *, progress=None):
    from .warehouse_bill_parser import CNY_ORIGINAL, parse_bill
    from .warehouse_bill_contract import settlement_facts
    month = options.get('bill_month')
    match = re.search(r'(20\d{2})[年.-](\d{1,2})(?:月|[.-])', file_name)
    month = month or (f'{match[1]}-{int(match[2]):02}' if match else '')
    country = options.get('country') or next((v for k,v in [('菲律宾','PH'),('泰国','TH'),('马来','MY')] if k in file_name), '')
    available = rules_for(user)
    if country: available = available.filter(warehouse__country_code=country)
    if options.get('warehouse_id'): available = available.filter(warehouse_id=options['warehouse_id'])
    chosen, config, warehouse = None, options.get('format_config'), None
    if config:
        warehouse = warehouses_for(user).filter(pk=options.get('warehouse_id')).first()
        if not warehouse: raise BillError('配置原文件格式前请选择有权限的仓库。')
    elif options.get('format_rule_id'):
        chosen = available.filter(pk=options['format_rule_id']).first()
        if not chosen: raise BillError('所选格式规则不存在或不在授权范围。')
    else:
        sample = inspect_file(path, progress=progress)
        actual = {s['name']: {r['row']:r['cells'] for r in s['sample']} for s in sample['sheets']}
        relevant, matches = [], []
        for rule in available:
            specs = rule.config.get('sheets', []) if isinstance(rule.config, dict) else []
            if not any(s.get('kind') != 'ignore' and s.get('name') in actual for s in specs): continue
            relevant.append(rule)
            if rule.config.get('schema_version') != SCHEMA: continue
            if {s.get('name') for s in specs} == set(actual) and all(s.get('kind') == 'ignore' or
                    {k:text(v) for k,v in actual[s['name']].get(s.get('header'),{}).items() if text(v)} ==
                    {k:text(v) for k,v in s.get('expected',{}).items() if text(v)} for s in specs):
                matches.append(rule)
        if len(matches) > 1:
            raise BillError('多个格式规则匹配，请明确选择：' + '、'.join(f'{r.name}（{r.warehouse.code}）' for r in matches)[:350])
        if matches: chosen = matches[0]
        elif relevant: raise BillError('已有相关规则发生工作表或表头漂移，请重新配置，不自动回退内置解析。')
    if chosen:
        config, warehouse = chosen.config, chosen.warehouse
    if config:
        if country and country != warehouse.country_code:
            raise BillError('文件国家与所选仓库不一致，请核对归属。')
        facts, summary = parse_mapped(path, file_name, config, warehouse, month, progress=progress)
        summary['applied_rule'] = {'id':chosen.pk if chosen else None,'name':chosen.name if chosen else '本批配置',
            'record_version':chosen.version if chosen else None,'config':deepcopy(config),'warehouse_id':warehouse.pk}
        return facts, summary
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
