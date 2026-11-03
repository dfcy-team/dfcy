(function(){
 'use strict';
 const display=n=>HTML2_FEE_RATES.displayAmount(n);
 function sourceRows(f){
  const excluded=globalThis.FEE_CHECKBOXES?.getExcluded()||{};
  if(f.kind==='product_cost'&&f.cost_calculation?.components&&f.cost_conversion){
   const calc=f.cost_calculation,conversion=f.cost_conversion,q=conversion.quote;
   return [{key:'cost',parent:'',level:2,leaf:false,included:false,label:'商品成本',amount:0n,status:f.status,
    cost_summary:{date:calc.cost_at,period:conversion.period,quote:q,from:conversion.from,to:conversion.to}},
    ...calc.components.map((c,i)=>({key:'cost/'+[c.sku_id||'unmapped',c.cost_version_id||f.source_id+':'+i,c.currency,c.warehouse_id||'',c.unit_cost].join(':'),parent:'cost',level:3,leaf:true,included:true,
     label:(c.sku_code||c.source_sku||'待关联SKU')+' × '+c.quantity,amount:c.local_amount==null?null:micro(c.local_amount),
     status:c.reasons?.length||c.local_amount==null?'pending':'confirmed',
     cost:{sku:c.sku_code||c.source_sku||'待关联SKU',legacy:c.legacy_sku_code||'',quantity:c.quantity,
      unit_cost:c.unit_cost,currency:c.currency,version_id:c.cost_version_id,version_no:c.cost_version_no,
      warehouse_id:c.warehouse_id,effective_from:c.cost_effective_from,effective_to:c.cost_effective_to,
      original_amount:c.unit_cost==null?null:micro(c.net_cost),reasons:c.reasons||[]}}))];
  }
  const rows=['order_fee','refund'].includes(f.kind)&&f.sp6th_components&&f.currency===(f.original_currency||f.currency)
   ?f.sp6th_components.map(c=>({key:c.field,label:c.label+' · '+c.field,amount:micro(c.amount),leaf:true,level:2,status:f.status,source:c.field}))
   :ledgerParts(f.source==='SaaS平台结算'?{...f,source:'平台结算'}:f);
  const stack=[],result=[];
  for(const r of rows){
   while(stack.length&&stack.at(-1).level>=r.level)stack.pop();
   const reference=r.status==='reference',key=(stack.at(-1)?.key||'')+'/'+(r.key||r.label)+(reference?'|reference':'');
   if(r.leaf&&excluded[globalThis.FEE_CHECKBOXES?.key(f,r)])continue;
   result.push({...r,key,parent:stack.at(-1)?.key||'',included:!!r.leaf&&!reference});
   if(!r.leaf)stack.push({...r,key});
  }
  return result;
 }
 function merge(rows){
  const combined=new Map();
  for(const r of rows){
   const key=r.key+'|'+(r.status==='reference'?'reference':'counted');
   if(!combined.has(key))combined.set(key,{...r,amount:0n,missing:false,sources:new Set(),
    ...(r.cost?{cost:{...r.cost,quantity:0,original_amount:0n,original_missing:false,reasons:[]}}:{}),
    ...(r.cost_summary?{dates:new Set(),periods:new Set(),quotes:new Map()}: {})});
   const out=combined.get(key);
   if(r.amount==null)out.missing=true;else out.amount+=r.amount;
   if(r.status==='pending'||r.amount==null)out.status='pending';
   if(r.cost){
    out.cost.quantity+=r.cost.quantity;
    if(r.cost.original_amount==null)out.cost.original_missing=true;else out.cost.original_amount+=r.cost.original_amount;
    out.cost.reasons=[...new Set(out.cost.reasons.concat(r.cost.reasons))];
   }
   if(r.cost_summary){
    if(r.cost_summary.date)out.dates.add(r.cost_summary.date);
    if(r.cost_summary.period)out.periods.add(r.cost_summary.period);
    const q=r.cost_summary.quote;
    if(q)out.quotes.set([q.input_id,q.rate,r.cost_summary.from,r.cost_summary.to].join('|'),{...q,from:r.cost_summary.from,to:r.cost_summary.to});
   }
   if(r.source)out.sources.add(r.source);
  }
  return [...combined.values()].map(r=>{
   let source=[...r.sources].join('；'),label=r.label;
   if(r.cost_summary){
    const dates=[...r.dates].sort();source='成本归属日：'+dates[0]+(dates.length>1?' 至 '+dates.at(-1):'')+
     '；按结算日有效版本计算；汇率月份：'+[...r.periods].sort().join('、')+'；'+r.quotes.size+'种汇率，来源见折叠详情';
   }
   if(r.cost){
    const c=r.cost;label=c.sku+' × '+c.quantity;
    source='单件成本：'+(c.unit_cost??'待核')+' '+c.currency+'；成本版本 #'+(c.version_id||'待核')+
     '（版本号 '+(c.version_no??'—')+'）；有效期：'+(c.effective_from||'未获取')+' 至 '+(c.effective_to||'未结束')+
     '；'+(c.original_missing?'已知原币成本：':'原币成本合计：')+fixed(c.original_amount)+' '+c.currency+
     (c.reasons.length?'；'+c.reasons.join('；'):'');
   }
   return {...r,label,amount:r.missing?null:r.amount,source};
  });
 }
 function finish(rows,target){
  rows=merge(rows);
  const leaves=rows.filter(r=>r.included),known=leaves.reduce((n,r)=>n+(r.amount||0n),0n);
  if(!leaves.length||target!=null&&known!==target){
   rows.push({key:'unresolved',parent:'',level:2,leaf:true,included:true,status:target===0n?'confirmed':'pending',
    label:target===0n?'本项费用为零':'来源待细分差额（已知部分）',amount:target==null?null:target-known,
    source:'保留已能核对的子项；差额不冒充平台佣金或手续费'});
  }
  for(const r of rows)if(!r.leaf&&r.status!=='reference'){
   const children=rows.filter(x=>x.included&&x.key.startsWith(r.key+'/'));
   r.amount=children.some(x=>x.amount==null)?null:children.reduce((n,x)=>n+x.amount,0n);
  }
  rows=rows.map(r=>({...r,amount:display(r.amount)}));
  const total=display(target),sum=rows.filter(r=>r.included).reduce((n,r)=>n+(r.amount||0n),0n);
  if(total!=null&&sum!==total)rows.push({key:'rounding',parent:'',level:2,leaf:true,included:true,label:'显示精度差额',amount:total-sum,status:'confirmed',source:'仅调节子项分别四舍五入产生的尾差'});
  for(const r of rows)if(!r.leaf&&r.status!=='reference'){
   const children=rows.filter(x=>x.included&&x.key.startsWith(r.key+'/'));
   r.amount=children.some(x=>x.amount==null)?null:children.reduce((n,x)=>n+x.amount,0n);
  }
  const ordered=[];
  function visit(parent){for(const r of rows.filter(x=>(x.parent||'')===parent)){ordered.push(r);if(!r.leaf)visit(r.key);}}
  visit('');
  return ordered;
 }
 function fromEntries(entries,target){return finish(entries.flatMap(sourceRows),target);}
 function build(data,kind){
  const ad=['operations','finance'].includes(kind),key=ad?'advertising':kind,group=ad?data[kind]:data.group,target=data.fees[kind]?.amount;
  if(!data.sku){
   let entries=group?.cells?.[key]?.entries||[];
   if(data.resolveControls&&(ad||key==='shop_adjustment')){
    const scope=new Set(Object.values(group?.cells||{}).flatMap(c=>c.entries).map(f=>[f.store_id,String(f.month||f.date).slice(0,7),f.currency].join('|')));
    const hierarchy=HTML2_STORE_HIERARCHY,before=hierarchy.mode();
    try{if(ad)hierarchy.setMode(kind);entries=hierarchy.controls().map(localFact).filter(f=>f.kind===key&&scope.has([f.store_id,String(f.month||f.date).slice(0,7),f.currency].join('|')));}
    finally{hierarchy.setMode(before);}
   }
   return fromEntries(entries,target);
  }
  const hierarchy=HTML2_STORE_HIERARCHY,before=hierarchy.mode();let parents;
  try{if(ad)hierarchy.setMode(kind);parents=hierarchy.controls().map(localFact);}finally{hierarchy.setMode(before);}
  const rows=[];
  for(const member of group?.members||group?.skus?.flatMap(s=>s.members)||[]){
   const amount=member.amounts[key];
   if(key==='product_cost'&&member.component&&member.fact?.cost_conversion){
    rows.push(...sourceRows({...member.fact,cost_calculation:{...member.fact.cost_calculation,components:[member.component]}}));
    continue;
   }
   if(amount==null)continue;
   const orders=new Set((member.orders||[]).map(o=>o.split('|').pop()));
   const own=member.fact?.kind===key?[localFact(member.fact)]:parents.filter(f=>f.kind===key&&String(f.store_id)===String(member.store)&&String(f.month||f.date).slice(0,7)===member.month&&f.currency===member.currency&&(!f.external_order_id||orders.has(f.external_order_id)));
   const parts=own.filter(countedFact).flatMap(sourceRows),leaves=parts.filter(r=>r.included&&r.amount!=null),net=leaves.reduce((n,r)=>n+r.amount,0n);
   if(!leaves.length||net===0n){
    rows.push({key:'allocated-unresolved',level:2,leaf:true,included:true,label:amount===0n?'本项费用为零':'来源待细分（已分摊）',amount,status:amount===0n?'confirmed':'pending',source:'原订单／店铺缺少可核对的非零净额子项'});
    continue;
   }
   let remaining=amount;
   leaves.forEach((r,i)=>{const share=i===leaves.length-1?remaining:amount*r.amount/net;remaining-=share;rows.push({...r,amount:share,source:(r.source||'')+'；按本行已分摊金额拆分，非平台直接返回的SKU费用'});});
   rows.push(...parts.filter(r=>!r.leaf).map(r=>({...r,amount:0n})));
  }
  return finish(rows,target);
 }
 function html(rows,sales,target,signed=false){
  const rate=r=>r.status==='reference'||r.amount==null?'—':HTML2_FEE_RATES.ratio(signed?r.amount:target<0n?-r.amount:r.amount,sales,true).replace(/^\+/,'');
  return '<table class="composition"><thead><tr><th>子项</th><th>金额</th><th>子费率</th></tr></thead><tbody>'+rows.map(r=>'<tr><td style="padding-left:'+((r.level||2)-1)*12+'px">'+(!r.leaf?'<strong>':'')+esc(r.label)+(!r.leaf?'</strong>':'')+(r.status==='reference'?'（仅核对，不计入）':'')+(r.status==='pending'?'（待核）':'')+'<small class="source">'+esc(r.source||'')+'</small></td><td class="num">'+(r.amount==null?'未获取':money(r.amount))+'</td><td class="num">'+rate(r)+'</td></tr>').join('')+'<tr class="balance"><td>合计（分类小计不重复计入）</td><td class="num">'+(target==null?'未获取':money(target))+'</td><td class="num">'+(target==null?'—':HTML2_FEE_RATES.ratio(signed?target:target<0n?-target:target,sales,true).replace(/^\+/,''))+'</td></tr></tbody></table>';
 }
 function costHtml(input){
  const entries=input.map(localFact),target=entries.reduce((n,f)=>n+(f.amount==null?0n:micro(f.amount)),0n);
  const pending=entries.filter(f=>f.cost_calculation?.state==='pending'||f.amount==null).length;
  const parts=fromEntries(entries,target),root=parts.find(r=>r.cost_summary),dates=root?[...root.dates].sort():[];
  let out='<h3>商品成本构成</h3><p>已知成本合计：'+money(target)+' '+esc(entries[0]?.currency||'')+
   '；'+entries.length+'笔记录，'+pending+'笔待核。缺项不补零，已知金额不代表完整成本。</p>'+
   '<p>按结算日有效的已确认成本版本计算，以成本归属月份业务汇率折算。数量取订单及有效调整明细，不是实际出库凭证；没有退货入库依据时不自动冲回成本。</p>'+
   '<details><summary>成本口径及汇率来源</summary><p>成本归属日：'+esc(dates[0]||'未获取')+(dates.length>1?' 至 '+esc(dates.at(-1)):'')+'</p>'+
   (root?[...root.quotes.values()].map(q=>'<p>1 '+esc(q.from)+' = '+esc(q.rate)+' '+esc(q.to)+'；汇率记录 #'+esc(q.input_id)+'<small>'+esc(q.source_description||q.source||'')+'</small></p>').join(''):'')+'</details>';
  if(entries.length>1)return out+'<table class="composition"><thead><tr><th>日期／店铺</th><th>订单</th><th>已知成本</th><th>状态</th></tr></thead><tbody>'+
   entries.map(f=>'<tr><td>'+esc(f.date)+'<small>'+esc(f.store_code)+'</small></td><td>'+esc(f.external_order_id||'店铺公共调整')+'</td><td>'+money(f.amount)+' '+esc(f.currency)+'</td><td>'+(f.cost_calculation?.state==='pending'?'待核':'已核算')+'</td></tr>').join('')+'</tbody></table>';
  return out+'<table class="composition"><thead><tr><th>SKU</th><th>累计数量</th><th>单件成本</th><th>原币成本合计</th><th>折算成本</th><th>版本及状态</th></tr></thead><tbody>'+
   parts.filter(r=>r.included).map(r=>{const c=r.cost;return'<tr><td>'+esc(c?.sku||r.label)+'</td><td>'+esc(c?.quantity??'—')+'</td><td>'+(c?.unit_cost==null?'未获取':preciseMoney(c.unit_cost)+' '+esc(c.currency))+'</td><td>'+(c&&!c.original_missing?money(c.original_amount)+' '+esc(c.currency):'未获取／部分待核')+'</td><td>'+money(r.amount)+'</td><td>'+esc(c?.version_id?'#'+c.version_id+' / v'+c.version_no:'版本待核')+'<small>'+esc(c?.effective_from||'')+' 至 '+esc(c?.effective_to||'未结束')+'</small><small>'+esc(c?.reasons.join('；')||r.source||'')+'</small></td></tr>';}).join('')+'</tbody></table>';
 }
 if(typeof productCostDetails==='function'){
  const previous=productCostDetails;
  productCostDetails=entries=>entries.some(f=>f.cost_conversion||f.cost_calculation?.time_basis==='settlement_date')?costHtml(entries):previous(entries);
 }
 globalThis.FINANCE_COMPOSITION={build,fromEntries,html};
})();
