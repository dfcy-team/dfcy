"""Build editable rules from supported original bills; never write fees or rules."""
from collections import Counter
from itertools import islice

from .warehouse_bill_parser import BillError, BillReader, CNY_ORIGINAL, parse_bill, text, decimal
from .warehouse_bill_contract import settlement_facts, audit_file
from .warehouse_bill_formats import clean_config, parse_mapped


def convert_file(path, warehouse):
    facts, summary = parse_bill(path, path.name, {'registration_mode': CNY_ORIGINAL})
    facts, summary = audit_file(settlement_facts(facts, summary), summary)
    if summary['country'] != warehouse.country_code:
        raise BillError('原文件国家与仓库不同。')
    reader = BillReader(path)
    reader.cny_original = True
    try:
        sheets = {name: {'name':name, 'kind':'ignore', 'reason':'原账单辅助明细，费用仅从订单计费表和结算清单取数，避免重复登记。'} for name in reader.sheets}
        order_sheets = {f['sheet'] for f in facts if f['kind'] == 'order'}
        for name in order_sheets:
            if summary['format'] == 'FUS':
                h, cols = reader.header(name, ['参考号','金额','交易单号','类型'])
                spec = {'filters':[{'column':cols['类型'], 'values':['outbound','Outbound','OutBound','OUTBOUND']}], 'group_by':cols['交易单号']}
                if '计费项类型' in cols:
                    spec['filters'].append({'column':cols['计费项类型'], 'values':['','出库费用']})
                number, money = cols['参考号'], cols['金额']
            elif summary['format'] == '世洋':
                h, cols = reader.header(name, ['费用单据号','总金额'])
                number = next((cols[k] for k in ['平台订单号','外部单号','运单号'] if k in cols), None)
                if not number: raise BillError('未识别世洋订单号列。')
                money, spec = cols['总金额'], {}
            else:
                h, cols = reader.header(name, ['平台订单号','实际应收'])
                number, money, spec = cols['平台订单号'], cols['实际应收'], {}
            header = next(c for n,c in reader.rows(name) if n == h)
            sheets[name] = dict(name=name,kind='order',header=h,columns={'number':number,'amount':money},
                expected={k:text(v) for k,v in header.items() if text(v)},skip_zero=True,**spec)
        lines = summary['settlement']['lines']
        names = {line['sheet'] for line in lines}
        if len(names) != 1: raise BillError('结算依据涉及多张工作表，需人工配置。')
        name = next(iter(names))
        rows = dict(islice(reader.rows(name), 40))
        if summary['format'] == 'FUS':
            h, cols = reader.header(name, ['汇总'])
            item_col, money_col = 'A', 'C'
        elif summary['format'] == '世洋':
            h, item_col, money_col = min(line['row'] for line in lines) - 1, 'A', 'D'
            # The category table starts below the account overview.
            h = max(n for n,c in rows.items() if n < min(line['row'] for line in lines) and text(c.get('D')) == '总计')
        else:
            h, cols = reader.header(name, ['总金额','备注'])
            item_col, money_col = cols['备注'], cols['总金额']
        first, last = min(line['row'] for line in lines), max(line['row'] for line in lines)
        total_source = 'sum'
        if summary['format'] == '世洋':
            overview_h, cols = reader.header(name, ['账单总金额'])
            total_source = f"{cols['账单总金额']}{overview_h + 1}"
        else:
            for n,cells in rows.items():
                if n > last and any(text(cells.get(c)) in {'合计','总计','总金额','总费用'} for c in ['A','F','H']):
                    total_source = f'{money_col}{n}'
                    break
        roles = {line['item']:{'role':line['kind']} for line in lines}
        for n,cells in rows.items():
            if first <= n <= last:
                label, value = text(cells.get(item_col)), text(cells.get(money_col))
                if label and label not in roles:
                    if value and decimal(value) != 0: raise BillError('结算范围存在未分类非零项目。')
                    roles[label] = {'role':'empty'}
        sheets[name] = dict(name=name,kind='settlement',header=h,start=first,end=last,
            columns={'item':item_col,'amount':money_col},expected={k:text(v) for k,v in rows[h].items() if text(v)},
            items=roles,total_source=total_source,skip_zero=True,
            reason='范围外为账单标题、总额及收款说明；总额按配置的单元格或结算项目合计核对。')
        add_warehouse_checks(reader,list(sheets.values()),sorted({w for f in facts for w in f.get('raw_warehouses',[]) if w}))
        config = clean_config({'schema_version':3,'sheets':list(sheets.values())})
    finally:
        reader.close()
    converted, result = parse_mapped(path,path.name,config,warehouse,summary['bill_month'])
    def identity(records):
        return Counter((f['kind'], f['external_order_id'], f['amount'], tuple(f['source_rows']),
                        f['fee_item'] if f['kind'] == 'other' else '') for f in records)
    if identity(facts) != identity(converted):
        raise BillError('转换前后记录不一致：' + str({'old_count':len(facts),'new_count':len(converted),'old_only':[(k[0],k[2],k[3],k[4],v) for k,v in (identity(facts)-identity(converted)).items()][:8], 'new_only':[(k[0],k[2],k[3],k[4],v) for k,v in (identity(converted)-identity(facts)).items()][:8]}))
    for key in ['file_total','effective_order_total','effective_other_total','processing_difference']:
        if summary.get(key) != result.get(key):
            raise BillError(f'转换前后{key}不一致，未生成规则。')
    return config, {'format':summary['format'],'month':summary['bill_month'],
        'rows':len(facts),'total':result.get('file_total'),'order_total':result.get('effective_order_total'),
        'other_total':result.get('effective_other_total'),
        'source_warehouses':sorted({w for f in facts for w in f.get('raw_warehouses',[]) if w})}


def add_warehouse_checks(reader,specs,values):
    if not values:
        raise BillError('原文件缺少可核对的仓库标识，不能自动生成仓库规则。')
    guarded = False
    for spec in specs:
        name=spec['name']
        if name not in {'订单','聚灵订单','极风订单','出库订单','出库费用','一件代发出库费用'} and '仓库清单' not in name:
            continue
        for label in ['仓库名称','仓库']:
            try:
                h,columns=reader.header(name,[label])
            except BillError:
                continue
            spec.update(warehouse_column=columns[label],warehouse_header=h,warehouse_values=values)
            guarded=True
            break
    if not guarded:
        raise BillError('原文件没有可配置的仓库依据列，需人工确认格式。')
