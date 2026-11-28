import { describe, expect, it } from 'vitest';
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { gunzipSync, gzipSync } from 'node:zlib';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createRequire } from 'node:module';
const require=createRequire(import.meta.url);
const {prepareSource,createEngine,readDocument}=require('../../backend/apps/finance/summary_engine.cjs');
const path='../backend/apps/finance/templates/database-v1.html.gz';
const template=gunzipSync(readFileSync(path)).toString();
describe('原生计算源减载',()=>{
 it('流式解压与原制品逐字节一致，预加载不改变核算输入',async()=>{
  const buffer=await readDocument(path);expect(buffer.equals(gunzipSync(readFileSync(path)))).toBe(true);
  const loaded=createEngine(path,{}, {memo:true,retainSource:false,documentBuffer:buffer}),existing=createEngine(path,{}, {memo:true,retainSource:false});
  expect(loaded.c.TEST_SNAPSHOT).toEqual(existing.c.TEST_SNAPSHOT);
 });
 it('流式读取校验CRC和长度，拒绝伪造超预算的解压长度',async()=>{
  const dir=mkdtempSync(join(tmpdir(),'finance-document-')),file=join(dir,'input.gz');
  try{
   const bytes=gzipSync(Buffer.from('合成来源 </script> '+ 'x'.repeat(100000)));
   writeFileSync(file,bytes);expect((await readDocument(file)).toString()).toBe(gunzipSync(bytes).toString());
   const broken=Buffer.from(bytes);broken[broken.length-8]^=1;writeFileSync(file,broken);await expect(readDocument(file)).rejects.toThrow();
   const oversized=Buffer.from(bytes);oversized.writeUInt32LE(1024**3+1,oversized.length-4);writeFileSync(file,oversized);await expect(readDocument(file)).rejects.toThrow('exceeds read budget');
   writeFileSync(file,Buffer.from('invalid'));await expect(readDocument(file)).rejects.toThrow('Invalid financial document');
  }finally{rmSync(dir,{recursive:true,force:true});}
 });
 it('共享结算字段和成本流水按原引用还原，不复制证据或丢失字段',()=>{
  const snapshot=JSON.parse(template.match(/id="snapshot">([\s\S]*?)<\/script>/)[1]);
  const fields={original_price:1,commission_fee:2,seller_return_refund:3},cost={source_id:'cost:1',amount:null,raw_cost_flow:true,cost_calculation:{components:[{quantity:2}]}};
  snapshot.database.native_finance_fields=[fields];snapshot.database.facts=[{platform:'shopee',store_id:1,external_order_id:'one',date:'2026-11-01',currency:'PHP',source_proof:{platform_finance_fields:0}}];
  snapshot.shopee_income=[{store_id:1,order:'one',date:'2026-11-01',currency:'PHP',platform_finance_fields:0}];snapshot.database.cost_flows=[cost];snapshot.database.raw_flows=[{native_cost_index:0}];
  const html=()=>template.replace(/(id="snapshot">)[\s\S]*?(<\/script>)/,(_,a,b)=>a+JSON.stringify(snapshot)+b);
  const restored=prepareSource(html(),true).snapshot;
  expect(restored.database.facts[0].source_proof.platform_finance_fields).toEqual(fields);
  expect(restored.shopee_income[0].platform_finance_fields).toBe(restored.database.facts[0].source_proof.platform_finance_fields);
  expect(restored.database.raw_flows[0]).toBe(restored.database.cost_flows[0]);expect(restored.database.raw_flows[0]).toEqual(cost);
  snapshot.database.facts[0].source_proof.platform_finance_fields=1;expect(()=>prepareSource(html(),true)).toThrow('Invalid financial evidence reference');
  snapshot.database.facts[0].source_proof.platform_finance_fields=0;snapshot.database.raw_flows[0].native_cost_index=-1;expect(()=>prepareSource(html(),true)).toThrow('Invalid cost source reference');
 });
 it('成本子项共享还原全部依据，损坏引用不能作为零成本继续计算',()=>{
  const snapshot=JSON.parse(template.match(/id="snapshot">([\s\S]*?)<\/script>/)[1]);
  const component={quantity:'2',unit_cost:null,reasons:['pending'],source_sku:'synthetic'};
  snapshot.database.native_cost_components=[component];snapshot.database.facts=[{cost_calculation:{components:[0],reasons:['pending']}}];
  snapshot.database.cost_flows=[{cost_calculation:{components:[0]}}];snapshot.database.raw_flows=[{native_cost_index:0}];
  const html=()=>template.replace(/(id="snapshot">)[\s\S]*?(<\/script>)/,(_,a,b)=>a+JSON.stringify(snapshot)+b);
  const db=prepareSource(html(),true).snapshot.database;
  expect(db.facts[0].cost_calculation.components).toEqual([component]);expect(db.cost_flows[0].cost_calculation.components[0]).toBe(db.facts[0].cost_calculation.components[0]);
  snapshot.database.facts[0].cost_calculation.components=[2];expect(()=>prepareSource(html(),true)).toThrow('Invalid cost component reference');
 });
 it('结算索引保留店铺、订单、日期、币种、类型及重复依据的匹配规则',()=>{
  const {c}=createEngine(path,{}, {memo:true,retainSource:false});
  const row={store_id:58,order:'same-order',date:'2026-10-01',currency:'PHP',income:{original_price:'100'}};
  c.TEST_SNAPSHOT.shopee_income=[row,{...row,store_id:59},{...row,date:'2026-10-02'},{...row,currency:'MYR'}];
  expect(c.shopeeIncomeRows(row)).toEqual([row]);
  expect(c.shopeeIncomeRows({...row,store_id:'58'})).toEqual([]);
  expect(c.hasShopeeIncome({store_id:'58',external_order_id:row.order,date:row.date,currency:row.currency})).toBe(true);
  c.TEST_SNAPSHOT.shopee_income.push({...row});
  expect(c.shopeeIncomeRows(row)).toHaveLength(2);
 });
 it('按脚本解码与整页解码保留相同输入和计算模块',()=>{
  const text=prepareSource(template,true,{retainJSON:false}),buffered=prepareSource(Buffer.from(template,'utf8'),true,{retainJSON:false});
  expect(buffered.snapshot).toEqual(text.snapshot);expect(buffered.data).toEqual(text.data);
  expect(buffered.code).toBe(text.code);expect(buffered.modules).toEqual(text.modules);
  expect(buffered.code.trimStart().startsWith("'use strict';")).toBe(true);
  expect(buffered.snapshotJSON).toBeNull();expect(buffered.dataJSON).toBeNull();
 });
 it('共享编码还原费用构成与核算来源，不改变金额、字段或顺序',()=>{
  const snapshot=JSON.parse(template.match(/id="snapshot">([\s\S]*?)<\/script>/)[1]);
  const parts=[{field:'commission_fee',label:'commission_fee',amount:'-1.000000'},{field:'service_fee',label:'service_fee',amount:null}];
  const fact={source_id:'synthetic-order-fee',kind:'order_fee',date:'2026-10-01',amount:'-1.000000',sp6th_components:[0,1,0]};
  snapshot.database.facts=[fact];snapshot.database.native_components=parts;snapshot.database.raw_flows=[{native_fact_index:0}];
  const html=template.replace(/(id="snapshot">)[\s\S]*?(<\/script>)/,(_,a,b)=>a+JSON.stringify(snapshot)+b);
  const result=prepareSource(html,true).snapshot.database;
  expect(result.facts[0]).toEqual({...fact,sp6th_components:[parts[0],parts[1],parts[0]]});
  expect(result.raw_flows[0]).toMatchObject(result.facts[0]);
  expect(result.raw_flows[0].sp6th_components).toBe(result.facts[0].sp6th_components);
  expect(result.facts[0].sp6th_components[0]).toBe(result.facts[0].sp6th_components[2]);
 });
 it('损坏的共享费用或来源引用拒绝计算，不能悄悄丢失子项',()=>{
  const snapshot=JSON.parse(template.match(/id="snapshot">([\s\S]*?)<\/script>/)[1]);
  snapshot.database.facts=[{sp6th_components:[9]}];snapshot.database.native_components=[];
  const html=()=>template.replace(/(id="snapshot">)[\s\S]*?(<\/script>)/,(_,a,b)=>a+JSON.stringify(snapshot)+b);
  expect(()=>prepareSource(html(),true)).toThrow('Invalid financial component reference');
  snapshot.database.facts=[];snapshot.database.raw_flows=[{native_fact_index:1}];
  expect(()=>prepareSource(html(),true)).toThrow('Invalid financial source reference');
 });
 it('只精简旧版输入，保留原始流水、成本构成和完整分摊分母',()=>{
  const snapshot=JSON.parse(template.match(/id="snapshot">([\s\S]*?)<\/script>/)[1]);
  snapshot.database.facts=[{kind:'product_cost',amount:'-10.25',cost_calculation:{components:[{quantity:2,unit_cost:'5.125'}]}}];
  snapshot.database.shares={order:[{amount:'-2.00',denominator:'1000.00'}]};snapshot.database.raw_flows=[{source_id:'raw:1',amount:'-10.25'}];
  snapshot.raw=[{platform:'lazada',store_id:1,store:'LZ1',raw:{duplicate:'payload'}},{platform:'lazada',store_id:1,store:'LZ1'}];
  snapshot.lazada_saas.sku_members=[{legacy:'not used by native itemMembers'}];snapshot.shopee_income=[{duplicate:'payload'}];
  const html=template.replace(/(id="snapshot">)[\s\S]*?(<\/script>)/,(_,a,b)=>a+JSON.stringify(snapshot)+b);
  const full=prepareSource(html),native=prepareSource(html,true);
  expect(full.snapshot).toEqual(snapshot);expect(native.snapshot.database).toEqual(snapshot.database);
  expect(native.snapshot.raw).toEqual([{platform:'lazada',store_id:1,store:'LZ1'}]);expect(native.snapshot.lazada_saas.sku_members).toEqual([]);expect(native.snapshot.shopee_income).toEqual([]);
  expect(native.code).toContain('SNAPSHOT.local_expenses.facts=FACTS');expect(native.snapshotJSON.length).toBeLessThan(full.snapshotJSON.length);
 });
 it('同一来源新建会话不会复用上一个会话修改过的对象',()=>{
  const first=createEngine(path,{}, {memo:true});first.c.TEST_SNAPSHOT.database.facts.push({source_id:'session-only'});
  const second=createEngine(path,{}, {memo:true});expect(second.c.TEST_SNAPSHOT.database.facts.some(f=>f.source_id==='session-only')).toBe(false);
 });
 it('单会话模式不生成JSON字符串副本，连续创建也不会共享可变输入',()=>{
  const parsed=prepareSource(template,true,{retainJSON:false});
  expect(parsed.snapshotJSON).toBeNull();expect(parsed.dataJSON).toBeNull();
  const first=createEngine(path,{}, {memo:true,retainSource:false});first.c.TEST_SNAPSHOT.database.facts.push({source_id:'single-use-only'});
  const second=createEngine(path,{}, {memo:true,retainSource:false});
  expect(second.c.TEST_SNAPSHOT.database.facts.some(f=>f.source_id==='single-use-only')).toBe(false);
  expect(second.c.TEST_SNAPSHOT).toEqual(parsed.snapshot);
 });
 it('分段计时只记录耗时，不改变计算输入或混入业务数据',()=>{
  const timings={},s=createEngine(path,{}, {memo:true,timings});
  expect(timings.vm_ms).toBeGreaterThanOrEqual(0);
  expect(timings.restore_ms??timings.prepare_ms).toBeGreaterThanOrEqual(0);
  expect(Object.values(timings).every(value=>typeof value==='number'&&Number.isFinite(value)&&value>=0)).toBe(true);
  expect(s.c.TEST_SNAPSHOT.database.facts.some(f=>f.source_id==='session-only')).toBe(false);
 });
 it('大型JSON按数据加载，正确处理引号、括号和分号，不改变后续脚本',()=>{
  const data={orders:{one:[{title:'quoted "name" }; [ bracket \\ path ;',quantity:2}]}};
  const html=template.replace(/(<script id="html2-store-hierarchy">)[\s\S]*?(<\/script>)/,(_,a,b)=>a+'globalThis.HTML2_SKU_ORDER_SALES='+JSON.stringify(data)+';globalThis.after=true;'+b);
  const native=prepareSource(html,true);expect(native.data.HTML2_SKU_ORDER_SALES).toEqual(data);expect(native.modules.get('html2-store-hierarchy')).toContain('globalThis.after=true;');expect(native.modules.get('html2-store-hierarchy')).toContain('__SOURCE_DATA__');expect(prepareSource(html).data).toEqual({});
 });
});

it('原生减载保留匹配当前订单的官方income构成依据，丢弃无关数据',()=>{
 const snapshot=JSON.parse(template.match(/id="snapshot">([\s\S]*?)<\/script>/)[1]);
 snapshot.database.facts=[{platform:'shopee',store_id:58,external_order_id:'SP-1',date:'2026-09-01',currency:'PHP'}];const matching={store_id:58,order:'SP-1',date:'2026-09-01',currency:'PHP',income:{original_price:'100',seller_discount:'-10'}};snapshot.shopee_income=[matching,{...matching,order:'other'}];
 const html=template.replace(/(id="snapshot">)[\s\S]*?(<\/script>)/,(_,a,b)=>a+JSON.stringify(snapshot)+b);expect(prepareSource(html,true).snapshot.shopee_income).toEqual([matching]);
});
