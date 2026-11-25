import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { gunzipSync } from 'node:zlib';
import { createRequire } from 'node:module';
import vm from 'node:vm';
const require=createRequire(import.meta.url);
const {accountingCode}=require('../../backend/apps/finance/summary_engine.cjs');
const {dailyAdvertising}=require('../../backend/apps/finance/summary_order_ledger.cjs');
const {micro,fixed}=require('../../backend/apps/finance/summary_allocation.cjs');
const template=gunzipSync(readFileSync('../backend/apps/finance/templates/database-v1.html.gz')).toString();
const moduleCode=id=>accountingCode(id,template.match(new RegExp('<script id="'+id+'">([\\s\\S]*?)</script>'))[1]);

describe('可选登记费用缺省为零',()=>{
 it('未登记显示零，已登记但金额或汇率缺失仍提示异常',()=>{
  const c={};vm.createContext(c);vm.runInContext(moduleCode('html2-fee-rates'),c);
  const api=c.HTML2_FEE_RATES;
  for(const kind of ['gcash','promotion','warehouse_order','warehouse_other']){
   expect(api.read({cells:{}},kind,false)).toEqual({amount:0n,partial:false});
   expect(api.read({amounts:{}},kind,true)).toEqual({amount:0n,partial:false});
   expect(api.read({cells:{[kind]:{amount:-300000000n,entries:[]}}},kind,false).amount).toBe(-300000000n);
   expect(api.read({cells:{[kind]:{amount:null,source_missing:true,entries:[]}}},kind,false).partial).toBe(true);
  }
  expect(api.read({cells:{}},'product_cost',false).amount).toBeNull();
  expect(api.read(null,'gcash',false).amount).toBeNull();
 });
 it('去掉旧批次虚构的登记缺项占位，不删除实际登记或调整缺项',()=>{
  const c={guard(){},sourceShops(){}};vm.createContext(c);
  vm.runInContext(accountingCode('html2-ledger-fees','function apply(rows){guard();sourceShops(rows);return rows;}'),c);
  const rows=[{source_id:'database:coverage:1:2026-09:gcash',kind:'gcash',amount:null},{source_id:'database:coverage:1:2026-09:promotion',kind:'promotion',amount:'0'},{source_id:'registration:7',kind:'gcash',amount:null},{source_id:'database:coverage:1:2026-09:adjustment',kind:'adjustment',amount:null}];
  expect(c.apply(rows).map(f=>f.source_id)).toEqual(['registration:7','database:coverage:1:2026-09:adjustment']);
  expect(rows).toHaveLength(4);
 });
});

describe('已确认广告口径',()=>{
 it('站外含税扣款同时计入两种口径，不叠加站外实际消耗或税额',()=>{
  const charge={id:'outside:1',date:'2026-10-01',time:'2026-10-01',sourceType:'wallet',channel:'outside',debit:'1050.00',principal:'1000.00',tax:'50.00',shop:'A'};
  const facts=[{kind:'advertising',source:'站内广告实际消耗',amount:'-100.00',date:'2026-10-01',store_code:'A'},{kind:'advertising',source:'Meta站外实际消耗',amount:'-999.00',date:'2026-10-01',store_code:'A'}];
  const c={micro,countedFact:()=>true,SHOPEE_RECHARGE:{data:{shops:[{code:'A',currency:'PHP'}],transactions:[charge]},state:()=>({amortization:{'A|outside':{days:1}}}),resolved:()=>[charge]}};
  vm.createContext(c);vm.runInContext(moduleCode('html2-advertising-columns'),c);
  const report=c.HTML2_ADVERTISING_COLUMNS.calculate('A','2026-10',facts);
  expect(report.operations).toBe(115000n);expect(report.finance).toBe(105000n);expect(report.tax).toBe(0n);
  const s={c:{HTML2_STORE_HIERARCHY:{stores:()=>facts},HTML2_ADVERTISING_COLUMNS:{calculate:()=>({...report,actualDetails:[facts[0]]})}},p:{localFact:f=>f}};
  const parent={kind:'advertising',source_id:'hierarchy-ad:A',store_code:'A',store_id:1,month:'2026-10',amount:'-1150.00'};
  const days=dailyAdvertising(s,[parent],'operations');
  expect(days.reduce((n,f)=>n+micro(f.amount),0n)).toBe(-1150000000n);expect(days.some(f=>!f.period_date)).toBe(false);
 });
 it('跨境已确认税额按拨款日期计入运营，不产生虚构摊销周期',()=>{
  const report={spend:0n,operations:5000n,outside:0n,crossBorder:true,details:[{id:'billing:1',date:'2026-10-03',channel:'inside',tax:'50.00',monthGross:'1050.00'}]};
  const s={c:{HTML2_STORE_HIERARCHY:{stores:()=>[]},HTML2_ADVERTISING_COLUMNS:{calculate:()=>report}},p:{localFact:f=>f}};
  const days=dailyAdvertising(s,[{kind:'advertising',source_id:'hierarchy-ad:A',store_code:'A',month:'2026-10',amount:'-50.00'}],'operations');
  expect(days.map(f=>[f.period_date,f.amount])).toEqual([['2026-10-03','-50.000000']]);
 });
});

describe('按店铺月份关账',()=>{
 function runtime(){
  const facts=[{source_id:'a',store_code:'A',store_id:1,kind:'sales',date:'2026-10-01',amount:'100.00',currency:'PHP'},{source_id:'b',store_code:'B',store_id:2,kind:'sales',date:'2026-10-01',amount:'200.00',currency:'PHP'}];
  const values=new Map(),c={micro,fixed,localFact:f=>f,entriesFor:()=>facts,sourceDetails:()=>'',SHOPEE_RECHARGE:{data:{shops:[{code:'A'},{code:'B'}]},baseEntries:()=>facts},HTML2_ADVERTISING_COLUMNS:{calculate:()=>({operations:0n,finance:0n})},localStorage:{getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)}};
  vm.createContext(c);vm.runInContext(moduleCode('html2-profit-rules'),c);return {api:c.HTML2_PROFIT_RULES,facts};
 }
 it('只冻结选中店铺，其他店铺金额继续更新且可以独立关账',()=>{
  const {api,facts}=runtime();api.closeMonth('2026-10','2026-11','A关账','A');
  expect(Object.keys(api.closed())).toEqual(['A|2026-10']);expect(api.closed()['A|2026-10'].rows.map(f=>f.store_code)).toEqual(['A']);
  const live=facts.map(f=>({...f,amount:f.store_code==='A'?'120.00':'250.00'})),rows=api.applyClosed(live);
  expect(rows.find(f=>f.store_code==='B').amount).toBe('250.00');expect(rows.find(f=>f.store_code==='A'&&f.date.startsWith('2026-10')).amount).toBe('100.00');
  expect(rows.find(f=>f.accounting_adjustment).amount).toBe('20.000000');expect(api.applyClosed(live)).toEqual(rows);
  api.closeMonth('2026-10','2026-11','B关账','B');expect(Object.keys(api.closed())).toHaveLength(2);
 });
 it('拒绝未指定店铺及未知店铺，不创建全租户快照',()=>{
  const {api}=runtime();expect(()=>api.closeMonth('2026-10','2026-11','reason')).toThrow('请选择');expect(()=>api.closeMonth('2026-10','2026-11','reason','other')).toThrow('请选择');expect(Object.keys(api.closed())).toHaveLength(0);
 });
});
