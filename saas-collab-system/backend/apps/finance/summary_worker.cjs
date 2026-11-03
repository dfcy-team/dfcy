// Isolated execution is retained for validation and writes.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const {createEngine}=require('./summary_engine.cjs'),input=JSON.parse(fs.readFileSync(0,'utf8'));
let session;try{session=createEngine(process.argv[2],input);}catch(e){process.stdout.write(JSON.stringify({ok:false,error:e.message}));process.exit(2);}
const {c,p,plain,storage,writes,proposed,feeKey}=session;
const {orderLedger,itemMembers,groupMembers,groupLinks,orderAttribution,attributionTotals,itemAttribution,ignoredWarehouse}=require('./summary_order_ledger.cjs');
session.counted=vm.runInContext('countedFact',c);
function eq(a,b){assert.deepEqual(plain(a),plain(b),'保存内容与服务器计算不一致，请刷新后重试。');}
function run(){
 if(input.action==='inspect'){
  if(input.state?.['html2-shopee-recharge-v1'])c.SHOPEE_RECHARGE.validateImport(input.state['html2-shopee-recharge-v1']);
  const rows=p.entriesFor('store');
  if(Object.keys(c.LEDGER_FEES.records()).length){p.entriesFor('detail');for(const [id,r]of Object.entries(c.LEDGER_FEES.records()))if(r.type==='patch'&&!c.LEDGER_FEES.find(id))throw Error('旧调整来源不在新批次中，请先核对，未丢弃既有调整。');}
  return {stores:[...new Map(rows.filter(f=>f.store_id).map(f=>[f.store_id,{id:f.store_id,code:f.store_code}])).values()],rawStores:[...new Set(c.TEST_SNAPSHOT.raw.map(r=>r.store_id).filter(Boolean))],snapshot:c.TEST_SNAPSHOT.snapshot_at,rawRows:c.TEST_SNAPSHOT.raw.length};
 }
 if(input.action==='reconcile'){
  const result=[],attribution=[],counted=vm.runInContext('countedFact',c),month=input.month;let orderChecks=0;
  for(const mode of ['operations','finance']){
   c.HTML2_STORE_HIERARCHY.setMode(mode);
   const full=orderLedger(session,'month',mode),ledger=full.filter(f=>p.matches(f,{month})),allQuery={parents:c.HTML2_STORE_HIERARCHY.controls().filter(f=>p.matches(f,{month})).map(p.localFact).filter(f=>!ignoredWarehouse(session,f)),rows:groupMembers(session,itemMembers(session,ledger))},allLinks=groupLinks(session,allQuery.rows,ledger);
   const assigned=ledger.filter(f=>!orderAttribution(session,f)),totals=attributionTotals(session,ledger);
   for(const row of totals)assert.equal(p.micro(row.total),p.micro(row.assigned)+p.micro(row.pending),'原额与订单归属分区不守恒');
   attribution.push({month,mode,pending_rows:totals.reduce((n,g)=>n+g.pending_rows+g.unknown_rows,0),item_gaps:itemAttribution(session,assigned,full),undated_rows:assigned.filter(f=>counted(f)&&f.amount!=null&&p.micro(f.amount)!==0n&&!f.period_date).length});
   const orderTotals=new Map(),itemTotals=new Map();
   for(const f of ledger)if(counted(f)&&f.amount!=null){const key=[f.store_id||'',f.external_order_id||'',f.currency,f.kind].join('|');orderTotals.set(key,(orderTotals.get(key)||0n)+p.micro(f.amount));}
   for(const g of allQuery.rows)for(const m of g.members)for(const [kind,n]of Object.entries(m.amounts))if(n!=null){const key=[m.store,m.fact.external_order_id||'',m.currency,kind].join('|');itemTotals.set(key,(itemTotals.get(key)||0n)+n);}
   for(const key of new Set([...orderTotals.keys(),...itemTotals.keys()])){assert.equal(orderTotals.get(key)||0n,itemTotals.get(key)||0n,'订单商品归属不守恒：'+key);orderChecks++;}
   const all=allQuery.parents,shops=[...new Map(all.filter(f=>f.kind==='sales').map(f=>[String(f.store_id),f.store_code])).entries()];
   const sourceRows={country:ledger,order:ledger,detail:ledger};
   for(const [store,shop]of shops){
    const filters={store,month},q={parents:all.filter(f=>p.matches(f,filters)),rows:allQuery.rows.filter(g=>g.members.some(m=>m.store===store))},links=allLinks.filter(g=>g.store===store),sums={};
    const kinds=[...new Set(q.parents.map(f=>f.kind))];
    const sources=Object.fromEntries(Object.entries(sourceRows).map(([view,rows])=>[view,rows.filter(f=>p.matches(f,filters))]));
    for(const kind of kinds){
     const control=q.parents.filter(f=>f.kind===kind&&counted(f)).reduce((n,f)=>n+(f.amount==null?0n:p.micro(f.amount)),0n);
     for(const [view,rows]of Object.entries(sources))assert.equal(rows.filter(f=>f.kind===kind&&counted(f)).reduce((n,f)=>n+(f.amount==null?0n:p.micro(f.amount)),0n),control,shop+'/'+mode+'/'+view+'/'+kind);
     for(const [view,rows]of [['sku',q.rows],['product_link',links]])assert.equal(rows.reduce((n,g)=>n+(g.amounts[kind]?.amount||0n),0n),control,shop+'/'+mode+'/'+view+'/'+kind);
     sums[kind]=p.fixed(control);
    }
    result.push({shop,store,month,mode,sku:q.rows.length,products:links.length,totals:sums,checks:kinds.length*5});
   }
  }
  return {passed:true,conservation_passed:true,attribution_complete:attribution.every(r=>!r.pending_rows&&!r.item_gaps.length&&!r.undated_rows),attribution,results:result,checks:orderChecks+result.reduce((n,r)=>n+r.checks,0),order_checks:orderChecks};
 }
 if(input.action==='prepare_fee'){p.entriesFor('store');p.entriesFor('detail');const r=input.record||{};if(r.kind==='advertising'){const shop=c.LEDGER_FEES.shops().find(s=>String(s.id)===String(r.store));if(shop)c.HTML2_ADVERTISING_COLUMNS.calculate(shop.code,r.month,p.entriesFor('store'));}c.LEDGER_FEES.save(r);return {key:feeKey,value:writes[feeKey]};}
 if(input.action==='report'){
  const filters=input.filters||{},mode=input.mode||'operations';c.HTML2_STORE_HIERARCHY.setMode(mode);
  const {inPeriod}=require('./summary_periods.cjs'),all=orderLedger(session,filters.period_type||'month',mode),rows=all.filter(f=>!orderAttribution(session,f)&&p.matches(f,filters)&&inPeriod(f,filters.period_type||'month',filters.period));
  if(['sku','product_link'].includes(input.view)){const sku=groupMembers(session,itemMembers(session,rows,all));return plain(input.view==='sku'?sku:groupLinks(session,sku,rows));}
  return plain(input.view==='detail'?rows:p.groupRows(rows,input.view));
 }
 if(input.action!=='save')throw Error('不支持的操作。');
 const key=input.key;
 if(key===feeKey){
  const old=JSON.parse(storage.get(key)||'{"version":1,"changes":{},"history":[]}');
  if(proposed.version!==1||proposed.history?.length!==old.history.length+1)throw Error('费用历史版本不一致。');
  eq(proposed.history.slice(0,-1),old.history);const last=proposed.history.at(-1),r=last.after;
  if(!r||!['save','disable','restore','delete'].includes(last.operation))throw Error('费用操作无效。');
  const existing=old.changes[r.id],fresh=r.type==='new'&&!existing;
  if(fresh&&!/^new:[\da-z-]{10,100}$/i.test(r.id))throw Error('新增费用标识无效。');
  p.entriesFor('store');p.entriesFor('detail');
  if(r.kind==='advertising'){const shop=c.LEDGER_FEES.shops().find(s=>s.id===r.store);if(shop)c.HTML2_ADVERTISING_COLUMNS.calculate(shop.code,r.month,p.entriesFor('store'));}
  c.LEDGER_FEES.save({...r,id:fresh?undefined:r.id,operation:last.operation});
  eq(JSON.parse(writes[key]).changes,proposed.changes);
 }else if(key==='html2-shopee-recharge-v1'){
  c.SHOPEE_RECHARGE.importState(c.SHOPEE_RECHARGE.validateImport(input.value));
 }else if(key==='html2-lazada-tax-rules-v1'){
  const old=c.HTML2_LAZADA_FINANCE.taxRules();if(!Array.isArray(proposed)||proposed.length!==old.length+1)throw Error('税规则只允许追加新版本。');
  eq(proposed.slice(0,-1),old);c.HTML2_LAZADA_FINANCE.addTaxRule(proposed.at(-1));eq(JSON.parse(writes[key]),proposed);
 }else if(key==='html2-lazada-amortization-v1'){
  const old=c.HTML2_LAZADA_FINANCE.manual(),keys=[...new Set([...Object.keys(old),...Object.keys(proposed)])].filter(k=>JSON.stringify(old[k])!==JSON.stringify(proposed[k]));
  if(keys.length!==1)throw Error('每次只调整一个店铺的摊销周期。');
  const k=keys[0];if(!k.endsWith('|inside'))throw Error('Lazada仅支持站内广告。');
  c.HTML2_LAZADA_FINANCE.setDays(k.slice(0,-7),proposed[k]?.days??'',proposed[k]?.reason||input.reason||'恢复按实际周期');eq(JSON.parse(writes[key]),proposed);
 }else if(key==='html2-profit-closed-periods-v1'){
  const old=c.HTML2_PROFIT_RULES.closed(),keys=Object.keys(proposed).filter(k=>!old[k]);
  if(keys.length!==1)throw Error('每次只能关账一个月份。');
  const month=keys[0],book=proposed[month];c.HTML2_PROFIT_RULES.closeMonth(month,book.adjustmentMonth,book.reason);
  const books=JSON.parse(writes[key]);
  for(const book of Object.values(books)){
   // localFact spreads the source row over these fields. Remove only shadowed
   // duplicates; keep all five explicitly locked money fields and extra flags.
   for(const row of book.rows)if(row.locked_local_fact)row.locked_local_fact=Object.fromEntries(Object.entries(row.locked_local_fact).filter(([k])=>['amount','currency','original_amount','original_currency','fx'].includes(k)||!Object.hasOwn(row,k)));
  }
  writes[key]=JSON.stringify(books);
 }else if(key==='finance-preview-fee-checkboxes-v1'){
  const old=JSON.parse(storage.get(key)||'{}'),keys=[...new Set([...Object.keys(old),...Object.keys(proposed)])].filter(k=>JSON.stringify(old[k])!==JSON.stringify(proposed[k]));
  if(!keys.length)throw Error('没有勾选变更。');const allowed=new Set();
  for(const f of p.entriesFor('store'))if(c.LEDGER_FEES.editable(f)&&!f.ledger_adjusted&&!f.ledger_added&&!f.allocated&&!f.warehouse_allocation&&!c.HTML2_PROFIT_RULES.closed()[String(f.month||f.date).slice(0,7)])for(const part of p.componentRows([f]))if(part.leaf&&part.amount!=null&&part.status==='confirmed')allowed.add(c.FEE_CHECKBOXES.key(f,part));
  for(const k of keys){if(!allowed.has(k))throw Error('该费用只读或已关账。');if(proposed[k]&&(!proposed[k].reason?.trim()||proposed[k].reason.length>1000))throw Error('请填写变更原因。');}
  c.localStorage.setItem(key,JSON.stringify(proposed));
 }else throw Error('不支持的设置。');
 if(!Object.hasOwn(writes,key))throw Error('服务器未生成有效保存结果。');return {values:writes};
}
try{process.stdout.write(JSON.stringify({ok:true,result:run()}));}catch(e){process.stdout.write(JSON.stringify({ok:false,error:e.message}));process.exitCode=2;}
