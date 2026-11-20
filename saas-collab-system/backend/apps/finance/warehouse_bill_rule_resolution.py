"""Resolve explicit, editable month and settlement variations without guessing fees."""
from copy import deepcopy
import re
from .warehouse_bill_parser import BillError, text


def month_name(name):
    return re.sub(r'20\d{2}(?:[年.\-/]\d{1,2}月?|(?:0[1-9]|1[0-2]))', '{月份}', name).strip()


def labelled_total_rows(rows, header, money_column):
    from .warehouse_bill_parser import decimal
    return [n for n,c in rows.items() if n > header and decimal(c.get(money_column)) is not None
            and any(text(v) in {'合计','总计','总金额','总费用'} or text(v).endswith('费用合计')
                    for v in c.values())]


def resolve_fields(spec, rows):
    """Only selected extraction fields participate in opt-in header matching."""
    selected = set(spec['columns'].values())
    selected.update(spec[k] for k in ('group_by', 'warehouse_column') if spec.get(k))
    optional = {c['column'] for c in spec.get('filters', []) if c.get('optional')}
    selected.update(c['column'] for c in spec.get('filters', []) if not c.get('optional'))
    if spec.get('settlement_auto') == 'sequence_total':
        selected.update(k for k,v in spec['expected'].items() if text(v) in {'序号','序列'})
    wanted = {k:{text(spec['expected'].get(k)), *spec.get('field_aliases',{}).get(k,[])} for k in selected | optional}
    if not selected or any('' in wanted[k] for k in selected):
        raise BillError('取数字段缺少表头名称，请重新选择列。')
    heads = [(n,c) for n,c in rows.items() if n <= 30 and all(wanted[k] & {text(v) for v in c.values()} for k in selected)]
    if len(heads) != 1:
        raise BillError('取数表头未唯一匹配，请核对必需字段。')
    number, cells = heads[0]
    mapping = {}
    for old in selected | optional:
        label = text(spec['expected'].get(old))
        columns = [k for k,v in cells.items() if text(v) in wanted[old]]
        if len(columns) > 1 or (not columns and old not in optional):
            raise BillError('取数列缺失或重复，请核对表头。')
        if not columns and old in optional and text(cells.get(old)):
            raise BillError('可选筛选字段原位置出现其他名称，不能当作旧版缺列，请重新核对筛选。')
        if columns: mapping[old] = columns[0]
    if len({mapping[col] for col in spec['columns'].values()}) != len(spec['columns']):
        raise BillError('不同取数字段匹配到同一列，请修改字段别名，单号、项目与金额不能共用一列。')
    shift = number - spec['header']
    for key in ('start','end'):
        if spec.get(key) is not None: spec[key] += shift
    spec['header'] = number
    spec['columns'] = {key:mapping[col] for key,col in spec['columns'].items()}
    for key in ('group_by','warehouse_column'):
        if spec.get(key): spec[key] = mapping[spec[key]]
    if 'filters' in spec:
        spec['filters'] = [{**c,'column':mapping[c['column']]} for c in spec['filters'] if c['column'] in mapping]
    if spec.get('total_source') not in {None,'','sum'}:
        col, row = re.fullmatch(r'([A-Z]+)([0-9]+)',spec['total_source']).groups()
        spec['total_source'] = f'{mapping.get(col,col)}{int(row)+shift}'
    if spec.get('field_aliases'):
        spec['field_aliases'] = {mapping[k]:sorted(wanted[k] - {text(cells.get(mapping[k]))}) for k in spec['field_aliases'] if k in mapping}
    spec['expected'] = {k:text(v) for k,v in cells.items() if text(v)}


def resolve_sequence_total(spec, rows):
    seq = [k for k,v in spec['expected'].items() if text(v) in {'序号','序列'}]
    if len(seq) != 1: raise BillError('序号列未唯一匹配，请核对。')
    item, money = spec['columns']['item'], spec['columns']['amount']
    projects = [(n,c) for n,c in rows.items() if n > spec['header']
        and re.fullmatch(r'[1-9][0-9]*(?:\.0+)?',text(c.get(seq[0]))) and text(c.get(item))]
    if not projects: raise BillError('未找到有效结算项目。')
    last = max(n for n,_ in projects)
    stop = min((n for n,c in rows.items() if n > last and any(
        text(v).startswith(('备注：','银行信息')) for v in c.values())),default=max(rows)+1)
    from .warehouse_bill_parser import decimal
    totals = [n for n,c in rows.items() if last < n < stop and decimal(c.get(money)) is not None
        and (text(c.get(seq[0])) in {'合计','总计'} or '费用合计' in text(c.get(seq[0]))
             or (not text(c.get(seq[0])) and not text(c.get(item))))]
    if len(totals) != 1: raise BillError('结算总额行未唯一匹配，请核对。')
    project_rows = {n for n,_ in projects}
    if any(n not in project_rows and spec['header'] < n < totals[0]
           and (text(c.get(item)) or decimal(c.get(money)) not in {None, 0}) for n,c in rows.items()):
        raise BillError('结算项目缺少序号或名称，请核对，不能忽略非空金额。')
    spec.update(start=spec['header']+1,end=last,total_source=f'{money}{totals[0]}')


