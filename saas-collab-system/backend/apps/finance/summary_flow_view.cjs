// Presentation of immutable source evidence; never changes the accounting ledger.
const {orderLedger,orderAttribution}=require('./summary_order_ledger.cjs');
function flowAmounts(s,f){
 const local=s.p.localFact(f),from=f.original_currency||f.currency,to=local.currency;
 const original=f.original_amount===undefined?f.amount:f.original_amount,quote=local.fx||f.fx||f.cost_conversion?.quote;
 return{amount:local.amount,currency:to,original_amount:original,original_currency:from,
  conversion:{from,to,rate:from===to?'1':quote?.rate??null,basis:from===to?'同币种，无需折算':quote?.basis||f.cost_conversion?.basis||'按来源日期有效汇率',period:quote?.date||quote?.period||f.cost_conversion?.period||String(f.date).slice(0,7),input_id:quote?.input_id??null,missing:original!=null&&local.amount==null}};
}
function sourceIndex(s){
 if(s.flowSourceIndex)return s.flowSourceIndex;
 const raw=new Map((s.rawFlows||[]).map(f=>[f.source_id,f])),index=new Map();
 const previous=s.c.HTML2_STORE_HIERARCHY.mode();
 try{for(const mode of ['operations','finance']){
  const rows=s.ledgers?.get('month|'+mode)||orderLedger(s,'month',mode);
  for(const f of rows){
   const ids=new Set([f.source_id,f.source_parent_id,f.warehouse_allocation?.source_id,
    ...(f.rows||[]).map(r=>'finance-transaction:'+r.id),
    ...(f.cost_calculation?.components||[]).map(r=>r.source_flow_id),
    ...(f.source_proof?.actual_source_ids||[]),...(f.source_proof?.recharge_source_ids||[])]);
   const reason=orderAttribution(s,f)||((!f.period_date||f.amount==null)?f.allocation_reason:'');
   for(const id of ids){const source=raw.get(id);if(!source||source.store_id&&String(source.store_id)!==String(f.store_id))continue;
    if(!index.has(id))index.set(id,{});const entry=index.get(id);entry[mode]||={};
    if(reason||f.amount==null||f.status==='pending'){entry[mode].pending=true;entry[mode].reason||=reason||'金额或核算依据未完整获取';}
    else if(s.counted(f))entry[mode].counted=true;
   }
  }
 }}finally{s.c.HTML2_STORE_HIERARCHY.setMode(previous);}
 s.flowSourceIndex=index;return index;
}
function flowInclusion(s,f,participation){
 if(f.ledger_disabled||participation?.excluded)return{state:'disabled',label:'已排除（原额保留）',mode_label:'不计入',reason:participation?.change?.reason||f.description||''};
 if(f.status==='reference')return{state:'reference',label:'仅核对，不计入',mode_label:'不计入',reason:'该来源用于核对，不重复计入利润'};
 const evidence=sourceIndex(s).get(f.source_id),modes=['operations','finance'],names={operations:'运营',finance:'财务'};
 if(evidence){
  const counted=modes.filter(m=>evidence[m]?.counted),pending=modes.filter(m=>evidence[m]?.pending);
  return{state:pending.length||!counted.length?'pending':'normal',label:pending.length?(counted.length?'部分已计入，部分待核':'计入依据待核'):counted.length?'已纳入汇总':'计入情况待核对',mode_label:modes.filter(m=>evidence[m]?.counted||evidence[m]?.pending).map(m=>names[m]+(evidence[m].pending?(evidence[m].counted?'（部分已计入，部分待核）':'待核'):'')).join('、')||'待核对',reason:pending.map(m=>names[m]+'：'+(evidence[m].counted?'已知部分保持计入；':'')+evidence[m].reason).join('；')};
 }
 return{state:'pending',label:'计入情况待核对',mode_label:'待核对',reason:'尚未取得该原始流水与正式核算结果的逐笔对应依据，不将来源正常等同于已计入'};
}
function flowStatus(f,inclusion,conversion){
 if(f.ledger_disabled||inclusion?.state==='disabled')return'已排除（原额保留）';
 if(f.status==='reference'||inclusion?.state==='reference')return'仅核对，不计入';
 if(conversion.missing)return'待核／缺汇率';
 return inclusion?.label||null;
}
function flowState(s,f,participation){
 if(f.ledger_disabled||participation?.excluded)return'disabled';
 if(f.status==='reference')return'reference';
 if(flowAmounts(s,f).conversion.missing||f.amount==null||f.status==='pending')return'pending';
 return flowInclusion(s,f,participation).label==='已纳入汇总'?'normal':'pending';
}
function flowEditBlock(s,f){
 if(s.c.HTML2_PROFIT_RULES?.closedFor(f.store_code,String(f.month||f.date).slice(0,7)))return'该店铺账期已关账，请在开放账期登记调整';
 if(f.allocation_readonly||f.warehouse_allocation)return'规则分摊记录只读，请核对对应原始来源';
 return'';
}
module.exports={flowAmounts,flowInclusion,flowState,flowStatus,flowEditBlock};
