"""Retain accepted calculation/UI code; replace every legacy financial input."""
import json
import re


def packed(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')


def replace_assignment(code, name, value):
    match = re.search(r'(?:globalThis\.)?'+re.escape(name)+r'\s*=\s*', code)
    if not match:
        return code
    _, length = json.JSONDecoder().raw_decode(code[match.end():])
    return code[:match.start()]+'globalThis.'+name+'='+packed(value)+code[match.end()+length:]


def warehouse_profit_rules(code):
    """Warehouse fees follow posted settlements, including zero/negative amounts."""
    if '// SAAS_WAREHOUSE_SETTLEMENT' in code:
        return code
    # Rebuilds can reuse a document carrying the previous bill-month fallback.
    code = code.replace("if(date)f={...f,", "f={...f,").replace(
        "\n   else{const month=f.source_bill_month||f.warehouse_allocation?.month||f.date.slice(0,7);f={...f,source_date:f.source_date||f.date,source_bill_month:month,date:month,month,accounting_basis:'已登记关联订单仓库费用；无正向销售结算时按原账单月计入'};}", '')
    code = code.replace("if(!date&&!['warehouse_order','warehouse_other'].includes(f.kind))", "if(!date)")
    return code.replace('const date=first.get(identity(f));',
        "// SAAS_WAREHOUSE_SETTLEMENT\n   const warehouse=['warehouse_order','warehouse_other'].includes(f.kind);\n"
        "   const date=warehouse?f.warehouse_settlement_date:first.get(identity(f));\n   if(warehouse&&!date)continue;").replace(
        "accounting_basis:'首次有效销售结算（已载入历史）'",
        "accounting_basis:warehouse?'关联订单有效结算日（不要求正向销售额）':'首次有效销售结算（已载入历史）'")


def render(template, source):
    """Template contributes algorithms and markup only, never source values."""
    database = {key: source[key] for key in ['schema', 'facts', 'shares', 'rates', 'order_dates', 'cost_flows', 'raw_flows'] if key in source}
    snapshot = {'snapshot_at': source['read_at'], 'database': database, 'raw': source['raw'], 'facts': [],
        'coverage': [], 'wide': {}, 'wide_rows': [], 'shopee_income': source['shopee_income'],
        'primary_collection': {'orders': [], 'rows': [], 'names': [], 'dates': [], 'matches': []},
        'allocations': {'views': {'store': [], 'order': [], 'sku': []},
                        'unallocated': {'store': [], 'order': [], 'sku': []}, 'basis': {}},
        'local_expenses': {'facts': [], 'views': {'store': [], 'order': []},
            'unallocated': {}, 'coverage': {}, 'source_totals': []},
        'lazada_saas': {'sku_members': source['sku_members'], 'snapshot_at': source['read_at'],
            'comparison': [], 'scope': 'SaaS数据库重新生成的财务来源', 'coverage': {}, 'source_totals': []}}
    html = re.sub(r'(<script[^>]*id="snapshot"[^>]*>)[\s\S]*?(</script>)',
                  lambda m: m[1]+packed(snapshot)+m[2], template, count=1)
    replacements = {
        'html2-sp6th-fees-data': ('HTML2_SP6TH_FEES', None),
        'html2-lazada-cycles-data': ('HTML2_LAZADA_CYCLES', source['cycles']),
        'html2-shopee-recharge-data': ('HTML2_RECHARGE_DATA', source['recharge']),
    }
    def script(match):
        attrs, code = match.groups()
        if 'application/json' in attrs:
            return match[0] if 'id="snapshot"' in attrs else ''
        identity = re.search(r'id="([^"]+)"', attrs)
        identity = identity[1] if identity else None
        if identity in replacements:
            name, value = replacements[identity]
            code = 'globalThis.'+name+'='+packed(value)+';'
        elif identity == 'html2-lazada-finance':
            code = code.replace('s=data.shops[shop],warnings=',
                                's=(data.history?.[month]||data.shops)[shop],warnings=')
        elif identity == 'html2-advertising-columns' and 'function calculateBaseCurrent(' not in code:
            code = code.replace('function calculateBase(shop,month,baseRows){',
                "function calculateBase(shop,month,baseRows){const history=data.history?.[month];"
                "if(!history)return calculateBaseCurrent(shop,month,baseRows);"
                "const transactions=data.transactions,actualSpend=data.actualSpend;"
                "try{data.transactions=history.transactions;data.actualSpend=history.actualSpend;"
                "return calculateBaseCurrent(shop,month,baseRows);}"
                "finally{data.transactions=transactions;data.actualSpend=actualSpend;}}\n"
                "function calculateBaseCurrent(shop,month,baseRows){")
        elif identity == 'html2-sp6th-fees' and '// SAAS_COST_CLASSIFICATION' not in code:
            code = code.replace('const c=f.cost_calculation,e=c.business_evidence;',
                "const c=f.cost_calculation,e=c.business_evidence;\n  // SAAS_COST_CLASSIFICATION\n  if(c.business_classification)return c.business_classification.category;")
        elif identity == 'html2-store-hierarchy':
            code = replace_assignment(code, 'HTML2_SKU_ORDER_SALES', source['sku_sales'])
        elif identity == 'html2-profit-rules':
            code = warehouse_profit_rules(code)
        elif identity == 'sku-summary-ui':
            # Build both platforms' costs from the same (possibly closed) parent facts.
            code = code.replace('const rows=SAAS_LAZADA.skuMembers(broad);', 'const rows=[];')
            code = code.replace("f.platform==='shopee'&&f.kind==='product_cost'",
                                "['shopee','lazada'].includes(f.platform)&&f.kind==='product_cost'")
            code = code.replace('const cost=c.net_cost==null?',
                "const cost=f.cost_conversion?(c.local_currency===f.currency&&c.local_amount!=null?micro(c.local_amount):null):c.net_cost==null?")
        elif identity == 'html2-product-links':
            code = replace_assignment(code, 'HTML2_PRODUCT_LINK_DATA', source['products'])
            code = replace_assignment(code, 'HTML2_PRODUCT_LINK_PROVENANCE', {'transactions': [], 'order_items': {}})
        elif not identity and 'const SNAPSHOT =' in code:
            if '// Only the reconciled' in code:
                start, end = code.index('// Only the reconciled'), code.index('const KINDS=')
                code = code[:start]+"const SP6TH_ADVERTISING_NOTE='SaaS数据库来源；缺少凭证的科目保留待核。';\n"+code[end:]
            code = re.sub(r'const HISTORICAL_FX=[\s\S]*?;\s*function displayCurrency',
                          'const HISTORICAL_FX=SNAPSHOT.database.rates.historical;\nfunction displayCurrency', code, count=1)
            code = re.sub(r'const WAREHOUSE_MONTHLY_FX=[\s\S]*?;\s*function warehouseKind',
                "const WAREHOUSE_MONTHLY_FX=Object.fromEntries(Object.entries(SNAPSHOT.database.rates.monthly).map(([k,v])=>[k,v.rate]));\nfunction warehouseKind", code, count=1)
            code = re.sub(r'const WAREHOUSE_COUNTRY_BASIS=[\s\S]*?;\s*const warehouseTrial',
                          'const WAREHOUSE_COUNTRY_BASIS={};\nconst warehouseTrial', code, count=1)
            code = code.replace('const FACTS=buildFacts();', 'const FACTS=SNAPSHOT.database.facts;')
            code = code.replace('const WAREHOUSE_SHARES=buildWarehouseShares();', 'const WAREHOUSE_SHARES=SNAPSHOT.database.shares;')
            local_start, local_end = code.index('function localFact(f){'), code.index('function fxDescription')
            code = code[:local_start]+DATABASE_LOCAL_FACT+'\n'+code[local_end:]
            code = re.sub(r'const FILE_TREE=\[[\s\S]*?\];', 'const FILE_TREE=[];', code, count=1)
            # Replace a previous generated adapter when rebuilding the same code template.
            code = code.split('// SAAS_DATABASE_ENTRIES')[0]
            code += '\n'+DATABASE_ENTRIES
        return '<script'+attrs+'>'+code+'</script>'
    html = re.sub(r'<script([^>]*)>([\s\S]*?)</script>', script, html)
    from .summary_composition import adapt_document
    return adapt_document(html.replace('临时 HTML · 未替换 SaaS 页面', 'SaaS数据库来源 · 财务汇总批次'))


def compact_browser_inputs(html):
    """Older DB batches contain duplicate JSON copies; share the canonical facts."""
    if '// SAAS_DATABASE_ENTRIES' not in html:
        return html
    match = re.search(r'(<script[^>]*id="snapshot"[^>]*>)([\s\S]*?)(</script>)', html)
    snapshot = json.loads(match[2])
    database = snapshot.get('database')
    if not database:
        return html
    missing_metadata = 'unallocated' not in snapshot['allocations']
    snapshot['allocations'].setdefault('unallocated', {'store': [], 'order': [], 'sku': []})
    snapshot['allocations'].setdefault('basis', {})
    if 'raw' in database or snapshot['local_expenses']['facts'] or missing_metadata:
        snapshot['database'] = {key: database[key] for key in ['schema', 'facts', 'shares', 'rates', 'order_dates', 'cost_flows', 'raw_flows'] if key in database}
        snapshot['local_expenses']['facts'] = []
        html = html[:match.start()]+match[1]+packed(snapshot)+match[3]+html[match.end():]
    if 'const FACTS=SNAPSHOT.database.facts;SNAPSHOT.local_expenses.facts=FACTS;' not in html:
        html = html.replace('const FACTS=SNAPSHOT.database.facts;', 'const FACTS=SNAPSHOT.database.facts;SNAPSHOT.local_expenses.facts=FACTS;', 1)
    return html


DATABASE_LOCAL_FACT = """function localFact(f){
 const amount=f.original_amount===undefined?f.amount:f.original_amount,currency=f.original_currency||f.currency,target=displayCurrency(f),month=String(f.date||'').slice(0,7),db=SNAPSHOT.database.rates;
 if(f.kind==='product_cost'&&f.cost_conversion){const c=f.cost_conversion;return {...f,original_amount:amount,original_currency:currency,currency:target,amount:c.to===target?c.local_amount:null,amount_missing:amount==null,fx:c.quote};}
 const historical=db.historical[[String(f.date).slice(0,10),currency,target].join('|')],monthly=db.monthly[[month,f.country,currency,target].join('|')];
 const fx=currency===target?null:warehouseKind(f)?monthly:historical||monthly;
 let converted=amount==null?null:currency===target?amount:fx?fixed(convertAmount(amount,fx.rate)):null;
 const a=f.warehouse_allocation;if(a&&currency!==target)converted=fx&&a.local_currency===target&&a.rate===fx.rate?a.local_amount:null;
 return {...f,original_amount:amount,original_currency:currency,currency:target,amount:converted,amount_missing:amount==null,fx};
}"""

DATABASE_ENTRIES = """
// SAAS_DATABASE_ENTRIES
outsidePrimaryScope=()=>false;
SNAPSHOT.local_expenses.facts=FACTS;
rawEntriesFor=function(view){return view==='detail'?FACTS:FACTS.filter(f=>f.scope!=='country').concat(WAREHOUSE_SHARES.order);};
entriesFor=function(view){return rawEntriesFor(view).filter(f=>view!=='order'||!!f.external_order_id);};
if(globalThis.PREVIEW_TEST){PREVIEW_TEST.entriesFor=entriesFor;PREVIEW_TEST.localFact=localFact;}
"""
