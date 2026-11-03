(function(){
 'use strict';
 // Cache only within this document and settings revision. Never persist results.
 let revision=0,sequence=0;const ids=new WeakMap(),caches=[];
 globalThis.SAAS_INVALIDATE=()=>{revision++;for(const cache of caches)cache.clear();};
 globalThis.SAAS_RENDER=()=>{if(globalThis.SAAS_READY)renderLedger();};
 globalThis.SAAS_MEMO=fn=>{
  const cache=new Map();caches.push(cache);
  return function(...args){
   const objectKey=x=>{if(x===null||typeof x!=='object')return String(x);if(x===state.filters)return'filters';if(!ids.has(x))ids.set(x,++sequence);return ids.get(x);};
   const key=JSON.stringify([revision,globalThis.HTML2_STORE_HIERARCHY?.mode(),state.filters,args.map(objectKey)]);
   if(cache.has(key))return cache.get(key);
   const result=fn.apply(this,args);if(cache.size>=8)cache.delete(cache.keys().next().value);cache.set(key,result);return result;
  };
 };
 // Resolve children lazily from accepted parent facts, without changing a row's
 // allocated amount. Credits keep their original sign; all arithmetic is micro units.
 globalThis.SAAS_FEE_PARTS=(data,kind)=>{
  if(!data.sku)return null;
  const mode=['operations','finance'].includes(kind)?kind:null,key=mode?'advertising':kind,group=mode?data[mode]:data.group;
  if(!group)return null;
  const hierarchy=HTML2_STORE_HIERARCHY,before=hierarchy.mode();let parents;
  try{if(mode)hierarchy.setMode(mode);parents=hierarchy.controls().map(localFact);}finally{hierarchy.setMode(before);}
  const combined=new Map(),scopes=new Map();
  for(const f of parents)if(f.kind===key){const k=[f.store_id,String(f.month||f.date).slice(0,7),f.currency].join('|');if(!scopes.has(k))scopes.set(k,[]);scopes.get(k).push(f);}
  for(const member of group.members||group.skus?.flatMap(s=>s.members)||[]){
   const amount=member.amounts[key];if(amount==null)continue;
   const orders=new Set((member.orders||[]).map(o=>o.split('|').pop()));
   const own=member.fact?.kind===key?[localFact(member.fact)]:(scopes.get([member.store,member.month,member.currency].join('|'))||[]).filter(f=>!f.external_order_id||orders.has(f.external_order_id));
   const rows=own.flatMap(f=>{
    if(!countedFact(f))return[];
    if(['order_fee','refund'].includes(key)&&f.sp6th_components&&f.currency===(f.original_currency||f.currency))return f.sp6th_components.map(c=>({label:c.label+' · '+c.field,amount:micro(c.amount)}));
    const excluded=globalThis.FEE_CHECKBOXES?.getExcluded()||{};
    return ledgerParts(f).filter(r=>r.leaf&&r.status!=='reference'&&r.amount!=null&&!excluded[globalThis.FEE_CHECKBOXES?.key(f,r)]);
   }),net=rows.reduce((n,r)=>n+r.amount,0n);
   if(!rows.length||net===0n){if(amount!==0n)combined.set('来源待细分（已分摊）',(combined.get('来源待细分（已分摊）')||0n)+amount);continue;}
   let remaining=amount;
   rows.forEach((r,i)=>{const share=i===rows.length-1?remaining:amount*r.amount/net;remaining-=share;combined.set(r.label,(combined.get(r.label)||0n)+share);});
  }
  const total=combined.size?[...combined.values()].reduce((n,v)=>n+v,0n):null,target=data.fees[kind]?.amount;
  if(total!==target)return null;
  return [...combined].map(([label,amount])=>({label,amount:HTML2_FEE_RATES.displayAmount(amount)}));
 };
})();
