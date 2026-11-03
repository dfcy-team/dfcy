import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { gzipSync } from 'node:zlib';
import { createRequire } from 'node:module';
const source=fs.readFileSync(path.resolve('../backend/apps/finance/summary_composition.js'),'utf8');
function runtime(){
 const c={HTML2_FEE_RATES:{displayAmount:n=>n==null?null:(n<0n?-1n:1n)*(((n<0n?-n:n)+5000n)/10000n)*10000n},micro:n=>BigInt(n),fixed:n=>String(n),ledgerParts:f=>f.parts||[],countedFact:()=>true,localFact:f=>f,parents:[],mode:'operations'};
 c.HTML2_STORE_HIERARCHY={mode:()=>c.mode,setMode:m=>{c.mode=m;},controls:()=>c.parents};
 vm.createContext(c);vm.runInContext(source,c);return c;
}
const fact=parts=>({kind:'order_fee',store_id:58,month:'2026-09',currency:'THB',parts});
const fees=[{key:'fees',label:'平台费用',level:2,leaf:false,amount:-900000n},
 {key:'commission',label:'佣金',level:3,leaf:true,amount:-800000n,source:'Commission'},
 {key:'payment',label:'支付手续费',level:3,leaf:true,amount:-200000n},
 {key:'return',label:'手续费返还',level:3,leaf:true,amount:100000n}];
