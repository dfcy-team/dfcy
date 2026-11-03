// Single order-level ledger for all native summary levels. No source writes.
const {micro,fixed,split,allocateAdvertising,allocatePublicFees,allocateItems}=require('./summary_allocation.cjs');
const {DAY,date,iso,datedFact}=require('./summary_periods.cjs');
const kinds=['sales','refund','order_fee','adjustment','shop_adjustment','advertising','product_cost','gcash','promotion','warehouse_order','warehouse_other'];
const bill=f=>String(f.month||f.date||'').slice(0,7);
const orderKey=f=>[f.store_id,f.external_order_id,f.currency].join('|');
function orderAttribution(s,f){
 if(!f.store_id)return '国家费用尚未归属具体订单；保留原账单分母，不转嫁给当前店铺';
 if(!f.external_order_id)return f.allocation_reason||'来源未关联订单，尚未确认公共分摊依据';
 const dates=s.c.TEST_SNAPSHOT?.database?.order_dates;
 if(dates&&!dates[f.store_id+'|'+f.external_order_id]?.order_id)return '未唯一关联本批次SaaS订单，待核对';
 return '';
}
function ignoredWarehouse(s,f){return ['warehouse_order','warehouse_other'].includes(f.kind)&&!!orderAttribution(s,f);}
function attributionTotals(s,facts){
 const groups=new Map();
 for(const f of facts){
  if(ignoredWarehouse(s,f))continue;
  if(!s.counted(f)&&(f.amount!=null||f.status==='reference'||f.ledger_disabled))continue;
  const key=[f.country,f.currency,f.kind].join('|');
  if(!groups.has(key))groups.set(key,{country:f.country,currency:f.currency,kind:f.kind,total:0n,assigned:0n,pending:0n,pending_rows:0,unknown_rows:0});
  const g=groups.get(key),pending=!!orderAttribution(s,f);
  if(f.amount==null){g.unknown_rows++;continue;}
  const n=micro(f.amount);g.total+=n;g[pending?'pending':'assigned']+=n;if(pending&&n!==0n)g.pending_rows++;
 }
 return [...groups.values()].map(g=>({...g,total:fixed(g.total),assigned:fixed(g.assigned),pending:fixed(g.pending)}));
}
function dailyAdvertising(s,parents,mode){
 const {c,p}=s,raw=c.HTML2_STORE_HIERARCHY.stores().map(p.localFact),out=[];
 for(const f of parents.filter(f=>f.kind==='advertising')){
  if(!String(f.source_id).startsWith('hierarchy-ad:')){out.push(datedFact(f,new Map()));continue;}
  const month=bill(f),r=c.HTML2_ADVERTISING_COLUMNS.calculate(f.store_code,month,raw),days=new Map(),proof=new Map();
  const add=(day,n)=>{if(date(day)&&day.startsWith(month))days.set(day,(days.get(day)||0n)+n);};
  if(mode==='operations')for(const a of r.actualDetails||[])if(a.amount!=null){const day=String(a.date).slice(0,10);add(day,micro(a.amount));if(a.source_id){if(!proof.has(day))proof.set(day,[]);proof.get(day).push(a.source_id);}}
  for(const plan of r.details||[]){
   const field=mode==='finance'?'debit':'tax',total=plan[field];
   // Operations tax is only included when the accepted report separately adds it.
   if(mode==='operations'&&(r.operations===r.spend||total==null))continue;
   if(plan.duration&&total!=null){
    const start=Date.parse(plan.time.length>10?plan.time.slice(0,19)+'Z':plan.time+'T00:00:00Z'),duration=plan.duration,cents=micro(total)/10000n;
    const cumulative=t=>{const elapsed=Math.max(0,Math.min(duration,t-start));return(cents*BigInt(Math.round(elapsed))*2n+BigInt(duration))/(2n*BigInt(duration));};
    if(!Number.isFinite(start)||duration<=0)continue;
    for(let d=date(month+'-01');iso(d).startsWith(month);d=new Date(+d+DAY))add(iso(d),-(cumulative(+d+DAY)-cumulative(+d))*10000n);
   }else if(mode==='finance'&&r.crossBorder&&plan.monthGross!=null)add(String(plan.date).slice(0,10),-micro(plan.monthGross));
  }
  // A disabled/replaced monthly base must not leave the original daily charges active.
  const zeroBase=r.ledgerBase&&r.ledgerOriginal&&r.ledgerBase[mode]!==r.ledgerOriginal[mode]&&r.ledgerBase[mode]===0n;
  if(r.ledgerBase&&r.ledgerOriginal&&r.ledgerBase[mode]!==r.ledgerOriginal[mode]){days.clear();proof.clear();if(zeroBase)for(let d=date(month+'-01');iso(d).startsWith(month);d=new Date(+d+DAY))add(iso(d),0n);}
  for(const entry of Object.values(c.LEDGER_FEES?.records()||{}))if(entry.type==='new'&&entry.state==='active'&&entry.kind==='advertising'&&entry.store===String(f.store_id)&&entry.month===month&&(entry.mode===mode||entry.mode==='both')){
   add(entry.date,micro(entry.amount));if(!proof.has(entry.date))proof.set(entry.date,[]);proof.get(entry.date).push(entry.id);
  }
  const total=f.amount==null?null:micro(f.amount),known=[...days.values()].reduce((n,v)=>n+v,0n);
  // Never invent daily consumption for manual/frozen differences or missing evidence.
  if(total==null){out.push({...f,period_date:null,allocation_reason:'本口径广告金额未确认'});continue;}
  for(const [day,n]of days)out.push({...f,date:day,period_date:day,source_id:f.source_id+':day:'+day,amount:fixed(n),source_proof:{actual_source_ids:proof.get(day)||[],recharge_source_ids:(r.details||[]).filter(p=>p.duration||r.crossBorder).map(p=>p.id)},period_date_basis:zeroBase?'月度广告禁用／零额规则适用日及已登记调整（非实际消耗日）':mode==='operations'?'广告实际日报／已登记调整及已确认税额日摊':'既有充值归集／周期日摊及已登记调整（非实际消耗）'});
  if(total!==known)out.push({...f,period_date:null,source_id:f.source_id+':undated',amount:fixed(total-known),allocation_reason:'月度控制额与具备日期依据的广告构成差额，保留待归期，不假填日期'});
 }
 return out;
}
function orderLedger(s,type='month',mode='operations'){
 s.c.HTML2_STORE_HIERARCHY.setMode(mode);
 if(!s.orderBases)s.orderBases=new Map();
 if(s.orderBases.has(mode)){const base=s.orderBases.get(mode),orders=type==='month'?base.orders:base.periodOrders.concat(allocatePublicFees(base.publicFees,base.sales,type));return orders.concat(allocateAdvertising(base.ads,base.sales,type)).filter(f=>!ignoredWarehouse(s,f)).map((f,i)=>({...f,allocation_key:[f.source_id,f.store_id||'country',f.external_order_id||'unassigned',f.currency,i].join('|')}));}
 const {c,p}=s,parents=c.HTML2_STORE_HIERARCHY.controls().map(p.localFact),first=new Map();
 for(const f of parents)if(f.kind==='sales'&&s.counted(f)&&f.amount!=null&&micro(f.amount)>0n&&date(f.date)){
  const key=bill(f)+'|'+orderKey(f);if(!first.has(key)||f.date<first.get(key))first.set(key,f.date);
 }
 const dated=f=>datedFact(f,new Map([[orderKey(f),first.get(bill(f)+'|'+orderKey(f))]]));
 const originals=parents.filter(f=>f.kind!=='advertising'),source=new Map(originals.map(f=>[f.source_id,f])),orders=[];
 const generated=c.HTML2_STORE_HIERARCHY.orderAllocation(originals),groups=new Map();
 for(const f of generated){
  if(!f.hierarchy_allocation){orders.push(dated(f));continue;}
  const ids=f.hierarchy_allocation.source_ids,key=JSON.stringify(ids);
  if(!groups.has(key))groups.set(key,{ids,rows:[]});groups.get(key).rows.push(f);
 }
 for(const {ids,rows}of groups.values())for(const id of ids){
  const f=source.get(id);if(!f)throw Error('公共费用原始来源缺失，未继续计算。');
  const quantity=rows[0].hierarchy_allocation.method==='order_quantity_share',weights=rows.map(r=>[r.external_order_id,micro(quantity?r.hierarchy_allocation.order_quantity:r.hierarchy_allocation.order_sales)]),parts=split(micro(f.amount),weights);
  for(const r of rows)orders.push(dated({...f,...(!Object.hasOwn(f,'statistics_date')&&date(f.date)&&!/^hierarchy-/.test(f.source_id)?{statistics_date:f.date,statistics_date_basis:'公共费用原流水日期'}:{}),source_id:f.source_id+':order:'+r.external_order_id,source_parent_id:f.source_id,external_order_id:r.external_order_id,amount:fixed(parts.get(r.external_order_id)),allocated:true,allocation_readonly:true,ledger_key:undefined,hierarchy_allocation:{...r.hierarchy_allocation,source_ids:[id],parent_amount:f.amount}}));
 }
 // Unassociated warehouse fees and country residuals stay in the original source,
 // outside this calculation and its pending queue; associated shares are unchanged.
 // Advertising reclassification offsets are not additional public expenses.
 const publicFees=originals.filter(f=>f.store_id&&!f.external_order_id&&['order_fee','shop_adjustment','adjustment'].includes(f.kind)&&!/^hierarchy-reclassification:/.test(f.source_id)&&s.counted(f)),publicIds=new Set(publicFees.map(f=>f.source_id));
 const sales=orders.filter(f=>f.kind==='sales'&&f.status!=='reference'),adjustments=publicFees.filter(f=>f.kind==='adjustment'),adjustmentIds=new Set(adjustments.map(f=>f.source_id));
 const monthly=orders.filter(f=>!adjustmentIds.has(f.source_parent_id||f.source_id)).concat(allocatePublicFees(adjustments.map(dated),sales,'month'));
 const base={orders:monthly,periodOrders:orders.filter(f=>!publicIds.has(f.source_parent_id||f.source_id)),publicFees:publicFees.map(dated),ads:dailyAdvertising(s,parents,mode),sales};
 s.orderBases.set(mode,base);
 return orderLedger(s,type,mode);
}
function itemMembers(s,facts,fullFacts=facts){
 const {c,p}=s,data=c.HTML2_SKU_ORDER_SALES||{},byOrder=new Map(),members=[];
 for(const f of facts)if(f.external_order_id&&f.kind==='product_cost'&&f.cost_event!=='return'&&f.cost_calculation?.components?.length){const key=orderKey(f);if(!byOrder.has(key))byOrder.set(key,f.cost_calculation.components);}
 for(const f of fullFacts)if(f.external_order_id&&f.kind==='product_cost'&&f.cost_event!=='return'&&f.cost_calculation?.components?.length){const key=orderKey(f);if(!byOrder.has(key))byOrder.set(key,f.cost_calculation.components);}
 function items(f){
  const lines=data.orders?.[f.store_id+'|'+f.external_order_id]||[],changes=data.exchanges?.[f.store_id+'|'+f.external_order_id]?.changes||[];
  let components=byOrder.get(orderKey(f));
  if(!components){
   const quantities=new Map();for(const l of lines){const key=l.internal_sku_id?'id:'+l.internal_sku_id:'code:'+l.seller_sku,part=quantities.get(key)||{sku_id:l.internal_sku_id,source_sku:l.seller_sku,sku_code:l.seller_sku,quantity:0};part.quantity+=Number(l.quantity||0);quantities.set(key,part);}
   for(const change of changes){
    if(['reduce','replace'].includes(change.action)){const part=quantities.get('id:'+(change.old_sku_id??change.sku_id));if(part)part.quantity=Math.max(0,part.quantity-Number(change.reduce_quantity||0));}
    if(['add','replace'].includes(change.action)){const id=change.new_sku_id??change.sku_id,key='id:'+id,part=quantities.get(key)||{sku_id:id,source_sku:change.new_sku_code||'',sku_code:change.new_sku_code||'换入SKU #'+id,quantity:0};part.quantity+=Number(change.add_quantity||0);quantities.set(key,part);}
   }
   components=[...quantities.values()];
  }
  return components.map((component,i)=>{
   let matched=lines.filter(l=>component.sku_id!=null?l.internal_sku_id===component.sku_id:l.seller_sku===component.source_sku);
   // The accepted cost snapshot can identify an SKU before the original item is bound.
   // Only a unique, unbound source line in this same order may supply price/link evidence.
   if(!matched.length&&component.sku_id!=null&&component.source_sku){
    const related=components.filter(c=>c.source_sku===component.source_sku),candidates=lines.filter(l=>l.seller_sku===component.source_sku);
    const identities=new Set(candidates.map(l=>[l.platform_product_id,l.platform_variant_id].join('|')));
    if(related.every(c=>c.sku_id===component.sku_id)&&candidates.length&&candidates.every(l=>l.internal_sku_id==null)&&
       (candidates.length===1||identities.size===1&&candidates.every(l=>l.platform_product_id&&l.platform_variant_id)))matched=candidates;
   }
   let replacement=false;if(!matched.length){const oldIds=changes.filter(x=>x.action==='replace'&&x.new_sku_id===component.sku_id).map(x=>x.old_sku_id);matched=lines.filter(l=>oldIds.includes(l.internal_sku_id));replacement=matched.length>0;}
   const quantity=BigInt(component.quantity||0),original=matched.reduce((n,l)=>n+BigInt(l.quantity||0),0n);
   let value=matched.length&&original>0n&&matched.every(l=>l.historical_line_amount!=null)?matched.reduce((n,l)=>n+micro(l.historical_line_amount),0n)*quantity/original:null;
   if(value!=null&&component.sku_id!=null){
    const related=components.map((c,j)=>({c,j})).filter(({c})=>c.sku_id===component.sku_id&&c.source_sku===component.source_sku),quantityTotal=related.reduce((n,{c})=>n+BigInt(c.quantity||0),0n);
    if(related.length>1&&quantityTotal===original)value=split(matched.reduce((n,l)=>n+micro(l.historical_line_amount),0n),related.map(({c,j})=>[j,BigInt(c.quantity||0)])).get(i)??null;
   }
   const added=!matched.length&&changes.some(x=>x.action==='add'&&(x.new_sku_id===component.sku_id||x.sku_id===component.sku_id));
   const products=[...new Set(matched.map(l=>String(l.platform_product_id||'')).filter(v=>v&&v!=='0'))];
   return{id:String(i),component,sales_weight:added?0n:value,quantity_weight:quantity,
    product_link_id:products.length===1?products[0]:undefined,product_link_basis:replacement?'换货后SKU沿原成交商品链接归属':'原订单商品行与原成交商品ID'};
  });
 }
 function member(f,item,amount,reason){
  const component=item?.component||{},amounts={[f.kind]:amount==null?null:micro(amount)};
  return{country:f.country,platform:f.platform||'',store:String(f.store_id||''),shop:f.store_code||'待归属店铺',month:bill(f),currency:f.currency,
   sku_id:component.sku_id||null,code:item?component.sku_code||component.source_sku||'待关联SKU':'待分摊（订单内）',legacy:component.legacy_sku_code||'',platform_sku:component.source_sku||'',
   identity:item?(component.sku_id?'internal:'+component.sku_id:'order-item:'+f.store_id+':'+f.external_order_id+':'+item.id):'unallocated:'+f.store_id+':'+(f.external_order_id||'store'),
   orders:f.external_order_id?[f.platform+'|'+f.store_id+'|'+f.external_order_id]:[],amounts,source:'order-ledger',fact:f,
   ...(f.kind==='product_cost'?{component}:{}),product_link_id:item?.product_link_id,product_link_basis:item?.product_link_basis,
   pending:!item||!component.sku_id||!item.product_link_id||amount==null||f.status==='pending'||!!component.reasons?.length,hierarchy_basis:reason,
   allocation_notes:{[f.kind]:reason}};
 }
 for(const f of facts){
  if(!s.counted(f))continue;
  const selected=f.external_order_id?items(f):[];
  if(f.kind==='product_cost'&&f.cost_calculation?.components?.length){
   const components=f.cost_calculation.components,values=components.map(component=>{
    if(Object.hasOwn(component,'unit_cost')&&component.unit_cost==null||component.reasons?.length)return null;
    if(f.cost_conversion)return component.local_currency===f.currency&&component.local_amount!=null?micro(component.local_amount):null;
    if(component.net_cost==null)return null;
    if(component.currency===f.currency)return -micro(component.net_cost);
    return f.fx?-micro(component.net_cost)*micro(f.fx.rate)/1000000n:null;
   });
   const known=values.reduce((n,v)=>n+(v||0n),0n),target=f.amount==null?null:micro(f.amount);
   // Conversion residuals are explicit, never spread onto a different order/SKU.
   components.forEach((component,i)=>{const item=selected.find(x=>component.sku_id!=null?x.component.sku_id===component.sku_id:x.component.source_sku===component.source_sku);members.push(member(f,item?{...item,component}:null,values[i]==null?null:fixed(values[i]),'原订单逐项成本快照；不按销售额重摊'));});
   if(target!=null&&target!==known)members.push(member(f,null,fixed(target-known),'成本折算尾差／原成本未细分部分，保留该订单待分摊'));
  }else for(const part of allocateItems(f,selected))members.push(member(f,part.item,part.amount,part.reason));
 }
 return members;
}
function normalizeGroups(groups){
 for(const g of groups){
  g.amounts=Object.fromEntries(kinds.map(kind=>[kind,{amount:0n,known:0,missing:0}]));
  for(const m of g.members)for(const [kind,n]of Object.entries(m.amounts)){if(n==null)g.amounts[kind].missing++;else{g.amounts[kind].amount+=n;g.amounts[kind].known++;}}
  for(const cell of Object.values(g.amounts))if(!cell.known&&!cell.missing)cell.known=1;
 }
 return groups;
}
function groupMembers(s,members,scope='store'){return normalizeGroups(s.c.SKU_SUMMARY.group(members,scope));}
function groupLinks(s,sku,facts){
 const links=s.c.HTML2_PRODUCT_LINKS.group(sku,facts);
 for(const g of links){normalizeGroups(g.skus);normalizeGroups([{...g,members:g.skus.flatMap(part=>part.members)}]).forEach(part=>g.amounts=part.amounts);g.pending=g.pending||!g.product_id;}
 return links;
}
function itemAttribution(s,facts,fullFacts){
 const groups=new Map();
 for(const m of itemMembers(s,facts,fullFacts)){
  if(!m.fact.external_order_id||Object.values(m.amounts).every(n=>n===0n)||m.sku_id&&m.product_link_id)continue;
  if(!groups.has(m.shop))groups.set(m.shop,{orders:new Set(),sku_orders:new Set(),link_orders:new Set()});
  const g=groups.get(m.shop),id=m.fact.external_order_id;g.orders.add(id);if(!m.sku_id)g.sku_orders.add(id);if(!m.product_link_id)g.link_orders.add(id);
 }
 return [...groups].map(([store,g])=>({store,...Object.fromEntries(Object.entries(g).map(([key,set])=>[key,set.size]))}));
}
module.exports={orderLedger,itemMembers,groupMembers,groupLinks,dailyAdvertising,orderAttribution,attributionTotals,itemAttribution,ignoredWarehouse};
