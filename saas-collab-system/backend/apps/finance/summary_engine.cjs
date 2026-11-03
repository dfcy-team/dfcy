const fs=require('node:fs'),zlib=require('node:zlib'),vm=require('node:vm'),crypto=require('node:crypto');
let source=null;
const plain=v=>JSON.parse(JSON.stringify(v,(_,x)=>typeof x==='bigint'?x.toString():Object.prototype.toString.call(x)==='[object Set]'?[...x]:Object.prototype.toString.call(x)==='[object Map]'?Object.fromEntries(x):x));
function warehouseProfitRules(code){
 if(code.includes('// SAAS_WAREHOUSE_SETTLEMENT'))return code;
 return code.replace('if(date)f={...f,','f={...f,')
  .replace("\n   else{const month=f.source_bill_month||f.warehouse_allocation?.month||f.date.slice(0,7);f={...f,source_date:f.source_date||f.date,source_bill_month:month,date:month,month,accounting_basis:'已登记关联订单仓库费用；无正向销售结算时按原账单月计入'};}",'')
  .replace("if(!date&&!['warehouse_order','warehouse_other'].includes(f.kind))",'if(!date)')
  .replace('const date=first.get(identity(f));',"// SAAS_WAREHOUSE_SETTLEMENT\n   const warehouse=['warehouse_order','warehouse_other'].includes(f.kind);\n   const date=warehouse?f.warehouse_settlement_date:first.get(identity(f));\n   if(warehouse&&!date)continue;")
  .replace("accounting_basis:'首次有效销售结算（已载入历史）'","accounting_basis:warehouse?'关联订单有效结算日（不要求正向销售额）':'首次有效销售结算（已载入历史）'");
}
function createEngine(path,input,{memo=false}={}){
 const stat=fs.statSync(path),stamp=path+'|'+stat.mtimeMs+'|'+stat.size+'|'+input.sourceHash;
 if(source?.stamp!==stamp){const html=zlib.gunzipSync(fs.readFileSync(path)).toString('utf8');if(input.sourceHash&&crypto.createHash('sha256').update(html).digest('hex')!==input.sourceHash)throw Error('财务批次来源校验失败，未执行计算或保存。');source={stamp,html};}
 const html=source.html,storage=new Map(Object.entries(input.state||{})),writes={},proposed=input.value?JSON.parse(input.value):null,feeKey='html2-ledger-fees-v1';
 const c={TEST_SNAPSHOT:JSON.parse(html.match(/id="snapshot">([\s\S]*?)<\/script>/)[1]),localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>{storage.set(k,v);writes[k]=v;}},crypto:{randomUUID:()=>proposed?.history?.at(-1)?.after?.id?.replace(/^new:/,'')||crypto.randomUUID()}};
 const ids=new WeakMap();let next=0;
 c.__memo=fn=>{const cache=new Map();return function(...args){const key=JSON.stringify([c.HTML2_STORE_HIERARCHY?.mode(),args.map(a=>{if(a===null||typeof a!=='object')return a;if(!ids.has(a))ids.set(a,++next);return ids.get(a);})]);if(cache.has(key))return cache.get(key);const value=fn.apply(this,args);if(cache.size>=64)cache.delete(cache.keys().next().value);cache.set(key,value);return value;};};
 vm.createContext(c);vm.runInContext(html.match(/<script>\s*([\s\S]*?)<\/script>/)[1],c,{timeout:60000});
 for(const id of ['unified-finance-ui','sku-summary-ui','finance-fee-checkboxes','html2-sp6th-fees-data','html2-sp6th-fees','html2-lazada-cycles-data','html2-lazada-finance','html2-ledger-fees','html2-profit-rules','html2-store-hierarchy','html2-shopee-recharge-data','html2-shopee-recharge','html2-advertising-columns','html2-product-links','html2-fee-rates']){
  let code=html.match(new RegExp('<script id="'+id+'">([\\s\\S]*?)</script>'))?.[1];if(!code)throw Error('Missing accepted module: '+id);
  // The domestic Shopee report calculates daily spend but omitted its evidence.
  if(id==='html2-advertising-columns')code=code.replace('outside,warnings:[...warnings],details};','outside,warnings:[...warnings],details,actualDetails:actual};');
  if(id==='html2-product-links')code=code.replace('const source=observed.length?observed:saved;',"const source=observed.length?observed:m.source==='order-ledger'?[]:saved;");
  if(id==='html2-profit-rules')code=warehouseProfitRules(code);
  if(memo&&id==='html2-store-hierarchy')code=code.replace('const api={stores,controls,sku,','stores=__memo(stores);controls=__memo(controls);orderAllocation=__memo(orderAllocation);const api={stores,controls,sku,');
  if(memo&&id==='html2-advertising-columns')code=code.replace('const api={allocate,schedules,calculate,profit,','calculate=__memo(calculate);const api={allocate,schedules,calculate,profit,');
  vm.runInContext(code,c,{timeout:60000});
 }
 if(storage.has('finance-preview-fee-checkboxes-v1'))c.FEE_CHECKBOXES.setExcluded(JSON.parse(storage.get('finance-preview-fee-checkboxes-v1')));
 vm.runInContext(fs.readFileSync(__dirname+'/summary_composition.js','utf8'),c,{timeout:60000});
 c.PREVIEW_TEST.localFact=vm.runInContext('localFact',c);
 return {c,p:c.PREVIEW_TEST,storage,writes,proposed,feeKey,plain};
}
module.exports={createEngine,plain,warehouseProfitRules};