describe('金额与费率共用构成',()=>{
 it('SaaS来源标记仍解析原平台费用，不退回来源名称一行',()=>{
  const c=runtime();c.ledgerParts=f=>f.source==='平台结算'?fees:[{key:'generic',label:f.source,level:2,leaf:true,amount:-900000n}];
  const rows=c.FINANCE_COMPOSITION.fromEntries([{...fact([]),source:'SaaS平台结算'}],-900000n);
  expect(rows.find(r=>r.label==='平台费用')).toBeDefined();
  expect(rows.find(r=>r.label==='佣金').amount).toBe(-800000n);
 });
 it('保留分类、子项、来源和返还方向，小计不重复计入',()=>{
  const c=runtime(),rows=c.FINANCE_COMPOSITION.fromEntries([fact(fees)],-900000n);
  expect(rows.map(r=>r.label)).toEqual(['平台费用','佣金','支付手续费','手续费返还']);
  expect(rows[0]).toMatchObject({amount:-900000n,included:false});
  expect(rows[1].source).toBe('Commission');
  expect(rows.filter(r=>r.included).reduce((n,r)=>n+r.amount,0n)).toBe(-900000n);
 });
 it('合计不匹配时保留已知子项，仅单独列出差额',()=>{
  const c=runtime(),rows=c.FINANCE_COMPOSITION.fromEntries([fact(fees)],-1000000n);
  expect(rows.find(r=>r.label==='佣金').amount).toBe(-800000n);
  expect(rows.find(r=>r.key==='unresolved').amount).toBe(-100000n);
 });
 it('取消子项后分类小计随之更新，参考金额不参与合计',()=>{
  const c=runtime();c.FEE_CHECKBOXES={getExcluded:()=>({payment:true}),key:(f,r)=>r.key};
  const rows=c.FINANCE_COMPOSITION.fromEntries([fact([...fees,{key:'ref',label:'对账金额',level:2,leaf:true,status:'reference',amount:9990000n}])],-700000n);
  expect(rows.find(r=>r.label==='平台费用').amount).toBe(-700000n);
  expect(rows.some(r=>r.label==='支付手续费')).toBe(false);
  expect(rows.find(r=>r.label==='对账金额').included).toBe(false);
  expect(rows.filter(r=>r.included).reduce((n,r)=>n+r.amount,0n)).toBe(-700000n);
 });
 it('SKU沿原费用子项拆分且恢复分类小计，正负守恒',()=>{
  const c=runtime();c.parents=[fact(fees)];
  const g={members:[{store:'58',month:'2026-09',currency:'THB',orders:[],amounts:{order_fee:-450000n}}]};
  const rows=c.FINANCE_COMPOSITION.build({sku:true,group:g,fees:{order_fee:{amount:-450000n}}},'order_fee');
  expect(rows.map(r=>r.amount)).toEqual([-450000n,-400000n,-100000n,50000n]);
  expect(rows[0].included).toBe(false);
 });
 it('缺失子项不补零、不同分类下同名费用不合并',()=>{
  const c=runtime(),rows=c.FINANCE_COMPOSITION.fromEntries([fact([
   {key:'a',label:'运费',level:2,leaf:false,amount:-10000n},
   {key:'fee',label:'费用',level:3,leaf:true,amount:-10000n},
   {key:'b',label:'平台费',level:2,leaf:false,amount:null},
   {key:'fee',label:'费用',level:3,leaf:true,amount:null,status:'pending'}])],-10000n);
  expect(rows.filter(r=>r.label==='费用')).toHaveLength(2);
  expect(rows.find(r=>r.label==='平台费').amount).toBeNull();
 });
 it('相同分类下的参考记录不重复展开已计入子项',()=>{
  const c=runtime(),rows=c.FINANCE_COMPOSITION.fromEntries([
   fact(fees),fact(fees.map(r=>({...r,status:'reference'})))],-900000n);
  expect(rows.filter(r=>r.included).reduce((n,r)=>n+r.amount,0n)).toBe(-900000n);
  expect(rows.filter(r=>r.label==='佣金'&&r.included)).toHaveLength(1);
  expect(c.FINANCE_COMPOSITION.fromEntries([],0n)[0].status).toBe('confirmed');
 });
 it('HTML2广告详情按所点口径取控制来源，恢复原口径状态',()=>{
  const c=runtime(),old={...fact([]),kind:'advertising'};
  c.HTML2_STORE_HIERARCHY.controls=()=>[{...old,parts:[{key:'actual',label:c.mode==='finance'?'充值周期':'实际消耗',level:2,leaf:true,amount:-30000n}]}];
  const group={cells:{sales:{entries:[old]},advertising:{entries:[old]}}};
  const rows=c.FINANCE_COMPOSITION.build({sku:false,resolveControls:true,group,finance:group,fees:{finance:{amount:-30000n}}},'finance');
  expect(rows[0].label).toBe('充值周期');
  expect(rows[0].amount).toBe(-30000n);
  expect(c.mode).toBe('operations');
 });
 it('SKU商品成本展示自身成本版本和冻结折算额，不按其他SKU成本比例再拆',()=>{
  const c=runtime(),a={sku_id:1,sku_code:'A',quantity:2,unit_cost:'10',currency:'CNY',net_cost:'20',
   local_amount:'-400000',cost_version_id:12,cost_version_no:2,cost_effective_from:'2026-08-01',reasons:[]};
  const f={...fact([]),kind:'product_cost',cost_conversion:{period:'2026-09',from:'CNY',to:'PHP',quote:{rate:'9.55',input_id:42}},
   cost_calculation:{cost_at:'2026-09-10',components:[a,{...a,sku_id:2,sku_code:'B',local_amount:'-500000'}]}};
  const group={members:[{store:'58',month:'2026-09',currency:'THB',orders:[],amounts:{product_cost:-400000n},component:a,fact:f}]};
  const rows=c.FINANCE_COMPOSITION.build({sku:true,group,fees:{product_cost:{amount:-400000n}}},'product_cost');
  expect(rows.filter(r=>r.included).map(r=>r.amount)).toEqual([-400000n]);
  expect(rows[1].label).toBe('A × 2');
  expect(rows[1].source).toContain('成本版本 #12');
  expect(rows[0].source).toContain('1种汇率');
  expect([...rows[0].quotes.values()][0].input_id).toBe(42);
 });
});

it('成本折算使用已冻结的同一金额，缺失时不回退到日汇率',()=>{
 const python=fs.readFileSync(path.resolve('../backend/apps/finance/summary_database_document.py'),'utf8');
 const local=python.match(/DATABASE_LOCAL_FACT = """([\s\S]*?)"""/)[1];
 const c={SNAPSHOT:{database:{rates:{historical:{'2026-09-10|CNY|PHP':{rate:'99'}},monthly:{}}}},displayCurrency:()=> 'PHP'};
 vm.createContext(c);vm.runInContext(local,c);
 const f={kind:'product_cost',date:'2026-09-10',currency:'CNY',amount:'-20',cost_conversion:{to:'PHP',local_amount:'-191',quote:{rate:'9.55'}}};
 expect(c.localFact(f).amount).toBe('-191');
 expect(c.localFact({...f,cost_conversion:{...f.cost_conversion,local_amount:null,quote:null}}).amount).toBeNull();
});

