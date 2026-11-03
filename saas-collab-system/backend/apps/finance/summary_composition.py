"""Use identical composition rows for the HTML preview and SaaS document."""
import re
from pathlib import Path


def adapt_document(html):
    code = Path(__file__).with_suffix('.js').read_text(encoding='utf-8')
    html = re.sub(r'<script id="finance-shared-composition">[\s\S]*?</script>\s*', '', html)
    html = html.replace('<script id="html2-fee-rates">',
        '<script id="finance-shared-composition">'+code+'</script>\n<script id="html2-fee-rates">', 1)
    # These adapters change only popup presentation, never allocation or source inputs.
    def adapt(match):
        attrs, source = match.groups()
        if 'id="html2-fee-rates"' in attrs and '// SHARED_COMPOSITION' not in source:
            source = source.replace('function composition(data,kind){',
                """function composition(data,kind){
  // SHARED_COMPOSITION
  if(kind!=='gross_margin'&&!kind.startsWith('profit_'))return FINANCE_COMPOSITION.build(data,kind);""", 1)
            source = source.replace('const sum=parts.reduce(',
                """if(!gross&&!net){openDrawer(fields.find(f=>f[0]===kind)[1]+' · 构成','<p>与金额详情使用同一构成；分母为本行订单销售额（不扣退款）。分类小计不重复计入合计。</p>'+FINANCE_COMPOSITION.html(parts,data.sales,total,signed));return;}
  const sum=parts.reduce(""", 1)
        if 'id="html2-fee-rates"' in attrs:
            source = source.replace('return{sales:sales.partial?null:sales.amount,fees,',
                                    'return{resolveControls:!p,sales:sales.partial?null:sales.amount,fees,', 1)
        if not re.search(r'\bid=', attrs) and 'function categoryTable(entries,kind){' in source and '// SHARED_CATEGORY' not in source:
            source = source.replace('function categoryTable(entries,kind){',
                """function categoryTable(entries,kind){
 // SHARED_CATEGORY
 if(globalThis.FINANCE_COMPOSITION){
  const cell=groupRows(entries,'country')[0]?.cells[kind],amount=cell?.amount??null;
  return '<h3>'+esc(kindLabel(kind))+'构成</h3>'+FINANCE_COMPOSITION.html(FINANCE_COMPOSITION.fromEntries(entries,amount),null,amount,['adjustment','shop_adjustment'].includes(kind))+(kind==='product_cost'&&entries.some(f=>f.cost_calculation)?productCostDetails(entries):'');
 }""", 1)
        if 'id="html2-summary-layout"' in attrs and '// SHARED_SUMMARY' not in source:
            source = source.replace('const group=d.group,rows=',
                """// SHARED_SUMMARY
  if(d.kind!=='result'){
   const sku=state.view==='sku',key=d.kind==='advertising'?d.mode:d.kind,g=d.group;
   const data={sku,group:g,[key]:g,fees:{[key]:{amount:d.amount}}},sales=HTML2_FEE_RATES.read(g,'sales',sku);
   openDrawer(d.label||kindLabel(d.kind),FINANCE_COMPOSITION.html(FINANCE_COMPOSITION.build(data,key),sales.partial?null:sales.amount,d.amount,['adjustment','shop_adjustment'].includes(key)));return;
  }
  const group=d.group,rows=""", 1)
        if 'id="html2-product-links"' in attrs and '// SHARED_PRODUCT' not in source:
            source = source.replace("""'data-product-detail="'+index+'"');}""",
                """'data-product-detail="'+index+'" data-product-kind="'+kind+'"');}""", 1)
            source = source.replace("const operation=displayedOperations.get(g.key),finance=displayedFinance.get(g.key);\n  openDrawer(",
                """const operation=displayedOperations.get(g.key),finance=displayedFinance.get(g.key);
  // SHARED_PRODUCT
  const kind=b.dataset.productKind;
  if(kind&&kind!=='result'){
   const selected=kind==='operations'?operation:kind==='finance'?finance:g,key=['operations','finance'].includes(kind)?'advertising':kind;
   const data={sku:true,group:g,operations:operation,finance,fees:{[kind]:{amount:value(selected,key)}}},sales=HTML2_FEE_RATES.read(g,'sales',true);
   openDrawer(kindLabel(key)+' · 构成',FINANCE_COMPOSITION.html(FINANCE_COMPOSITION.build(data,kind),sales.partial?null:sales.amount,value(selected,key),['adjustment','shop_adjustment'].includes(kind)));return;
  }
  openDrawer(""", 1)
        if 'id="finance-fee-checkboxes"' in attrs and '// SHARED_SELECTION' not in source:
            source = source.replace('const api={key:key,setExcluded:setExcluded,',
                """// SHARED_SELECTION
 const selectionCategory=categoryTable;
 categoryTable=function(entries,kind){
  if(!entries.length||['sales','product_cost','receipt'].includes(kind))return selectionCategory(entries,kind);
  const cell=groupRows(entries,'country')[0]?.cells[kind],target=cell?.amount??null;
  return FINANCE_COMPOSITION.html(FINANCE_COMPOSITION.fromEntries(entries,target),null,target,['adjustment','shop_adjustment'].includes(kind))+'<details><summary>费用勾选与原始来源</summary>'+selectionCategory(entries,kind)+'</details>';
 };
 const api={key:key,setExcluded:setExcluded,""", 1)
        if 'id="html2-layout"' in attrs and '// SHARED_AD_DRAWER' not in source:
            source = source.replace('openDrawer(', 'sharedAdDrawer(')
            source = source.replace("if(!detail)return;\n",
                """if(!detail)return;
  // SHARED_AD_DRAWER
  function sharedAdDrawer(title,content){
   if(detail.kind==='profit')return openDrawer(title,content);
   const row=trigger.closest('tr'),group=shownGroups[(state.page-1)*state.size+row.sectionRowIndex],kind=detail.kind==='reclassification'?'shop_adjustment':detail.key;
   const amount=detail.kind==='reclassification'?detail.net:detail.wrongCurrency||!/^[-+]?[\\d,]+(?:\\.\\d+)?$/.test(trigger.textContent.trim())?null:-detail.amount*10000n;
   const data={sku:false,resolveControls:true,group,[kind]:group,fees:{[kind]:{amount}}},sales=HTML2_FEE_RATES.read(group,'sales',false);
   return openDrawer(title,FINANCE_COMPOSITION.html(FINANCE_COMPOSITION.build(data,kind),sales.partial?null:sales.amount,amount,kind==='shop_adjustment')+'<details><summary>广告规则、重分类及原始来源说明</summary>'+content+'</details>');
  }
""", 1)
        return '<script'+attrs+'>'+source+'</script>'
    return re.sub(r'<script([^>]*)>([\s\S]*?)</script>', adapt, html)
