const {anchor,datedFact}=require('./summary_periods.cjs');
function micro(value){const s=String(value),negative=s.startsWith('-'),[w,d='']=s.replace(/^[+-]/,'').split('.');return(BigInt(w||0)*1000000n+BigInt((d+'000000').slice(0,6)))*(negative?-1n:1n);}
const fixed=n=>(n<0n?'-':'')+(n<0n?-n:n)/1000000n+'.'+String((n<0n?-n:n)%1000000n).padStart(6,'0');
function split(amount,weights){
 const rows=weights.filter(([,n])=>n>0n),total=rows.reduce((n,[,w])=>n+w,0n);if(!total)return new Map();
 const absolute=amount<0n?-amount:amount,parts=rows.map(([id,w],i)=>({id,i,n:absolute*w/total,remainder:absolute*w%total}));
 let rest=absolute-parts.reduce((n,p)=>n+p.n,0n);
 for(const p of [...parts].sort((a,b)=>a.remainder===b.remainder?a.i-b.i:a.remainder>b.remainder?-1:1)){if(!rest)break;p.n++;rest--;}
 return new Map(parts.map(p=>[p.id,amount<0n?-p.n:p.n]));
}
const periodScope=(f,type)=>[f.store_id,f.currency,anchor(type,Object.hasOwn(f,'period_date')?f.period_date:f.date)||'undated'].join('|');
function settlementWeights(sales,type){
 const weights=new Map(),incomplete=new Set(),scope=f=>periodScope(f,type);
 for(const f of sales)if(f.kind==='sales'&&f.external_order_id){const key=scope(f);if(f.amount==null||f.status==='pending'){incomplete.add(key);continue;}if(!weights.has(key))weights.set(key,new Map());const m=weights.get(key);m.set(f.external_order_id,(m.get(f.external_order_id)||0n)+micro(f.amount));}
 for(const [key,orders]of weights)weights.set(key,new Map([...orders].filter(([,amount])=>amount>0n)));
 for(const key of incomplete)weights.delete(key);
 return weights;
}
function allocateAdvertising(ads,sales,type){
 const pools=new Map(),weights=settlementWeights(sales,type),scope=f=>periodScope(f,type);
 for(const f of ads){const key=scope(f)+'|'+String(f.month||f.date).slice(0,7);if(!pools.has(key))pools.set(key,[]);pools.get(key).push(f);}
 return [...pools].flatMap(([key,rows])=>{
  const first=rows[0],period=key.split('|')[2],basis=period==='undated'?null:weights.get(scope(first)),known=rows.filter(f=>f.amount!=null),amount=known.reduce((n,f)=>n+micro(f.amount),0n);
  // Shares are already in display currency; re-localizing must not restore the monthly parent.
  const base={...first,amount:known.length?fixed(amount):null,original_amount:known.length?fixed(amount):null,original_currency:first.currency,fx:null,locked_local_fact:undefined,period_date:period==='undated'?null:period,
   ledger_key:undefined,ledger_original:undefined,ledger_record:undefined,allocated:true,allocation_readonly:true,
   rows:undefined,sp6th_components:undefined,
   source_id:'period-ad:'+type+':'+key,source:'同期广告分摊',
   advertising_evidence:rows.map(f=>({date:f.period_date,source_id:f.source_id,amount:f.amount,proof:f.source_proof})),
   hierarchy_allocation:{method:'period_order_sales_share',period_type:type,period,source_ids:rows.map(f=>f.source_id),parent_amount:known.length?fixed(amount):null},
   allocation_reason:'同店同币种同期广告金额 × 订单同期退款前结算销售额 ÷ 同期全部有效结算订单销售额'};
  if(!basis?.size||!known.length)return[{...base,external_order_id:'',allocation_reason:'当期有效结算销售额／广告金额缺失，或结算分母不完整，保留待分摊，不跨期转嫁'}];
  const shares=split(amount,[...basis]);return [...basis].map(([order,weight])=>({...base,source_id:base.source_id+':'+order,external_order_id:order,amount:fixed(shares.get(order)),original_amount:fixed(shares.get(order)),hierarchy_allocation:{...base.hierarchy_allocation,order_sales:fixed(weight),store_sales:fixed([...basis.values()].reduce((a,b)=>a+b,0n))}}));
 });
}
function allocatePublicFees(fees,sales,type){
 const weights=settlementWeights(sales,type);
 return fees.flatMap(f=>{
  const day=Object.hasOwn(f,'period_date')?f.period_date:f.date,period=anchor(type,day),basis=period?weights.get(periodScope(f,type)):null;
  const base={...f,source_id:f.source_id+':period:'+type+':'+(period||'undated'),source_parent_id:f.source_id,source:'同期公共费用分摊 · '+f.source,
   original_amount:f.amount,original_currency:f.currency,fx:null,locked_local_fact:undefined,ledger_key:undefined,ledger_original:undefined,ledger_record:undefined,rows:undefined,sp6th_components:undefined,
   external_order_id:'',allocated:true,allocation_readonly:true,period_date:period?day:null,period_date_basis:'公共费用原流水日期；按所选期间分摊',
   public_fee_evidence:{source_id:f.source_id,date:day,amount:f.amount,currency:f.currency,source:f.source,fee_names:[...new Set((f.rows||[]).map(r=>r.name||r.label).filter(Boolean))]},
   hierarchy_allocation:{method:'period_order_sales_share',period_type:type,period,source_ids:[f.source_id],parent_amount:f.amount},
   allocation_reason:'同店同币种同期公共费用 × 订单同期退款前结算销售额 ÷ 同期全部有效结算订单销售额'};
  if(!basis?.size||f.amount==null)return[{...base,allocation_reason:'费用日期或同期有效结算分母缺失／不完整，保留待分摊，不跨期转嫁'}];
  const shares=split(micro(f.amount),[...basis]),denominator=fixed([...basis.values()].reduce((a,b)=>a+b,0n));
  return [...basis].map(([order,weight])=>({...base,source_id:base.source_id+':order:'+order,external_order_id:order,amount:fixed(shares.get(order)),original_amount:fixed(shares.get(order)),hierarchy_allocation:{...base.hierarchy_allocation,order_sales:fixed(weight),store_sales:denominator}}));
 });
}
function allocateItems(f,items){
 const quantity=['warehouse_order','warehouse_other'].includes(f.kind),field=quantity?'quantity_weight':'sales_weight';
 const selected=items.filter(i=>i[field]>0n),unknown=items.some(i=>i[field]==null),weights=selected.map(i=>[i.id,i[field]]);
 if(!selected.length||unknown)return[{fact:f,item:null,amount:f.amount==null?null:fixed(micro(f.amount)),reason:'缺少可靠订单商品'+(quantity?'最终数量':'历史成交金额')+'，保留订单内待分摊'}];
 const shares=f.amount==null?null:split(micro(f.amount),weights);
 return selected.map(item=>({fact:f,item,amount:shares?fixed(shares.get(item.id)):null,reason:'订单内按'+(quantity?'最终数量':'历史成交金额')+'占比分摊'}));
}
module.exports={micro,fixed,split,allocateAdvertising,allocatePublicFees,allocateItems,datedFact};