it('引擎导出的换算器使用关账模块的最终版本，保留已锁定金额',()=>{
 const require=createRequire(import.meta.url),{createEngine}=require(path.resolve('../backend/apps/finance/summary_engine.cjs'));
 const ids=['unified-finance-ui','sku-summary-ui','finance-fee-checkboxes','html2-sp6th-fees-data','html2-sp6th-fees','html2-lazada-cycles-data','html2-lazada-finance','html2-ledger-fees','html2-profit-rules','html2-store-hierarchy','html2-shopee-recharge-data','html2-shopee-recharge','html2-advertising-columns','html2-product-links','html2-fee-rates'];
 const html='<script type="application/json" id="snapshot">{}</script><script>function localFact(f){return f;}globalThis.PREVIEW_TEST={localFact};</script>'+
  ids.map(id=>'<script id="'+id+'">'+(id==='html2-profit-rules'?'localFact=f=>({...f,amount:f.locked_local_fact?.amount??f.amount});':';')+'</script>').join('');
 const dir=fs.mkdtempSync(path.join(tmpdir(),'finance-close-')),file=path.join(dir,'source.gz');
 try{
  fs.writeFileSync(file,gzipSync(html));
  const engine=createEngine(file,{state:{}});
  expect(engine.p.localFact({amount:'-999',locked_local_fact:{amount:'-20'}}).amount).toBe('-20');
 }finally{fs.unlinkSync(file);fs.rmdirSync(dir);}
});

it('Shopee月度广告报告保留已筛选的实际日报，供周／半月读取且不再次重复读取原始行',()=>{
 const require=createRequire(import.meta.url),{createEngine}=require(path.resolve('../backend/apps/finance/summary_engine.cjs')),{dailyAdvertising}=require(path.resolve('../backend/apps/finance/summary_order_ledger.cjs'));
 const ids=['unified-finance-ui','sku-summary-ui','finance-fee-checkboxes','html2-sp6th-fees-data','html2-sp6th-fees','html2-lazada-cycles-data','html2-lazada-finance','html2-ledger-fees','html2-profit-rules','html2-store-hierarchy','html2-shopee-recharge-data','html2-shopee-recharge','html2-advertising-columns','html2-product-links','html2-fee-rates'];
 const adCode=`globalThis.HTML2_ADVERTISING_COLUMNS={calculate(shop,month,baseRows){const actual=baseRows.filter(f=>f.kind==='advertising'&&f.status==='confirmed'&&f.store_code===shop&&f.date.startsWith(month)),outside=0n,warnings=[],details=[];return{shop,month,operations:300n,spend:300n,outside,warnings:[...warnings],details};}};`;
 const html='<script type="application/json" id="snapshot">{}</script><script>function localFact(f){return f;}globalThis.PREVIEW_TEST={localFact};</script>'+ids.map(id=>'<script id="'+id+'">'+(id==='html2-advertising-columns'?adCode:';')+'</script>').join('');
 const dir=fs.mkdtempSync(path.join(tmpdir(),'finance-ad-days-')),file=path.join(dir,'source.gz');
 try{
  fs.writeFileSync(file,gzipSync(html));const s=createEngine(file,{state:{}}),raw=[{kind:'advertising',status:'confirmed',source_id:'day:1',store_code:'SP6TH',date:'2026-09-03',amount:'-1'},{kind:'advertising',status:'confirmed',source_id:'day:2',store_code:'SP6TH',date:'2026-09-18',amount:'-2'},{kind:'advertising',status:'reference',store_code:'SP6TH',date:'2026-09-18',amount:'-999'}];
  s.c.HTML2_STORE_HIERARCHY={stores:()=>raw};const report=s.c.HTML2_ADVERTISING_COLUMNS.calculate('SP6TH','2026-09',raw);expect(report.actualDetails).toHaveLength(2);
  const rows=dailyAdvertising(s,[{kind:'advertising',source_id:'hierarchy-ad:58',store_code:'SP6TH',month:'2026-09',amount:'-3'}],'operations');expect(rows.map(r=>[r.period_date,r.amount])).toEqual([['2026-09-03','-1.000000'],['2026-09-18','-2.000000']]);expect(rows[0].source_proof.actual_source_ids).toEqual(['day:1']);
 }finally{fs.unlinkSync(file);fs.rmdirSync(dir);}
});