def resolve_config(config, samples):
    result = deepcopy(config)
    actual = {s['name']: {r['row']:r['cells'] for r in s['sample']} for s in samples}
    used, resolved = set(), []
    for spec in result['sheets']:
        aliases = [spec['name'], *spec.get('sheet_aliases', [])]
        names = [n for n in actual if any(month_name(n) == month_name(alias) if spec.get('month_name') else n == alias for alias in aliases)]
        if not names and spec.get('optional_sheet') and spec['kind'] == 'ignore':
            continue
        if len(names) != 1 or names[0] in used:
            raise BillError('工作表未唯一对应，请核对格式配置。')
        spec['name'] = names[0]; used.add(names[0])
        rows = actual[names[0]]
        if spec.get('header_mode') == 'fields' and spec['kind'] != 'ignore':
            resolve_fields(spec, rows)
        mode = spec.pop('settlement_auto', None)
        spec.pop('month_name', None)
        if mode:
            expected = {k:text(v) for k,v in spec['expected'].items() if text(v)}
            heads = [n for n,c in rows.items() if {k:text(v) for k,v in c.items() if text(v)} == expected]
            if len(heads) != 1:
                raise BillError('结算表头未唯一匹配，请核对。')
            spec['header'] = heads[0]
            if mode == 'sequence_total':
                resolve_sequence_total(spec, rows)
            if mode == 'total_row':
                totals = labelled_total_rows(rows, heads[0], spec['columns']['amount'])
                if not totals:
                    raise BillError('未找到有效的合计标签及金额，请核对总额定位方式。')
                if len(totals) > 1:
                    raise BillError('找到多个合计金额行，请明确总额位置。')
                spec.update(start=heads[0]+1, end=totals[0]-1, total_source=f"{spec['columns']['amount']}{totals[0]}")
            start, end = spec.get('start', spec['header']+1), spec.get('end')
            if end is None or end > max(rows, default=0):
                raise BillError('结算范围超出已核对范围，请调整配置。')
            labels = [text(c.get(spec['columns']['item'])) for n,c in rows.items() if start <= n <= end
                      and (text(c.get(spec['columns']['item'])) if mode == 'sequence_total' else any(text(v) for v in c.values()))]
            if not labels or len(set(labels)) != len(labels) or any(label not in spec['items'] for label in labels):
                raise BillError('存在新增、缺失或重复结算项目，请逐项核对。')
            spec['items'] = {label:spec['items'][label] for label in labels}
        if spec['kind'] != 'ignore':
            expected = {k:text(v) for k,v in spec['expected'].items() if text(v)}
            if {k:text(v) for k,v in rows.get(spec['header'],{}).items() if text(v)} != expected:
                raise BillError('表头或列结构已变化，请核对格式。')
            if spec['kind'] == 'settlement' and spec.get('end') and spec['end'] <= max(rows,default=0):
                labels = [text(c.get(spec['columns']['item'])) for n,c in rows.items() if spec.get('start',spec['header']+1) <= n <= spec['end'] and text(c.get(spec['columns']['item']))]
                if set(labels) != set(spec['items']):
                    raise BillError('结算项目与规则不一致，请核对。')
        spec.pop('header_mode',None)
        spec.pop('optional_sheet',None)
        spec.pop('sheet_aliases',None)
        resolved.append(spec)
    if used != set(actual):
        raise BillError('文件包含未配置工作表，请核对。')
    result['sheets'] = resolved
    return result


def editable_config(config, samples):
    """Keep editable variations and known roles while displaying this file's rows."""
    from .warehouse_bill_formats import clean_config
    result = resolve_config(clean_config(config), samples)
    for original in config['sheets']:
        aliases = [original['name'], *original.get('sheet_aliases', [])]
        spec = next((s for s in result['sheets'] if any(month_name(s['name']) == month_name(alias)
            if original.get('month_name') else s['name'] == alias for alias in aliases)),None)
        if spec is None:
            if original.get('optional_sheet'): result['sheets'].append(deepcopy(original))
            continue
        for key in ('month_name', 'settlement_auto', 'header_mode', 'optional_sheet'):
            if key in original:
                spec[key] = original[key]
        if original.get('sheet_aliases') or spec['name'] != original['name']:
            spec['sheet_aliases'] = list(dict.fromkeys(n for n in aliases if n != spec['name']))
        if original.get('settlement_auto'):
            spec['items'] = deepcopy(original['items'])
        if original.get('header_mode') == 'fields':
            for condition in original.get('filters', []):
                label = text(original['expected'].get(condition['column']))
                if condition.get('optional') and label not in spec['expected'].values():
                    col = condition['column']
                    if col in spec['expected']:
                        raise BillError('可选筛选列与当前列冲突，请另存格式。')
                    spec['expected'][col] = label
                    spec.setdefault('filters', []).append(deepcopy(condition))
    return result
