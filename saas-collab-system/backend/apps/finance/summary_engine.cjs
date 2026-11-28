const fs=require('node:fs'),zlib=require('node:zlib'),vm=require('node:vm'),crypto=require('node:crypto');
const accountingRules=require('./summary_accounting_rules.json');
function accountingCode(id,code){for(const rule of accountingRules)if(rule.module===id)code=rule.regex?code.replace(new RegExp(rule.find),()=>rule.replace):code.split(rule.find).join(rule.replace);return code;}
let source=null;
const moduleIds=['unified-finance-ui','sku-summary-ui','finance-fee-checkboxes','html2-sp6th-fees-data','html2-sp6th-fees','html2-lazada-cycles-data','html2-lazada-finance','html2-ledger-fees','html2-profit-rules','html2-store-hierarchy','html2-shopee-recharge-data','html2-shopee-recharge','html2-advertising-columns','html2-product-links','html2-fee-rates'];
// Copy substrings so compiled VM code cannot retain the entire HTML backing string.
const copyText=text=>Buffer.from(text,'utf8').toString('utf8');
const incomeIndexCode=`let incomeArray,incomeLength,incomeIndex,incomePresence;
function indexShopeeIncome(){
 const rows=SNAPSHOT.shopee_income||[];if(incomeArray===rows&&incomeLength===rows.length)return;
 incomeArray=rows;incomeLength=rows.length;incomeIndex=new Map();incomePresence=new Set();
 for(const row of rows){const key=JSON.stringify([row.store_id,row.order,row.date,row.currency]);if(!incomeIndex.has(key))incomeIndex.set(key,[]);incomeIndex.get(key).push(row);incomePresence.add(JSON.stringify([String(row.store_id),row.order,row.date,row.currency]));}
}
function shopeeIncomeRows(g){indexShopeeIncome();return incomeIndex.get(JSON.stringify([g.store_id,g.order,g.date,g.currency]))||[];}
function hasShopeeIncome(f){indexShopeeIncome();return incomePresence.has(JSON.stringify([String(f.store_id),f.external_order_id,f.date,f.original_currency||f.currency]));}`;
function hydrateAssignment(code,name,data){
 const match=new RegExp('globalThis\\.'+name+'\\s*=\\s*').exec(code);if(!match)return code;
 const start=match.index+match[0].length;if(!['{','['].includes(code[start]))return code;
 let depth=0,quoted=false,escaped=false;
 for(let i=start;i<code.length;i++){
  const ch=code[i];
  if(quoted){if(escaped)escaped=false;else if(ch==='\\')escaped=true;else if(ch==='"')quoted=false;continue;}
  if(ch==='"'){quoted=true;continue;}if(ch==='{'||ch==='[')depth++;else if(ch==='}'||ch===']')depth--;
  if(depth===0){try{data[name]=JSON.parse(code.slice(start,i+1));}catch{return code;}return copyText(code.slice(0,start)+'globalThis.__SOURCE_DATA__['+JSON.stringify(name)+']'+code.slice(i+1));}
 }
 return code;
}
function prepareSource(html,native=false,{retainJSON=true}={}){
 const buffered=Buffer.isBuffer(html),script=id=>{
  if(!buffered)return id===null?html.match(/<script>\s*([\s\S]*?)<\/script>/)?.[1]:html.match(new RegExp((id==='snapshot'?'id="snapshot">':'<script id="'+id+'">')+'([\\s\\S]*?)</script>'))?.[1];
  const marker=id===null?'<script>':id==='snapshot'?'id="snapshot">':'<script id="'+id+'">',start=html.indexOf(marker);
  if(start<0)return;const begin=start+Buffer.byteLength(marker),end=html.indexOf('</script>',begin);if(end<0)return;
  const text=html.subarray(begin,end).toString('utf8');return id===null?text.trimStart():text;
 };
 let snapshotText=script('snapshot');const snapshot=JSON.parse(snapshotText);
 if(!retainJSON)snapshotText=null;
 let code=copyText(script(null));
 // Reuse the accepted composition hierarchy with canonical SaaS source groups.
 code=code.replace('function ledgerParts(f){','function ledgerParts(f,sourceGroup){').replace("const g=f.source==='平台结算'?settlementFor(f):null,parts=[];","const g=sourceGroup||(f.source==='平台结算'?settlementFor(f):null),parts=[];");
 const incomeLookup='const sources=(SNAPSHOT.shopee_income||[]).filter(function(r){return r.store_id===g.store_id&&r.order===g.order&&r.date===g.date&&r.currency===g.currency;});';
 if(code.includes(incomeLookup))code=code.replace(incomeLookup,'const sources=shopeeIncomeRows(g);').replace('function shopeeSummary(g){',incomeIndexCode+'\nfunction shopeeSummary(g){');
 const compact=native&&html.includes('// SAAS_DATABASE_ENTRIES')&&snapshot.database;
 if(compact){
  const database=snapshot.database,pool=database.native_components;
  if(database.native_cost_components){
   const components=database.native_cost_components;if(!Array.isArray(components))throw Error('Invalid cost component dictionary');
   for(const record of [...database.facts,...(database.cost_flows||[]),...(database.raw_flows||[])]){
    const calculation=record.cost_calculation;if(!Array.isArray(calculation?.components))continue;
    calculation.components=calculation.components.map(index=>{
     if(!Number.isInteger(index)||index<0||index>=components.length||!components[index]||typeof components[index]!=='object')throw Error('Invalid cost component reference');
     return components[index];
    });
   }
  }
  if(database.native_finance_fields){
   const fields=database.native_finance_fields;if(!Array.isArray(fields))throw Error('Invalid financial evidence dictionary');
   for(const record of [...database.facts,...(snapshot.shopee_income||[])]){
    const proof=Object.hasOwn(record,'source_proof')?record.source_proof:record;
    if(!proof||!Object.hasOwn(proof,'platform_finance_fields'))continue;
    const index=proof.platform_finance_fields;
    if(!Number.isInteger(index)||index<0||index>=fields.length||fields[index]===null||typeof fields[index]!=='object')throw Error('Invalid financial evidence reference');
    proof.platform_finance_fields=fields[index];
   }
  }
  if(pool){
   if(!Array.isArray(pool))throw Error('Invalid financial component dictionary');
   for(const fact of database.facts)if(Array.isArray(fact.sp6th_components))fact.sp6th_components=fact.sp6th_components.map(index=>{
    if(!Number.isInteger(index)||index<0||index>=pool.length)throw Error('Invalid financial component reference');
    return pool[index];
   });
  }
  if(database.raw_flows)database.raw_flows=database.raw_flows.map(flow=>{
   if(Object.hasOwn(flow,'native_cost_index')){
    const index=flow.native_cost_index;
    if(!Number.isInteger(index)||index<0||!Array.isArray(database.cost_flows)||index>=database.cost_flows.length)throw Error('Invalid cost source reference');
    return database.cost_flows[index];
   }
   if(!Object.hasOwn(flow,'native_fact_index'))return flow;
   const index=flow.native_fact_index;
   if(!Number.isInteger(index)||index<0||index>=database.facts.length)throw Error('Invalid financial source reference');
   const fact=database.facts[index];
   return {...fact,raw_source_flow:true,period_date:fact.date?.length===10?fact.date:null,period_date_basis:'订单核算归属日期'};
  });
  // Native SKU rows come from canonical costs and HTML2_SKU_ORDER_SALES, not
  // the legacy browser-only SKU cache. Preserve source store identifiers.
  snapshot.raw=[...new Map((snapshot.raw||[]).map(r=>[[r.platform,r.store_id,r.store].join('|'),{platform:r.platform,store_id:r.store_id,store:r.store}])).values()];
  // Keep only income evidence referenced by canonical facts, for the accepted hierarchy.
  const incomeKey=f=>[f.store_id,f.external_order_id||f.order,f.date,f.original_currency||f.currency].join('|');
  const incomeKeys=new Set(snapshot.database.facts.filter(f=>f.platform==='shopee').map(incomeKey));
  snapshot.shopee_income=(snapshot.shopee_income||[]).filter(f=>incomeKeys.has(incomeKey(f)));
  if(snapshot.lazada_saas)snapshot.lazada_saas.sku_members=[];
  if(snapshot.local_expenses)snapshot.local_expenses.facts=[];
  delete snapshot.database.raw;
  if(!code.includes('const FACTS=SNAPSHOT.database.facts;SNAPSHOT.local_expenses.facts=FACTS;'))code=code.replace('const FACTS=SNAPSHOT.database.facts;','const FACTS=SNAPSHOT.database.facts;SNAPSHOT.local_expenses.facts=FACTS;');
 }
 const data={},dataNames={'html2-store-hierarchy':['HTML2_SKU_ORDER_SALES'],'html2-lazada-cycles-data':['HTML2_LAZADA_CYCLES'],'html2-shopee-recharge-data':['HTML2_RECHARGE_DATA'],'html2-product-links':['HTML2_PRODUCT_LINK_DATA']};
 const modules=new Map(moduleIds.map(id=>{let code=script(id);if(!code)throw Error('Missing accepted module: '+id);if(!buffered)code=copyText(code);if(compact)for(const name of dataNames[id]||[])code=hydrateAssignment(code,name,data);return[id,code];}));
 return{snapshot,snapshotJSON:retainJSON?(compact?JSON.stringify(snapshot):copyText(snapshotText)):null,code,modules,data,dataJSON:retainJSON?JSON.stringify(data):null};
}
const plain=v=>JSON.parse(JSON.stringify(v,(_,x)=>typeof x==='bigint'?x.toString():Object.prototype.toString.call(x)==='[object Set]'?[...x]:Object.prototype.toString.call(x)==='[object Map]'?Object.fromEntries(x):x));
function warehouseProfitRules(code){
 if(code.includes('// SAAS_WAREHOUSE_SETTLEMENT'))return code;
 return code.replace('if(date)f={...f,','f={...f,')
  .replace("\n   else{const month=f.source_bill_month||f.warehouse_allocation?.month||f.date.slice(0,7);f={...f,source_date:f.source_date||f.date,source_bill_month:month,date:month,month,accounting_basis:'已登记关联订单仓库费用；无正向销售结算时按原账单月计入'};}",'')
  .replace("if(!date&&!['warehouse_order','warehouse_other'].includes(f.kind))",'if(!date)')
  .replace('const date=first.get(identity(f));',"// SAAS_WAREHOUSE_SETTLEMENT\n   const warehouse=['warehouse_order','warehouse_other'].includes(f.kind);\n   const date=warehouse?f.warehouse_settlement_date:first.get(identity(f));\n   if(warehouse&&!date)continue;")
  .replace("accounting_basis:'首次有效销售结算（已载入历史）'","accounting_basis:warehouse?'关联订单有效结算日（不要求正向销售额）':'首次有效销售结算（已载入历史）'");
}
async function readDocument(path){
 const fd=fs.openSync(path,'r');let length;
 try{
  const tail=Buffer.alloc(4),size=fs.fstatSync(fd).size;
  if(size<18||fs.readSync(fd,tail,0,4,size-4)!==4)throw Error('Invalid financial document');
  length=tail.readUInt32LE(0);
  if(!length||length>1024**3)throw Error('Financial document exceeds read budget');
 }finally{fs.closeSync(fd);}
 const input=fs.createReadStream(path),unzip=zlib.createGunzip();
 input.on('error',error=>unzip.destroy(error));
 try{
  const output=Buffer.allocUnsafe(length);let offset=0;
  for await(const chunk of input.pipe(unzip)){
   if(chunk.length>length-offset)throw Error('Invalid financial document length');
   chunk.copy(output,offset);offset+=chunk.length;
  }
  if(offset!==length)throw Error('Invalid financial document length');
  return output;
 }finally{input.destroy();unzip.destroy();}
}
function createEngine(path,input,{memo=false,timings=null,retainSource=true,documentBuffer=null}={}){
 const stat=fs.statSync(path),stamp=path+'|'+stat.mtimeMs+'|'+stat.size+'|'+input.sourceHash+'|'+memo;
 let snapshot,data,engineSource;
 if(!retainSource||source?.stamp!==stamp){
  let started=performance.now(),html=documentBuffer||zlib.gunzipSync(fs.readFileSync(path));if(!memo||retainSource)html=html.toString('utf8');
  if(timings)timings.read_decode_ms=performance.now()-started;
  started=performance.now();
  if(input.sourceHash&&crypto.createHash('sha256').update(html).digest('hex')!==input.sourceHash)throw Error('财务批次来源校验失败，未执行计算或保存。');
  if(timings)timings.validate_ms=performance.now()-started;
  started=performance.now();const prepared=prepareSource(html,memo,{retainJSON:retainSource});snapshot=prepared.snapshot;data=prepared.data;engineSource={stamp,snapshotJSON:prepared.snapshotJSON,code:prepared.code,modules:prepared.modules,dataJSON:prepared.dataJSON};
  html=null;
  if(retainSource)source=engineSource;
  if(timings)timings.prepare_ms=performance.now()-started;
 }else{
  const started=performance.now();engineSource=source;snapshot=JSON.parse(source.snapshotJSON);data=JSON.parse(source.dataJSON);
  if(timings)timings.restore_ms=performance.now()-started;
 }
 const vmStarted=performance.now();
 const storage=new Map(Object.entries(input.state||{})),writes={},proposed=input.value?JSON.parse(input.value):null,feeKey='html2-ledger-fees-v1';
 const c={TEST_SNAPSHOT:snapshot,__SOURCE_DATA__:data,localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>{storage.set(k,v);writes[k]=v;}},crypto:{randomUUID:()=>proposed?.history?.at(-1)?.after?.id?.replace(/^new:/,'')||crypto.randomUUID()}};
 const ids=new WeakMap();let next=0;
 c.__memo=fn=>{const cache=new Map();return function(...args){const key=JSON.stringify([c.HTML2_STORE_HIERARCHY?.mode(),args.map(a=>{if(a===null||typeof a!=='object')return a;if(!ids.has(a))ids.set(a,++next);return ids.get(a);})]);if(cache.has(key))return cache.get(key);const value=fn.apply(this,args);if(cache.size>=64)cache.delete(cache.keys().next().value);cache.set(key,value);return value;};};
 vm.createContext(c);vm.runInContext(engineSource.code,c,{timeout:60000});
 vm.runInContext(fs.readFileSync(__dirname+'/summary_participation.js','utf8'),c,{timeout:60000});
 for(const id of moduleIds){
  let code=engineSource.modules.get(id);
  // The domestic Shopee report calculates daily spend but omitted its evidence.
  if(id==='html2-advertising-columns')code=code.replace('outside,warnings:[...warnings],details};','outside,warnings:[...warnings],details,actualDetails:actual};');
  if(id==='html2-product-links')code=code.replace('const source=observed.length?observed:saved;',"const source=observed.length?observed:m.source==='order-ledger'?[]:saved;");
  if(id==='html2-profit-rules')code=warehouseProfitRules(code);
  code=accountingCode(id,code);
  if(memo&&id==='html2-store-hierarchy')code=code.replace('const api={stores,controls,sku,','stores=__memo(stores);controls=__memo(controls);orderAllocation=__memo(orderAllocation);const api={stores,controls,sku,');
  if(memo&&id==='html2-advertising-columns')code=code.replace('const api={allocate,schedules,calculate,profit,','calculate=__memo(calculate);const api={allocate,schedules,calculate,profit,');
  vm.runInContext(code,c,{timeout:60000});
 }
 if(storage.has('finance-preview-fee-checkboxes-v1'))c.FEE_CHECKBOXES.setExcluded(JSON.parse(storage.get('finance-preview-fee-checkboxes-v1')));
 vm.runInContext(fs.readFileSync(__dirname+'/summary_composition.js','utf8'),c,{timeout:60000});
 c.PREVIEW_TEST.localFact=vm.runInContext('localFact',c);
 if(timings)timings.vm_ms=performance.now()-vmStarted;
 return {c,p:c.PREVIEW_TEST,storage,writes,proposed,feeKey,plain};
}
module.exports={createEngine,plain,warehouseProfitRules,accountingCode,prepareSource,readDocument};
