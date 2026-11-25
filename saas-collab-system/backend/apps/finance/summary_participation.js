(function(){
 'use strict';
 const key='saas-finance-source-participation-v1';
 const storage=()=>globalThis.SAAS_STORAGE||globalThis.localStorage;
 const database=()=>globalThis.TEST_SNAPSHOT?.database||SNAPSHOT.database;
 let cached;
 function index(){
  if(cached)return cached;
  const data=database(),raw=new Map((data?.raw_flows||data?.participation_sources||[]).map(f=>[f.source_id,f])),targets=new Map();
  for(const f of data?.facts||[]){
   if(['sales','advertising','product_cost','warehouse_order','warehouse_other'].includes(f.kind)||f.amount==null||f.original_amount!==undefined||f.locked_local_fact||f.status==='reference'||f.status==='pending')continue;
   const members=f.rows||[];
   if(members.length){
    if(members.some(r=>r.amount==null||r.currency!==f.currency)||members.reduce((n,r)=>n+micro(r.amount),0n)!==micro(f.amount))continue;
    for(const r of members){const id='finance-transaction:'+r.id;if(!targets.has(id))targets.set(id,[]);targets.get(id).push(f);}
   }else if(raw.has(f.source_id)){
    const r=raw.get(f.source_id);
    if(r.currency===f.currency&&r.amount!=null&&micro(r.amount)===micro(f.amount)){if(!targets.has(f.source_id))targets.set(f.source_id,[]);targets.get(f.source_id).push(f);}
   }
  }
  cached={raw,targets};return cached;
 }
 function state(){const text=storage()?.getItem(key);if(!text)return{version:1,changes:{},history:[]};const value=JSON.parse(text);if(value.version!==1||!value.changes||!Array.isArray(value.history))throw Error('流水参与设置格式无效，未按空设置计算。');return value;}
 function info(id){
  const {raw,targets}=index(),f=raw.get(id),matches=targets.get(id)||[];
  let reason='';
  if(!f)reason='当前批次未找到该原始流水';
  else if(f.status==='reference')reason='该记录仅用于核对，本来就不计入利润';
  else if(f.amount==null||f.status==='pending')reason='原始金额或来源仍待核实';
  else if(['sales','advertising','product_cost','warehouse_order','warehouse_other'].includes(f.kind))reason='该记录由销售、广告或成本分摊规则处理，请到对应来源核对';
  else if(matches.length!==1)reason='尚不能与唯一核算来源逐笔对应，请先核对来源；未改变参与状态';
  else if(globalThis.HTML2_PROFIT_RULES?.closedFor(f.store_code,String(f.date).slice(0,7)))reason='该店铺账期已关账，请在开放月份登记调整';
  const saved=state().changes[id];
  return{supported:!reason,reason,excluded:!!saved?.excluded,change:saved,source:f,target:matches[0]};
 }
 function apply(rows){
  const changes=state().changes,disabled=new Set(Object.keys(changes).filter(id=>changes[id].excluded));if(!disabled.size)return rows;
  // Verify source identity on every batch. Never silently reattach an old exclusion.
  for(const id of disabled){const {raw,targets}=index();const f=raw.get(id),r=changes[id];if(!f||targets.get(id)?.length!==1||String(f.store_id)!==r.store||f.currency!==r.currency||f.amount!==r.amount||String(f.date)!==r.date)throw Error('原流水归属或金额已变化，请先核对参与设置：'+id);}
  return rows.map(f=>{
   if(f.rows?.length){const removed=f.rows.filter(r=>disabled.has('finance-transaction:'+r.id));if(!removed.length)return f;
    const excluded=removed.reduce((n,r)=>n+micro(r.amount),0n);
    return{...f,amount:fixed(micro(f.amount)-excluded),rows:f.rows.filter(r=>!disabled.has('finance-transaction:'+r.id)),participation_original:f};
   }
   return disabled.has(f.source_id)?{...f,amount:'0.00',participation_original:f}:f;
  });
 }
 function prepare(record){
  if(!record||Object.keys(record).some(k=>!['id','operation','reason'].includes(k))||!['exclude_source','restore_source'].includes(record.operation))throw Error('流水参与操作无效。');
  const reason=String(record.reason||'').trim();if(!reason||reason.length>1000)throw Error('请填写本次变更原因（最多1000字）。');
  const current=info(record.id);if(!current.supported)throw Error(current.reason);
  const excluded=record.operation==='exclude_source';if(current.excluded===excluded)throw Error('该流水参与状态未改变，请刷新后核对。');
  const f=current.source,old=state(),after={id:f.source_id,store:String(f.store_id),month:String(f.date).slice(0,7),date:f.date,kind:f.kind,currency:f.currency,amount:f.amount,excluded,reason};
  return{version:1,changes:{...old.changes,[f.source_id]:after},history:old.history.concat({at:new Date().toISOString(),operation:record.operation,before:current.change||null,after})};
 }
 globalThis.RAW_PARTICIPATION={key,info,apply,prepare,state};
})();
